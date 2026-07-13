from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import LeadRepository
from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CRMProvider


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
    skipped_active_count: int
    skipped_not_due_count: int


class ActiveWorkspaceIdRepository(Protocol):
    async def list_active_ids(self, *, limit: int = 100) -> tuple[WorkspaceId, ...]:
        raise NotImplementedError


class LeadSnapshotSyncJobRepository(Protocol):
    async def list_recent(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> tuple[CRMSyncJob, ...]:
        raise NotImplementedError

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        raise NotImplementedError


class CRMSyncRequestJobRepository(Protocol):
    async def get_active_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def insert_pending_if_no_active(self, job: CRMSyncJob) -> CRMSyncJob | None:
        raise NotImplementedError


class QueuedCRMSyncJobRepository(LeadSnapshotSyncJobRepository, Protocol):
    async def claim_pending_by_id(
        self,
        workspace_id: WorkspaceId,
        sync_job_id: UUID,
        *,
        now: datetime,
    ) -> CRMSyncJob | None:
        raise NotImplementedError


class DueCRMSyncJobRepository(CRMSyncRequestJobRepository, Protocol):
    async def get_latest_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError

    async def get_latest_completed_for_workspace_provider(
        self,
        workspace_id: WorkspaceId,
        crm_provider: str,
    ) -> CRMSyncJob | None:
        raise NotImplementedError


async def run_follow_up_boss_lead_snapshot_sync(
    *,
    workspace_id: WorkspaceId,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: LeadSnapshotSyncJobRepository,
    now: datetime,
    sync_type: CRMSyncType = CRMSyncType.INCREMENTAL,
    page_size: int = 100,
    created_by_user_id: UUID | None = None,
    updated_after: datetime | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    sync_job_id_factory: Callable[[], UUID] | None = None,
    sync_job: CRMSyncJob | None = None,
) -> RunFollowUpBossLeadSyncResult:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")

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
    page_count = 0
    first_failure: str | None = None
    try:
        while True:
            page = await lead_snapshot_source.list_lead_snapshots(
                workspace_id=workspace_id,
                page_size=page_size,
                cursor=next_cursor,
                updated_after=cursor_started_at,
                updated_before=cursor_finished_at,
                mapped_custom_field_keys=mapped_custom_field_keys,
            )
            page_count += 1
            total_seen = job.total_seen + len(page.leads)
            total_upserted = job.total_upserted
            total_failed = job.total_failed
            for lead in page.leads:
                try:
                    await lead_repository.upsert(lead)
                    total_upserted += 1
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
    crm_sync_job_repository: CRMSyncRequestJobRepository,
    event_bus: EventBus,
    now: datetime,
    created_by_user_id: UUID | None = None,
    sync_job_id_factory: Callable[[], UUID] | None = None,
) -> RequestCRMSyncResult:
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
    crm_sync_job_repository: QueuedCRMSyncJobRepository,
    now: datetime,
    page_size: int = 100,
    mapped_custom_field_keys: tuple[str, ...] = (),
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
        created_by_user_id=claimed.created_by_user_id,
        mapped_custom_field_keys=mapped_custom_field_keys,
        sync_job=claimed,
    )
    return ExecuteQueuedCRMSyncResult(
        status=ExecuteQueuedCRMSyncStatus(result.status.value),
        job=result.job,
        page_count=result.page_count,
    )


async def enqueue_due_follow_up_boss_crm_syncs(
    *,
    workspace_repository: ActiveWorkspaceIdRepository,
    crm_sync_job_repository: DueCRMSyncJobRepository,
    event_bus: EventBus,
    now: datetime,
    minimum_interval: timedelta,
    workspace_limit: int = 100,
) -> EnqueueDueCRMSyncsResult:
    workspace_ids = await workspace_repository.list_active_ids(limit=workspace_limit)
    requested_count = 0
    skipped_active_count = 0
    skipped_not_due_count = 0
    for workspace_id in workspace_ids:
        active = await crm_sync_job_repository.get_active_for_workspace_provider(
            workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if active is not None:
            skipped_active_count += 1
            continue

        latest = await crm_sync_job_repository.get_latest_for_workspace_provider(
            workspace_id,
            CRMProvider.FOLLOW_UP_BOSS.value,
        )
        if latest is not None and _latest_attempt_at(latest) > now - minimum_interval:
            skipped_not_due_count += 1
            continue

        latest_completed = (
            await crm_sync_job_repository.get_latest_completed_for_workspace_provider(
                workspace_id,
                CRMProvider.FOLLOW_UP_BOSS.value,
            )
        )
        sync_type = CRMSyncType.INCREMENTAL if latest_completed else CRMSyncType.FULL
        request = await request_crm_sync(
            workspace_id=workspace_id,
            sync_type=sync_type,
            crm_sync_job_repository=crm_sync_job_repository,
            event_bus=event_bus,
            now=now,
        )
        if request.status == RequestCRMSyncStatus.REQUESTED:
            requested_count += 1

    return EnqueueDueCRMSyncsResult(
        scanned_count=len(workspace_ids),
        requested_count=requested_count,
        skipped_active_count=skipped_active_count,
        skipped_not_due_count=skipped_not_due_count,
    )


async def _resolve_cursor_started_at(
    *,
    workspace_id: WorkspaceId,
    crm_sync_job_repository: LeadSnapshotSyncJobRepository,
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
