import json
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import NamedTuple, cast
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent, CRMClient
from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.ports.notifications import (
    HandoffNotification,
    NotificationProvider,
    NotificationSendResult,
)
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
from app.application.use_cases.evaluate_inbound_action import InboundAction
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    CRMTagCampaignEnrollmentStatus,
    process_crm_tag_campaign_enrollment,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns import (
    CampaignStatus,
    CampaignVersionStatus,
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrackFamily,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import (
    Conversation,
    ConversationSummary,
    Handoff,
    HandoffCompletionRecord,
    InboundMessage,
    WorkspaceHandoffConfig,
)
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    ExternalEvent,
)
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    PausedSearchReasonCode,
)
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_admin_fakes import FakeEventBus
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeClassificationLLMClient,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeInboundMessageCRMCompletionRepository,
    _draft_json,
    _FakeLLMClientForContinuation,
    _lead_state_classification_json,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeLLMClient as FakeInboundLLMClient,
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
PAUSED_SEARCH_TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000013")
PAUSED_SEARCH_STEP_ID = UUID("00000000-0000-0000-0000-000000000014")


class _PreparedBusinessFlow(NamedTuple):
    lead_repository: FakeLeadRepository
    lead_workflow_repository: FakeLeadWorkflowRepository
    workflow_transition_repository: FakeWorkflowTransitionRepository
    message_repository: FakeOutboundMessageRepository
    conversations: "FakeConversationRepository"
    inbound_messages: "FakeInboundMessageRepository"
    summaries: "FakeConversationSummaryRepository"


