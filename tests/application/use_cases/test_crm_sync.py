from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.crm import CRMActivity
from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.application.use_cases.crm_sync import (
    ExecuteQueuedCRMSyncStatus,
    RequestCRMSyncStatus,
    RunFollowUpBossLeadSyncStatus,
    _map_crm_activity_to_event,
    enqueue_due_follow_up_boss_crm_syncs,
    execute_queued_follow_up_boss_crm_sync,
    request_crm_sync,
    run_follow_up_boss_lead_snapshot_sync,
)
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
    WorkspaceAgentMappingConfig,
)
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    WorkspaceCRMSyncConfig,
    WorkspaceCRMSyncScheduleTarget,
)
from app.domain.events import DomainEvent, DomainEventType
from app.domain.identity import (
    User,
    UserStatus,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.domain.leads import (
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    EffectiveOwnerSource,
)
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeOutboundMessageRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOperationalControlRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
PREVIOUS_SYNC_AT = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
SYNC_JOB_ID = UUID("22222222-2222-2222-2222-222222222222")
CRM_AGENT_RECORD_ID = UUID("33333333-3333-3333-3333-333333333333")
MAPPING_ID = UUID("44444444-4444-4444-4444-444444444444")
ASSIGNED_AGENT_USER_ID = UUID("55555555-5555-5555-5555-555555555555")
FALLBACK_MANAGER_USER_ID = UUID("66666666-6666-6666-6666-666666666666")
MEMBERSHIP_ID = UUID("77777777-7777-7777-7777-777777777777")


class FakeLeadRepository:
    def __init__(
        self,
        existing: tuple[CanonicalLeadRecord, ...] = (),
        failing_crm_lead_ids: set[str] | None = None,
    ) -> None:
        self.failing_crm_lead_ids = failing_crm_lead_ids or set()
        self.saved: list[CanonicalLeadRecord] = []
        self.by_crm_id = {
            (lead.workspace_id, lead.crm_provider, lead.crm_lead_id): lead for lead in existing
        }

    async def get_by_id(self, workspace_id: UUID, lead_id: UUID) -> CanonicalLeadRecord | None:
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> CanonicalLeadRecord | None:
        return None

    async def get_by_crm_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return self.by_crm_id.get((workspace_id, crm_provider, crm_lead_id))

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: UUID,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        return tuple(
            lead
            for lead in self.by_crm_id.values()
            if lead.workspace_id == workspace_id
            and lead.assigned_agent_crm_id == assigned_agent_crm_id
        )

    async def get_by_primary_phone(
        self,
        workspace_id: UUID,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        _ = (workspace_id, phone_number)
        return None

    async def get_by_primary_email(
        self,
        workspace_id: UUID,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        matches = await self.list_by_primary_email(workspace_id, email_address)
        if len(matches) != 1:
            return None
        return matches[0]

    async def list_by_primary_email(
        self,
        workspace_id: UUID,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        requested = email_address.strip().lower()
        if not requested:
            return ()
        return tuple(
            lead
            for lead in self.by_crm_id.values()
            if lead.workspace_id == workspace_id
            and lead.primary_email is not None
            and lead.primary_email.strip().lower() == requested
        )

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        if record.crm_lead_id in self.failing_crm_lead_ids:
            raise RuntimeError(f"boom::{record.crm_lead_id}")
        self.saved.append(record)
        self.by_crm_id[(record.workspace_id, record.crm_provider, record.crm_lead_id)] = record
        return record


class FakeCRMSyncJobRepository:
    def __init__(
        self,
        recent_jobs: tuple[CRMSyncJob, ...] = (),
        active_job: CRMSyncJob | None = None,
        latest_job: CRMSyncJob | None = None,
        latest_completed_job: CRMSyncJob | None = None,
    ) -> None:
        self.recent_jobs = recent_jobs
        self.active_job = active_job
        self.latest_job = latest_job
        self.latest_completed_job = latest_completed_job
        self.saved: list[CRMSyncJob] = []

    async def get_by_id(self, workspace_id: UUID, sync_job_id: UUID) -> CRMSyncJob | None:
        return next((job for job in self.saved if job.sync_job_id == sync_job_id), None)

    async def list_recent(self, workspace_id: UUID, limit: int = 100) -> tuple[CRMSyncJob, ...]:
        return self.recent_jobs[:limit]

    async def get_latest_for_workspace_provider(
        self,
        workspace_id: UUID,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        return self.latest_job

    async def get_latest_completed_for_workspace_provider(
        self,
        workspace_id: UUID,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        return self.latest_completed_job

    async def get_active_for_workspace_provider(
        self,
        workspace_id: UUID,
        crm_provider: str,
    ) -> CRMSyncJob | None:
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
        workspace_id: UUID,
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
            updated_at=now,
        )
        self.active_job = claimed
        self.saved.append(claimed)
        return claimed

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        self.saved.append(job)
        self.latest_job = job
        self.active_job = (
            job if job.status in {CRMSyncJobStatus.PENDING, CRMSyncJobStatus.RUNNING} else None
        )
        if job.status == CRMSyncJobStatus.COMPLETED:
            self.latest_completed_job = job
        return job


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeWorkspaceCRMSyncConfigRepository:
    def __init__(
        self,
        targets: tuple[WorkspaceCRMSyncScheduleTarget, ...],
    ) -> None:
        self.targets = targets

    async def get_by_workspace_id(self, workspace_id: UUID) -> None:
        _ = workspace_id
        return None

    async def list_active_workspace_schedule_targets(
        self,
        *,
        limit: int = 100,
        default_interval_seconds: int,
    ) -> tuple[WorkspaceCRMSyncScheduleTarget, ...]:
        _ = default_interval_seconds
        return self.targets[:limit]

    async def save(self, config: WorkspaceCRMSyncConfig) -> WorkspaceCRMSyncConfig:
        return config


class FakeLeadSnapshotSource:
    def __init__(
        self,
        pages: tuple[CanonicalLeadSnapshotPage, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self.pages = list(pages)
        self.error = error
        self.requests: list[dict[str, object]] = []

    async def list_lead_snapshots(
        self,
        *,
        workspace_id: UUID,
        page_size: int = 100,
        cursor: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        sort_by: CRMSyncLeadSort | None = None,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        self.requests.append(
            {
                "workspace_id": workspace_id,
                "page_size": page_size,
                "cursor": cursor,
                "updated_after": updated_after,
                "updated_before": updated_before,
                "sort_by": sort_by,
                "mapped_custom_field_keys": mapped_custom_field_keys,
            },
        )
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)


class FakeCRMActivitySource:
    def __init__(
        self,
        activities_by_lead: dict[str, tuple[CRMActivity, ...]] | None = None,
    ) -> None:
        self.activities_by_lead = activities_by_lead or {}
        self.calls: list[dict[str, object]] = []

    async def get_recent_activity(
        self,
        workspace_id: UUID,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "crm_lead_id": crm_lead_id,
                "limit": limit,
            }
        )
        return list(self.activities_by_lead.get(crm_lead_id, ()))


class FakeCrmConversationEventRepository:
    def __init__(self) -> None:
        self.saved: list[CrmConversationEvent] = []

    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        _ = (workspace_id, lead_id, limit)
        return ()

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        self.saved.append(event)
        return event


class FakeCRMAgentRepository:
    def __init__(self, agents: tuple[CRMAgent, ...] = ()) -> None:
        self._by_record_id = {agent.agent_record_id: agent for agent in agents}
        self.agents = agents

    async def get_by_record_id(self, workspace_id: UUID, agent_record_id: UUID) -> CRMAgent | None:
        agent = self._by_record_id.get(agent_record_id)
        if agent is None or agent.workspace_id != workspace_id:
            return None
        return agent

    async def get_by_external_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        return next(
            (
                agent
                for agent in self.agents
                if agent.workspace_id == workspace_id
                and agent.crm_provider == crm_provider
                and agent.external_agent_id == external_agent_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[CRMAgent, ...]:
        return tuple(agent for agent in self.agents if agent.workspace_id == workspace_id)

    async def save(self, agent: CRMAgent) -> CRMAgent:
        self._by_record_id[agent.agent_record_id] = agent
        self.agents = tuple(
            item for item in self.agents if item.agent_record_id != agent.agent_record_id
        ) + (agent,)
        return agent


class FakeWorkspaceAgentCRMMappingRepository:
    def __init__(self, mappings: tuple[WorkspaceAgentCRMMapping, ...] = ()) -> None:
        self.mappings = mappings

    async def get_by_id(
        self,
        workspace_id: UUID,
        mapping_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.mappings
                if mapping.workspace_id == workspace_id and mapping.mapping_id == mapping_id
            ),
            None,
        )

    async def get_by_crm_agent_record_id(
        self,
        workspace_id: UUID,
        crm_agent_record_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.mappings
                if mapping.workspace_id == workspace_id
                and mapping.crm_agent_record_id == crm_agent_record_id
            ),
            None,
        )

    async def get_by_app_user_id(
        self,
        workspace_id: UUID,
        app_user_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.mappings
                if mapping.workspace_id == workspace_id and mapping.app_user_id == app_user_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[WorkspaceAgentCRMMapping, ...]:
        return tuple(mapping for mapping in self.mappings if mapping.workspace_id == workspace_id)

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        self.mappings = tuple(
            item for item in self.mappings if item.mapping_id != mapping.mapping_id
        ) + (mapping,)
        return mapping


class FakeWorkspaceAgentMappingConfigRepository:
    def __init__(self, config: WorkspaceAgentMappingConfig | None) -> None:
        self.config = config

    async def get_by_workspace_id(self, workspace_id: UUID) -> WorkspaceAgentMappingConfig | None:
        if self.config is None or self.config.workspace_id != workspace_id:
            return None
        return self.config

    async def save(self, config: WorkspaceAgentMappingConfig) -> WorkspaceAgentMappingConfig:
        self.config = config
        return config


class FakeWorkspaceMembershipRepository:
    def __init__(self, memberships: tuple[WorkspaceMembership, ...] = ()) -> None:
        self.memberships = memberships

    async def get_by_id(self, membership_id: UUID) -> WorkspaceMembership | None:
        return next(
            (
                membership
                for membership in self.memberships
                if membership.membership_id == membership_id
            ),
            None,
        )

    async def get_by_user_and_workspace(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None:
        return next(
            (
                membership
                for membership in self.memberships
                if membership.user_id == user_id and membership.workspace_id == workspace_id
            ),
            None,
        )

    async def list_by_user_id(self, user_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(membership for membership in self.memberships if membership.user_id == user_id)

    async def list_by_workspace_id(self, workspace_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            membership for membership in self.memberships if membership.workspace_id == workspace_id
        )

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        self.memberships = tuple(
            item for item in self.memberships if item.membership_id != membership.membership_id
        ) + (membership,)
        return membership


class FakeUserRepository:
    def __init__(self, users: dict[UUID, User] | None = None) -> None:
        self.users = users or {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        return next(
            (user for user in self.users.values() if user.email_normalized == email_normalized),
            None,
        )

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
        _ = (workspace_id, allowed_roles)
        return await self.get_by_email_normalized(email_normalized)

    async def save(self, user: User) -> User:
        self.users[user.user_id] = user
        return user


def _lead(
    crm_lead_id: str,
    *,
    tags: tuple[str, ...] = (),
    source_updated_at: datetime | None = NOW,
    assigned_agent_crm_id: str | None = None,
    has_accountable_owner: bool = False,
    primary_email: str | None = None,
    has_email: bool = False,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.UNKNOWN,
    do_not_contact: bool | None = None,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=UUID(f"00000000-0000-0000-0000-{int(crm_lead_id):012d}"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=crm_lead_id,
        facts_derived_at=NOW,
        source_payload_version="follow_up_boss_person:v1",
        source_updated_at=source_updated_at,
        tags=tags,
        assigned_agent_crm_id=assigned_agent_crm_id,
        has_accountable_owner=has_accountable_owner,
        primary_email=primary_email,
        has_email=has_email,
        email_permission_status=email_permission_status,
        do_not_contact=do_not_contact,
    )


def _campaign_config(*, crm_enrollment_tag: str | None) -> CampaignExecutionConfig:
    return CampaignExecutionConfig(
        campaign_id=UUID("44444444-4444-4444-4444-444444444444"),
        campaign_version_id=UUID("55555555-5555-5555-5555-555555555555"),
        workspace_id=WORKSPACE_ID,
        campaign_name="Configured Campaign",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(ContactChannel.EMAIL,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=NOW.time(),
        quiet_hours_end=NOW.time(),
        timezone="UTC",
        sms_compliance_required=False,
        preflight_digest_enabled=False,
        crm_enrollment_tag=crm_enrollment_tag,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(),
        created_at=NOW,
        published_at=NOW,
    )


def _contact_policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        sms_compliance_state=SmsComplianceState.APPROVED,
    )


async def _record_commit(calls: list[str]) -> None:
    calls.append("commit")


def _activity(
    *,
    crm_activity_id: str,
    activity_type: str = "Note",
    direction: str | None = "internal",
) -> CRMActivity:
    return CRMActivity(
        crm_activity_id=crm_activity_id,
        activity_type=activity_type,
        timestamp=NOW,
        content=f"content::{crm_activity_id}",
        agent_id="42",
        actor_name="Agent Ada",
        direction=direction,
    )


def _completed_job(*, cursor_finished_at: datetime) -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=UUID("33333333-3333-3333-3333-333333333333"),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=CRMSyncType.INCREMENTAL,
        status=CRMSyncJobStatus.COMPLETED,
        started_at=PREVIOUS_SYNC_AT,
        finished_at=PREVIOUS_SYNC_AT,
        cursor_started_at=None,
        cursor_finished_at=cursor_finished_at,
        total_seen=2,
        total_upserted=2,
        total_failed=0,
        failure_reason=None,
        created_by_user_id=None,
        created_at=PREVIOUS_SYNC_AT,
        updated_at=PREVIOUS_SYNC_AT,
    )


def _pending_job() -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=SYNC_JOB_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=CRMSyncType.FULL,
        status=CRMSyncJobStatus.PENDING,
        started_at=None,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        created_by_user_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _crm_agent(external_agent_id: str, *, is_active: bool = True) -> CRMAgent:
    return CRMAgent(
        agent_record_id=CRM_AGENT_RECORD_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id=external_agent_id,
        name="Agent Ada",
        email="agent@example.com",
        email_normalized="agent@example.com",
        phone="+15550000000",
        is_active=is_active,
        last_seen_at=NOW,
        raw_payload={"id": external_agent_id},
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=UUID("99999999-9999-9999-9999-999999999999"),
        temporal_workflow_id="workflow-123",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        campaign_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        lead_id=UUID("00000000-0000-0000-0000-000000000001"),
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _pending_message() -> OutboundMessage:
    return OutboundMessage(
        message_id=UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        workspace_id=WORKSPACE_ID,
        lead_id=UUID("00000000-0000-0000-0000-000000000001"),
        campaign_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="pending-message-1",
        body="hello",
        created_at=NOW,
        updated_at=NOW,
        provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
    )


def _mapping(*, app_user_id: UUID | None) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=MAPPING_ID,
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=CRM_AGENT_RECORD_ID,
        app_user_id=app_user_id,
        mapping_status=CRMAgentMappingStatus.VERIFIED,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        resolved_by_user_id=None,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping_config(user_id: UUID | None) -> WorkspaceAgentMappingConfig:
    return WorkspaceAgentMappingConfig(
        workspace_id=WORKSPACE_ID,
        unmapped_assignment_fallback_user_id=user_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _membership(
    *,
    membership_id: UUID,
    user_id: UUID,
    role: WorkspaceMembershipRole,
) -> WorkspaceMembership:
    return WorkspaceMembership(
        membership_id=membership_id,
        workspace_id=WORKSPACE_ID,
        user_id=user_id,
        role=role,
        status=WorkspaceMembershipStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
    )


def _user(user_id: UUID) -> User:
    email = f"{str(user_id)[:8]}@example.com"
    return User(
        user_id=user_id,
        email=email,
        email_normalized=email,
        full_name="Agent User",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_runs_full_sync_across_multiple_pages() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(leads=(_lead("1"), _lead("2")), next_cursor="cursor-2"),
            CanonicalLeadSnapshotPage(leads=(_lead("3"),), next_cursor=None),
        ),
    )
    lead_repository = FakeLeadRepository()
    job_repository = FakeCRMSyncJobRepository()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=job_repository,
        now=NOW,
        sync_type=CRMSyncType.FULL,
        page_size=2,
        mapped_custom_field_keys=("budget",),
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert result.page_count == 2
    assert result.job.sync_job_id == SYNC_JOB_ID
    assert result.job.total_seen == 3
    assert result.job.total_upserted == 3
    assert result.job.total_failed == 0
    assert result.job.status == CRMSyncJobStatus.COMPLETED
    assert result.job.cursor_started_at is None
    assert result.job.cursor_finished_at == NOW
    assert [lead.crm_lead_id for lead in lead_repository.saved] == ["1", "2", "3"]
    assert source.requests[0]["cursor"] is None
    assert source.requests[0]["updated_after"] is None
    assert source.requests[0]["updated_before"] == NOW
    assert source.requests[0]["mapped_custom_field_keys"] == ("budget",)
    assert source.requests[1]["cursor"] == "cursor-2"


async def test_sync_resolves_effective_owner_from_verified_mapping() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(
                leads=(_lead("1", assigned_agent_crm_id="agent-99", has_accountable_owner=True),),
            ),
        ),
    )
    lead_repository = FakeLeadRepository()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        crm_agent_repository=FakeCRMAgentRepository((_crm_agent("agent-99"),)),
        workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(
            (_mapping(app_user_id=ASSIGNED_AGENT_USER_ID),),
        ),
        workspace_agent_mapping_config_repository=FakeWorkspaceAgentMappingConfigRepository(
            _mapping_config(FALLBACK_MANAGER_USER_ID),
        ),
        workspace_membership_repository=FakeWorkspaceMembershipRepository(
            (
                _membership(
                    membership_id=MEMBERSHIP_ID,
                    user_id=ASSIGNED_AGENT_USER_ID,
                    role=WorkspaceMembershipRole.ASSIGNED_AGENT,
                ),
            ),
        ),
        user_repository=FakeUserRepository({ASSIGNED_AGENT_USER_ID: _user(ASSIGNED_AGENT_USER_ID)}),
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    saved_lead = lead_repository.saved[0]
    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert saved_lead.assigned_agent_user_id == ASSIGNED_AGENT_USER_ID
    assert saved_lead.effective_owner_user_id == ASSIGNED_AGENT_USER_ID
    assert saved_lead.effective_owner_source == EffectiveOwnerSource.CRM_MAPPING
    assert saved_lead.assignment_resolution_status == AssignmentResolutionStatus.RESOLVED
    assert saved_lead.assignment_last_resolved_at == NOW


async def test_sync_routes_unmapped_assignment_to_fallback_manager() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(
                leads=(_lead("1", assigned_agent_crm_id="agent-99", has_accountable_owner=True),),
            ),
        ),
    )
    lead_repository = FakeLeadRepository()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        crm_agent_repository=FakeCRMAgentRepository((_crm_agent("agent-99"),)),
        workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(),
        workspace_agent_mapping_config_repository=FakeWorkspaceAgentMappingConfigRepository(
            _mapping_config(FALLBACK_MANAGER_USER_ID),
        ),
        workspace_membership_repository=FakeWorkspaceMembershipRepository(
            (
                _membership(
                    membership_id=MEMBERSHIP_ID,
                    user_id=FALLBACK_MANAGER_USER_ID,
                    role=WorkspaceMembershipRole.MANAGER,
                ),
            ),
        ),
        user_repository=FakeUserRepository(
            {FALLBACK_MANAGER_USER_ID: _user(FALLBACK_MANAGER_USER_ID)},
        ),
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    saved_lead = lead_repository.saved[0]
    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert saved_lead.assigned_agent_user_id is None
    assert saved_lead.effective_owner_user_id == FALLBACK_MANAGER_USER_ID
    assert saved_lead.effective_owner_source == EffectiveOwnerSource.WORKSPACE_MANAGER_FALLBACK
    assert saved_lead.assignment_resolution_status == AssignmentResolutionStatus.UNMAPPED_CRM_AGENT


async def test_sync_reconciles_ownership_change_without_pausing_workflow_or_cancelling_messages(
) -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(
                leads=(_lead("1", assigned_agent_crm_id="agent-99", has_accountable_owner=True),),
            ),
        ),
    )
    existing_lead = replace(
        _lead("1", assigned_agent_crm_id="agent-10", has_accountable_owner=True),
        assigned_agent_user_id=UUID("88888888-8888-8888-8888-888888888888"),
        effective_owner_user_id=UUID("88888888-8888-8888-8888-888888888888"),
        effective_owner_source=EffectiveOwnerSource.CRM_MAPPING,
        assignment_resolution_status=AssignmentResolutionStatus.RESOLVED,
        assignment_last_resolved_at=NOW - timedelta(hours=1),
    )
    lead_repository = FakeLeadRepository(existing=(existing_lead,))
    workflows = FakeLeadWorkflowRepository()
    transitions = FakeWorkflowTransitionRepository()
    outbox = FakeTemporalSignalOutboxRepository()
    messages = FakeOutboundMessageRepository()
    event_bus = FakeEventBus()
    await workflows.save(_workflow())
    await messages.save(_pending_message())

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        crm_agent_repository=FakeCRMAgentRepository((_crm_agent("agent-99"),)),
        workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(
            (_mapping(app_user_id=ASSIGNED_AGENT_USER_ID),),
        ),
        workspace_agent_mapping_config_repository=FakeWorkspaceAgentMappingConfigRepository(
            _mapping_config(FALLBACK_MANAGER_USER_ID),
        ),
        workspace_membership_repository=FakeWorkspaceMembershipRepository(
            (
                _membership(
                    membership_id=MEMBERSHIP_ID,
                    user_id=ASSIGNED_AGENT_USER_ID,
                    role=WorkspaceMembershipRole.ASSIGNED_AGENT,
                ),
            ),
        ),
        user_repository=FakeUserRepository({ASSIGNED_AGENT_USER_ID: _user(ASSIGNED_AGENT_USER_ID)}),
        lead_workflow_repository=workflows,
        workflow_transition_repository=transitions,
        temporal_signal_outbox_repository=outbox,
        outbound_message_repository=messages,
        event_bus=event_bus,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    workflow = workflows.latest_by_lead[(WORKSPACE_ID, existing_lead.lead_id)]
    assert workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert transitions.transitions == {}
    assert outbox.entries == {}
    assert messages.saved == [_pending_message()]
    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == DomainEventType.LEAD_ASSIGNMENT_RECONCILED


async def test_incremental_sync_uses_latest_completed_cursor_finished_at() -> None:
    source = FakeLeadSnapshotSource(pages=(CanonicalLeadSnapshotPage(),))
    job_repository = FakeCRMSyncJobRepository(
        recent_jobs=(_completed_job(cursor_finished_at=PREVIOUS_SYNC_AT),),
    )

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=job_repository,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert result.job.cursor_started_at == PREVIOUS_SYNC_AT
    assert source.requests[0]["updated_after"] == PREVIOUS_SYNC_AT
    assert source.requests[0]["updated_before"] == NOW


async def test_runs_limited_full_sync_for_most_recent_leads_only() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(leads=(_lead("1"), _lead("2")), next_cursor="cursor-2"),
            CanonicalLeadSnapshotPage(leads=(_lead("3"),), next_cursor="cursor-3"),
        ),
    )
    lead_repository = FakeLeadRepository()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        now=NOW,
        sync_type=CRMSyncType.FULL,
        page_size=2,
        max_leads=3,
        latest_by=CRMSyncLeadSort.UPDATED,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert result.page_count == 2
    assert result.job.total_seen == 3
    assert [lead.crm_lead_id for lead in lead_repository.saved] == ["1", "2", "3"]
    assert source.requests[0]["page_size"] == 2
    assert source.requests[0]["sort_by"] == CRMSyncLeadSort.UPDATED
    assert source.requests[1]["page_size"] == 1
    assert len(source.requests) == 2


async def test_limited_full_sync_imports_activity_for_selected_leads_only() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(leads=(_lead("1"), _lead("2")), next_cursor="cursor-2"),
            CanonicalLeadSnapshotPage(leads=(_lead("3"),), next_cursor="cursor-3"),
        ),
    )
    activity_source = FakeCRMActivitySource(
        {
            "1": (_activity(crm_activity_id="a-1"),),
            "2": (_activity(crm_activity_id="a-2", direction="outbound"),),
            "3": (_activity(crm_activity_id="a-3", direction="inbound"),),
        }
    )
    conversation_repository = FakeCrmConversationEventRepository()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        crm_activity_source=activity_source,
        crm_conversation_event_repository=conversation_repository,
        activity_limit=25,
        now=NOW,
        sync_type=CRMSyncType.FULL,
        page_size=2,
        max_leads=2,
        latest_by=CRMSyncLeadSort.CREATED,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert [call["crm_lead_id"] for call in activity_source.calls] == ["1", "2"]
    assert all(call["limit"] == 25 for call in activity_source.calls)
    assert [event.crm_activity_id for event in conversation_repository.saved] == ["a-1", "a-2"]
    assert source.requests[0]["sort_by"] == CRMSyncLeadSort.CREATED
    assert len(source.requests) == 1


async def test_marks_job_failed_when_some_leads_fail_to_upsert() -> None:
    source = FakeLeadSnapshotSource(
        pages=(CanonicalLeadSnapshotPage(leads=(_lead("1"), _lead("2"))),),
    )
    lead_repository = FakeLeadRepository(failing_crm_lead_ids={"2"})

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=lead_repository,
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.FAILED
    assert result.job.status == CRMSyncJobStatus.FAILED
    assert result.job.total_seen == 2
    assert result.job.total_upserted == 1
    assert result.job.total_failed == 1
    assert result.job.failure_reason == "1 lead(s) failed during sync; first failure: boom::2"
    assert [lead.crm_lead_id for lead in lead_repository.saved] == ["1"]


async def test_marks_job_failed_when_page_fetch_raises() -> None:
    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(error=RuntimeError("network")),
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.FAILED
    assert result.page_count == 0
    assert result.job.status == CRMSyncJobStatus.FAILED
    assert result.job.total_seen == 0
    assert result.job.total_upserted == 0
    assert result.job.total_failed == 0
    assert result.job.failure_reason == "sync page fetch failed: network"


async def test_sync_starts_matching_campaign_when_pulled_lead_has_configured_tag() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(
                leads=(
                    _lead(
                        "1",
                        tags=("ai_nurture",),
                        assigned_agent_crm_id="agent-99",
                        has_accountable_owner=True,
                        primary_email="lead@example.com",
                        has_email=True,
                        email_permission_status=ContactPermissionStatus.CONFIRMED,
                        do_not_contact=False,
                    ),
                ),
            ),
        ),
    )
    enrollment_repository = FakeCampaignEnrollmentRepository()
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    temporal = FakeTemporalWorkflowStarter()
    commit_calls: list[str] = []

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_config(crm_enrollment_tag="ai_nurture"),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _contact_policy(),
        ),
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        temporal_workflow_starter=temporal,
        event_bus=FakeEventBus(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(None),
        commit=lambda: _record_commit(commit_calls),
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert len(enrollment_repository.enrollments) == 1
    assert len(workflow_repository.workflows) == 1
    assert len(transition_repository.transitions) == 1
    assert len(temporal.calls) == 1
    assert commit_calls == ["commit"]


async def test_sync_does_not_start_campaign_when_pulled_lead_tag_does_not_match() -> None:
    source = FakeLeadSnapshotSource(
        pages=(
            CanonicalLeadSnapshotPage(
                leads=(
                    _lead(
                        "1",
                        tags=("other_tag",),
                        assigned_agent_crm_id="agent-99",
                        has_accountable_owner=True,
                        primary_email="lead@example.com",
                        has_email=True,
                        email_permission_status=ContactPermissionStatus.CONFIRMED,
                        do_not_contact=False,
                    ),
                ),
            ),
        ),
    )
    enrollment_repository = FakeCampaignEnrollmentRepository()
    temporal = FakeTemporalWorkflowStarter()

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_config(crm_enrollment_tag="ai_nurture"),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            _contact_policy(),
        ),
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert enrollment_repository.enrollments == {}
    assert temporal.calls == []


