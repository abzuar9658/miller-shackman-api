from __future__ import annotations

# ruff: noqa: E402
import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.auth import PasswordHasher
from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent
from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.ports.messaging import EmailMessage, SMSMessage
from app.application.ports.notifications import (
    HandoffNotification,
    NotificationSendResult,
    PreflightDigestNotification,
)
from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightVetoRecord,
)
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.services.llm.outbound_message_drafting import (
    outbound_message_draft_prompt_version_for_revision,
)
from app.application.services.llm.reply_classification import (
    INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
)
from app.application.use_cases.apply_workflow_state_transition import (
    apply_workflow_state_transition,
)
from app.application.use_cases.campaign_admin import (
    CampaignCadenceStepInput,
    CampaignConfigInput,
    CreateDraftCampaignStatus,
    PublishCampaignVersionStatus,
    create_draft_campaign,
    publish_campaign_version,
)
from app.application.use_cases.campaign_cadence_execution import (
    CadenceStepExecutionStatus,
    CadenceStepScheduleStatus,
    execute_campaign_cadence_step,
    schedule_next_campaign_cadence_step,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.crm_sync import (
    RunFollowUpBossLeadSyncStatus,
    run_follow_up_boss_lead_snapshot_sync,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.core.config import Settings, get_settings
from app.core.database import enable_postgres_service_access
from app.domain.campaigns.admin import CampaignAdminView
from app.domain.campaigns.enrollment import CampaignEnrollmentSource, CampaignEnrollmentStatus
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.conversations import HandoffStatus, WorkspaceHandoffConfig
from app.domain.crm_sync import CRMSyncLeadSort, CRMSyncType
from app.domain.identity import (
    AuthenticatedActor,
    PasswordCredential,
    User,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import (
    ActivityReliability,
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationReason,
    LeadType,
)
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
from app.infrastructure.auth.passwords import PasslibPasswordHasher
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminAuditLogRepository,
    PostgresCampaignAdminRepository,
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
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresPasswordCredentialRepository,
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.models import (
    ConversationModel,
    ConversationSummaryModel,
    CRMSyncJobModel,
    ExternalEventModel,
    HandoffCompletionModel,
    HandoffModel,
    InboundMessageModel,
    LeadModel,
    OutboundMessageModel,
    PreflightDigestModel,
    PreflightVetoModel,
    ProviderMessageEventModel,
)
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
)
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
    WorkflowTransitionModel,
)
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

DEMO_NAMESPACE = UUID("7fd27473-6513-4e13-81ce-94e8e02d15ce")
DEMO_PASSWORD = "DemoPassword123!"
DEMO_EMAIL_DOMAIN = "demo.millerschackman.dev"
PRODUCTION_CONFIRM_TEXT = "CREATE_DEMO_WORKSPACE"
BASE_TIME = datetime(2026, 7, 11, 15, 0, tzinfo=UTC)
CAMPAIGN_NAME = "Dormant Buyers Reactivation"
DEMO_OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION = (
    outbound_message_draft_prompt_version_for_revision(1)
)


@dataclass(frozen=True)
class DemoSeedOptions:
    workspace_name: str = "Demo: Miller Schackman"
    allow_production: bool = False
    confirm_text: str = ""
    reset_leads: bool = False
    require_sink_providers: bool = True


@dataclass(frozen=True)
class DemoSeedUser:
    email: str
    full_name: str
    role: WorkspaceMembershipRole
    user_id: UUID
    membership_id: UUID


@dataclass(frozen=True)
class DemoSeedResult:
    workspace_id: WorkspaceId
    campaign_id: UUID
    campaign_version_id: UUID
    lead_count: int
    workflow_count: int
    handoff_count: int
    demo_users: tuple[DemoSeedUser, ...]


class DemoSeedSafetyError(ValueError):
    pass


class DemoLeadSnapshotSource:
    def __init__(self, leads: Sequence[CanonicalLeadRecord]) -> None:
        self._leads = tuple(leads)
        self._served = False

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
        if self._served:
            return CanonicalLeadSnapshotPage()
        self._served = True
        return CanonicalLeadSnapshotPage(leads=self._leads, next_cursor=None)


class DemoLLMClient:
    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        if request.prompt_version == INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION:
            text = _classification_response_for_prompt(request.prompt)
        elif request.prompt_version == DEMO_OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION:
            text = json.dumps(
                {
                    "body": (
                        "Hi, this is Miller Schackman Realty checking in. "
                        "Are you still thinking about a move this year? "
                        "Reply anytime and your agent can help."
                    ),
                    "subject": "Still considering a move?",
                    "confidence": 0.93,
                    "personalization_notes": ["Kept outreach administrative and low pressure."],
                    "safety_flags": [],
                },
            )
        else:
            text = json.dumps({"error": "unsupported_prompt_version"})
        return LLMResult(
            text=text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=9,
            usage_tokens=42,
        )


class DemoSMSProvider:
    provider_name = "sink"

    async def send(self, message: SMSMessage) -> str:
        return f"demo-sms-{message.idempotency_key[-12:]}"


class DemoEmailProvider:
    provider_name = "sink"

    async def send(self, message: EmailMessage) -> str:
        return f"demo-email-{message.idempotency_key[-12:]}"


class DemoCRMClient:
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    async def validate_connection(self, workspace_id: UUID) -> bool:
        return True

    async def get_lead(self, workspace_id: UUID, crm_lead_id: str) -> CanonicalLead | None:
        return None

    async def search_leads(
        self,
        workspace_id: UUID,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        return []

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        return []

    async def get_assigned_agent(self, workspace_id: UUID, crm_lead_id: str) -> CRMAgent | None:
        return CRMAgent(
            crm_agent_id="demo-agent-001",
            name="Avery Demo Agent",
            email=f"agent@{DEMO_EMAIL_DOMAIN}",
        )

    async def get_lead_url(self, workspace_id: UUID, crm_lead_id: str) -> str | None:
        _ = workspace_id
        return f"https://demo.followupboss.test/lead/{crm_lead_id}"

    async def add_note(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        return None

    async def add_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def remove_tag(self, workspace_id: UUID, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        return None

    async def subscribe_to_events(self, workspace_id: UUID, webhook_url: str) -> None:
        return None

    async def fetch_resource_by_uri(
        self, workspace_id: UUID, uri: str
    ) -> dict[str, object] | None:
        return None


class DemoNotificationProvider:
    async def send_preflight_digest(
        self,
        notification: PreflightDigestNotification,
    ) -> NotificationSendResult:
        return NotificationSendResult(
            accepted=True,
            provider_reference=f"demo-digest-{notification.batch_id}",
        )

    async def send_handoff_notification(
        self,
        notification: HandoffNotification,
    ) -> NotificationSendResult:
        return NotificationSendResult(
            accepted=True,
            provider_reference=f"demo-handoff-{notification.handoff_id}",
        )

    async def send_review_notification(
        self,
        notification: object,
    ) -> NotificationSendResult:
        return NotificationSendResult(accepted=True, provider_reference="demo-review")


class DemoTemporalWorkflowStarter:
    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_version_id: UUID,
        temporal_workflow_id: str,
    ) -> None:
        return None


def validate_demo_seed_safety(settings: Settings, options: DemoSeedOptions) -> None:
    environment = settings.environment.strip().lower()
    if environment in {"production", "prod"} and not (
        options.allow_production and options.confirm_text == PRODUCTION_CONFIRM_TEXT
    ):
        raise DemoSeedSafetyError(
            "Refusing to seed production without --allow-production and matching --confirm-text.",
        )

    if "demo" not in options.workspace_name.strip().lower():
        raise DemoSeedSafetyError("Demo workspace name must contain 'Demo'.")

    if options.require_sink_providers and settings.sms_provider.strip().lower() != "sink":
        raise DemoSeedSafetyError("SMS_PROVIDER must be 'sink' for demo seeding.")

    if options.require_sink_providers and settings.email_provider.strip().lower() != "sink":
        raise DemoSeedSafetyError("EMAIL_PROVIDER must be 'sink' for demo seeding.")


async def seed_demo_workspace(
    session: AsyncSession,
    *,
    settings: Settings,
    options: DemoSeedOptions,
    now: datetime = BASE_TIME,
    password_hasher: PasswordHasher | None = None,
) -> DemoSeedResult:
    validate_demo_seed_safety(settings, options)
    await enable_postgres_service_access(session)

    workspace_id = _demo_uuid(options.workspace_name, "workspace")
    users = _demo_users(options.workspace_name)
    if options.reset_leads:
        await _reset_demo_lead_data(session, workspace_id)

    await _seed_workspace(session, workspace_id, options.workspace_name, now)
    await _seed_demo_users(session, workspace_id, users, now, password_hasher)
    actor = _admin_actor(workspace_id, users[0])
    campaign_view = await _ensure_campaign(session, workspace_id, actor, now)
    leads = _demo_leads(workspace_id, users[2], now)
    _validate_synthetic_leads(leads)
    await _sync_leads(session, workspace_id, leads, actor.user_id, now)
    await _seed_workflow_scenarios(session, workspace_id, campaign_view, leads, actor, now)
    await _seed_preflight_digest(
        session,
        workspace_id,
        campaign_view.campaign.campaign_id,
        leads,
        users,
        now,
    )

    reporting = PostgresReportingRepository(session)
    summary = await reporting.get_campaign_operations_summary(
        workspace_id,
        campaign_view.campaign.campaign_id,
    )
    assert summary is not None
    return DemoSeedResult(
        workspace_id=workspace_id,
        campaign_id=campaign_view.campaign.campaign_id,
        campaign_version_id=campaign_view.version.campaign_version_id,
        lead_count=len(leads),
        workflow_count=sum(summary.workflow_counts.__dict__.values()),
        handoff_count=sum(summary.handoff_counts.__dict__.values()),
        demo_users=users,
    )


async def _seed_workspace(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    workspace_name: str,
    now: datetime,
) -> None:
    await PostgresWorkspaceRepository(session).save(
        Workspace(
            workspace_id=workspace_id,
            name=workspace_name.strip(),
            status=WorkspaceStatus.ACTIVE,
            default_timezone="America/Chicago",
            created_at=now,
            updated_at=now,
        ),
    )
    await PostgresWorkspaceContactPolicyRepository(session).save(
        WorkspaceContactPolicy(
            workspace_id=workspace_id,
            sms_compliance_state=SmsComplianceState.APPROVED,
            quiet_hours_start=time(10, 0),
            quiet_hours_end=time(17, 0),
        ),
    )
    await PostgresWorkspaceHandoffConfigRepository(session).save(
        WorkspaceHandoffConfig(
            workspace_id=workspace_id,
            fallback_recipient_email=f"handoff@{DEMO_EMAIL_DOMAIN}",
            crm_handoff_tag="human_handoff_required",
            crm_custom_fields={"handoff_status": "required"},
        ),
    )


async def _seed_demo_users(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    users: tuple[DemoSeedUser, ...],
    now: datetime,
    password_hasher: PasswordHasher | None,
) -> None:
    user_repository = PostgresUserRepository(session)
    membership_repository = PostgresWorkspaceMembershipRepository(session)
    credential_repository = PostgresPasswordCredentialRepository(session)
    hasher = password_hasher or PasslibPasswordHasher()
    password_hash = hasher.hash_password(DEMO_PASSWORD)

    for demo_user in users:
        await user_repository.save(
            User(
                user_id=demo_user.user_id,
                email=demo_user.email,
                email_normalized=demo_user.email,
                full_name=demo_user.full_name,
                status=UserStatus.ACTIVE,
                email_verified_at=now,
                created_at=now,
                updated_at=now,
            ),
        )
        await membership_repository.save(
            WorkspaceMembership(
                membership_id=demo_user.membership_id,
                workspace_id=workspace_id,
                user_id=demo_user.user_id,
                role=demo_user.role,
                status=WorkspaceMembershipStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )
        await credential_repository.save(
            PasswordCredential(
                user_id=demo_user.user_id,
                password_hash=password_hash,
                password_changed_at=now,
                failed_attempt_count=0,
                locked_until=None,
                created_at=now,
                updated_at=now,
            ),
        )


async def _ensure_campaign(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    actor: AuthenticatedActor,
    now: datetime,
) -> CampaignAdminView:
    campaign_repository = PostgresCampaignAdminRepository(session)
    audit_repository = PostgresCampaignAdminAuditLogRepository(session)
    existing = await campaign_repository.get_campaign_by_name(workspace_id, CAMPAIGN_NAME)
    if existing is not None:
        view = await _active_campaign_view(campaign_repository, existing.campaign_id, workspace_id)
        if view is None:
            raise RuntimeError("Existing demo campaign is missing an active published version.")
        return view

    create_result = await create_draft_campaign(
        actor=actor,
        workspace_id=workspace_id,
        name=CAMPAIGN_NAME,
        config=_campaign_config(),
        campaign_admin_repository=campaign_repository,
        audit_log_repository=audit_repository,
        now=now,
    )
    if create_result.status != CreateDraftCampaignStatus.CREATED or create_result.view is None:
        raise RuntimeError(f"Failed to create demo campaign: {create_result.reasons}")

    publish_result = await publish_campaign_version(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=create_result.view.campaign.campaign_id,
        campaign_version_id=create_result.view.version.campaign_version_id,
        campaign_admin_repository=campaign_repository,
        audit_log_repository=audit_repository,
        now=now + timedelta(minutes=1),
    )
    if (
        publish_result.status != PublishCampaignVersionStatus.PUBLISHED
        or publish_result.view is None
    ):
        raise RuntimeError(f"Failed to publish demo campaign: {publish_result.reasons}")
    return publish_result.view


async def _sync_leads(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    leads: tuple[CanonicalLeadRecord, ...],
    actor_user_id: UUID,
    now: datetime,
) -> None:
    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=workspace_id,
        lead_snapshot_source=DemoLeadSnapshotSource(leads),
        lead_repository=PostgresLeadRepository(session),
        crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
        now=now + timedelta(minutes=2),
        sync_type=CRMSyncType.FULL,
        created_by_user_id=actor_user_id,
        sync_job_id_factory=lambda: _demo_uuid(str(workspace_id), f"sync:{now.isoformat()}"),
    )
    if result.status != RunFollowUpBossLeadSyncStatus.COMPLETED:
        raise RuntimeError(f"Demo lead sync failed: {result.job.failure_reason}")


async def _seed_workflow_scenarios(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    campaign_view: CampaignAdminView,
    leads: tuple[CanonicalLeadRecord, ...],
    actor: AuthenticatedActor,
    now: datetime,
) -> None:
    enrollment_repository = PostgresCampaignEnrollmentRepository(session)
    workflow_repository = PostgresLeadWorkflowRepository(session)
    transition_repository = PostgresWorkflowTransitionRepository(session)
    lead_repository = PostgresLeadRepository(session)
    conversation_repository = PostgresConversationRepository(session)
    inbound_repository = PostgresInboundMessageRepository(session)
    summary_repository = PostgresConversationSummaryRepository(session)
    handoff_repository = PostgresHandoffRepository(session)
    handoff_completion_repository = PostgresHandoffCompletionRepository(session)

    if await _existing_workflow_count(session, workspace_id, campaign_view.campaign.campaign_id):
        return

    for index, lead in enumerate(leads):
        start_result = await start_single_campaign_enrollment(
            workspace_id=workspace_id,
            campaign_id=campaign_view.campaign.campaign_id,
            campaign_version_id=campaign_view.version.campaign_version_id,
            lead_id=lead.lead_id,
            source=CampaignEnrollmentSource.MANUAL_ADMIN,
            reason_codes=("demo_workspace_seed",),
            actor_user_id=actor.user_id,
            campaign_enrollment_repository=enrollment_repository,
            lead_workflow_repository=workflow_repository,
            workflow_transition_repository=transition_repository,
            temporal_workflow_starter=DemoTemporalWorkflowStarter(),
            now=now + timedelta(minutes=3, seconds=index),
            campaign_enrollment_id=_demo_uuid(str(lead.lead_id), "enrollment"),
            workflow_id=_demo_uuid(str(lead.lead_id), "workflow"),
            transition_id=_demo_uuid(str(lead.lead_id), "transition:queued"),
            temporal_workflow_id=f"demo-lead-nurture:{lead.lead_id}",
            metadata={"seed": "demo_workspace"},
        )
        if start_result.status != LeadStartStatus.STARTED:
            raise RuntimeError(f"Demo workflow start failed: {start_result.error}")

    await _execute_first_step(session, campaign_view, leads[3], now + timedelta(minutes=10))
    await _execute_first_step(session, campaign_view, leads[4], now + timedelta(minutes=11))
    await _activate_workflow(
        workflow_repository,
        transition_repository,
        workspace_id,
        leads[5],
        now,
    )
    await _pause_workflow(
        workflow_repository,
        transition_repository,
        workspace_id,
        leads[6],
        actor,
        now,
    )
    await _inbound_reply(
        event_body="Can an agent call me today?",
        event_suffix="human-requested",
        lead=leads[7],
        session=session,
        repositories=(
            lead_repository,
            PostgresExternalEventRepository(session),
            conversation_repository,
            inbound_repository,
            summary_repository,
            handoff_repository,
            handoff_completion_repository,
        ),
        workspace_id=workspace_id,
        now=now + timedelta(minutes=20),
    )
    await _inbound_reply(
        event_body="I need to sell my condo and buy soon.",
        event_suffix="seller-interest",
        lead=leads[8],
        session=session,
        repositories=(
            lead_repository,
            PostgresExternalEventRepository(session),
            conversation_repository,
            inbound_repository,
            summary_repository,
            handoff_repository,
            handoff_completion_repository,
        ),
        workspace_id=workspace_id,
        now=now + timedelta(minutes=21),
    )
    await _acknowledge_latest_handoff(
        session,
        workspace_id,
        leads[8].lead_id,
        now + timedelta(minutes=30),
    )
    await _inbound_reply(
        event_body="Stop texting me please.",
        event_suffix="opt-out",
        lead=leads[9],
        session=session,
        repositories=(
            lead_repository,
            PostgresExternalEventRepository(session),
            conversation_repository,
            inbound_repository,
            summary_repository,
            handoff_repository,
            handoff_completion_repository,
        ),
        workspace_id=workspace_id,
        now=now + timedelta(minutes=22),
    )
    await _mark_terminal_workflow(
        session,
        workflow_repository,
        workspace_id,
        leads[10].lead_id,
        WorkflowState.COMPLETED,
        CampaignEnrollmentStatus.COMPLETED,
        now + timedelta(minutes=40),
    )
    await _seed_manual_messages(session, campaign_view, leads, now)


async def _execute_first_step(
    session: AsyncSession,
    campaign_view: CampaignAdminView,
    lead: CanonicalLeadRecord,
    now: datetime,
) -> None:
    schedule_result = await schedule_next_campaign_cadence_step(
        workspace_id=campaign_view.campaign.workspace_id,
        lead_id=lead.lead_id,
        campaign_version_id=campaign_view.version.campaign_version_id,
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        now=now,
    )
    if schedule_result.status != CadenceStepScheduleStatus.SCHEDULED:
        return
    assert schedule_result.cadence_step_id is not None
    assert schedule_result.scheduled_for is not None
    execute_result = await execute_campaign_cadence_step(
        workspace_id=campaign_view.campaign.workspace_id,
        lead_id=lead.lead_id,
        campaign_version_id=campaign_view.version.campaign_version_id,
        cadence_step_id=schedule_result.cadence_step_id,
        scheduled_for=schedule_result.scheduled_for,
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        lead_repository=PostgresLeadRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        message_repository=PostgresOutboundMessageRepository(session),
        llm_client=DemoLLMClient(),
        sms_provider=DemoSMSProvider(),
        email_provider=DemoEmailProvider(),
        now=now,
    )
    if execute_result.status not in {
        CadenceStepExecutionStatus.SENT,
        CadenceStepExecutionStatus.ALREADY_SENT,
        CadenceStepExecutionStatus.ALREADY_WAITING_FOR_RESPONSE,
    }:
        raise RuntimeError(f"Demo cadence execution failed: {execute_result.status}")


async def _activate_workflow(
    workflow_repository: PostgresLeadWorkflowRepository,
    transition_repository: PostgresWorkflowTransitionRepository,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    now: datetime,
) -> None:
    outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        to_state=WorkflowState.ACTIVE_NURTURE,
        reason_code=WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        now=now + timedelta(minutes=12),
        transition_id_factory=lambda: _demo_uuid(str(lead.lead_id), "transition:active"),
    )
    if outcome.workflow is not None:
        await workflow_repository.save(
            replace(outcome.workflow, next_action_at=now + timedelta(hours=24)),
        )


async def _pause_workflow(
    workflow_repository: PostgresLeadWorkflowRepository,
    transition_repository: PostgresWorkflowTransitionRepository,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    actor: AuthenticatedActor,
    now: datetime,
) -> None:
    await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=WorkflowTransitionReasonCode.MANUAL_PAUSE,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        now=now + timedelta(minutes=13),
        actor_user_id=actor.user_id,
        pause_reason="demo_recent_agent_activity",
        transition_id_factory=lambda: _demo_uuid(str(lead.lead_id), "transition:paused"),
    )


async def _inbound_reply(
    *,
    event_body: str,
    event_suffix: str,
    lead: CanonicalLeadRecord,
    session: AsyncSession,
    repositories: tuple[
        PostgresLeadRepository,
        PostgresExternalEventRepository,
        PostgresConversationRepository,
        PostgresInboundMessageRepository,
        PostgresConversationSummaryRepository,
        PostgresHandoffRepository,
        PostgresHandoffCompletionRepository,
    ],
    workspace_id: WorkspaceId,
    now: datetime,
) -> None:
    (
        lead_repository,
        external_event_repository,
        conversation_repository,
        inbound_repository,
        summary_repository,
        handoff_repository,
        handoff_completion_repository,
    ) = repositories
    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=workspace_id,
            provider=CRMProvider.FOLLOW_UP_BOSS.value,
            provider_event_id=f"demo-{lead.crm_lead_id}-{event_suffix}",
            provider_message_id=f"demo-msg-{lead.crm_lead_id}-{event_suffix}",
            crm_lead_id=lead.crm_lead_id,
            channel=ContactChannel.SMS,
            body=event_body,
            received_at=now,
            from_address_redacted="+1555***0100",
            to_address_redacted="+1555***0000",
            payload_redacted={"source": "demo_workspace_seed"},
        ),
        lead_repository=lead_repository,
        external_event_repository=external_event_repository,
        conversation_repository=conversation_repository,
        inbound_message_repository=inbound_repository,
        conversation_summary_repository=summary_repository,
        handoff_repository=handoff_repository,
        crm_client=DemoCRMClient(),
        notification_provider=DemoNotificationProvider(),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        handoff_completion_repository=handoff_completion_repository,
        llm_client=DemoLLMClient(),
        now=now,
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        external_event_id_factory=lambda: _demo_uuid(str(lead.lead_id), f"external:{event_suffix}"),
        conversation_id_factory=lambda: _demo_uuid(str(lead.lead_id), "conversation"),
        inbound_message_id_factory=lambda: _demo_uuid(str(lead.lead_id), f"inbound:{event_suffix}"),
        summary_id_factory=lambda: _demo_uuid(str(lead.lead_id), f"summary:{event_suffix}"),
        handoff_id_factory=lambda: _demo_uuid(str(lead.lead_id), f"handoff:{event_suffix}"),
        workflow_transition_id_factory=lambda: _demo_uuid(
            str(lead.lead_id),
            f"transition:{event_suffix}",
        ),
    )
    if result.status not in {
        ProcessInboundMessageEventStatus.PROCESSED,
        ProcessInboundMessageEventStatus.DUPLICATE,
    }:
        raise RuntimeError(f"Demo inbound event failed: {result.status}")