class FakeCRMSyncJobRepository:
    def __init__(self) -> None:
        self.saved: list[CRMSyncJob] = []
        self.active_job: CRMSyncJob | None = None
        self.latest_job: CRMSyncJob | None = None
        self.latest_completed_job: CRMSyncJob | None = None

    async def get_by_id(self, workspace_id: WorkspaceId, sync_job_id: UUID) -> CRMSyncJob | None:
        return next((job for job in reversed(self.saved) if job.sync_job_id == sync_job_id), None)

    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        return tuple(self.saved[-limit:])

    async def get_latest_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        _ = (workspace_id, crm_provider)
        return self.latest_job

    async def get_latest_completed_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        _ = (workspace_id, crm_provider)
        return self.latest_completed_job

    async def get_active_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        _ = (workspace_id, crm_provider)
        return self.active_job

    async def insert_pending_if_no_active(self, job: CRMSyncJob) -> CRMSyncJob | None:
        if self.active_job is not None:
            return None
        self.active_job = job
        self.latest_job = job
        self.saved.append(job)
        return job

    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        pending = next(
            (
                job
                for job in self.saved
                if job.workspace_id == workspace_id
                and job.sync_job_id == sync_job_id
                and job.status == CRMSyncJobStatus.PENDING
            ),
            None,
        )
        if pending is None:
            return None
        claimed = replace(
            pending,
            status=CRMSyncJobStatus.RUNNING,
            started_at=now,
            last_heartbeat_at=now,
            updated_at=now,
        )
        self.active_job = claimed
        self.latest_job = claimed
        self.saved.append(claimed)
        return claimed

    async def fail_stale_active_jobs(
        self,
        *,
        now: datetime,
        pending_timeout_seconds: int,
        running_timeout_seconds: int,
    ) -> int:
        _ = (now, pending_timeout_seconds, running_timeout_seconds)
        return 0

    async def touch_running_heartbeat(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        running = next(
            (
                job
                for job in reversed(self.saved)
                if job.workspace_id == workspace_id
                and job.sync_job_id == sync_job_id
                and job.status == CRMSyncJobStatus.RUNNING
            ),
            None,
        )
        if running is None:
            return None
        touched = replace(running, last_heartbeat_at=now, updated_at=now)
        self.active_job = touched
        self.latest_job = touched
        self.saved.append(touched)
        return touched

    async def save_if_running(self, job: CRMSyncJob) -> CRMSyncJob | None:
        if self.active_job is None or self.active_job.sync_job_id != job.sync_job_id:
            return None
        if self.active_job.status != CRMSyncJobStatus.RUNNING:
            return None
        return await self.save(job)

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        self.saved.append(job)
        self.latest_job = job
        self.active_job = (
            job if job.status in {CRMSyncJobStatus.PENDING, CRMSyncJobStatus.RUNNING} else None
        )
        if job.status == CRMSyncJobStatus.COMPLETED:
            self.latest_completed_job = job
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
        sort_by: CRMSyncLeadSort | None = None,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        _ = (
            workspace_id,
            page_size,
            cursor,
            updated_after,
            updated_before,
            sort_by,
            mapped_custom_field_keys,
        )
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
        self.messages_by_id: dict[tuple[WorkspaceId, UUID], InboundMessage] = {}

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> InboundMessage | None:
        return self.messages_by_id.get((workspace_id, inbound_message_id))

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        matches = tuple(
            sorted(
                (
                    message
                    for message in self.messages_by_id.values()
                    if message.workspace_id == workspace_id and message.lead_id == lead_id
                ),
                key=lambda message: message.received_at,
                reverse=True,
            )
        )
        return matches[:limit]

    async def save(self, message: InboundMessage) -> InboundMessage:
        self.messages[(message.workspace_id, message.provider, message.provider_message_id)] = (
            message
        )
        self.messages_by_id[(message.workspace_id, message.inbound_message_id)] = message
        return message


class FakeConversationSummaryRepository:
    def __init__(self) -> None:
        self.saved: list[ConversationSummary] = []

    async def get_latest_for_conversation(
        self,
        workspace_id: WorkspaceId,
        conversation_id: UUID,
    ) -> ConversationSummary | None:
        matches = [
            summary
            for summary in self.saved
            if summary.workspace_id == workspace_id and summary.conversation_id == conversation_id
        ]
        return max(matches, key=lambda summary: summary.created_at) if matches else None

    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        self.saved.append(summary)
        return summary


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.saved: list[Handoff] = []
        self.by_id: dict[UUID, Handoff] = {}

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        handoffs = tuple(
            handoff
            for handoff in self.saved
            if handoff.workspace_id == workspace_id and handoff.lead_id == lead_id
        )
        return handoffs[:limit]

    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        handoffs = tuple(
            handoff for handoff in self.saved if handoff.workspace_id == workspace_id
        )
        return handoffs[:limit]

    async def get_by_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Handoff | None:
        handoff = self.by_id.get(handoff_id)
        if handoff is None or handoff.workspace_id != workspace_id:
            return None
        return handoff

    async def save(self, handoff: Handoff) -> Handoff:
        self.saved.append(handoff)
        self.by_id[handoff.handoff_id] = handoff
        return handoff


class FakeHandoffCompletionRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, HandoffCompletionRecord] = {}

    async def get_by_handoff_id(
        self,
        workspace_id: WorkspaceId,
        handoff_id: UUID,
    ) -> HandoffCompletionRecord | None:
        record = self.by_id.get(handoff_id)
        if record is None or record.workspace_id != workspace_id:
            return None
        return record

    async def save(self, record: HandoffCompletionRecord) -> HandoffCompletionRecord:
        self.by_id[record.handoff_id] = record
        return record


class FakeWorkspaceHandoffConfigRepository:
    def __init__(self, config: WorkspaceHandoffConfig | None = None) -> None:
        self.config = config

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceHandoffConfig | None:
        if self.config is None or self.config.workspace_id != workspace_id:
            return None
        return self.config

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        self.config = config
        return config