async def test_repeat_sync_for_tagged_lead_is_idempotent_when_already_enrolled() -> None:
    lead = _lead(
        "1",
        tags=("ai_nurture",),
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        primary_email="lead@example.com",
        has_email=True,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )
    enrollment_repository = FakeCampaignEnrollmentRepository()
    workflow_repository = FakeLeadWorkflowRepository()
    transition_repository = FakeWorkflowTransitionRepository()
    temporal = FakeTemporalWorkflowStarter()
    execution_repository = FakeCampaignExecutionRepository(
        _campaign_config(crm_enrollment_tag="ai_nurture"),
    )
    contact_policy_repository = FakeWorkspaceContactPolicyRepository(_contact_policy())

    first = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(
            pages=(CanonicalLeadSnapshotPage(leads=(lead,)),),
        ),
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        campaign_execution_repository=execution_repository,
        workspace_contact_policy_repository=contact_policy_repository,
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        temporal_workflow_starter=temporal,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )
    second = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=WORKSPACE_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(
            pages=(CanonicalLeadSnapshotPage(leads=(lead,)),),
        ),
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        campaign_execution_repository=execution_repository,
        workspace_contact_policy_repository=contact_policy_repository,
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        temporal_workflow_starter=temporal,
        now=NOW + timedelta(minutes=5),
        sync_job_id_factory=lambda: UUID("66666666-6666-6666-6666-666666666666"),
    )

    assert first.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert second.status == RunFollowUpBossLeadSyncStatus.COMPLETED
    assert len(enrollment_repository.enrollments) == 1
    assert len(temporal.calls) == 1