async def _acknowledge_latest_handoff(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    now: datetime,
) -> None:
    handoff = await session.scalar(
        select(HandoffModel)
        .where(HandoffModel.workspace_id == workspace_id)
        .where(HandoffModel.lead_id == lead_id)
        .order_by(HandoffModel.created_at.desc())
        .limit(1),
    )
    if handoff is None:
        return
    handoff.status = HandoffStatus.ACKNOWLEDGED.value
    handoff.acknowledged_at = now
    await session.flush()


async def _mark_terminal_workflow(
    session: AsyncSession,
    workflow_repository: PostgresLeadWorkflowRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow_state: WorkflowState,
    enrollment_status: CampaignEnrollmentStatus,
    now: datetime,
) -> None:
    workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
    if workflow is None:
        return
    await workflow_repository.save(
        replace(
            workflow,
            state=workflow_state,
            next_action_at=None,
            current_step_id=None,
            last_transition_at=now,
            updated_at=now,
            state_version=workflow.state_version + 1,
        ),
    )
    await session.execute(
        update(CampaignEnrollmentModel)
        .where(CampaignEnrollmentModel.campaign_enrollment_id == workflow.campaign_enrollment_id)
        .values(status=enrollment_status.value, ended_at=now, updated_at=now),
    )


async def _seed_manual_messages(
    session: AsyncSession,
    campaign_view: CampaignAdminView,
    leads: tuple[CanonicalLeadRecord, ...],
    now: datetime,
) -> None:
    repository = PostgresOutboundMessageRepository(session)
    step_id = str(campaign_view.cadence_steps[0].cadence_step_id)
    await repository.save(
        _outbound_message(
            campaign_view=campaign_view,
            lead=leads[10],
            step_id=step_id,
            status=OutboundMessageStatus.CANCELLED,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
            provider_delivery_status=None,
            suffix="cancelled",
            now=now + timedelta(minutes=41),
        ),
    )
    await repository.save(
        _outbound_message(
            campaign_view=campaign_view,
            lead=leads[11],
            step_id=step_id,
            status=OutboundMessageStatus.FAILED,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
            provider_delivery_status=ProviderDeliveryStatus.FAILED,
            suffix="failed",
            now=now + timedelta(minutes=42),
            failure_reason="demo_provider_failure",
        ),
    )