class FakeCRMClient:
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    def __init__(self) -> None:
        self.notes: list[tuple[WorkspaceId, str, str]] = []
        self.note_subjects: list[str | None] = []
        self.tags: list[tuple[WorkspaceId, str, str]] = []
        self.updated_fields: list[tuple[WorkspaceId, str, dict[str, str]]] = []

    async def validate_connection(self, workspace_id: WorkspaceId) -> bool:
        _ = workspace_id
        return True

    async def get_lead(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CanonicalLead | None:
        _ = (workspace_id, crm_lead_id)
        return None

    async def search_leads(
        self,
        workspace_id: WorkspaceId,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        _ = (workspace_id, tag, limit)
        return []

    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        _ = (workspace_id, crm_lead_id, limit)
        return []

    async def get_assigned_agent(
        self, workspace_id: WorkspaceId, crm_lead_id: str
    ) -> CRMAgent | None:
        return CRMAgent(crm_agent_id="agent-99", name="Agent Smith", email="agent@example.com")

    async def get_lead_url(self, workspace_id: WorkspaceId, crm_lead_id: str) -> str | None:
        return f"https://app.followupboss.com/2/people/{crm_lead_id}"

    async def add_note(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        self.notes.append((workspace_id, crm_lead_id, content))
        self.note_subjects.append(subject)

    async def add_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        self.tags.append((workspace_id, crm_lead_id, tag))

    async def remove_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        _ = (workspace_id, crm_lead_id, tag)

    async def update_custom_fields(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        self.updated_fields.append((workspace_id, crm_lead_id, fields))

    async def subscribe_to_events(self, workspace_id: WorkspaceId, webhook_url: str) -> None:
        _ = (workspace_id, webhook_url)

    async def fetch_resource_by_uri(
        self, workspace_id: WorkspaceId, uri: str
    ) -> dict[str, object] | None:
        _ = (workspace_id, uri)
        return None


class FakeNotificationProvider:
    def __init__(self) -> None:
        self.notifications: list[HandoffNotification] = []

    async def send_handoff_notification(
        self,
        notification: HandoffNotification,
    ) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult(accepted=True, provider_reference="notif-123")

    async def send_preflight_digest(
        self, notification: object
    ) -> NotificationSendResult:  # pragma: no cover
        raise AssertionError("preflight digest should not be used in business flow harness")


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
    handoff_completions = FakeHandoffCompletionRepository()
    workspace_handoff_config_repository = FakeWorkspaceHandoffConfigRepository(
        WorkspaceHandoffConfig(
            workspace_id=WORKSPACE_ID,
            fallback_recipient_email="fallback@example.com",
            crm_handoff_tag="human_handoff_required",
            crm_custom_fields={"handoff_status": "required"},
        )
    )
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

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
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
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
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        handoff_completion_repository=handoff_completions,
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
    assert inbound_result.handoff_completion_failure_reason is None

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
    assert handoffs.by_id[HANDOFF_ID].status.value == "notified"
    assert conversations.by_id[CONVERSATION_ID].status.value == "human_handoff"
    assert summaries.saved[0].summary_id == SUMMARY_ID
    assert len(notification_provider.notifications) == 1
    assert crm_client.tags == [(WORKSPACE_ID, "crm-123", "human_handoff_required")]


async def test_business_flow_harness_runs_crm_tag_to_paused_search_send_to_handoff() -> None:
    lead_repository = FakeLeadRepository(None)
    enrollments = FakeCampaignEnrollmentRepository()
    workflow_repository = FakeLeadWorkflowRepository()
    workflow_transitions = FakeWorkflowTransitionRepository()
    temporal_workflow_starter = FakeTemporalWorkflowStarter()
    message_repository = FakeOutboundMessageRepository()
    email_provider = FakeEmailProvider("paused-email-123")
    conversations = FakeConversationRepository()
    inbound_messages = FakeInboundMessageRepository()
    summaries = FakeConversationSummaryRepository()
    handoffs = FakeHandoffRepository()
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

    tagged_lead = _lead(tags=("configured_tag",))
    await lead_repository.upsert(tagged_lead)

    enrollment_result = await process_crm_tag_campaign_enrollment(
        workspace_id=WORKSPACE_ID,
        lead=tagged_lead,
        observed_at=NOW,
        now=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _config(crm_enrollment_tag="configured_tag")
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(_contact_policy()),
        campaign_enrollment_repository=enrollments,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=workflow_transitions,
        temporal_workflow_starter=temporal_workflow_starter,
        lead_repository=lead_repository,
        paused_search_history_repository=lead_repository,
        paused_search_track_repository=_paused_search_track_repository(),
        artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        llm_client=FakeClassificationLLMClient(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            summary="Lead wants to wait for better mortgage rates.",
        ),
        event_bus=FakeEventBus(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(None),
    )

    assert enrollment_result.status == CRMTagCampaignEnrollmentStatus.STARTED
    assert enrollment_result.route == "paused_search"
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.paused_search_track_version_id == PAUSED_SEARCH_TRACK_VERSION_ID

    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=workflow_repository,
        lead_repository=lead_repository,
        paused_search_track_repository=_paused_search_track_repository(),
        now=NOW,
    )

    assert schedule_result.status == CadenceStepScheduleStatus.SCHEDULED
    assert schedule_result.cadence_step_id == PAUSED_SEARCH_STEP_ID

    execute_result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=PAUSED_SEARCH_STEP_ID,
        scheduled_for=NOW,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        paused_search_track_repository=_paused_search_track_repository(),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        lead_repository=lead_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=workflow_transitions,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW,
    )

    assert execute_result.status == CadenceStepExecutionStatus.SENT
    assert len(email_provider.messages) == 1

    inbound_result = await process_inbound_message_event(
        event=_event(body="Yes, I want to talk to an agent now."),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=inbound_messages,
        conversation_summary_repository=summaries,
        handoff_repository=handoffs,
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                fallback_recipient_email="fallback@example.com",
                crm_handoff_tag="human_handoff_required",
                crm_custom_fields={"handoff_status": "required"},
            )
        ),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="human_requested",
                asks_for_human=True,
            ),
            draft_text=_draft_json(),
            lead_state_text=_lead_state_classification_json(
                outcome="human_handoff",
                summary="Lead explicitly wants a human agent now.",
            ),
        ),
        now=NOW,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=workflow_transitions,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("handoff-email-1"),
        event_bus=FakeEventBus(),
        paused_search_track_repository=_paused_search_track_repository(),
        lead_classification_artifact_repository=FakeLeadClassificationArtifactRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.inbound_action == InboundAction.HUMAN_HANDOFF
    assert len(handoffs.by_id) == 1
    final_workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.HUMAN_HANDOFF
    assert len(notification_provider.notifications) == 1