async def test_request_crm_sync_creates_pending_job_and_outbox_event() -> None:
    job_repository = FakeCRMSyncJobRepository()
    event_bus = FakeEventBus()

    result = await request_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_type=CRMSyncType.FULL,
        crm_sync_job_repository=job_repository,
        event_bus=event_bus,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert result.status == RequestCRMSyncStatus.REQUESTED
    assert result.job.status == CRMSyncJobStatus.PENDING
    assert result.job.sync_type == CRMSyncType.FULL
    assert event_bus.events[0].event_type == DomainEventType.CRM_SYNC_REQUESTED
    assert event_bus.events[0].payload["sync_job_id"] == str(SYNC_JOB_ID)


async def test_request_crm_sync_includes_recent_limit_options_in_event_payload() -> None:
    job_repository = FakeCRMSyncJobRepository()
    event_bus = FakeEventBus()

    await request_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_type=CRMSyncType.FULL,
        max_leads=50,
        crm_sync_job_repository=job_repository,
        event_bus=event_bus,
        now=NOW,
        sync_job_id_factory=lambda: SYNC_JOB_ID,
    )

    assert event_bus.events[0].payload["max_leads"] == 50
    assert event_bus.events[0].payload["latest_by"] == CRMSyncLeadSort.UPDATED.value


