from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.crm_sync import CanonicalLeadSnapshotPage
from app.application.use_cases.crm_sync import (
    RunFollowUpBossLeadSyncStatus,
    run_follow_up_boss_lead_snapshot_sync,
)
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
PREVIOUS_SYNC_AT = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
SYNC_JOB_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeLeadRepository:
    def __init__(self, failing_crm_lead_ids: set[str] | None = None) -> None:
        self.failing_crm_lead_ids = failing_crm_lead_ids or set()
        self.saved: list[CanonicalLeadRecord] = []

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
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        if record.crm_lead_id in self.failing_crm_lead_ids:
            raise RuntimeError(f"boom::{record.crm_lead_id}")
        self.saved.append(record)
        return record


class FakeCRMSyncJobRepository:
    def __init__(self, recent_jobs: tuple[CRMSyncJob, ...] = ()) -> None:
        self.recent_jobs = recent_jobs
        self.saved: list[CRMSyncJob] = []

    async def get_by_id(self, workspace_id: UUID, sync_job_id: UUID) -> CRMSyncJob | None:
        return next((job for job in self.saved if job.sync_job_id == sync_job_id), None)

    async def list_recent(self, workspace_id: UUID, limit: int = 100) -> tuple[CRMSyncJob, ...]:
        return self.recent_jobs[:limit]

    async def save(self, job: CRMSyncJob) -> CRMSyncJob:
        self.saved.append(job)
        return job


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
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadSnapshotPage:
        self.requests.append(
            {
                "workspace_id": workspace_id,
                "page_size": page_size,
                "cursor": cursor,
                "updated_after": updated_after,
                "updated_before": updated_before,
                "mapped_custom_field_keys": mapped_custom_field_keys,
            },
        )
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)


def _lead(crm_lead_id: str) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=UUID(f"00000000-0000-0000-0000-{int(crm_lead_id):012d}"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=crm_lead_id,
        facts_derived_at=NOW,
        source_payload_version="follow_up_boss_person:v1",
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