async def test_business_flow_harness_runs_sync_to_continue_ai_path() -> None:
    prepared = await _prepare_business_flow_until_waiting_for_response()
    handoffs = FakeHandoffRepository()
    continuation_email_provider = FakeEmailProvider("email-456")

    inbound_result = await process_inbound_message_event(
        event=_event(
            provider_event_id="evt-continue-1",
            provider_message_id="msg-continue-1",
            body="Can you send a little more detail?",
        ),
        lead_repository=prepared.lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=prepared.conversations,
        inbound_message_repository=prepared.inbound_messages,
        conversation_summary_repository=prepared.summaries,
        handoff_repository=handoffs,
        crm_client=cast(CRMClient, FakeCRMClient()),
        notification_provider=cast(NotificationProvider, FakeNotificationProvider()),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(workspace_id=WORKSPACE_ID)
        ),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                asks_for_human=False,
                summary_text="Lead asked a general follow-up question.",
            ),
            draft_text=_draft_json(body="Absolutely — here are a few more details."),
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        message_repository=prepared.message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=continuation_email_provider,
        now=NOW,
        lead_workflow_repository=prepared.lead_workflow_repository,
        workflow_transition_repository=prepared.workflow_transition_repository,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.handoff_required is False
    assert inbound_result.continue_ai_provider_message_id == "email-456"
    assert inbound_result.continue_ai_outbound_message_id is not None
    final_workflow = prepared.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert prepared.conversations.by_id[CONVERSATION_ID].ai_interaction_count == 1
    assert len(continuation_email_provider.messages) == 1
    assert handoffs.saved == []


