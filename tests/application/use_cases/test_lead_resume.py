from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.lead_resume import (
    LeadResumeActionStatus,
    LeadResumeEligibilityReasonCode,
    LeadResumeEligibilityStatus,
    get_lead_resume_eligibility,
    resume_lead_workflow,
)
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    ContactSuppressionKind,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.crm_sync import ExternalEvent
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    WorkflowState,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000005")


async def test_resume_eligibility_returns_resumable_for_contactable_paused_workflow() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(
        WorkflowState.PAUSED,
        pause_reason=WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED.value,
    )
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is True
    assert result.eligibility.contactable_channels == (ContactChannel.SMS, ContactChannel.EMAIL)


async def test_resume_eligibility_blocks_assigned_agent_for_handoff_state() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.HUMAN_HANDOFF)
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is False
    assert result.eligibility.reasons == (
        LeadResumeEligibilityReasonCode.HANDOFF_REQUIRES_MANAGER,
    )


async def test_resume_eligibility_blocks_assigned_agent_for_opt_out_pause() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(
        WorkflowState.PAUSED,
        pause_reason=WorkflowTransitionReasonCode.OPT_OUT_DETECTED.value,
    )
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is False
    assert result.eligibility.reasons == (
        LeadResumeEligibilityReasonCode.SUPPRESSION_REQUIRES_MANAGER,
    )


async def test_resume_eligibility_allows_manager_for_opt_out_pause() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(
        WorkflowState.PAUSED,
        pause_reason=ContactSuppressionKind.SMS_OPT_OUT.value,
    )
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    lead = _lead(
        sms_permission_status=ContactPermissionStatus.DENIED,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
    )

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(lead),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is True
    assert result.eligibility.contactable_channels == (ContactChannel.EMAIL,)


async def test_resume_eligibility_blocks_suppressed_workflow() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.SUPPRESSED)
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is False
    assert result.eligibility.reasons == (
        LeadResumeEligibilityReasonCode.SUPPRESSION_NOT_RESUMABLE,
    )


async def test_resume_eligibility_blocks_active_workflow() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.WAITING_FOR_RESPONSE)
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is False
    assert result.eligibility.reasons == (
        LeadResumeEligibilityReasonCode.WORKFLOW_ALREADY_ACTIVE,
    )


async def test_resume_eligibility_blocks_when_no_contactable_channels_exist() -> None:
    blocked_lead = _lead(
        has_sms_capable_phone=False,
        has_email=False,
        sms_permission_status=ContactPermissionStatus.UNKNOWN,
        email_permission_status=ContactPermissionStatus.UNKNOWN,
    )
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.PAUSED)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await get_lead_resume_eligibility(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(blocked_lead),
        workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(workspace_id=WORKSPACE_ID)
        ),
    )

    assert result.status == LeadResumeEligibilityStatus.OK
    assert result.eligibility is not None
    assert result.eligibility.can_resume is False
    assert LeadResumeEligibilityReasonCode.NO_CONTACTABLE_CHANNELS in result.eligibility.reasons


async def test_resume_lead_workflow_transitions_workflow_and_queues_resume_signal() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.HUMAN_HANDOFF)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow
    outbox = FakeTemporalSignalOutboxRepository()

    result = await resume_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="agent approved follow-up",
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=outbox,
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadResumeActionStatus.REQUESTED
    assert result.signal_queued is True
    latest = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert latest.state == WorkflowState.ACTIVE_NURTURE
    assert len(outbox.entries) == 1
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name == TemporalSignalName.RESUME_REQUESTED
    assert entry.temporal_workflow_id == workflow.temporal_workflow_id
    assert entry.payload["reason"] == "agent approved follow-up"


async def test_resume_lead_workflow_rejects_assigned_agent_for_unowned_lead() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.PAUSED)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow

    transitions = FakeWorkflowTransitionRepository()
    result = await resume_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="resume",
        lead_repository=FakeLeadRepository(_lead(assigned_agent_user_id=UUID(int=999))),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
        workflow_transition_repository=transitions,
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadResumeActionStatus.REJECTED
    assert len(transitions.transitions) == 0


async def test_resume_lead_workflow_records_transition_and_outbox_entry() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.PAUSED)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow
    transitions = FakeWorkflowTransitionRepository()
    outbox = FakeTemporalSignalOutboxRepository()
    committed = False

    async def commit() -> None:
        nonlocal committed
        committed = True

    result = await resume_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="resume after review",
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
        workflow_transition_repository=transitions,
        temporal_signal_outbox_repository=outbox,
        external_event_repository=FakeExternalEventRepository(),
        commit=commit,
        now=NOW,
    )

    assert result.status == LeadResumeActionStatus.REQUESTED
    assert result.signal_queued is True
    assert committed is True
    latest = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert latest.state == WorkflowState.ACTIVE_NURTURE
    assert len(transitions.transitions) == 1
    assert len(outbox.entries) == 1


async def test_resume_lead_workflow_does_not_resume_handoff_for_assigned_agent() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow(WorkflowState.HUMAN_HANDOFF)
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    workflow_repository.workflows[workflow.workflow_id] = workflow
    transitions = FakeWorkflowTransitionRepository()
    outbox = FakeTemporalSignalOutboxRepository()

    result = await resume_lead_workflow(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="resume after handoff",
        lead_repository=FakeLeadRepository(_lead()),
        workflow_repository=workflow_repository,
        lead_workflow_repository=workflow_repository,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_policy()),
        workflow_transition_repository=transitions,
        temporal_signal_outbox_repository=outbox,
        external_event_repository=FakeExternalEventRepository(),
        commit=_noop_commit,
        now=NOW,
    )

    assert result.status == LeadResumeActionStatus.NOT_RESUMABLE
    assert result.eligibility is not None
    assert result.eligibility.reasons == (
        LeadResumeEligibilityReasonCode.HANDOFF_REQUIRES_MANAGER,
    )
    assert len(transitions.transitions) == 0
    assert len(outbox.entries) == 0


def _lead(
    *,
    assigned_agent_user_id: UUID = USER_ID,
    has_sms_capable_phone: bool = True,
    has_email: bool = True,
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        has_accountable_owner=True,
        mapped_custom_fields={"assigned_agent_user_id": str(assigned_agent_user_id)},
        primary_email="lead@example.com" if has_email else None,
        primary_phone="+15555550100" if has_sms_capable_phone else None,
        has_email=has_email,
        has_phone=has_sms_capable_phone,
        has_sms_capable_phone=has_sms_capable_phone,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
    )


def _workflow(state: WorkflowState, *, pause_reason: str | None = None) -> LeadWorkflow:
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
        pause_reason=pause_reason,
    )


def _policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
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


async def _noop_commit() -> None:
    return None


class FakeExternalEventRepository:
    async def save(self, event: ExternalEvent) -> ExternalEvent:
        return event

    async def get_by_provider_event_id(
        self,
        workspace_id: UUID,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        return None
