import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from twilio.request_validator import RequestValidator

from app.core.config import Settings, get_settings
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderMessageEvent,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent
from app.interfaces.api.dependencies.provider_delivery import (
    ProviderDeliveryServiceBundle,
    get_provider_delivery_service_bundle,
)
from app.main import create_app

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("11111111-1111-1111-1111-111111111111")
LEAD_ID = LeadId("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeOutboundMessageRepository:
    def __init__(self, message: OutboundMessage | None) -> None:
        self.message = message

    async def get_by_id(
        self, workspace_id: WorkspaceId, message_id: UUID
    ) -> OutboundMessage | None:
        return self.message

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return self.message

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return self.message

    async def get_by_provider_message_id_for_update(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        if (
            self.message is not None
            and self.message.provider_name == provider_name
            and self.message.provider_message_id == provider_message_id
        ):
            return self.message
        return None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.message = message
        return message


class FakeProviderMessageEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], ProviderMessageEvent] = {}

    async def get_by_external_provider_event_id(
        self,
        provider: str,
        external_provider_event_id: str,
    ) -> ProviderMessageEvent | None:
        return self.events.get((provider, external_provider_event_id))

    async def save(self, event: ProviderMessageEvent) -> ProviderMessageEvent:
        self.events[(event.provider, event.external_provider_event_id)] = event
        return event


def _message(
    *, provider_name: str, provider_message_id: str, channel: ContactChannel
) -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("44444444-4444-4444-4444-444444444444"),
        cadence_step_id="step-1",
        channel=channel,
        status=OutboundMessageStatus.SENT,
        idempotency_key="outbound:test",
        body="Checking in.",
        created_at=NOW,
        updated_at=NOW,
        sent_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name=provider_name,
        provider_message_id=provider_message_id,
    )


def _client(bundle: ProviderDeliveryServiceBundle, settings: Settings | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_provider_delivery_service_bundle] = lambda: bundle
    app.dependency_overrides[get_settings] = lambda: (
        settings
        or Settings(
            twilio_auth_token=None,
            sendgrid_event_webhook_public_key=None,
        )
    )
    return TestClient(app)


def test_twilio_status_callback_updates_outbound_delivery_state() -> None:
    session = FakeSession()
    message_repository = FakeOutboundMessageRepository(
        _message(provider_name="twilio", provider_message_id="SM123", channel=ContactChannel.SMS)
    )
    bundle = ProviderDeliveryServiceBundle(
        session=session,
        message_repository=message_repository,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )

    with _client(bundle) as client:
        response = client.post(
            "/api/v1/webhooks/twilio/message-status",
            data={"MessageSid": "SM123", "MessageStatus": "delivered"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["results"][0]["status"] == "processed"
    message = message_repository.message
    assert message is not None
    assert message.provider_delivery_status is not None
    assert message.provider_delivery_status.value == "delivered"
    assert session.commit_count == 1


def test_twilio_signature_is_required_when_auth_token_is_configured() -> None:
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="twilio", provider_message_id="SM123", channel=ContactChannel.SMS
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )
    settings = Settings(twilio_auth_token=SecretStr("secret-token"))
    validator = RequestValidator("secret-token")
    form_data = {"MessageSid": "SM123", "MessageStatus": "delivered"}
    signature = validator.compute_signature(
        "http://testserver/api/v1/webhooks/twilio/message-status",
        form_data,
    )

    with _client(bundle, settings) as client:
        good = client.post(
            "/api/v1/webhooks/twilio/message-status",
            data=form_data,
            headers={"X-Twilio-Signature": signature},
        )
        bad = client.post(
            "/api/v1/webhooks/twilio/message-status",
            data=form_data,
            headers={"X-Twilio-Signature": "bad-signature"},
        )

    assert good.status_code == 200
    assert bad.status_code == 401


def test_sendgrid_batch_processes_delivery_events_and_ignores_non_delivery_events() -> None:
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="sendgrid",
                provider_message_id="msg-123",
                channel=ContactChannel.EMAIL,
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )
    body = json.dumps(
        [
            {
                "event": "processed",
                "timestamp": int(NOW.timestamp()),
                "sg_event_id": "evt-1",
                "sg_message_id": "msg-123.filter0001",
            },
            {
                "event": "open",
                "timestamp": int(NOW.timestamp()),
                "sg_event_id": "evt-2",
                "sg_message_id": "msg-123.filter0001",
            },
        ]
    )

    with _client(bundle) as client:
        response = client.post(
            "/api/v1/webhooks/sendgrid/message-events",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["ignored_count"] == 1
    assert payload["results"][1]["reasons"] == ["unsupported_event_type:open"]


def test_sendgrid_signature_validation_and_duplicate_event_handling() -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    public_key = "".join(
        line.strip()
        for line in public_key_pem.splitlines()
        if "BEGIN" not in line and "END" not in line
    )
    settings = Settings(sendgrid_event_webhook_public_key=SecretStr(public_key))
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="sendgrid",
                provider_message_id="msg-123",
                channel=ContactChannel.EMAIL,
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )
    body = json.dumps(
        [
            {
                "event": "delivered",
                "timestamp": int(NOW.timestamp()),
                "sg_event_id": "evt-1",
                "sg_message_id": "msg-123.filter0001",
            }
        ]
    )
    timestamp = str(int(NOW.timestamp()))
    signature = base64.b64encode(
        private_key.sign(f"{timestamp}{body}".encode(), ec.ECDSA(hashes.SHA256()))
    ).decode()

    with _client(bundle, settings) as client:
        first = client.post(
            "/api/v1/webhooks/sendgrid/message-events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": signature,
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
            },
        )
        second = client.post(
            "/api/v1/webhooks/sendgrid/message-events",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Twilio-Email-Event-Webhook-Signature": signature,
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["processed_count"] == 1
    assert second.json()["duplicate_count"] == 1
