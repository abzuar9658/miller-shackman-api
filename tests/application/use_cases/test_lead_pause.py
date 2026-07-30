from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.lead_pause import (
    LeadPauseActionReasonCode,
    LeadPauseActionStatus,
    pause_lead_workflow,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases.test_lead_resume import (
    FakeExternalEventRepository,
    _noop_commit,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")


async def test_pause_lead_workflow_transitions_workflow_and_queues_pause_signal() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.ACTIVE_NURTURE)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow
    outbox = FakeTemporalSignalOutboxRepository()

    result = await pause_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="Agent requested a manual pause while they take over.",
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=outbox,
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadPauseActionStatus.REQUESTED
    assert result.signal_queued is True
    latest = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert latest.state == WorkflowState.PAUSED
    assert latest.pause_reason == "manual_pause"
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name == TemporalSignalName.PAUSE_REQUESTED
    assert entry.payload["reason"] == "Agent requested a manual pause while they take over."


async def test_pause_lead_workflow_rejects_assigned_agent_for_unowned_lead() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.ACTIVE_NURTURE)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow

    result = await pause_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="pause",
        lead_repository=FakeLeadRepository(_lead(assigned_agent_user_id=UUID(int=999))),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadPauseActionStatus.REJECTED
    assert result.reasons == (LeadPauseActionReasonCode.PERMISSION_DENIED,)


async def test_pause_lead_workflow_returns_not_pausable_for_human_handoff() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.HUMAN_HANDOFF)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow

    result = await pause_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="pause",
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadPauseActionStatus.NOT_PAUSABLE
    assert result.reasons == (LeadPauseActionReasonCode.WORKFLOW_STATE_NOT_PAUSABLE,)


def _lead(*, assigned_agent_user_id: UUID = USER_ID) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        assigned_agent_user_id=assigned_agent_user_id,
        effective_owner_user_id=assigned_agent_user_id,
        has_accountable_owner=True,
        primary_email="lead@example.com",
        primary_phone="+15555550100",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
    )


def _workflow(state: WorkflowState) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-workflow-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000006"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000007"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )