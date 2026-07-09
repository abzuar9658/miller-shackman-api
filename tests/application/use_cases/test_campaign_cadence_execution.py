from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from app.application.use_cases.campaign_cadence_execution import (
    FirstCadenceStepExecutionStatus,
    FirstCadenceStepScheduleStatus,
    execute_first_campaign_cadence_step,
    schedule_first_campaign_cadence_step,
)
from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.compliance.contactability import ContactChannel, ContactPermissionStatus
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
STEP_ID = UUID("00000000-0000-0000-0000-000000000007")


async def test_schedule_first_campaign_cadence_step_sets_due_time_and_current_step() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())

    result = await schedule_first_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    assert result.status == FirstCadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == STEP_ID
    assert result.scheduled_for == NOW + timedelta(hours=24)
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id == STEP_ID
    assert saved_workflow.next_action_at == NOW + timedelta(hours=24)


async def test_execute_first_campaign_cadence_step_sends_email_and_waits_for_response() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_first_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("email-123")
    result = await execute_first_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW + timedelta(hours=24),
    )

    assert result.status == FirstCadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.cadence_step_id == STEP_ID
    assert len(email_provider.messages) == 1
    assert message_repository.saved[-1].provider_message_id == "email-123"
    assert message_repository.saved[-1].status.value == "sent"
    assert [
        transition.reason_code for transition in transition_repository.transitions.values()
    ] == [
        WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
    ]


async def test_execute_first_campaign_cadence_step_pauses_when_planning_is_blocked() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_first_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    email_provider = FakeEmailProvider("email-123")
    result = await execute_first_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        lead_repository=FakeLeadRepository(_lead(has_email=False)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW + timedelta(hours=24),
    )

    assert result.status == FirstCadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    assert email_provider.messages == []
    assert list(transition_repository.transitions.values())[-1].reason_code == (
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.QUEUED,
        current_step_id=None,
        next_action_at=None,
        last_transition_at=NOW,
        pause_reason=None,
        resume_reason=None,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Miller Schackman",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Chicago",
        created_at=NOW,
        updated_at=NOW,
    )


def _lead(*, has_email: bool = True) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        primary_email="lead@example.com" if has_email else None,
        has_email=has_email,
        email_count=1 if has_email else 0,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


def _config() -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(_step(),),
        created_at=NOW,
        published_at=NOW,
    )


def _step() -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        step_order=1,
        channel=ContactChannel.EMAIL,
        delay_hours=24,
        message_goal="Check whether the lead is still considering a move.",
        template_key="dormant-email-1",
        max_attempts=1,
        created_at=NOW,
    )