async def test_request_crm_sync_returns_active_job_without_publishing_duplicate() -> None:
    active = replace(_pending_job(), status=CRMSyncJobStatus.RUNNING, started_at=NOW)
    event_bus = FakeEventBus()

    result = await request_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_type=CRMSyncType.INCREMENTAL,
        crm_sync_job_repository=FakeCRMSyncJobRepository(active_job=active),
        event_bus=event_bus,
        now=NOW,
    )

    assert result.status == RequestCRMSyncStatus.ALREADY_ACTIVE
    assert result.job == active
    assert event_bus.events == []


async def test_execute_queued_sync_claims_pending_job_and_runs_snapshot_sync() -> None:
    source = FakeLeadSnapshotSource(pages=(CanonicalLeadSnapshotPage(leads=(_lead("1"),)),))
    job_repository = FakeCRMSyncJobRepository()
    await job_repository.insert_pending_if_no_active(_pending_job())

    result = await execute_queued_follow_up_boss_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_job_id=SYNC_JOB_ID,
        lead_snapshot_source=source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=job_repository,
        now=NOW,
    )

    assert result.status == ExecuteQueuedCRMSyncStatus.COMPLETED
    assert result.job is not None
    assert result.job.status == CRMSyncJobStatus.COMPLETED
    assert result.job.created_at == NOW
    assert result.page_count == 1


