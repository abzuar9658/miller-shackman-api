import base64
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from twilio.request_validator import RequestValidator

from app.application.ports.repositories import (
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
)
from app.core.config import Settings, get_settings
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
    ProviderMessageEvent,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent
from app.domain.workflows import LeadWorkflow, TemporalSignalOutboxEntry, WorkflowState
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

    async def get_by_id_for_update(
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

    async def get_by_provider_message_id(
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

    async def get_by_provider_message_id_for_update(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        return await self.get_by_provider_message_id(provider_name, provider_message_id)

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


class FakeOccurrenceRepository:
    def __init__(self, occurrence: RecurringOccurrence) -> None:
        self.occurrence = occurrence

    async def get_by_provider_message_id_for_update(
        self, workspace_id: WorkspaceId, provider_message_id: str
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence.workspace_id == workspace_id
            and self.occurrence.provider_message_id == provider_message_id
        ):
            return self.occurrence
        return None

    async def update_status(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence:
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
            provider_message_id=provider_message_id,
            provider_delivery_status=provider_delivery_status,
            failure_reason=failure_reason,
            logical_touch_count=1,
        )
        return self.occurrence


class FakeLeadWorkflowRepository:
    def __init__(self, workflow: LeadWorkflow) -> None:
        self.workflow = workflow

    async def get_latest_for_lead_for_update(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> LeadWorkflow | None:
        return self.workflow

    async def list_active_paused_search_for_lead_for_update(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> tuple[LeadWorkflow, ...]:
        return ()

    async def list_paused_for_workspace(
        self, workspace_id: WorkspaceId, *, limit: int = 100
    ) -> tuple[LeadWorkflow, ...]:
        return (self.workflow,)[:limit]

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflow = workflow
        return workflow


class FakeTemporalSignalOutboxRepository:
    def __init__(self) -> None:
        self.entries: list[TemporalSignalOutboxEntry] = []

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        self.entries.append(entry)
        return entry


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
            mailgun_webhook_signing_key=None,
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


def test_sendgrid_delivery_reconciles_uncertain_occurrence_and_wakes_workflow() -> None:
    provider_message_id = "msg-uncertain"
    occurrence = RecurringOccurrence(
        occurrence_id=UUID("66666666-6666-6666-6666-666666666666"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=UUID("77777777-7777-7777-7777-777777777777"),
        track_version_id=UUID("88888888-8888-8888-8888-888888888888"),
        step_id=UUID("99999999-9999-9999-9999-999999999999"),
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.UNCERTAIN,
        idempotency_key="occurrence:uncertain",
        logical_touch_count=0,
        provider_message_id=provider_message_id,
        created_at=NOW,
    )
    occurrence_repository = FakeOccurrenceRepository(occurrence)
    workflow_repository = FakeLeadWorkflowRepository(
        LeadWorkflow(
            workflow_id=occurrence.workflow_id,
            temporal_workflow_id="lead-nurture:uncertain",
            workspace_id=WORKSPACE_ID,
            campaign_enrollment_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            campaign_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            lead_id=LEAD_ID,
            state=WorkflowState.PAUSED,
            last_transition_at=NOW,
            state_version=1,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    signal_repository = FakeTemporalSignalOutboxRepository()
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="sendgrid",
                provider_message_id=provider_message_id,
                channel=ContactChannel.EMAIL,
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        lead_workflow_repository=workflow_repository,
        temporal_signal_outbox_repository=cast(
            TemporalSignalOutboxRepository, signal_repository
        ),
        event_bus=FakeEventBus(),
    )
    body = json.dumps(
        [
            {
                "event": "delivered",
                "timestamp": int(NOW.timestamp()),
                "sg_event_id": "evt-uncertain",
                "sg_message_id": provider_message_id,
            }
        ]
    )

    with _client(bundle) as client:
        response = client.post(
            "/api/v1/webhooks/sendgrid/message-events",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert response.json()["processed_count"] == 1
    assert occurrence_repository.occurrence.status == RecurringOccurrenceStatus.SENT
    assert occurrence_repository.occurrence.logical_touch_count == 1
    assert workflow_repository.workflow.logical_touch_count == 1
    assert len(signal_repository.entries) == 1
    assert signal_repository.entries[0].payload["reason"] == "provider_delivery_reconciled"


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


def _mailgun_signature(signing_key: str, token: str, timestamp: str) -> str:
    return hmac.new(
        signing_key.encode(),
        f"{timestamp}{token}".encode(),
        sha256,
    ).hexdigest()


def _mailgun_delivery_body(
    *,
    event: str,
    provider_message_id: str,
    event_id: str,
    timestamp: int,
    severity: str | None = None,
) -> str:
    return json.dumps(
        {
            "event": event,
            "timestamp": timestamp,
            "id": event_id,
            "severity": severity,
            "recipient": "lead@example.com",
            "message": {
                "headers": {"message-id": f"<{provider_message_id}>"},
            },
            "delivery-status": {"message": "OK", "description": "Accepted"},
        }
    )


def test_mailgun_delivery_webhook_processes_delivered_event() -> None:
    message_repository = FakeOutboundMessageRepository(
        _message(
            provider_name="mailgun",
            provider_message_id="msg-123@example.com",
            channel=ContactChannel.EMAIL,
        )
    )
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=message_repository,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )
    body = _mailgun_delivery_body(
        event="delivered",
        provider_message_id="msg-123@example.com",
        event_id="evt-1",
        timestamp=int(NOW.timestamp()),
    )

    with _client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/message-events/{WORKSPACE_ID}",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 1
    assert payload["results"][0]["status"] == "processed"
    message = message_repository.message
    assert message is not None
    assert message.provider_delivery_status is not None
    assert message.provider_delivery_status.value == "delivered"


def test_mailgun_delivery_webhook_ignores_unsupported_event() -> None:
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="mailgun",
                provider_message_id="msg-123@example.com",
                channel=ContactChannel.EMAIL,
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )
    body = _mailgun_delivery_body(
        event="opened",
        provider_message_id="msg-123@example.com",
        event_id="evt-2",
        timestamp=int(NOW.timestamp()),
    )

    with _client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/message-events/{WORKSPACE_ID}",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed_count"] == 0
    assert payload["ignored_count"] == 1
    assert payload["results"][0]["reasons"] == ["unsupported_event_type:opened"]


def test_mailgun_delivery_signature_is_required_when_signing_key_is_configured() -> None:
    signing_key = "mailgun-signing-key"
    settings = Settings(mailgun_webhook_signing_key=SecretStr(signing_key))
    token = "token-123"
    timestamp = "1234567890"
    signature = _mailgun_signature(signing_key, token, timestamp)
    body = json.dumps(
        {
            "signature": {"token": token, "timestamp": timestamp, "signature": signature},
            "event": "delivered",
            "timestamp": int(NOW.timestamp()),
            "id": "evt-1",
            "recipient": "lead@example.com",
            "message": {"headers": {"message-id": "<msg-123@example.com>"}},
        }
    )
    bundle = ProviderDeliveryServiceBundle(
        session=FakeSession(),
        message_repository=FakeOutboundMessageRepository(
            _message(
                provider_name="mailgun",
                provider_message_id="msg-123@example.com",
                channel=ContactChannel.EMAIL,
            )
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=FakeEventBus(),
    )

    with _client(bundle, settings) as client:
        good = client.post(
            f"/api/v1/webhooks/mailgun/message-events/{WORKSPACE_ID}",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        bad = client.post(
            f"/api/v1/webhooks/mailgun/message-events/{WORKSPACE_ID}",
            content=json.dumps(
                {
                    "signature": {"token": token, "timestamp": timestamp, "signature": "bad"},
                    "event": "delivered",
                    "timestamp": int(NOW.timestamp()),
                    "id": "evt-1",
                    "recipient": "lead@example.com",
                    "message": {"headers": {"message-id": "<msg-123@example.com>"}},
                }
            ),
            headers={"Content-Type": "application/json"},
        )

    assert good.status_code == 200
    assert bad.status_code == 401
