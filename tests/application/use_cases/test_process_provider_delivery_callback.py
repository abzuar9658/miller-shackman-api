from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
)
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
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent, DomainEventType
from app.domain.workflows import LeadWorkflow, TemporalSignalOutboxEntry, WorkflowState

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

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
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
        self.locked_provider_messages.append((provider_name, provider_message_id))
        return await self.get_by_provider_message_id(provider_name, provider_message_id)

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


class FakeOutboundSendReconciliationRepository:
    def __init__(self, reconciliation: OutboundSendReconciliation) -> None:
        self.reconciliation = reconciliation

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return self.reconciliation

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return self.reconciliation

    async def get_by_outbound_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return self.reconciliation

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        return self.reconciliation

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        return self.reconciliation

    async def create_or_get(
        self,
        reconciliation: OutboundSendReconciliation,
    ) -> OutboundSendReconciliation:
        self.reconciliation = reconciliation
        return reconciliation

    async def resolve(self, **kwargs: object) -> OutboundSendReconciliation | None:
        self.reconciliation = replace(
            self.reconciliation,
            status=cast(OutboundSendReconciliationStatus, kwargs["status"]),
            provider_message_id=cast(str | None, kwargs.get("provider_message_id")),
            provider_delivery_status=cast(
                ProviderDeliveryStatus | None,
                kwargs.get("provider_delivery_status"),
            ),
            resolved_at=cast(datetime, kwargs["now"]),
            updated_at=cast(datetime, kwargs["now"]),
        )
        return self.reconciliation


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeLeadWorkflowRepository:
    def __init__(self, workflow: LeadWorkflow) -> None:
        self.workflow = workflow
        self.saved: list[LeadWorkflow] = []

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        return self.workflow

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflow = workflow
        self.saved.append(workflow)
        return workflow


class FakeTemporalSignalOutboxRepository:
    def __init__(self) -> None:
        self.entries: list[TemporalSignalOutboxEntry] = []

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        self.entries.append(entry)
        return entry


class FakeOccurrenceRepository:
    def __init__(self, occurrence: RecurringOccurrence) -> None:
        self.occurrence = occurrence
        self.updated: list[RecurringOccurrence] = []

    async def get_latest_for_step(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        return self.occurrence

    async def get_by_identity(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: UUID,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: datetime,
    ) -> RecurringOccurrence | None:
        return self.occurrence

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence.workspace_id == workspace_id
            and self.occurrence.idempotency_key == idempotency_key
        ):
            return self.occurrence
        return None

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        self.occurrence = occurrence
        return occurrence

    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        provider_message_id: str,
    ) -> RecurringOccurrence | None:
        if self.occurrence.provider_message_id == provider_message_id:
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
    ) -> RecurringOccurrence | None:
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
            logical_touch_count=(
                1
                if RecurringOccurrenceStatus(status) == RecurringOccurrenceStatus.SENT
                else self.occurrence.logical_touch_count
            ),
            closed_at=(
                self.occurrence.closed_at or now
                if RecurringOccurrenceStatus(status)
                in {RecurringOccurrenceStatus.SENT, RecurringOccurrenceStatus.FAILED}
                else self.occurrence.closed_at
            ),
            provider_message_id=provider_message_id or self.occurrence.provider_message_id,
            provider_delivery_status=provider_delivery_status,
            failure_reason=failure_reason,
            fallback_used=(
                fallback_used if fallback_used is not None else self.occurrence.fallback_used
            ),
        )
        self.updated.append(self.occurrence)
        return self.occurrence

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        return 0

    async def resolve_uncertain(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        reason: str,
    ) -> RecurringOccurrence | None:
        return None

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        if (
            self.occurrence.workspace_id != workspace_id
            or self.occurrence.occurrence_id != occurrence_id
        ):
            return None
        return self.occurrence

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        return await self.get_by_id(workspace_id, occurrence_id)


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
    idempotency_key: str | None = None,
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
        idempotency_key=idempotency_key,
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


