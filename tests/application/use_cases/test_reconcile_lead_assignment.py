from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.use_cases.reconcile_lead_assignment import (
    LeadAssignmentReconciliationStatus,
    reconcile_lead_assignment_change,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent, DomainEventType
from app.domain.leads import (
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    EffectiveOwnerSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)

NOW = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("10000000-0000-0000-0000-000000000002")
PREVIOUS_OWNER_ID = UUID("10000000-0000-0000-0000-000000000003")
CURRENT_OWNER_ID = UUID("10000000-0000-0000-0000-000000000004")
FALLBACK_MANAGER_ID = UUID("10000000-0000-0000-0000-000000000005")


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


async def test_reconcile_lead_assignment_keeps_workflow_and_messages_unchanged() -> None:
    workflows = FakeLeadWorkflowRepository()
    transitions = FakeWorkflowTransitionRepository()
    outbox = FakeTemporalSignalOutboxRepository()
    messages = FakeOutboundMessageRepository()
    event_bus = FakeEventBus()
    await workflows.save(_workflow())
    await messages.save(_pending_message())

    result = await reconcile_lead_assignment_change(
        previous_lead=_lead(owner_id=PREVIOUS_OWNER_ID),
        current_lead=_lead(owner_id=CURRENT_OWNER_ID),
        lead_workflow_repository=workflows,
        workflow_transition_repository=transitions,
        temporal_signal_outbox_repository=outbox,
        outbound_message_repository=messages,
        event_bus=event_bus,
        now=NOW,
    )

    assert result.status == LeadAssignmentReconciliationStatus.RECONCILED
    assert result.ownership_changed is True
    assert result.pause_requested is False
    assert result.signal_queued is False
    assert result.cancelled_message_count == 0
    workflow = workflows.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert transitions.transitions == {}
    assert outbox.entries == {}
    assert messages.saved == [_pending_message()]
    assert [event.event_type for event in event_bus.events] == [
        DomainEventType.LEAD_ASSIGNMENT_RECONCILED,
    ]


async def test_reconcile_lead_assignment_publishes_resolution_change_without_pause() -> None:
    event_bus = FakeEventBus()

    result = await reconcile_lead_assignment_change(
        previous_lead=_lead(
            owner_id=FALLBACK_MANAGER_ID,
            source=EffectiveOwnerSource.WORKSPACE_MANAGER_FALLBACK,
            status=AssignmentResolutionStatus.UNMAPPED_CRM_AGENT,
        ),
        current_lead=_lead(
            owner_id=FALLBACK_MANAGER_ID,
            source=EffectiveOwnerSource.WORKSPACE_MANAGER_FALLBACK,
            status=AssignmentResolutionStatus.CRM_AGENT_INACTIVE,
        ),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        outbound_message_repository=FakeOutboundMessageRepository(),
        event_bus=event_bus,
        now=NOW,
    )

    assert result.status == LeadAssignmentReconciliationStatus.RECONCILED
    assert result.ownership_changed is False
    assert result.resolution_changed is True
    assert result.pause_requested is False
    assert [event.event_type for event in event_bus.events] == [
        DomainEventType.LEAD_ASSIGNMENT_RECONCILED,
    ]


async def test_reconcile_lead_assignment_noops_when_nothing_changed() -> None:
    current = _lead(owner_id=CURRENT_OWNER_ID)

    result = await reconcile_lead_assignment_change(
        previous_lead=current,
        current_lead=current,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        outbound_message_repository=FakeOutboundMessageRepository(),
        event_bus=FakeEventBus(),
        now=NOW,
    )

    assert result.status == LeadAssignmentReconciliationStatus.NO_CHANGE


def _lead(
    *,
    owner_id: UUID,
    source: EffectiveOwnerSource = EffectiveOwnerSource.CRM_MAPPING,
    status: AssignmentResolutionStatus = AssignmentResolutionStatus.RESOLVED,
) -> CanonicalLeadRecord:
    assigned_agent_user_id = owner_id if source == EffectiveOwnerSource.CRM_MAPPING else None
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_crm_id="agent-99",
        assigned_agent_user_id=assigned_agent_user_id,
        effective_owner_user_id=owner_id,
        effective_owner_source=source,
        assignment_resolution_status=status,
        assignment_last_resolved_at=NOW - timedelta(minutes=5),
        has_accountable_owner=True,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=UUID("10000000-0000-0000-0000-000000000010"),
        temporal_workflow_id="workflow-123",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("10000000-0000-0000-0000-000000000011"),
        campaign_id=UUID("10000000-0000-0000-0000-000000000012"),
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW,
        updated_at=NOW,
    )


def _pending_message() -> OutboundMessage:
    return OutboundMessage(
        message_id=UUID("10000000-0000-0000-0000-000000000013"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("10000000-0000-0000-0000-000000000012"),
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="pending-1",
        body="hello",
        created_at=NOW,
        updated_at=NOW,
        provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
    )