async def _seed_preflight_digest(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    campaign_id: UUID,
    leads: tuple[CanonicalLeadRecord, ...],
    users: tuple[DemoSeedUser, ...],
    now: datetime,
) -> None:
    digest_id = _demo_uuid(str(workspace_id), "preflight:digest")
    await PostgresPreflightDigestRepository(session).save_digest(
        PreflightDigestRecord(
            digest_id=str(digest_id),
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id="demo-preflight-001",
            status=PreflightDigestIssueStatus.ISSUED,
            entries=tuple(
                PreflightDigestEntry(
                    lead_id=lead.lead_id,
                    recipient_id=str(users[2].user_id),
                    recipient_destination=users[2].email,
                    display_name=lead.mapped_custom_fields.get("display_name", lead.crm_lead_id),
                )
                for lead in leads[:3]
            ),
            notification_records=(
                PreflightDigestNotificationRecord(
                    recipient_id=str(users[2].user_id),
                    idempotency_key=f"demo-preflight:{digest_id}:agent",
                    accepted=True,
                    provider_reference="demo-preflight-email-001",
                ),
            ),
            digest_sent_at=now + timedelta(minutes=5),
            veto_window_expires_at=now + timedelta(hours=24),
            vetoes=(
                PreflightVetoRecord(
                    lead_id=leads[2].lead_id,
                    actor_id=str(users[2].user_id),
                    recorded_at=now + timedelta(hours=1),
                    idempotency_key=f"demo-veto:{leads[2].lead_id}",
                    reason="Agent already reached out manually.",
                ),
            ),
        ),
    )


