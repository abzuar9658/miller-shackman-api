from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionStatus,
    CadenceStepScheduleStatus,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakeRejectedDraftReviewRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceRepository,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000007")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000008")


def _crm_event(
    *,
    crm_activity_id: str,
    content: str,
    direction: CrmConversationEventDirection,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction=direction,
        occurred_at=NOW,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_schedule_next_campaign_cadence_step_sets_due_time_and_current_step() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    await workflow_repository.save(_workflow())

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    assert result.status == CadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == STEP_ONE_ID
    assert result.scheduled_for == NOW + timedelta(hours=24)
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id == STEP_ONE_ID
    assert saved_workflow.next_action_at == NOW + timedelta(hours=24)


async def test_execute_campaign_cadence_step_sends_first_step_and_advances_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    llm_client = FakeLLMClient()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("email-123")
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=message_repository,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            (
                _crm_event(
                    crm_activity_id="act-1",
                    content="Sent a check-in email last week.",
                    direction=CrmConversationEventDirection.OUTBOUND,
                ),
                _crm_event(
                    crm_activity_id="act-2",
                    content="We are hoping to move before school starts.",
                    direction=CrmConversationEventDirection.INBOUND,
                ),
            )
        ),
        llm_client=llm_client,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.workflow.current_step_id == STEP_TWO_ID
    assert result.workflow.next_action_at is None
    assert result.cadence_step_id == STEP_ONE_ID
    assert result.has_more_steps is True
    assert len(email_provider.messages) == 1
    assert message_repository.saved[-1].provider_message_id == "email-123"
    assert message_repository.saved[-1].status.value == "sent"
    assert [
        transition.reason_code for transition in transition_repository.transitions.values()
    ] == [
        WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
    ]
    assert len(llm_client.requests) == 1
    assert "Recent CRM conversation history:" in llm_client.requests[0].prompt
    assert "We are hoping to move before school starts." in llm_client.requests[0].prompt


async def test_schedule_next_campaign_cadence_step_schedules_second_step_after_first_send() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    await _send_first_step(
        workflow_repository=workflow_repository,
        transition_repository=transition_repository,
    )

    result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )

    assert result.status == CadenceStepScheduleStatus.SCHEDULED
    assert result.cadence_step_id == STEP_TWO_ID
    assert result.scheduled_for == NOW + timedelta(days=1, hours=48)
    saved_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved_workflow.current_step_id == STEP_TWO_ID
    assert saved_workflow.next_action_at == NOW + timedelta(days=1, hours=48)


async def test_execute_campaign_cadence_step_sends_final_step_without_advancing_cursor() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    await _send_first_step(
        workflow_repository=workflow_repository,
        transition_repository=transition_repository,
    )
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW + timedelta(days=1),
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_TWO_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("email-456"),
        now=datetime(2026, 7, 12, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.workflow.current_step_id == STEP_TWO_ID
    assert result.workflow.next_action_at is None
    assert result.has_more_steps is False


async def test_execute_campaign_cadence_step_pauses_when_planning_is_blocked() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    email_provider = FakeEmailProvider("email-123")
    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead(has_email=False)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    assert result.workflow.current_step_id == STEP_ONE_ID
    assert result.workflow.next_action_at is None
    assert email_provider.messages == []
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == (
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
    )
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["channel_destination_missing"]
    assert last_transition.metadata["evaluated_channels"] == ["email"]
    assert last_transition.metadata["channel_block_outcomes"] == ["missing_destination"]
    assert "Planning blocked: channel destination missing." in last_transition.metadata[
        "explanation"
    ]


async def test_execute_campaign_cadence_step_persists_rich_draft_rejection_details() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    review_repository = FakeRejectedDraftReviewRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        rejected_draft_review_repository=review_repository,
        llm_client=FakeLLMClient(
            safety_flags=("property_advice_requested", "tour_request_detected"),
        ),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.reason_code == (
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
    )
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["draft_rejected"]
    assert last_transition.metadata["draft_reasons"] == ["safety_flags_present"]
    assert last_transition.metadata["draft_safety_flags"] == [
        "property_advice_requested",
        "tour_request_detected",
    ]
    assert last_transition.metadata["draft_confidence"] == 0.91
    assert last_transition.metadata["draft_model"] == "openai/gpt-4o-mini"
    assert last_transition.metadata["draft_prompt_version"] == "outbound_message_draft:v1"
    assert last_transition.metadata["selected_channel"] == "email"
    assert "Draft validation failed: safety flags present." in last_transition.metadata[
        "explanation"
    ]
    assert "Safety flags: property advice requested, tour request detected." in (
        last_transition.metadata["explanation"]
    )
    assert len(review_repository.saved) == 1
    assert review_repository.saved[0].draft_body == "Hi — just checking in."
    assert review_repository.saved[0].review_blockers == ("safety_flags_present",)
    assert review_repository.saved[0].can_approve_send is False


async def test_execute_campaign_cadence_step_allows_sms_without_compliance_gate() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.SMS,))
        ),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(channels=(ContactChannel.SMS,))
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(sms_compliance_state=SmsComplianceState.NOT_APPROVED)
        ),
        lead_repository=FakeLeadRepository(_lead(has_phone=True)),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.SENT
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE


async def test_execute_campaign_cadence_step_respects_persisted_quiet_hours() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    await workflow_repository.save(_workflow())
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )

    result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy(
                quiet_hours_start=time(10, 0),
                quiet_hours_end=time(17, 0),
            )
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
    )

    assert result.status == CadenceStepExecutionStatus.REJECTED
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED
    last_transition = list(transition_repository.transitions.values())[-1]
    assert last_transition.metadata["block_stage"] == "planning"
    assert last_transition.metadata["reason_codes"] == ["pre_send_blocked"]
    assert last_transition.metadata["evaluated_channels"] == ["email"]
    assert last_transition.metadata["channel_block_outcomes"] == ["pre_send_blocked"]
    assert last_transition.metadata["pre_send_reasons"] == ["outside_allowed_hours"]
    assert last_transition.metadata["next_allowed_at"] == "2026-07-10T15:00:00+00:00"


async def _send_first_step(
    *,
    workflow_repository: FakeLeadWorkflowRepository,
    transition_repository: FakeWorkflowTransitionRepository,
) -> None:
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        now=NOW,
    )
    await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ONE_ID,
        scheduled_for=schedule_result.scheduled_for or NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _workspace_contact_policy()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        message_repository=FakeOutboundMessageRepository(),
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("email-123"),
        now=datetime(2026, 7, 10, 15, 0, tzinfo=UTC),
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


def _workspace_contact_policy(
    *,
    sms_compliance_state: SmsComplianceState = SmsComplianceState.APPROVED,
    quiet_hours_start: time = time(10, 0),
    quiet_hours_end: time = time(17, 0),
) -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=sms_compliance_state,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )


def _lead(*, has_email: bool = True, has_phone: bool = False) -> CanonicalLeadRecord:
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
        primary_phone="+15551234567" if has_phone else None,
        has_phone=has_phone,
        has_sms_capable_phone=has_phone,
        phone_count=1 if has_phone else 0,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


def _config(
    *,
    channels: tuple[ContactChannel, ...] = (ContactChannel.EMAIL,),
) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=channels,
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        crm_enrollment_tag=None,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=_steps(channels=channels),
        created_at=NOW,
        published_at=NOW,
    )


def _steps(
    *,
    channels: tuple[ContactChannel, ...],
) -> tuple[CampaignCadenceStep, ...]:
    first_channel = channels[0]
    second_channel = channels[-1]
    return (
        _step(
            cadence_step_id=STEP_ONE_ID,
            step_order=1,
            channel=first_channel,
            delay_hours=24,
            template_key="dormant-step-1",
        ),
        _step(
            cadence_step_id=STEP_TWO_ID,
            step_order=2,
            channel=second_channel,
            delay_hours=48,
            template_key="dormant-step-2",
        ),
    )


def _step(
    *,
    cadence_step_id: UUID,
    step_order: int,
    channel: ContactChannel,
    delay_hours: int,
    template_key: str,
) -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=cadence_step_id,
        workspace_id=WORKSPACE_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        step_order=step_order,
        channel=channel,
        delay_hours=delay_hours,
        message_goal="Check whether the lead is still considering a move.",
        template_key=template_key,
        max_attempts=1,
        created_at=NOW,
    )
