import json
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.crm_sync import CRMSyncJobStatus, CRMSyncType, ExternalEventStatus
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresCRMSyncJobRepository,
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresWorkspaceRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    CampaignCadenceStepModel,
    CampaignModel,
    CampaignVersionModel,
    ConversationSummaryModel,
    HandoffModel,
    InboundMessageModel,
    OutboundMessageModel,
    UserModel,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeEmailProvider,
    FakeLLMClient,
    FakeSMSProvider,
)
from tests.application.use_cases._campaign_enrollment_fakes import FakeTemporalWorkflowStarter

BASE_TIME = datetime(2026, 7, 11, 15, 0, tzinfo=UTC)
SYNC_TIME = BASE_TIME
ENROLL_TIME = BASE_TIME + timedelta(minutes=1)
EXECUTE_TIME = BASE_TIME + timedelta(minutes=2)
INBOUND_TIME = BASE_TIME + timedelta(minutes=3)

WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("10000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("10000000-0000-0000-0000-000000000003")
CAMPAIGN_VERSION_ID = UUID("10000000-0000-0000-0000-000000000004")
STEP_ID = UUID("10000000-0000-0000-0000-000000000005")
SYNC_JOB_ID = UUID("10000000-0000-0000-0000-000000000006")
EXTERNAL_EVENT_ID = UUID("10000000-0000-0000-0000-000000000007")
CONVERSATION_ID = UUID("10000000-0000-0000-0000-000000000008")
INBOUND_MESSAGE_ID = UUID("10000000-0000-0000-0000-000000000009")
SUMMARY_ID = UUID("10000000-0000-0000-0000-000000000010")
HANDOFF_ID = UUID("10000000-0000-0000-0000-000000000011")
ACTOR_ID = UUID("10000000-0000-0000-0000-000000000012")


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


async def test_business_flow_harness_runs_against_real_postgres(
    postgres_session: AsyncSession,
) -> None:
    await _seed_business_flow_prerequisites(postgres_session)

    lead_repository = PostgresLeadRepository(postgres_session)
    crm_sync_job_repository = PostgresCRMSyncJobRepository(postgres_session)
    external_event_repository = PostgresExternalEventRepository(postgres_session)
    campaign_enrollment_repository = PostgresCampaignEnrollmentRepository(postgres_session)
    lead_workflow_repository = PostgresLeadWorkflowRepository(postgres_session)
    workflow_transition_repository = PostgresWorkflowTransitionRepository(postgres_session)
    campaign_execution_repository = PostgresCampaignExecutionRepository(postgres_session)
    workspace_repository = PostgresWorkspaceRepository(postgres_session)
    workspace_contact_policy_repository = PostgresWorkspaceContactPolicyRepository(postgres_session)
    message_repository = PostgresOutboundMessageRepository(postgres_session)
    conversation_repository = PostgresConversationRepository(postgres_session)
    inbound_message_repository = PostgresInboundMessageRepository(postgres_session)
    conversation_summary_repository = PostgresConversationSummaryRepository(postgres_session)
    handoff_repository = PostgresHandoffRepository(postgres_session)

    sync_result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(
            pages=(CanonicalLeadSnapshotPage(leads=(_lead(),), next_cursor=None),)
        ),
        lead_repository=lead_repository,
        crm_sync_job_repository=crm_sync_job_repository,
        now=SYNC_TIME,
        sync_type=CRMSyncType.FULL,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert sync_result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert sync_result.job.status == CRMSyncJobStatus.COMPLETED
    synced_lead = await lead_repository.get_by_id(WORKSPACE_ID, LEAD_ID)
    assert synced_lead is not None
    assert synced_lead.crm_lead_id == "crm-123"

    enrollment_result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=["postgres_business_flow_harness"],
        actor_user_id=ACTOR_ID,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        now=ENROLL_TIME,
    )

    assert enrollment_result.started_count == 1
    workflow = await lead_workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID)
    assert workflow is not None
    assert workflow.state == WorkflowState.QUEUED

    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        campaign_execution_repository=campaign_execution_repository,
        lead_workflow_repository=lead_workflow_repository,
        now=ENROLL_TIME,
    )

    assert schedule_result.status == CadenceStepScheduleStatus.SCHEDULED
    assert schedule_result.cadence_step_id == STEP_ID
    assert schedule_result.scheduled_for == ENROLL_TIME

    execute_result = await execute_campaign_cadence_step(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        cadence_step_id=STEP_ID,
        scheduled_for=ENROLL_TIME,
        campaign_execution_repository=campaign_execution_repository,
        workspace_repository=workspace_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        message_repository=message_repository,
        llm_client=FakeLLMClient(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("email-123"),
        now=EXECUTE_TIME,
    )

    assert execute_result.status == CadenceStepExecutionStatus.SENT
    assert execute_result.workflow is not None
    assert execute_result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert execute_result.outbound_message_id is not None

    inbound_result = await process_inbound_message_event(
        event=_event(),
        lead_repository=lead_repository,
        external_event_repository=external_event_repository,
        conversation_repository=conversation_repository,
        inbound_message_repository=inbound_message_repository,
        conversation_summary_repository=conversation_summary_repository,
        handoff_repository=handoff_repository,
        llm_client=FakeInboundReplyLLMClient(_classification_json()),
        now=INBOUND_TIME,
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

    final_workflow = await lead_workflow_repository.get_latest_for_lead(WORKSPACE_ID, LEAD_ID)
    assert final_workflow is not None
    assert final_workflow.state == WorkflowState.HUMAN_HANDOFF
    assert final_workflow.current_step_id is None
    assert final_workflow.next_action_at is None

    transitions = await workflow_transition_repository.list_for_workflow(
        WORKSPACE_ID,
        final_workflow.workflow_id,
    )
    assert [transition.reason_code for transition in transitions] == [
        WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED,
        WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED,
    ]

    external_event = await external_event_repository.get_by_provider_event_id(
        WORKSPACE_ID,
        CRMProvider.FOLLOW_UP_BOSS.value,
        "evt-1",
    )
    assert external_event is not None
    assert external_event.status == ExternalEventStatus.PROCESSED

    outbound_message = await message_repository.get_by_id(
        WORKSPACE_ID,
        execute_result.outbound_message_id,
    )
    assert outbound_message is not None
    assert outbound_message.provider_message_id == "email-123"

    inbound_message = await postgres_session.scalar(
        select(InboundMessageModel).where(
            InboundMessageModel.inbound_message_id == INBOUND_MESSAGE_ID,
        )
    )
    assert inbound_message is not None
    assert inbound_message.body == "Can an agent call me today?"

    summary = await postgres_session.scalar(
        select(ConversationSummaryModel).where(ConversationSummaryModel.summary_id == SUMMARY_ID)
    )
    assert summary is not None
    assert summary.summary_text == "Lead asked for a human callback."

    handoff = await postgres_session.scalar(
        select(HandoffModel).where(HandoffModel.handoff_id == HANDOFF_ID)
    )
    assert handoff is not None
    assert handoff.assigned_agent_crm_id == "agent-99"

    persisted_message = await postgres_session.scalar(
        select(OutboundMessageModel).where(
            OutboundMessageModel.message_id == execute_result.outbound_message_id,
        )
    )
    assert persisted_message is not None
    assert persisted_message.status == "sent"


async def _seed_business_flow_prerequisites(session: AsyncSession) -> None:
    workspace_repository = PostgresWorkspaceRepository(session)
    workspace_contact_policy_repository = PostgresWorkspaceContactPolicyRepository(session)

    await workspace_repository.save(_workspace())
    await workspace_contact_policy_repository.save(_workspace_contact_policy())

    session.add(
        UserModel(
            user_id=ACTOR_ID,
            email="broker@example.com",
            email_normalized="broker@example.com",
            full_name="Broker Admin",
            status="active",
            email_verified_at=BASE_TIME,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    await session.flush()

    session.add(
        CampaignModel(
            campaign_id=CAMPAIGN_ID,
            workspace_id=WORKSPACE_ID,
            name="Dormant Buyers",
            status="active",
            active_version_id=None,
            created_by_user_id=ACTOR_ID,
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )
    )
    await session.flush()

    session.add(
        CampaignVersionModel(
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            version_number=1,
            status="published",
            enabled_channels=[ContactChannel.EMAIL.value],
            daily_start_cap=50,
            dormant_threshold_days=60,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
            timezone="America/Chicago",
            sms_compliance_required=True,
            preflight_digest_enabled=False,
            prompt_version="v1",
            approved_model="openai/gpt-4o-mini",
            created_by_user_id=ACTOR_ID,
            published_at=BASE_TIME,
            created_at=BASE_TIME,
        )
    )
    await session.flush()

    campaign = await session.get(CampaignModel, CAMPAIGN_ID)
    assert campaign is not None
    campaign.active_version_id = CAMPAIGN_VERSION_ID
    await session.flush()

    session.add(
        CampaignCadenceStepModel(
            cadence_step_id=STEP_ID,
            workspace_id=WORKSPACE_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            step_order=1,
            channel=ContactChannel.EMAIL.value,
            delay_hours=0,
            message_goal="Check whether the lead is still considering a move.",
            template_key="dormant-email-1",
            max_attempts=1,
            created_at=BASE_TIME,
        )
    )
    await session.flush()


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Miller Schackman",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Chicago",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def _workspace_contact_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
    )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=SYNC_TIME,
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


def _event() -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id="evt-1",
        provider_message_id="msg-1",
        crm_lead_id="crm-123",
        channel=ContactChannel.EMAIL,
        body="Can an agent call me today?",
        received_at=INBOUND_TIME,
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