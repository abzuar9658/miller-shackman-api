import json
from datetime import UTC, datetime, time
from uuid import UUID

from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionStatus,
    CadenceStepScheduleStatus,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.application.use_cases.crm_sync import (
    RunFollowUpBossLeadSyncStatus,
    run_follow_up_boss_lead_snapshot_sync,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel, ContactPermissionStatus
from app.domain.conversations import Conversation, ConversationSummary, Handoff, InboundMessage
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType, ExternalEvent
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeEmailProvider,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
)

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
STEP_ID = UUID("00000000-0000-0000-0000-000000000005")
SYNC_JOB_ID = UUID("00000000-0000-0000-0000-000000000006")
EXTERNAL_EVENT_ID = UUID("00000000-0000-0000-0000-000000000007")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000008")
INBOUND_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000009")
SUMMARY_ID = UUID("00000000-0000-0000-0000-000000000010")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000011")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000012")


class FakeCRMSyncJobRepository:
    def __init__(self) -> None:
        self.saved: list[CRMSyncJob] = []

    async def get_by_id(self, workspace_id: WorkspaceId, sync_job_id: UUID) -> CRMSyncJob | None:
        return next((job for job in self.saved if job.sync_job_id == sync_job_id), None)

    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        return tuple(self.saved[-limit:])

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        self.saved.append(job)
        return job


class FakeLeadSnapshotSource:
    def __init__(self, pages: tuple[CanonicalLeadSnapshotPage, ...]) -> None:
        self.pages = list(pages)

    async def list_lead_snapshots(
        self,
        *,
        workspace_id: WorkspaceId,
        page_size: int = 100,
        cursor: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        return self.pages.pop(0)


class FakeExternalEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[WorkspaceId, str, str], ExternalEvent] = {}

    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        return self.events.get((workspace_id, provider, provider_event_id))

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events[(event.workspace_id, event.provider, event.provider_event_id)] = event
        return event


class FakeConversationRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, Conversation] = {}

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Conversation | None:
        matches = [
            conversation
            for conversation in self.by_id.values()
            if conversation.workspace_id == workspace_id and conversation.lead_id == lead_id
        ]
        return max(matches, key=lambda conversation: conversation.updated_at) if matches else None

    async def save(self, conversation: Conversation) -> Conversation:
        self.by_id[conversation.conversation_id] = conversation
        return conversation


class FakeInboundMessageRepository:
    def __init__(self) -> None:
        self.messages: dict[tuple[WorkspaceId, str, str], InboundMessage] = {}

    async def save(self, message: InboundMessage) -> InboundMessage:
        self.messages[
            (message.workspace_id, message.provider, message.provider_message_id)
        ] = message
        return message


class FakeConversationSummaryRepository:
    def __init__(self) -> None:
        self.saved: list[ConversationSummary] = []

    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        self.saved.append(summary)
        return summary


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.saved: list[Handoff] = []

    async def save(self, handoff: Handoff) -> Handoff:
        self.saved.append(handoff)
        return handoff


class FakeInboundReplyLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


async def test_business_flow_harness_runs_sync_to_handoff_path() -> None:
    lead_repository = FakeLeadRepository(None)
    sync_job_repository = FakeCRMSyncJobRepository()
    campaign_enrollment_repository = FakeCampaignEnrollmentRepository()
    lead_workflow_repository = FakeLeadWorkflowRepository()
    workflow_transition_repository = FakeWorkflowTransitionRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("email-123")
    conversations = FakeConversationRepository()
    inbound_messages = FakeInboundMessageRepository()
    summaries = FakeConversationSummaryRepository()
    handoffs = FakeHandoffRepository()

    sync_result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(
            pages=(CanonicalLeadSnapshotPage(leads=(_lead(),), next_cursor=None),)
        ),
        lead_repository=lead_repository,
        crm_sync_job_repository=sync_job_repository,
        now=NOW,
        sync_type=CRMSyncType.FULL,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert sync_result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert sync_result.job.sync_job_id == SYNC_JOB_ID
    assert sync_result.job.status == CRMSyncJobStatus.COMPLETED
    assert lead_repository.saved[-1].crm_lead_id == "crm-123"

    enrollment_result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=["business_flow_harness"],
        actor_user_id=ACTOR_ID,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        now=NOW,
    )

    assert enrollment_result.started_count == 1
    workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.QUEUED
    assert len(temporal_workflow_starter.calls) == 1

    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=lead_workflow_repository,
        now=NOW,
    )

    assert schedule_result.status == CadenceStepScheduleStatus.SCHEDULED
    assert schedule_result.cadence_step_id == STEP_ID
    assert schedule_result.scheduled_for == NOW

    execute_result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ID,
        scheduled_for=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW,
    )

    assert execute_result.status == CadenceStepExecutionStatus.SENT
    assert execute_result.workflow is not None
    assert execute_result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert execute_result.outbound_message_id is not None
    assert len(email_provider.messages) == 1

    inbound_result = await process_inbound_message_event(
        event=_event(),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=inbound_messages,
        conversation_summary_repository=summaries,
        handoff_repository=handoffs,
        llm_client=FakeInboundReplyLLMClient(_classification_json()),
        now=NOW,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.handoff_required is True
    assert inbound_result.handoff_id == HANDOFF_ID

    final_workflow = lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.HUMAN_HANDOFF
    assert final_workflow.current_step_id is None
    assert final_workflow.next_action_at is None

    transitions = await workflow_transition_repository.list_for_workflow(
        WORKSPACE_ID,
        final_workflow.workflow_id,
    )
    assert [transition.reason_code for transition in transitions] == [
        WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED,
        WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED,
    ]
    assert handoffs.saved[0].workflow_id == final_workflow.workflow_id
    assert handoffs.saved[0].assigned_agent_crm_id == "agent-99"
    assert conversations.by_id[CONVERSATION_ID].status.value == "human_handoff"
    assert summaries.saved[0].summary_id == SUMMARY_ID


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        primary_email="lead@example.com",
        has_email=True,
        email_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
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
        delay_hours=0,
        message_goal="Check whether the lead is still considering a move.",
        template_key="dormant-email-1",
        max_attempts=1,
        created_at=NOW,
    )


def _event() -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id="evt-1",
        provider_message_id="msg-1",
        crm_lead_id="crm-123",
        channel=ContactChannel.EMAIL,
        body="Can an agent call me today?",
        received_at=NOW,
        payload_redacted={"event": "redacted"},
    )


def _classification_json() -> str:
    return json.dumps(
        {
            "intent": "human_requested",
            "confidence": 0.94,
            "handoff_required": True,
            "handoff_reason": "human_requested",
            "opt_out_detected": False,
            "summary_text": "Lead asked for a human callback.",
            "preferences": {"timeline": "today"},
        }
    )