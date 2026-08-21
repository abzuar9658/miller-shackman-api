"""Run-isolation harness.

Executable guarantee that a lead never confuses an old track (run) with the
current one: a track switch closes the old run and the fresh run starts with
zeroed run-scoped state, its own idempotency space, and timing from its own
track — while person-scoped safety (consent) still binds across runs.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.application.services.paused_search_track_assignment import (
    PausedSearchTrackAssignmentSyncStatus,
    synchronize_paused_search_track_assignment,
)
from app.application.use_cases.plan_outbound_message import (
    OutboundPlanningContext,
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageStatus,
    plan_outbound_message,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackStatus,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000004")
TRACK_A_VERSION_ID = UUID("00000000-0000-0000-0000-00000000000a")
TRACK_B_VERSION_ID = UUID("00000000-0000-0000-0000-00000000000b")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000010")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000008")
RUN_A_WORKFLOW_ID = UUID("00000000-0000-0000-0000-0000000000aa")


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="waiting-rates",
        display_name="Waiting for rates",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=TRACK_B_VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _track_b_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=TRACK_B_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=2,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Track B: fresh cadence for the switched lead.",
        enabled=True,
        allowed_channels=(ContactChannel.SMS,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=30,
        reactivation_window_days=30,
        max_total_touches=4,
        max_ai_interactions=2,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _run_a_workflow() -> LeadWorkflow:
    """Run A mid-flight: it has spent budget, touches, and a step cursor."""
    return LeadWorkflow(
        workflow_id=RUN_A_WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:run-a",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW - timedelta(days=40),
        updated_at=NOW,
        paused_search_track_version_id=TRACK_A_VERSION_ID,
        paused_search_track_step_id=UUID("00000000-0000-0000-0000-0000000000f1"),
        logical_touch_count=3,
        ai_interaction_count=4,
    )


def _run_a_assignment() -> PausedSearchTrackAssignment:
    return PausedSearchTrackAssignment(
        assignment_id=UUID("00000000-0000-0000-0000-000000000006"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        track_id=TRACK_ID,
        track_version_id=TRACK_A_VERSION_ID,
        track_key_snapshot="waiting-rates",
        track_name_snapshot="Waiting for rates",
        track_version_snapshot=1,
        source=PausedSearchTrackAssignmentSource.CLASSIFICATION,
        assigned_by_user_id=USER_ID,
        assigned_at=NOW - timedelta(days=40),
    )


def _enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000011"),
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.ACTIVE,
        eligible_at=NOW - timedelta(days=40),
        enrolled_at=NOW - timedelta(days=40),
        started_at=NOW - timedelta(days=40),
        ended_at=None,
        created_by_user_id=USER_ID,
        reason_codes=("manual",),
        created_at=NOW - timedelta(days=40),
        updated_at=NOW,
    )


def _lead(*, sms_opted_out: bool = False) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-lead-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_phone="+15551230000",
        has_sms_capable_phone=True,
        has_email=False,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        sms_opted_out=sms_opted_out,
        suppression_types=(
            frozenset({SuppressionType.SMS_OPT_OUT}) if sms_opted_out else frozenset()
        ),
        do_not_contact=False,
        last_meaningful_communication_at=NOW - timedelta(days=90),
    )


def _planning_context(
    *,
    workflow_id: UUID,
    cadence_step_id: str = "step-1",
) -> OutboundPlanningContext:
    return OutboundPlanningContext(
        campaign_status=CampaignStatus.ACTIVE,
        workflow_state=WorkflowState.ACTIVE_NURTURE,
        enabled_channels=(ContactChannel.SMS,),
        workspace_contact_policy=WorkspaceContactPolicy(workspace_id=WORKSPACE_ID),
        campaign_goal="Stay in touch while the lead's search is paused.",
        brokerage_name="Miller Schackman",
        cadence_step_id=cadence_step_id,
        workflow_id=workflow_id,
        assigned_agent_name="Alex Agent",
        drafting_config=default_workspace_outbound_drafting_config(WORKSPACE_ID),
    )


async def _switch_track_a_to_track_b(
    *,
    workflows: FakeLeadWorkflowRepository,
    lead_sms_opted_out: bool = False,
) -> tuple[LeadWorkflow, LeadWorkflow, FakeWorkflowTransitionRepository]:
    """Run A is active on track A; the admin assigns track B. Returns
    (old run, new run, transitions)."""
    await workflows.save(_run_a_workflow())
    assignments = FakePausedSearchTrackAssignmentRepository((_run_a_assignment(),))
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()
    track_repository = FakePausedSearchTrackAdminRepository(
        tracks=(_track(),),
        versions=(_track_b_version(),),
    )

    result = await synchronize_paused_search_track_assignment(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        clear=False,
        actor_user_id=USER_ID,
        source=PausedSearchTrackAssignmentSource.OPERATOR,
        assignment_repository=assignments,
        track_repository=track_repository,
        lead_workflow_repository=workflows,
        now=NOW,
        target_track_version_id=TRACK_B_VERSION_ID,
        workflow_transition_repository=transitions,
        campaign_enrollment_repository=enrollments,
        temporal_workflow_starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.REASSIGNED
    assert result.error is None
    old_run = workflows.workflows[RUN_A_WORKFLOW_ID]
    new_run = result.workflow
    assert new_run is not None
    return old_run, new_run, transitions


@pytest.mark.asyncio
async def test_track_switch_starts_fresh_run_with_zeroed_journey_state() -> None:
    """Track B cannot see track A's journey state: budget, touches, and the
    step cursor all start from zero on a brand-new workflow row."""
    workflows = FakeLeadWorkflowRepository()

    old_run, new_run, transitions = await _switch_track_a_to_track_b(workflows=workflows)

    # Old run is terminal and audited — immutable history.
    assert old_run.state is WorkflowState.CLOSED
    assert any(
        transition.reason_code is WorkflowTransitionReasonCode.TRACK_REASSIGNED
        for transition in transitions.transitions.values()
    )

    # New run is a different row pinned to track B with zeroed run-scoped state.
    assert new_run.workflow_id != old_run.workflow_id
    assert new_run.state is WorkflowState.ACTIVE_NURTURE
    assert new_run.paused_search_track_version_id == TRACK_B_VERSION_ID
    assert new_run.paused_search_track_step_id is None
    assert new_run.logical_touch_count == 0
    assert new_run.ai_interaction_count == 0
    assert new_run.campaign_enrollment_id != old_run.campaign_enrollment_id
    assert new_run.temporal_workflow_id != old_run.temporal_workflow_id


@pytest.mark.asyncio
async def test_new_run_plans_first_send_despite_old_run_message_history() -> None:
    """Track A already sent a message for the "same" step id. The new run must
    still plan its own first send: idempotency keys are scoped by workflow_id,
    and no frequency rule reads the lead's old-run send history."""
    workflows = FakeLeadWorkflowRepository()
    messages = FakeOutboundMessageRepository()

    # Run A sent a step-1 SMS one hour ago — recent enough that any lead-wide
    # frequency rule would have blocked the new run's first send.
    old_message = OutboundMessage(
        message_id=UUID("00000000-0000-0000-0000-0000000000c1"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        workflow_id=RUN_A_WORKFLOW_ID,
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.SENT,
        idempotency_key=(
            f"outbound:{WORKSPACE_ID}:{CAMPAIGN_ID}:{LEAD_ID}"
            f":wf:{RUN_A_WORKFLOW_ID}:step-1:sms:v1"
        ),
        body="Old run message.",
        sent_at=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
    )
    await messages.save(old_message)

    old_run, new_run, _ = await _switch_track_a_to_track_b(workflows=workflows)

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_id=new_run.workflow_id),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=FakeLLMClient(subject=None),
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.message is not None
    assert result.message.workflow_id == new_run.workflow_id
    assert result.message.message_version == 1
    # Distinct idempotency space: old and new runs never collide.
    assert result.message.idempotency_key != old_message.idempotency_key
    assert f":wf:{new_run.workflow_id}:" in result.message.idempotency_key