async def test_provider_callback_confirms_uncertain_outbound_send_and_wakes_workflow() -> None:
    message = replace(
        _message(provider_delivery_status=ProviderDeliveryStatus.UNKNOWN),
        status=OutboundMessageStatus.UNCERTAIN,
        provider_send_status=ProviderSendStatus.UNCERTAIN,
    )
    reconciliation = OutboundSendReconciliation(
        reconciliation_id=UUID("55555555-5555-5555-5555-555555555555"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=UUID("77777777-7777-7777-7777-777777777777"),
        temporal_workflow_id="lead-nurture/77777777",
        outbound_message_id=MESSAGE_ID,
        idempotency_key=message.idempotency_key,
        status=OutboundSendReconciliationStatus.PENDING,
        provider_name="sendgrid",
        provider_message_id=None,
        provider_delivery_status=None,
        created_at=NOW,
        updated_at=NOW,
    )
    messages = FakeOutboundMessageRepository(message)
    reconciliations = FakeOutboundSendReconciliationRepository(reconciliation)
    signals = FakeTemporalSignalOutboxRepository()

    result = await process_provider_delivery_callback(
        callback=_callback(
            provider_message_id="callback-msg",
            status=ProviderDeliveryStatus.DELIVERED,
            idempotency_key=message.idempotency_key,
        ),
        message_repository=messages,
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        reconciliation_repository=reconciliations,
        temporal_signal_outbox_repository=cast(TemporalSignalOutboxRepository, signals),
        workspace_id=WORKSPACE_ID,
        now=NOW,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED
    assert messages.message is not None
    assert messages.message.status is OutboundMessageStatus.SENT
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.CONFIRMED
    assert len(signals.entries) == 1
    assert signals.entries[0].payload["reason"] == "provider_delivery_reconciled"


async def test_provider_callback_updates_linked_occurrence_without_new_touch() -> None:
    occurrence_repository = FakeOccurrenceRepository(
        RecurringOccurrence(
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
            status=RecurringOccurrenceStatus.SENT,
            idempotency_key="occurrence:callback",
            logical_touch_count=1,
            provider_message_id="msg-123",
            created_at=NOW,
        )
    )
    result = await process_provider_delivery_callback(
        callback=_callback(
            event_type="delivered",
            status=ProviderDeliveryStatus.DELIVERED,
        ),
        message_repository=FakeOutboundMessageRepository(_message()),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        occurrence_repository=occurrence_repository,
        now=NOW,
    )

    assert result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED
    assert occurrence_repository.occurrence.status == RecurringOccurrenceStatus.SENT
    assert occurrence_repository.occurrence.logical_touch_count == 1
    assert occurrence_repository.occurrence.provider_delivery_status == (
        ProviderDeliveryStatus.DELIVERED
    )


async def test_provider_callback_resolves_uncertain_occurrence_once_and_wakes_workflow() -> None:
    workflow_id = UUID("77777777-7777-7777-7777-777777777777")
    occurrence_repository = FakeOccurrenceRepository(
        RecurringOccurrence(
            occurrence_id=UUID("66666666-6666-6666-6666-666666666666"),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            workflow_id=workflow_id,
            track_version_id=UUID("88888888-8888-8888-8888-888888888888"),
            step_id=UUID("99999999-9999-9999-9999-999999999999"),
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            occurrence_number=1,
            scheduled_for=NOW,
            due_at=NOW,
            status=RecurringOccurrenceStatus.UNCERTAIN,
            idempotency_key="occurrence:uncertain",
            logical_touch_count=0,
            provider_message_id="msg-123",
            provider_delivery_status=ProviderDeliveryStatus.UNKNOWN,
            created_at=NOW,
        )
    )
    workflow_repository = FakeLeadWorkflowRepository(
        LeadWorkflow(
            workflow_id=workflow_id,
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

    await process_provider_delivery_callback(
        callback=_callback(status=ProviderDeliveryStatus.DELIVERED),
        message_repository=FakeOutboundMessageRepository(
            _message(provider_delivery_status=ProviderDeliveryStatus.UNKNOWN)
        ),
        provider_message_event_repository=FakeProviderMessageEventRepository(),
        occurrence_repository=occurrence_repository,
        lead_workflow_repository=cast(LeadWorkflowRepository, workflow_repository),
        temporal_signal_outbox_repository=cast(TemporalSignalOutboxRepository, signal_repository),
        now=NOW,
    )

    assert occurrence_repository.occurrence.status == RecurringOccurrenceStatus.SENT
    assert occurrence_repository.occurrence.logical_touch_count == 1
    assert workflow_repository.workflow.logical_touch_count == 1
    assert len(signal_repository.entries) == 1
    assert signal_repository.entries[0].payload["reason"] == "provider_delivery_reconciled"


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
