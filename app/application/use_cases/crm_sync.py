from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.crm import CRMActivity
from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    CRMSyncJobRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceCRMSyncConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.process_crm_tag_campaign_enrollment import (
    process_crm_tag_campaign_enrollment,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncLeadSort, CRMSyncType
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workspace_automation import WorkspaceAutomationStatus


class RunFollowUpBossLeadSyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class RunFollowUpBossLeadSyncResult:
    status: RunFollowUpBossLeadSyncStatus
    job: CRMSyncJob
    page_count: int


class RequestCRMSyncStatus(StrEnum):
    REQUESTED = "requested"
    ALREADY_ACTIVE = "already_active"


@dataclass(frozen=True)
class RequestCRMSyncResult:
    status: RequestCRMSyncStatus
    job: CRMSyncJob


class ExecuteQueuedCRMSyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_CLAIMED = "not_claimed"


@dataclass(frozen=True)
class ExecuteQueuedCRMSyncResult:
    status: ExecuteQueuedCRMSyncStatus
    job: CRMSyncJob | None
    page_count: int = 0


@dataclass(frozen=True)
class EnqueueDueCRMSyncsResult:
    scanned_count: int
    requested_count: int
    skipped_disabled_count: int
    skipped_automation_blocked_count: int
    skipped_active_count: int
    skipped_not_due_count: int


class CRMActivitySource(Protocol):
    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        raise NotImplementedError


async def run_follow_up_boss_lead_snapshot_sync(
    *,
    workspace_id: WorkspaceId,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    now: datetime,
    sync_type: CRMSyncType = CRMSyncType.INCREMENTAL,
    page_size: int = 100,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    created_by_user_id: UUID | None = None,
    updated_after: datetime | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    sync_job_id_factory: Callable[[], UUID] | None = None,
    sync_job: CRMSyncJob | None = None,
    crm_activity_source: CRMActivitySource | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    activity_limit: int = 50,
) -> RunFollowUpBossLeadSyncResult:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    max_leads, latest_by = _normalize_recent_limit(
        sync_type=sync_type,
        max_leads=max_leads,
        latest_by=latest_by,
    )

    cursor_started_at = await _resolve_cursor_started_at(
        workspace_id=workspace_id,
        crm_sync_job_repository=crm_sync_job_repository,
        sync_type=sync_type,
        updated_after=updated_after,
    )
    cursor_finished_at = now
    job = await crm_sync_job_repository.save(
        _running_sync_job(
            workspace_id=workspace_id,
            sync_type=sync_type,
            now=now,
            cursor_started_at=cursor_started_at,
            cursor_finished_at=cursor_finished_at,
            created_by_user_id=created_by_user_id,
            sync_job_id_factory=sync_job_id_factory,
            sync_job=sync_job,
        ),
    )

    next_cursor: str | None = None
    remaining_leads = max_leads
    page_count = 0
    first_failure: str | None = None
    try:
        while True:
            request_page_size = page_size
            if remaining_leads is not None:
                if remaining_leads <= 0:
                    break
                request_page_size = min(page_size, remaining_leads)
            page = await lead_snapshot_source.list_lead_snapshots(
                workspace_id=workspace_id,
                page_size=request_page_size,
                cursor=next_cursor,
                updated_after=cursor_started_at,
                updated_before=cursor_finished_at,
                sort_by=latest_by,
                mapped_custom_field_keys=mapped_custom_field_keys,
            )
            page_count += 1
            total_seen = job.total_seen + len(page.leads)
            total_upserted = job.total_upserted
            total_failed = job.total_failed
            for lead in page.leads:
                try:
                    upserted_lead = await lead_repository.upsert(lead)
                    total_upserted += 1
                    if (
                        crm_activity_source is not None
                        and crm_conversation_event_repository is not None
                    ):
                        await _sync_recent_crm_activity_for_lead(
                            workspace_id=workspace_id,
                            lead_id=upserted_lead.lead_id,
                            crm_provider=upserted_lead.crm_provider,
                            crm_lead_id=upserted_lead.crm_lead_id,
                            crm_activity_source=crm_activity_source,
                            crm_conversation_event_repository=crm_conversation_event_repository,
                            activity_limit=activity_limit,
                            now=now,
                        )
                    if _can_process_crm_tag_enrollment(
                        campaign_execution_repository=campaign_execution_repository,
                        workspace_contact_policy_repository=workspace_contact_policy_repository,
                        campaign_enrollment_repository=campaign_enrollment_repository,
                        lead_workflow_repository=lead_workflow_repository,
                        workflow_transition_repository=workflow_transition_repository,
                        temporal_workflow_starter=temporal_workflow_starter,
                    ):
                        assert campaign_execution_repository is not None
                        assert workspace_contact_policy_repository is not None
                        assert campaign_enrollment_repository is not None
                        assert lead_workflow_repository is not None
                        assert workflow_transition_repository is not None
                        assert temporal_workflow_starter is not None
                        await process_crm_tag_campaign_enrollment(
                            workspace_id=workspace_id,
                            lead=upserted_lead,
                            observed_at=_crm_tag_enrollment_observed_at(upserted_lead),
                            now=now,
                            campaign_execution_repository=campaign_execution_repository,
                            workspace_contact_policy_repository=workspace_contact_policy_repository,
                            campaign_enrollment_repository=campaign_enrollment_repository,
                            lead_workflow_repository=lead_workflow_repository,
                            workflow_transition_repository=workflow_transition_repository,
                            temporal_workflow_starter=temporal_workflow_starter,
                            event_bus=event_bus,
                            workspace_operational_control_repository=(
                                workspace_operational_control_repository
                            ),
                            commit=commit,
                        )
                except Exception as exc:
                    total_failed += 1
                    if first_failure is None:
                        first_failure = str(exc) or exc.__class__.__name__
            job = await crm_sync_job_repository.save(
                replace(
                    job,
                    total_seen=total_seen,
                    total_upserted=total_upserted,
                    total_failed=total_failed,
                    updated_at=now,
                ),
            )
            if remaining_leads is not None:
                remaining_leads -= len(page.leads)
                if remaining_leads <= 0:
                    break
            if page.next_cursor is None:
                break
            next_cursor = page.next_cursor
    except Exception as exc:
        failed_job = await crm_sync_job_repository.save(
            replace(
                job,
                status=CRMSyncJobStatus.FAILED,
                finished_at=now,
                failure_reason=_page_failure_reason(exc),
                updated_at=now,
            ),
        )
        return RunFollowUpBossLeadSyncResult(
            status=RunFollowUpBossLeadSyncStatus.FAILED,
            job=failed_job,
            page_count=page_count,
        )

    final_status = (
        RunFollowUpBossLeadSyncStatus.COMPLETED
        if job.total_failed == 0
        else RunFollowUpBossLeadSyncStatus.FAILED
    )
    final_job = await crm_sync_job_repository.save(
        replace(
            job,
            status=(
                CRMSyncJobStatus.COMPLETED
                if final_status == RunFollowUpBossLeadSyncStatus.COMPLETED
                else CRMSyncJobStatus.FAILED
            ),
            finished_at=now,
            failure_reason=_lead_failure_reason(job.total_failed, first_failure),
            updated_at=now,
        ),
    )
    return RunFollowUpBossLeadSyncResult(
        status=final_status,
        job=final_job,
        page_count=page_count,
    )


async def request_crm_sync(
    *,
    workspace_id: WorkspaceId,
    sync_type: CRMSyncType,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    crm_sync_job_repository: CRMSyncJobRepository,
    event_bus: EventBus,
    now: datetime,
    created_by_user_id: UUID | None = None,
    sync_job_id_factory: Callable[[], UUID] | None = None,
) -> RequestCRMSyncResult:
    max_leads, latest_by = _normalize_recent_limit(
        sync_type=sync_type,
        max_leads=max_leads,
        latest_by=latest_by,
    )
    job = CRMSyncJob(
        sync_job_id=(sync_job_id_factory or uuid4)(),
        workspace_id=workspace_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=sync_type,
        status=CRMSyncJobStatus.PENDING,
        started_at=None,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    inserted = await crm_sync_job_repository.insert_pending_if_no_active(job)
    if inserted is None:
        active = await crm_sync_job_repository.get_active_for_workspace_provider(
            workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if active is None:
            active = job
        return RequestCRMSyncResult(status=RequestCRMSyncStatus.ALREADY_ACTIVE, job=active)

    await event_bus.publish(
        DomainEvent(
            workspace_id=workspace_id,
            aggregate_type=AggregateType.CRM_SYNC,
            aggregate_id=inserted.sync_job_id,
            event_type=DomainEventType.CRM_SYNC_REQUESTED,
            payload={
                "sync_job_id": str(inserted.sync_job_id),
                "crm_provider": inserted.crm_provider,
                "sync_type": inserted.sync_type.value,
                "max_leads": max_leads,
                "latest_by": latest_by.value if latest_by is not None else None,
            },
        ),
    )
    return RequestCRMSyncResult(status=RequestCRMSyncStatus.REQUESTED, job=inserted)


async def execute_queued_follow_up_boss_crm_sync(
    *,
    workspace_id: WorkspaceId,
    sync_job_id: UUID,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    now: datetime,
    page_size: int = 100,
    max_leads: int | None = None,
    latest_by: CRMSyncLeadSort | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    crm_activity_source: CRMActivitySource | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    activity_limit: int = 50,
) -> ExecuteQueuedCRMSyncResult:
    claimed = await crm_sync_job_repository.claim_pending_by_id(
        workspace_id,
        sync_job_id,
        now=now,
    )
    if claimed is None:
        return ExecuteQueuedCRMSyncResult(status=ExecuteQueuedCRMSyncStatus.NOT_CLAIMED, job=None)

    result = await run_follow_up_boss_lead_snapshot_sync(
        workspace_id=workspace_id,
        lead_snapshot_source=lead_snapshot_source,
        lead_repository=lead_repository,
        crm_sync_job_repository=crm_sync_job_repository,
        now=now,
        sync_type=claimed.sync_type,
        page_size=page_size,
        max_leads=max_leads,
        latest_by=latest_by,
        created_by_user_id=claimed.created_by_user_id,
        mapped_custom_field_keys=mapped_custom_field_keys,
        sync_job=claimed,
        crm_activity_source=crm_activity_source,
        crm_conversation_event_repository=crm_conversation_event_repository,
        campaign_execution_repository=campaign_execution_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        activity_limit=activity_limit,
    )
    return ExecuteQueuedCRMSyncResult(
        status=ExecuteQueuedCRMSyncStatus(result.status.value),
        job=result.job,
        page_count=result.page_count,
    )


async def enqueue_due_follow_up_boss_crm_syncs(
    *,
    workspace_crm_sync_config_repository: WorkspaceCRMSyncConfigRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    event_bus: EventBus,
    now: datetime,
    default_interval_seconds: int,
    workspace_limit: int = 100,
) -> EnqueueDueCRMSyncsResult:
    schedule_targets = (
        await workspace_crm_sync_config_repository.list_active_workspace_schedule_targets(
            limit=workspace_limit,
            default_interval_seconds=default_interval_seconds,
        )
    )
    requested_count = 0
    skipped_disabled_count = 0
    skipped_automation_blocked_count = 0
    skipped_active_count = 0
    skipped_not_due_count = 0
    for target in schedule_targets:
        if not target.crm_sync_enabled:
            skipped_disabled_count += 1
            continue

        if target.automation_status != WorkspaceAutomationStatus.ACTIVE:
            skipped_automation_blocked_count += 1
            continue

        active = await crm_sync_job_repository.get_active_for_workspace_provider(
            target.workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if active is not None:
            skipped_active_count += 1
            continue

        latest = await crm_sync_job_repository.get_latest_for_workspace_provider(
            target.workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if latest is not None and _latest_attempt_at(latest) > now - timedelta(
            seconds=target.crm_sync_interval_seconds,
        ):
            skipped_not_due_count += 1
            continue

        latest_completed = (
            await crm_sync_job_repository.get_latest_completed_for_workspace_provider(
                target.workspace_id,
                CRMProvider.FOLLOW_UP_BOSS.value,
            )
        )
        sync_type = CRMSyncType.INCREMENTAL if latest_completed else CRMSyncType.FULL
        request = await request_crm_sync(
            workspace_id=target.workspace_id,
            sync_type=sync_type,
            crm_sync_job_repository=crm_sync_job_repository,
            event_bus=event_bus,
            now=now,
        )
        if request.status == RequestCRMSyncStatus.REQUESTED:
            requested_count += 1

    return EnqueueDueCRMSyncsResult(
        scanned_count=len(schedule_targets),
        requested_count=requested_count,
        skipped_disabled_count=skipped_disabled_count,
        skipped_automation_blocked_count=skipped_automation_blocked_count,
        skipped_active_count=skipped_active_count,
        skipped_not_due_count=skipped_not_due_count,
    )


async def _resolve_cursor_started_at(
    *,
    workspace_id: WorkspaceId,
    crm_sync_job_repository: CRMSyncJobRepository,
    sync_type: CRMSyncType,
    updated_after: datetime | None,
) -> datetime | None:
    if updated_after is not None or sync_type == CRMSyncType.FULL:
        return updated_after
    recent_jobs = await crm_sync_job_repository.list_recent(workspace_id, limit=25)
    for job in recent_jobs:
        if job.crm_provider != CRMProvider.FOLLOW_UP_BOSS.value:
            continue
        if job.status != CRMSyncJobStatus.COMPLETED:
            continue
        return job.cursor_finished_at or job.finished_at
    return None


def _page_failure_reason(exc: Exception) -> str:
    detail = str(exc) or exc.__class__.__name__
    return f"sync page fetch failed: {detail}"


async def _sync_recent_crm_activity_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_provider: CRMProvider,
    crm_lead_id: str,
    crm_activity_source: CRMActivitySource,
    crm_conversation_event_repository: CrmConversationEventRepository,
    activity_limit: int,
    now: datetime,
) -> None:
    activities = await crm_activity_source.get_recent_activity(
        workspace_id=workspace_id,
        crm_lead_id=crm_lead_id,
        limit=activity_limit,
    )
    for activity in activities:
        event = _map_crm_activity_to_event(
            workspace_id=workspace_id,
            lead_id=lead_id,
            crm_provider=crm_provider,
            activity=activity,
            now=now,
        )
        await crm_conversation_event_repository.save(event)


def _map_crm_activity_to_event(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    crm_provider: CRMProvider,
    activity: CRMActivity,
    now: datetime,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        crm_provider=crm_provider.value,
        crm_activity_id=activity.crm_activity_id,
        activity_type=activity.activity_type,
        occurred_at=activity.timestamp,
        content=activity.content,
        actor_agent_id=activity.agent_id,
        actor_name=activity.actor_name,
        direction=_crm_activity_direction(activity.direction),
        source_payload_version="follow_up_boss/v1",
        created_at=now,
        updated_at=now,
    )


def _crm_activity_direction(value: str | None) -> CrmConversationEventDirection | None:
    if value is None:
        return None
    try:
        return CrmConversationEventDirection(value)
    except ValueError:
        return None


def _can_process_crm_tag_enrollment(
    *,
    campaign_execution_repository: CampaignExecutionRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    temporal_workflow_starter: TemporalWorkflowStarter | None,
) -> bool:
    return all(
        dependency is not None
        for dependency in (
            campaign_execution_repository,
            workspace_contact_policy_repository,
            campaign_enrollment_repository,
            lead_workflow_repository,
            workflow_transition_repository,
            temporal_workflow_starter,
        )
    )


def _crm_tag_enrollment_observed_at(lead: CanonicalLeadRecord) -> datetime:
    return lead.source_updated_at or lead.crm_updated_at or lead.facts_derived_at


def _normalize_recent_limit(
    *,
    sync_type: CRMSyncType,
    max_leads: int | None,
    latest_by: CRMSyncLeadSort | None,
) -> tuple[int | None, CRMSyncLeadSort | None]:
    if latest_by is not None and max_leads is None:
        raise ValueError("latest_by requires max_leads")
    if max_leads is None:
        return None, None
    if max_leads < 1:
        raise ValueError("max_leads must be greater than 0")
    if sync_type != CRMSyncType.FULL:
        raise ValueError("max_leads is only supported for full syncs")
    return max_leads, latest_by or CRMSyncLeadSort.UPDATED


def _lead_failure_reason(total_failed: int, first_failure: str | None) -> str | None:
    if total_failed == 0:
        return None
    if first_failure:
        return f"{total_failed} lead(s) failed during sync; first failure: {first_failure}"
    return f"{total_failed} lead(s) failed during sync"


def _running_sync_job(
    *,
    workspace_id: WorkspaceId,
    sync_type: CRMSyncType,
    now: datetime,
    cursor_started_at: datetime | None,
    cursor_finished_at: datetime | None,
    created_by_user_id: UUID | None,
    sync_job_id_factory: Callable[[], UUID] | None,
    sync_job: CRMSyncJob | None,
) -> CRMSyncJob:
    if sync_job is None:
        return CRMSyncJob(
            sync_job_id=(sync_job_id_factory or uuid4)(),
            workspace_id=workspace_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
            sync_type=sync_type,
            status=CRMSyncJobStatus.RUNNING,
            started_at=now,
            finished_at=None,
            cursor_started_at=cursor_started_at,
            cursor_finished_at=cursor_finished_at,
            total_seen=0,
            total_upserted=0,
            total_failed=0,
            failure_reason=None,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )
    return replace(
        sync_job,
        status=CRMSyncJobStatus.RUNNING,
        started_at=sync_job.started_at or now,
        finished_at=None,
        cursor_started_at=cursor_started_at,
        cursor_finished_at=cursor_finished_at,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        updated_at=now,
    )


def _latest_attempt_at(job: CRMSyncJob) -> datetime:
    return job.finished_at or job.started_at or job.updated_at