async def _existing_workflow_count(
    session: AsyncSession,
    workspace_id: WorkspaceId,
    campaign_id: UUID,
) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(LeadWorkflowModel)
        .where(LeadWorkflowModel.workspace_id == workspace_id)
        .where(LeadWorkflowModel.campaign_id == campaign_id),
    )
    return int(value or 0)


async def _active_campaign_view(
    repository: PostgresCampaignAdminRepository,
    campaign_id: UUID,
    workspace_id: WorkspaceId,
) -> CampaignAdminView | None:
    campaign = await repository.get_campaign(workspace_id, campaign_id)
    if campaign is None or campaign.active_version_id is None:
        return None
    version = await repository.get_version(workspace_id, campaign.active_version_id)
    if version is None or version.status != CampaignVersionStatus.PUBLISHED:
        return None
    steps = await repository.get_cadence_steps(workspace_id, version.campaign_version_id)
    return CampaignAdminView(campaign=campaign, version=version, cadence_steps=steps)


async def _reset_demo_lead_data(session: AsyncSession, workspace_id: WorkspaceId) -> None:
    for model in (
        ProviderMessageEventModel,
        HandoffCompletionModel,
        HandoffModel,
        ConversationSummaryModel,
        InboundMessageModel,
        ConversationModel,
        PreflightVetoModel,
        PreflightDigestModel,
        OutboundMessageModel,
        WorkflowTransitionModel,
        LeadWorkflowModel,
        CampaignEnrollmentModel,
        ExternalEventModel,
        CRMSyncJobModel,
        LeadModel,
    ):
        await session.execute(delete(model).where(model.workspace_id == workspace_id))