async def test_business_flow_harness_runs_sync_to_review_pause_path() -> None:
    prepared = await _prepare_business_flow_until_waiting_for_response()
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    handoffs = FakeHandoffRepository()

    inbound_result = await process_inbound_message_event(
        event=_event(
            provider_event_id="evt-review-1",
            provider_message_id="msg-review-1",
            body="I'm not really sure what I want yet.",
        ),
        lead_repository=prepared.lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=prepared.conversations,
        inbound_message_repository=prepared.inbound_messages,
        conversation_summary_repository=prepared.summaries,
        handoff_repository=handoffs,
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                fallback_recipient_email="fallback@example.com",
                crm_review_tag="needs_agent_review",
            )
        ),
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        llm_client=FakeInboundLLMClient(
            _classification_json(
                intent="unclear",
                asks_for_human=False,
                summary_text="Lead reply is ambiguous.",
            )
        ),
        now=NOW,
        lead_workflow_repository=prepared.lead_workflow_repository,
        workflow_transition_repository=prepared.workflow_transition_repository,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    final_workflow = prepared.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.PAUSED
    assert handoffs.saved == []


async def test_business_flow_harness_runs_sync_to_suppress_path() -> None:
    prepared = await _prepare_business_flow_until_waiting_for_response()
    handoffs = FakeHandoffRepository()

    inbound_result = await process_inbound_message_event(
        event=_event(
            provider_event_id="evt-suppress-1",
            provider_message_id="msg-suppress-1",
            body="Please unsubscribe me from these emails.",
        ),
        lead_repository=prepared.lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=prepared.conversations,
        inbound_message_repository=prepared.inbound_messages,
        conversation_summary_repository=prepared.summaries,
        handoff_repository=handoffs,
        llm_client=FakeInboundLLMClient(
            _classification_json(
                intent="opt_out",
                asks_for_human=False,
                opt_out_detected=True,
                summary_text="Lead opted out of automated outreach.",
            )
        ),
        now=NOW,
        lead_workflow_repository=prepared.lead_workflow_repository,
        workflow_transition_repository=prepared.workflow_transition_repository,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.opt_out_detected is True
    assert prepared.lead_repository.lead is not None
    assert prepared.lead_repository.lead.email_unsubscribed is True
    final_workflow = prepared.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.SUPPRESSED
    assert prepared.conversations.by_id[CONVERSATION_ID].status.value == "closed"
    assert handoffs.saved == []


async def test_business_flow_harness_runs_sync_to_not_interested_completion_path() -> None:
    prepared = await _prepare_business_flow_until_waiting_for_response()
    handoffs = FakeHandoffRepository()

    inbound_result = await process_inbound_message_event(
        event=_event(
            provider_event_id="evt-not-interested-1",
            provider_message_id="msg-not-interested-1",
            body="No thanks, I am not interested anymore.",
        ),
        lead_repository=prepared.lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=prepared.conversations,
        inbound_message_repository=prepared.inbound_messages,
        conversation_summary_repository=prepared.summaries,
        handoff_repository=handoffs,
        llm_client=FakeInboundLLMClient(
            _classification_json(
                intent="not_interested",
                asks_for_human=False,
                summary_text="Lead is no longer interested in continuing.",
            )
        ),
        now=NOW,
        lead_workflow_repository=prepared.lead_workflow_repository,
        workflow_transition_repository=prepared.workflow_transition_repository,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
    )

    assert inbound_result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert inbound_result.inbound_action == InboundAction.COMPLETE_AUTOMATION
    final_workflow = prepared.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert final_workflow.state == WorkflowState.COMPLETED
    assert prepared.conversations.by_id[CONVERSATION_ID].status.value == "closed"
    assert handoffs.saved == []


async def _prepare_business_flow_until_waiting_for_response() -> _PreparedBusinessFlow:
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

    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=FakeCampaignExecutionRepository(_config()),
        lead_workflow_repository=lead_workflow_repository,
        now=NOW,
    )
    assert schedule_result.status == CadenceStepScheduleStatus.SCHEDULED

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

    return _PreparedBusinessFlow(
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        message_repository=message_repository,
        conversations=conversations,
        inbound_messages=inbound_messages,
        summaries=summaries,
    )


