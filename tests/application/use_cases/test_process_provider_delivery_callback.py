from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.use_cases.process_provider_delivery_callback import (
    ProcessProviderDeliveryCallbackReasonCode,
    ProcessProviderDeliveryCallbackStatus,
    ProviderDeliveryCallback,
    process_provider_delivery_callback,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
    ProviderMessageEvent,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent, DomainEventType

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("11111111-1111-1111-1111-111111111111")
LEAD_ID = LeadId("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("33333333-3333-3333-3333-333333333333")
PROVIDER_EVENT_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeOutboundMessageRepository:
    def __init__(self, message: OutboundMessage | None) -> None:
        self.message = message
        self.saved: list[OutboundMessage] = []
        self.locked_provider_messages: list[tuple[str, str]] = []

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
        self.locked_provider_messages.append((provider_name, provider_message_id))
        if (
            self.message is not None
            and self.message.provider_name == provider_name
            and self.message.provider_message_id == provider_message_id
        ):
            return self.message
        return None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.message = message
        self.saved.append(message)
        return message


class FakeProviderMessageEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], ProviderMessageEvent] = {}
        self.saved: list[ProviderMessageEvent] = []

    async def get_by_external_provider_event_id(
        self,
        provider: str,
        external_provider_event_id: str,
    ) -> ProviderMessageEvent | None:
        return self.events.get((provider, external_provider_event_id))

    async def save(self, event: ProviderMessageEvent) -> ProviderMessageEvent:
        self.events[(event.provider, event.external_provider_event_id)] = event
        self.saved.append(event)
        return event


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _message(
    *,
    provider_delivery_status: ProviderDeliveryStatus | None = None,
    provider_status_updated_at: datetime | None = None,
    delivered_at: datetime | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("55555555-5555-5555-5555-555555555555"),
        cadence_step_id="step-1",
        channel=ContactChannel.EMAIL,
        status=OutboundMessageStatus.SENT,
        idempotency_key="outbound:test",
        body="Checking in.",
        created_at=NOW,
        updated_at=NOW,
        sent_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name="sendgrid",
        provider_message_id="msg-123",
        provider_delivery_status=provider_delivery_status,
        provider_status_updated_at=provider_status_updated_at,
        delivered_at=delivered_at,
    )


def _callback(
    *,
    provider_message_id: str = "msg-123",
    event_type: str = "processed",
    status: ProviderDeliveryStatus = ProviderDeliveryStatus.ACCEPTED,
    occurred_at: datetime = NOW,
    failure_reason: str | None = None,
) -> ProviderDeliveryCallback:
    return ProviderDeliveryCallback(
        provider="sendgrid",
        provider_event_id="evt-123",
        provider_message_id=provider_message_id,
        event_type=event_type,
        status=status,
        occurred_at=occurred_at,
        failure_reason=failure_reason,
        payload_redacted={"event": event_type},
    )


async def test_returns_duplicate_when_provider_event_already_exists() -> None:
    events = FakeProviderMessageEventRepository()
    existing = ProviderMessageEvent(
        provider_event_id=PROVIDER_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider="sendgrid",
        provider_message_id="msg-123",
        outbound_message_id=MESSAGE_ID,
        external_provider_event_id="evt-123",
        event_type="processed",
        status=ProviderDeliveryStatus.ACCEPTED,
        received_at=NOW,
        payload_redacted={"event": "processed"},
        created_at=NOW,
    )
    await events.save(existing)

    result = await process_provider_delivery_callback(
        callback=_callback(),
        message_repository=FakeOutboundMessageRepository(_message()),
        provider_message_event_repository=events,
        now=NOW,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.DUPLICATE
    assert result.reasons == (ProcessProviderDeliveryCallbackReasonCode.DUPLICATE_EVENT,)


async def test_ignores_when_outbound_message_cannot_be_found() -> None:
    result = await process_provider_delivery_callback(
        callback=_callback(provider_message_id="missing"),
        message_repository=FakeOutboundMessageRepository(_message()),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        now=NOW,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.IGNORED
    assert result.reasons == (ProcessProviderDeliveryCallbackReasonCode.OUTBOUND_MESSAGE_NOT_FOUND,)


async def test_records_delivery_event_and_updates_delivery_summary() -> None:
    messages = FakeOutboundMessageRepository(_message())
    events = FakeProviderMessageEventRepository()
    event_bus = FakeEventBus()

    result = await process_provider_delivery_callback(
        callback=_callback(
            event_type="delivered",
            status=ProviderDeliveryStatus.DELIVERED,
            occurred_at=NOW + timedelta(minutes=3),
        ),
        message_repository=messages,
        provider_message_event_repository=events,
        event_bus=event_bus,
        now=NOW + timedelta(minutes=3),
        provider_message_event_id_factory=lambda: PROVIDER_EVENT_ID,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED
    assert result.provider_event_id == PROVIDER_EVENT_ID
    assert result.provider_delivery_status == ProviderDeliveryStatus.DELIVERED
    assert messages.message is not None
    assert messages.message.status == OutboundMessageStatus.SENT
    assert messages.message.provider_delivery_status == ProviderDeliveryStatus.DELIVERED
    assert messages.message.delivered_at == NOW + timedelta(minutes=3)
    assert len(events.saved) == 1
    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == DomainEventType.MESSAGE_DELIVERED


async def test_marks_delivery_failure_without_regressing_sent_message_status() -> None:
    messages = FakeOutboundMessageRepository(_message())
    event_bus = FakeEventBus()

    result = await process_provider_delivery_callback(
        callback=_callback(
            event_type="bounce",
            status=ProviderDeliveryStatus.BOUNCED,
            failure_reason="mailbox unavailable",
        ),
        message_repository=messages,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        event_bus=event_bus,
        now=NOW,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED
    assert messages.message is not None
    assert messages.message.status == OutboundMessageStatus.SENT
    assert messages.message.provider_delivery_status == ProviderDeliveryStatus.BOUNCED
    assert messages.message.failure_reason == "mailbox unavailable"
    assert event_bus.events[0].event_type == DomainEventType.MESSAGE_DELIVERY_FAILED


async def test_deferred_status_updates_summary_without_marking_failure() -> None:
    messages = FakeOutboundMessageRepository(_message())

    await process_provider_delivery_callback(
        callback=_callback(
            event_type="deferred",
            status=ProviderDeliveryStatus.DEFERRED,
            occurred_at=NOW + timedelta(minutes=2),
        ),
        message_repository=messages,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        now=NOW + timedelta(minutes=2),
    )

    assert messages.message is not None
    assert messages.message.status == OutboundMessageStatus.SENT
    assert messages.message.provider_delivery_status == ProviderDeliveryStatus.DEFERRED
    assert messages.message.failure_reason is None


async def test_older_callback_does_not_regress_delivered_status() -> None:
    messages = FakeOutboundMessageRepository(
        _message(
            provider_delivery_status=ProviderDeliveryStatus.DELIVERED,
            provider_status_updated_at=NOW,
            delivered_at=NOW,
        )
    )

    await process_provider_delivery_callback(
        callback=_callback(
            event_type="processed",
            status=ProviderDeliveryStatus.ACCEPTED,
            occurred_at=NOW - timedelta(minutes=5),
        ),
        message_repository=messages,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        now=NOW,
    )

    assert messages.message is not None
    assert messages.message.provider_delivery_status == ProviderDeliveryStatus.DELIVERED
    assert messages.message.delivered_at == NOW