def _campaign_config() -> CampaignConfigInput:
    return CampaignConfigInput(
        enabled_channels=(ContactChannel.EMAIL, ContactChannel.SMS),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="America/Chicago",
        sms_compliance_required=True,
        preflight_digest_enabled=True,
        crm_enrollment_tag="ai_nurture",
        allow_assigned_agent_manual_enrollment=True,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStepInput(
                channel=ContactChannel.EMAIL,
                delay_hours=0,
                message_goal="Check whether the dormant lead is still considering a move.",
                template_key="demo-dormant-email-1",
                max_attempts=1,
            ),
            CampaignCadenceStepInput(
                channel=ContactChannel.SMS,
                delay_hours=48,
                message_goal="Briefly ask if the lead wants their assigned agent to follow up.",
                template_key="demo-dormant-sms-1",
                max_attempts=1,
            ),
            CampaignCadenceStepInput(
                channel=ContactChannel.EMAIL,
                delay_hours=120,
                message_goal="Make one final low-pressure follow-up before ending the cadence.",
                template_key="demo-dormant-email-2",
                max_attempts=1,
            ),
        ),
    )


def _demo_users(workspace_name: str) -> tuple[DemoSeedUser, ...]:
    return (
        _demo_user(
            workspace_name,
            "admin",
            "Demo Brokerage Admin",
            WorkspaceMembershipRole.BROKERAGE_ADMIN,
        ),
        _demo_user(
            workspace_name,
            "manager",
            "Demo Sales Manager",
            WorkspaceMembershipRole.MANAGER,
        ),
        _demo_user(
            workspace_name,
            "agent",
            "Avery Demo Agent",
            WorkspaceMembershipRole.ASSIGNED_AGENT,
        ),
    )