async def test_execute_queued_sync_passes_activity_dependencies_and_recent_limit() -> None:
    source = FakeLeadSnapshotSource(pages=(CanonicalLeadSnapshotPage(leads=(_lead("1"),)),))
    activity_source = FakeCRMActivitySource({"1": (_activity(crm_activity_id="a-1"),)})
    conversation_repository = FakeCrmConversationEventRepository()
    job_repository = FakeCRMSyncJobRepository()
    await job_repository.insert_pending_if_no_active(_pending_job())

    result = await execute_queued_follow_up_boss_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_job_id=SYNC_JOB_ID,
        lead_snapshot_source=source,
        crm_activity_source=activity_source,
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=job_repository,
        crm_conversation_event_repository=conversation_repository,
        now=NOW,
        max_leads=1,
        latest_by=CRMSyncLeadSort.UPDATED,
    )

    assert result.status == ExecuteQueuedCRMSyncStatus.COMPLETED
    assert [call["crm_lead_id"] for call in activity_source.calls] == ["1"]
    assert [event.crm_activity_id for event in conversation_repository.saved] == ["a-1"]


async def test_execute_queued_sync_is_noop_when_job_was_already_claimed() -> None:
    result = await execute_queued_follow_up_boss_crm_sync(
        workspace_id=WORKSPACE_ID,
        sync_job_id=SYNC_JOB_ID,
        lead_snapshot_source=FakeLeadSnapshotSource(),
        lead_repository=FakeLeadRepository(),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        now=NOW,
    )

    assert result.status == ExecuteQueuedCRMSyncStatus.NOT_CLAIMED
    assert result.job is None


