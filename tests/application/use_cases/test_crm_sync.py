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
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncLeadSort, CRMSyncType
from app.domain.events import DomainEvent, DomainEventType
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


class FakeWorkspaceRepository:
    def __init__(self, workspace_ids: tuple[UUID, ...]) -> None:
        self.workspace_ids = workspace_ids

    async def get_by_id(self, workspace_id: UUID) -> None:
        return None

    async def list_active_ids(self, *, limit: int = 100) -> tuple[UUID, ...]:
        return self.workspace_ids[:limit]

    async def save(self, workspace: object) -> object:
        return workspace


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


def _lead(crm_lead_id: str) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=UUID(f"00000000-0000-0000-0000-{int(crm_lead_id):012d}"),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=crm_lead_id,
        facts_derived_at=NOW,
        source_payload_version="follow_up_boss_person:v1",
    )


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
        workspace_repository=FakeWorkspaceRepository((WORKSPACE_ID,)),
        crm_sync_job_repository=never_synced_repository,
        event_bus=event_bus,
        now=NOW,
        minimum_interval=timedelta(minutes=5),
    )

    assert first_result.requested_count == 1
    assert never_synced_repository.saved[0].sync_type == CRMSyncType.FULL

    completed = _completed_job(cursor_finished_at=NOW - timedelta(minutes=10))
    due_repository = FakeCRMSyncJobRepository(
        latest_job=completed,
        latest_completed_job=completed,
    )

    second_result = await enqueue_due_follow_up_boss_crm_syncs(
        workspace_repository=FakeWorkspaceRepository((WORKSPACE_ID,)),
        crm_sync_job_repository=due_repository,
        event_bus=event_bus,
        now=NOW,
        minimum_interval=timedelta(minutes=5),
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
        workspace_repository=FakeWorkspaceRepository((WORKSPACE_ID,)),
        crm_sync_job_repository=repository,
        event_bus=FakeEventBus(),
        now=NOW,
        minimum_interval=timedelta(minutes=5),
    )

    assert result.requested_count == 0
    assert result.skipped_active_count == 1


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
