import json
from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.application.use_cases.process_provider_delivery_callback import (
    ProcessProviderDeliveryCallbackStatus,
    ProviderDeliveryCallback,
    process_provider_delivery_callback,
)
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.core.database import set_postgres_workspace_context
from app.domain.campaigns.admin import CampaignAdminAuditAction, CampaignAdminAuditLog
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.crm_sync import (
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    ExternalEventStatus,
)
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminAuditLogRepository,
)
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffCompletionRepository,
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
    HandoffCompletionModel,
    HandoffModel,
    InboundMessageModel,
    OutboundMessageModel,
    UserModel,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.provider_message_event_repository import (
    PostgresProviderMessageEventRepository,
)
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
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
DELIVERY_TIME = BASE_TIME + timedelta(minutes=2, seconds=30)
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


class FakeCRMClient:
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    def __init__(self) -> None:
        self.notes: list[tuple[WorkspaceId, str, str]] = []
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
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CRMAgent | None:
        return CRMAgent(crm_agent_id="agent-99", name="Agent Smith", email="agent@example.com")

    async def add_note(self, workspace_id: WorkspaceId, crm_lead_id: str, content: str) -> None:
        self.notes.append((workspace_id, crm_lead_id, content))

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
        self,
        notification: object,
    ) -> NotificationSendResult:  # pragma: no cover
        raise AssertionError("preflight digest should not be used in this harness")


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
    provider_message_event_repository = PostgresProviderMessageEventRepository(postgres_session)
    conversation_repository = PostgresConversationRepository(postgres_session)
    inbound_message_repository = PostgresInboundMessageRepository(postgres_session)
    conversation_summary_repository = PostgresConversationSummaryRepository(postgres_session)
    handoff_repository = PostgresHandoffRepository(postgres_session)
    handoff_completion_repository = PostgresHandoffCompletionRepository(postgres_session)
    workspace_handoff_config_repository = PostgresWorkspaceHandoffConfigRepository(postgres_session)
    reporting_repository = PostgresReportingRepository(postgres_session)
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

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

    delivery_result = await process_provider_delivery_callback(
        callback=ProviderDeliveryCallback(
            provider="sendgrid",
            provider_event_id="delivery-evt-1",
            provider_message_id="email-123",
            event_type="delivered",
            status=ProviderDeliveryStatus.DELIVERED,
            occurred_at=DELIVERY_TIME,
            payload_redacted={"event": "delivered"},
        ),
        message_repository=message_repository,
        provider_message_event_repository=provider_message_event_repository,
        now=DELIVERY_TIME,
    )

    assert delivery_result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED
    assert delivery_result.provider_delivery_status == ProviderDeliveryStatus.DELIVERED

    inbound_result = await process_inbound_message_event(
        event=_event(),
        lead_repository=lead_repository,
        external_event_repository=external_event_repository,
        conversation_repository=conversation_repository,
        inbound_message_repository=inbound_message_repository,
        conversation_summary_repository=conversation_summary_repository,
        handoff_repository=handoff_repository,
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        handoff_completion_repository=handoff_completion_repository,
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
    assert inbound_result.handoff_completion_failure_reason is None

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
    assert handoff.status == "notified"

    handoff_completion = await postgres_session.scalar(
        select(HandoffCompletionModel).where(HandoffCompletionModel.handoff_id == HANDOFF_ID)
    )
    assert handoff_completion is not None
    assert handoff_completion.notification_recipient_destination == "agent@example.com"
    assert handoff_completion.completed_at == INBOUND_TIME
    assert crm_client.tags == [(WORKSPACE_ID, "crm-123", "human_handoff_required")]
    assert crm_client.updated_fields == [(WORKSPACE_ID, "crm-123", {"handoff_status": "required"})]
    assert len(notification_provider.notifications) == 1

    persisted_message = await postgres_session.scalar(
        select(OutboundMessageModel).where(
            OutboundMessageModel.message_id == execute_result.outbound_message_id,
        )
    )
    assert persisted_message is not None
    assert persisted_message.status == "sent"
    assert persisted_message.provider_delivery_status == ProviderDeliveryStatus.DELIVERED.value

    audit_repository = PostgresCampaignAdminAuditLogRepository(postgres_session)
    await audit_repository.append(
        CampaignAdminAuditLog(
            audit_log_id=UUID("10000000-0000-0000-0000-000000000013"),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            action=CampaignAdminAuditAction.BATCH_LAUNCHED,
            actor_user_id=ACTOR_ID,
            details={"started_count": 1},
            created_at=DELIVERY_TIME,
        )
    )

    await set_postgres_workspace_context(postgres_session, str(WORKSPACE_ID))
    workspace_report = await reporting_repository.get_workspace_operations_summary(WORKSPACE_ID)
    campaign_report = await reporting_repository.get_campaign_operations_summary(
        WORKSPACE_ID,
        CAMPAIGN_ID,
    )
    audit_entries = await reporting_repository.list_campaign_audit_logs(WORKSPACE_ID, CAMPAIGN_ID)

    assert workspace_report.active_campaigns == 1
    assert workspace_report.workflow_counts.human_handoff == 1
    assert workspace_report.message_counts.delivered == 1
    assert campaign_report is not None
    assert campaign_report.enrollment_counts.queued == 1
    assert campaign_report.handoff_counts.notified == 1
    assert audit_entries[0].action == CampaignAdminAuditAction.BATCH_LAUNCHED


async def _seed_business_flow_prerequisites(session: AsyncSession) -> None:
    workspace_repository = PostgresWorkspaceRepository(session)
    workspace_contact_policy_repository = PostgresWorkspaceContactPolicyRepository(session)
    workspace_handoff_config_repository = PostgresWorkspaceHandoffConfigRepository(session)

    await workspace_repository.save(_workspace())
    await workspace_contact_policy_repository.save(_workspace_contact_policy())
    await workspace_handoff_config_repository.save(_workspace_handoff_config())

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


def _workspace_handoff_config() -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=WORKSPACE_ID,
        fallback_recipient_email="fallback@example.com",
        crm_handoff_tag="human_handoff_required",
        crm_custom_fields={"handoff_status": "required"},
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