async def test_scheduler_enqueues_full_until_first_success_then_incremental_when_due() -> None:
    event_bus = FakeEventBus()
    never_synced_repository = FakeCRMSyncJobRepository()

    first_result = await enqueue_due_follow_up_boss_crm_syncs(
        workspace_crm_sync_config_repository=FakeWorkspaceCRMSyncConfigRepository(
            (
                WorkspaceCRMSyncScheduleTarget(
                    workspace_id=WORKSPACE_ID,
                    crm_sync_enabled=True,
                    crm_sync_interval_seconds=300,
                ),
            ),
        ),
        crm_sync_job_repository=never_synced_repository,
        event_bus=event_bus,
        now=NOW,
        default_interval_seconds=300,
    )

    assert first_result.requested_count == 1
    assert never_synced_repository.saved[0].sync_type == CRMSyncType.FULL

    completed = _completed_job(cursor_finished_at=NOW - timedelta(minutes=10))
    due_repository = FakeCRMSyncJobRepository(
        latest_job=completed,
        latest_completed_job=completed,
    )

    second_result = await enqueue_due_follow_up_boss_crm_syncs(
        workspace_crm_sync_config_repository=FakeWorkspaceCRMSyncConfigRepository(
            (
                WorkspaceCRMSyncScheduleTarget(
                    workspace_id=WORKSPACE_ID,
                    crm_sync_enabled=True,
                    crm_sync_interval_seconds=300,
                ),
            ),
        ),
        crm_sync_job_repository=due_repository,
        event_bus=event_bus,
        now=NOW,
        default_interval_seconds=300,
    )

    assert second_result.requested_count == 1
    assert due_repository.saved[0].sync_type == CRMSyncType.INCREMENTAL