def _demo_user(
    workspace_name: str,
    handle: str,
    full_name: str,
    role: WorkspaceMembershipRole,
) -> DemoSeedUser:
    return DemoSeedUser(
        email=f"{handle}@{DEMO_EMAIL_DOMAIN}",
        full_name=full_name,
        role=role,
        user_id=_demo_uuid(workspace_name, f"user:{handle}"),
        membership_id=_demo_uuid(workspace_name, f"membership:{handle}"),
    )


def _demo_leads(
    workspace_id: WorkspaceId,
    assigned_agent: DemoSeedUser,
    now: datetime,
) -> tuple[CanonicalLeadRecord, ...]:
    scenarios = (
        ("queued-one", "Morgan Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        ("queued-two", "Taylor Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        ("vetoed", "Jordan Demo", LeadType.SELLER, ContactPermissionStatus.CONFIRMED, False),
        ("waiting-email", "Riley Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        (
            "waiting-email-two",
            "Casey Demo",
            LeadType.BUYER_SELLER,
            ContactPermissionStatus.CONFIRMED,
            False,
        ),
        ("active", "Skyler Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        ("paused", "Jamie Demo", LeadType.UNKNOWN, ContactPermissionStatus.CONFIRMED, False),
        ("handoff", "Quinn Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        ("acknowledged", "Parker Demo", LeadType.SELLER, ContactPermissionStatus.CONFIRMED, False),
        ("suppressed", "Reese Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, True),
        ("completed", "Dakota Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
        ("failed-message", "Finley Demo", LeadType.BUYER, ContactPermissionStatus.CONFIRMED, False),
    )
    return tuple(
        _lead(
            workspace_id=workspace_id,
            slug=slug,
            display_name=display_name,
            lead_type=lead_type,
            email_permission=email_permission,
            sms_opted_out=sms_opted_out,
            assigned_agent=assigned_agent,
            now=now,
            index=index,
        )
        for index, (slug, display_name, lead_type, email_permission, sms_opted_out) in enumerate(
            scenarios,
            start=1,
        )
    )


def _lead(
    *,
    workspace_id: WorkspaceId,
    slug: str,
    display_name: str,
    lead_type: LeadType,
    email_permission: ContactPermissionStatus,
    sms_opted_out: bool,
    assigned_agent: DemoSeedUser,
    now: datetime,
    index: int,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=workspace_id,
        lead_id=_demo_uuid(str(workspace_id), f"lead:{slug}"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=f"demo-crm-{index:03d}",
        source_payload_version="demo_seed:v1",
        source_updated_at=now - timedelta(days=1),
        facts_derived_at=now,
        assigned_agent_crm_id="demo-agent-001",
        assigned_agent_name_present=True,
        has_accountable_owner=True,
        ownership_last_changed_at=now - timedelta(days=180),
        lead_type=lead_type,
        classification_reason=LeadClassificationReason.CRM_TYPE_BUYER
        if lead_type == LeadType.BUYER
        else LeadClassificationReason.CRM_TYPE_SELLER
        if lead_type == LeadType.SELLER
        else LeadClassificationReason.CRM_TYPE_BUYER_SELLER
        if lead_type == LeadType.BUYER_SELLER
        else LeadClassificationReason.CRM_TYPE_MISSING,
        crm_type_raw=lead_type.value,
        lead_source="demo_seed",
        lead_stage="long_term_nurture",
        created_via="demo_seed",
        tags=("ai_nurture_demo", "dormant_candidate"),
        mapped_custom_fields={
            "display_name": display_name,
            "assigned_agent_user_id": str(assigned_agent.user_id),
        },
        primary_email=f"lead-{slug}@{DEMO_EMAIL_DOMAIN}",
        primary_phone=f"+1555010{index:04d}",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=email_permission,
        sms_opted_out=sms_opted_out,
        email_unsubscribed=False,
        do_not_contact=False,
        suppression_types=frozenset({SuppressionType.SMS_OPT_OUT})
        if sms_opted_out
        else frozenset(),
        permission_evidence={"source": "synthetic_demo_seed", "captured_at": now.isoformat()},
        crm_created_at=now - timedelta(days=240),
        crm_updated_at=now - timedelta(days=90),
        last_activity_at=now - timedelta(days=90),
        last_meaningful_communication_at=now - timedelta(days=90),
        last_agent_activity_at=None,
        contacted_count=0,
        activity_reliability=ActivityReliability.RELIABLE,
    )


def _outbound_message(
    *,
    campaign_view: CampaignAdminView,
    lead: CanonicalLeadRecord,
    step_id: str,
    status: OutboundMessageStatus,
    provider_send_status: ProviderSendStatus,
    provider_delivery_status: ProviderDeliveryStatus | None,
    suffix: str,
    now: datetime,
    failure_reason: str | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=_demo_uuid(str(lead.lead_id), f"message:{suffix}"),
        workspace_id=campaign_view.campaign.workspace_id,
        lead_id=lead.lead_id,
        campaign_id=campaign_view.campaign.campaign_id,
        cadence_step_id=step_id,
        channel=ContactChannel.EMAIL,
        status=status,
        idempotency_key=f"demo:{lead.lead_id}:{suffix}",
        body="Demo operational message state for UI review.",
        subject="Demo follow-up state",
        planned_at=now,
        sent_at=now if status == OutboundMessageStatus.SENT else None,
        message_version=1,
        provider_send_status=provider_send_status,
        provider_name="sink",
        provider_message_id=f"demo-provider-{suffix}",
        provider_delivery_status=provider_delivery_status,
        provider_status_updated_at=now,
        delivered_at=now if provider_delivery_status == ProviderDeliveryStatus.DELIVERED else None,
        failure_reason=failure_reason,
        draft_prompt_version=DEMO_OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION,
        draft_model="openai/gpt-4o-mini",
        draft_latency_ms=9,
        draft_usage_tokens=42,
        draft_confidence=0.91,
        draft_personalization_notes=("Demo seed state",),
        draft_safety_flags=(),
        created_at=now,
        updated_at=now,
    )


def _classification_response_for_prompt(prompt: str) -> str:
    normalized = prompt.lower()
    if "stop texting" in normalized or "unsubscribe" in normalized:
        return json.dumps(
            {
                "intent": "opt_out",
                "confidence": 0.98,
                "asks_for_human": False,
                "shows_buying_interest": False,
                "shows_selling_interest": False,
                "asks_property_or_advice": False,
                "opt_out_detected": True,
                "summary_text": "Lead requested no further SMS outreach.",
                "preferences": {},
            },
        )
    if "sell my condo" in normalized or "seller" in normalized:
        return json.dumps(
            {
                "intent": "seller_interest",
                "confidence": 0.94,
                "asks_for_human": False,
                "shows_buying_interest": False,
                "shows_selling_interest": True,
                "asks_property_or_advice": False,
                "opt_out_detected": False,
                "summary_text": "Lead expressed seller interest and a near-term move need.",
                "preferences": {"timeline": "soon", "intent": "sell_and_buy"},
            },
        )
    return json.dumps(
        {
            "intent": "human_requested",
            "confidence": 0.95,
            "asks_for_human": True,
            "shows_buying_interest": False,
            "shows_selling_interest": False,
            "asks_property_or_advice": False,
            "opt_out_detected": False,
            "summary_text": "Lead asked for an agent callback.",
            "preferences": {"next_action": "call_today"},
        },
    )


def _validate_synthetic_leads(leads: tuple[CanonicalLeadRecord, ...]) -> None:
    for lead in leads:
        if lead.primary_email is None or not lead.primary_email.endswith(
            f"@{DEMO_EMAIL_DOMAIN}"
        ):
            raise DemoSeedSafetyError(
                f"All demo lead emails must use @{DEMO_EMAIL_DOMAIN}."
            )
        if lead.primary_phone is None or not lead.primary_phone.startswith("+1555"):
            raise DemoSeedSafetyError("All demo lead phones must use fictitious +1555 numbers.")


def _admin_actor(workspace_id: WorkspaceId, admin: DemoSeedUser) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=admin.user_id,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=workspace_id,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=admin.membership_id,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _demo_uuid(seed: str, key: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"{seed}:{key}")


def _parse_args() -> DemoSeedOptions:
    parser = argparse.ArgumentParser(description="Create or refresh a synthetic demo workspace.")
    parser.add_argument("--workspace-name", default="Demo: Miller Schackman")
    parser.add_argument("--allow-production", action="store_true")
    parser.add_argument("--confirm-text", default="")
    parser.add_argument("--reset-leads", action="store_true")
    args = parser.parse_args()
    return DemoSeedOptions(
        workspace_name=args.workspace_name,
        allow_production=args.allow_production,
        confirm_text=args.confirm_text,
        reset_leads=args.reset_leads,
    )


async def _run_cli() -> None:
    options = _parse_args()
    settings = get_settings()
    validate_demo_seed_safety(settings, options)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await seed_demo_workspace(session, settings=settings, options=options)
        await session.commit()
    await engine.dispose()
    print(
        "Demo workspace seeded: "
        f"workspace_id={result.workspace_id} campaign_id={result.campaign_id} "
        f"leads={result.lead_count} workflows={result.workflow_count} "
        f"handoffs={result.handoff_count}",
    )
    print(f"Demo sign-in users use password: {DEMO_PASSWORD}")
    for user in result.demo_users:
        print(f"- {user.role.value}: {user.email}")


def main() -> None:
    asyncio.run(_run_cli())


if __name__ == "__main__":
    main()