def _lead(*, tags: tuple[str, ...] = ()) -> CanonicalLeadRecord:
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
        tags=tags,
        primary_email="lead@example.com",
        has_email=True,
        email_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


def _paused_search_track_repository() -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        mappings=(
            PausedSearchReasonMapping(
                mapping_id=UUID("00000000-0000-0000-0000-000000000016"),
                workspace_id=WORKSPACE_ID,
                reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
                track_id=UUID("00000000-0000-0000-0000-000000000015"),
                track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
                created_by_user_id=ACTOR_ID,
                created_at=NOW,
            ),
        ),
        versions=(
            PausedSearchTrackVersion(
                track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
                workspace_id=WORKSPACE_ID,
                track_id=UUID("00000000-0000-0000-0000-000000000015"),
                version_number=1,
                status=CampaignVersionStatus.PUBLISHED,
                track_family=PausedSearchTrackFamily.MAINTENANCE,
                enabled=True,
                allowed_channels=(ContactChannel.EMAIL,),
                default_for_reason_codes=(PausedSearchReasonCode.WAITING_FOR_RATES,),
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
                maintenance_interval_days=60,
                reactivation_window_days=30,
                max_total_touches=4,
                requires_review_before_publish=False,
                created_by_user_id=ACTOR_ID,
                created_at=NOW,
                published_at=NOW,
            ),
        ),
        steps=(
            PausedSearchTrackStep(
                step_id=PAUSED_SEARCH_STEP_ID,
                workspace_id=WORKSPACE_ID,
                track_version_id=PAUSED_SEARCH_TRACK_VERSION_ID,
                step_order=1,
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                channel=ContactChannel.EMAIL,
                delay_hours=0,
                message_goal="Check whether the paused-search timing has changed.",
                template_key="paused-search-email-1",
                max_attempts=1,
                review_required=False,
                created_at=NOW,
            ),
        ),
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


def _config(*, crm_enrollment_tag: str | None = None) -> CampaignExecutionConfig:
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
        crm_enrollment_tag=crm_enrollment_tag,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(_step(),),
        created_at=NOW,
        published_at=NOW,
    )


def _contact_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
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


def _event(
    *,
    provider_event_id: str = "evt-1",
    provider_message_id: str = "msg-1",
    body: str = "Can an agent call me today?",
    channel: ContactChannel = ContactChannel.EMAIL,
) -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id=provider_event_id,
        provider_message_id=provider_message_id,
        crm_lead_id="crm-123",
        channel=channel,
        body=body,
        received_at=NOW,
        payload_redacted={"event": "redacted"},
    )


def _classification_json(
    *,
    intent: str = "human_requested",
    asks_for_human: bool | None = None,
    opt_out_detected: bool = False,
    summary_text: str = "Lead asked for a human callback.",
) -> str:
    if asks_for_human is None:
        asks_for_human = intent == "human_requested"
    return json.dumps(
        {
            "intent": intent,
            "confidence": 0.94,
            "asks_for_human": asks_for_human,
            "shows_buying_interest": False,
            "shows_selling_interest": False,
            "asks_property_or_advice": False,
            "opt_out_detected": opt_out_detected,
            "summary_text": summary_text,
            "preferences": {"timeline": "today"},
        }
    )