async def test_scheduler_skips_active_or_not_due_workspaces() -> None:
    active = _pending_job()
    repository = FakeCRMSyncJobRepository(
        active_job=active,
        latest_job=replace(active, updated_at=NOW - timedelta(minutes=1)),
    )

    result = await enqueue_due_follow_up_boss_crm_syncs(
        workspace_crm_sync_config_repository=FakeWorkspaceCRMSyncConfigRepository(
            (
                WorkspaceCRMSyncScheduleTarget(
                    workspace_id=WORKSPACE_ID,
                    crm_sync_enabled=True,
                    crm_sync_interval_seconds=300,
                ),
            ),
        ),
        crm_sync_job_repository=repository,
        event_bus=FakeEventBus(),
        now=NOW,
        default_interval_seconds=300,
    )

    assert result.requested_count == 0
    assert result.skipped_active_count == 1


async def test_scheduler_skips_disabled_workspaces() -> None:
    result = await enqueue_due_follow_up_boss_crm_syncs(
        workspace_crm_sync_config_repository=FakeWorkspaceCRMSyncConfigRepository(
            (
                WorkspaceCRMSyncScheduleTarget(
                    workspace_id=WORKSPACE_ID,
                    crm_sync_enabled=False,
                    crm_sync_interval_seconds=300,
                ),
            ),
        ),
        crm_sync_job_repository=FakeCRMSyncJobRepository(),
        event_bus=FakeEventBus(),
        now=NOW,
        default_interval_seconds=300,
    )

    assert result.requested_count == 0
    assert result.skipped_disabled_count == 1


def test_map_crm_activity_to_event_preserves_direction_and_actor_name() -> None:
    event = _map_crm_activity_to_event(
        workspace_id=WORKSPACE_ID,
        lead_id=_lead("1").lead_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        activity=_activity(crm_activity_id="text_message:88", direction="outbound"),
        now=NOW,
    )

    assert event.crm_activity_id == "text_message:88"
    assert event.actor_agent_id == "42"
    assert event.actor_name == "Agent Ada"
    assert event.direction == CrmConversationEventDirection.OUTBOUND