@pytest.mark.asyncio
async def test_duplicate_within_the_same_run_is_still_rejected() -> None:
    """Isolation removes cross-run interference, not the duplicate guard:
    planning the same step twice within one run is a duplicate."""
    workflows = FakeLeadWorkflowRepository()
    messages = FakeOutboundMessageRepository()
    _, new_run, _ = await _switch_track_a_to_track_b(workflows=workflows)

    first = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_id=new_run.workflow_id),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=FakeLLMClient(subject=None),
        now=NOW,
    )
    assert first.status == PlanOutboundMessageStatus.PLANNED

    second = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_id=new_run.workflow_id),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=FakeLLMClient(subject=None),
        now=NOW,
    )
    assert second.status == PlanOutboundMessageStatus.DUPLICATE


@pytest.mark.asyncio
async def test_consent_from_old_run_still_binds_new_run() -> None:
    """Person-scoped safety survives the switch: an SMS opt-out recorded
    during track A blocks track B's sends too."""
    workflows = FakeLeadWorkflowRepository()
    _, new_run, _ = await _switch_track_a_to_track_b(workflows=workflows)

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_id=new_run.workflow_id),
        lead_repository=FakeLeadRepository(_lead(sms_opted_out=True)),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(subject=None),
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert PlanOutboundMessageReasonCode.CHANNEL_NOT_CONTACTABLE in result.reasons
