from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.repositories import CRMSyncJobRepository, LeadRepository
from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType
from app.domain.leads import CRMProvider


class RunFollowUpBossLeadSyncStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class RunFollowUpBossLeadSyncResult:
    status: RunFollowUpBossLeadSyncStatus
    job: CRMSyncJob
    page_count: int


async def run_follow_up_boss_lead_snapshot_sync(
    *,
    workspace_id: WorkspaceId,
    lead_snapshot_source: CanonicalLeadSnapshotSource,
    lead_repository: LeadRepository,
    crm_sync_job_repository: CRMSyncJobRepository,
    now: datetime,
    sync_type: CRMSyncType = CRMSyncType.INCREMENTAL,
    page_size: int = 100,
    created_by_user_id: UUID | None = None,
    updated_after: datetime | None = None,
    mapped_custom_field_keys: tuple[str, ...] = (),
    sync_job_id_factory: Callable[[], UUID] | None = None,
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
        CRMSyncJob(
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


def _lead_failure_reason(total_failed: int, first_failure: str | None) -> str | None:
    if total_failed == 0:
        return None
    if first_failure:
        return f"{total_failed} lead(s) failed during sync; first failure: {first_failure}"
    return f"{total_failed} lead(s) failed during sync"