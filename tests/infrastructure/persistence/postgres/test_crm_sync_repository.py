from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import (
    CRMSyncJob,
    CRMSyncJobStatus,
    CRMSyncLeadSort,
    CRMSyncType,
    CRMSyncWindowState,
    ExternalEvent,
    ExternalEventStatus,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresCRMSyncJobRepository,
    PostgresCRMSyncWindowStateRepository,
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.models import (
    CRMSyncJobModel,
    CRMSyncWindowStateModel,
    ExternalEventModel,
)

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("00000000-0000-0000-0000-000000000001")
SYNC_JOB_ID = UUID("00000000-0000-0000-0000-000000000002")
EXTERNAL_EVENT_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")
CREATOR_USER_ID = UUID("00000000-0000-0000-0000-000000000005")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_values: list[object] | None = None,
        rowcount: int | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def _sync_job_model() -> CRMSyncJobModel:
    return CRMSyncJobModel(
        sync_job_id=SYNC_JOB_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider="follow_up_boss",
        sync_type="full",
        status="running",
        started_at=NOW,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=NOW,
        created_by_user_id=CREATOR_USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _sync_job() -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=SYNC_JOB_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider="follow_up_boss",
        sync_type=CRMSyncType.FULL,
        status=CRMSyncJobStatus.RUNNING,
        started_at=NOW,
        finished_at=None,
        cursor_started_at=None,
        cursor_finished_at=None,
        total_seen=0,
        total_upserted=0,
        total_failed=0,
        failure_reason=None,
        last_heartbeat_at=NOW,
        created_by_user_id=CREATOR_USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _external_event_model() -> ExternalEventModel:
    return ExternalEventModel(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider="follow_up_boss",
        event_type="lead.updated",
        provider_event_id="evt-123",
        crm_lead_id="456",
        lead_id=LEAD_ID,
        received_at=NOW,
        processed_at=None,
        status="pending",
        payload_redacted={"id": "evt-123"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _external_event() -> ExternalEvent:
    return ExternalEvent(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider="follow_up_boss",
        event_type="lead.updated",
        provider_event_id="evt-123",
        crm_lead_id="456",
        lead_id=LEAD_ID,
        received_at=NOW,
        processed_at=None,
        status=ExternalEventStatus.PENDING,
        payload_redacted={"id": "evt-123"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _window_state_model() -> CRMSyncWindowStateModel:
    return CRMSyncWindowStateModel(
        workspace_id=WORKSPACE_ID,
        crm_provider="follow_up_boss",
        sync_type="incremental",
        updated_after=NOW,
        updated_before=NOW.replace(hour=13),
        next_cursor="cursor-2",
        sort_by="updated",
        created_at=NOW,
        updated_at=NOW,
    )


def _window_state() -> CRMSyncWindowState:
    return CRMSyncWindowState(
        workspace_id=WORKSPACE_ID,
        crm_provider="follow_up_boss",
        sync_type=CRMSyncType.INCREMENTAL,
        updated_after=NOW,
        updated_before=NOW.replace(hour=13),
        next_cursor="cursor-2",
        sort_by=CRMSyncLeadSort.UPDATED,
        created_at=NOW,
        updated_at=NOW,
    )


def test_sync_job_repository_get_by_id_maps_domain() -> None:
    model = _sync_job_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    result = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).get_by_id(
            WORKSPACE_ID,
            SYNC_JOB_ID,
        ),
    )

    assert result == _sync_job()
    assert "crm_sync_jobs.workspace_id" in str(session.statements[0])
    assert "crm_sync_jobs.sync_job_id" in str(session.statements[0])


def test_sync_job_repository_list_recent_orders_by_created_at() -> None:
    older = _sync_job_model()
    newer = _sync_job_model()
    newer.sync_job_id = UUID("00000000-0000-0000-0000-00000000000a")
    newer.created_at = NOW.replace(minute=1)
    session = _FakeSession(_FakeResult(scalar_values=[newer, older]))

    jobs = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).list_recent(
            WORKSPACE_ID,
            limit=10,
        ),
    )

    assert len(jobs) == 2
    assert jobs[0].sync_job_id == newer.sync_job_id
    assert jobs[1].sync_job_id == older.sync_job_id
    statement_str = str(session.statements[0])
    assert "crm_sync_jobs.workspace_id" in statement_str
    assert "ORDER BY" in statement_str
    assert "LIMIT" in statement_str


def test_sync_job_repository_get_latest_active_filters_provider_and_active_status() -> None:
    model = _sync_job_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    result = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).get_active_for_workspace_provider(
            WORKSPACE_ID,
            "follow_up_boss",
        ),
    )

    assert result == _sync_job()
    statement_str = str(session.statements[0])
    assert "crm_sync_jobs.workspace_id" in statement_str
    assert "crm_sync_jobs.crm_provider" in statement_str
    assert "crm_sync_jobs.status IN" in statement_str


def test_sync_job_repository_insert_pending_uses_active_partial_conflict_guard() -> None:
    job = _sync_job()
    pending = replace(job, status=CRMSyncJobStatus.PENDING, started_at=None)
    model = _sync_job_model()
    model.status = "pending"
    model.started_at = None
    session = _FakeSession(_FakeResult(scalar_value=model))

    saved = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).insert_pending_if_no_active(
            pending,
        ),
    )

    assert saved is not None
    assert saved.status == CRMSyncJobStatus.PENDING
    statement_str = str(session.statements[0])
    assert "ON CONFLICT (workspace_id, crm_provider)" in statement_str
    assert "DO NOTHING" in statement_str


def test_sync_job_repository_claim_pending_by_id_updates_only_pending_job() -> None:
    model = _sync_job_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    claimed = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).claim_pending_by_id(
            WORKSPACE_ID,
            SYNC_JOB_ID,
            now=NOW,
        ),
    )

    assert claimed == _sync_job()
    statement_str = str(session.statements[0])
    assert "UPDATE crm_sync_jobs" in statement_str
    assert "last_heartbeat_at" in statement_str
    assert "crm_sync_jobs.status" in statement_str
    assert "RETURNING" in statement_str


def test_sync_job_repository_save_returns_domain() -> None:
    job = _sync_job()
    model = _sync_job_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    saved = _run(PostgresCRMSyncJobRepository(cast(AsyncSession, session)).save(job))

    assert saved == job
    statement_str = str(session.statements[0])
    assert "ON CONFLICT (sync_job_id) DO UPDATE" in statement_str


def test_sync_job_repository_fail_stale_active_jobs_marks_pending_and_running() -> None:
    session = _FakeSession(_FakeResult(rowcount=2))

    updated = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).fail_stale_active_jobs(
            now=NOW,
            pending_timeout_seconds=600,
            running_timeout_seconds=28800,
        )
    )

    assert updated == 2
    statement_str = str(session.statements[0])
    assert "UPDATE crm_sync_jobs" in statement_str
    assert "coalesce" in statement_str.lower()
    assert "last_heartbeat_at" in statement_str
    assert "status" in statement_str


def test_sync_job_repository_touch_running_heartbeat_updates_only_running_job() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_sync_job_model()))

    touched = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).touch_running_heartbeat(
            WORKSPACE_ID,
            SYNC_JOB_ID,
            now=NOW,
        )
    )

    assert touched == _sync_job()
    statement_str = str(session.statements[0])
    assert "UPDATE crm_sync_jobs" in statement_str
    assert "last_heartbeat_at" in statement_str


def test_sync_job_repository_save_if_running_requires_running_status() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_sync_job_model()))

    saved = _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).save_if_running(_sync_job())
    )

    assert saved == _sync_job()
    statement_str = str(session.statements[0])
    assert "UPDATE crm_sync_jobs" in statement_str
    assert "crm_sync_jobs.status" in statement_str


def test_window_state_repository_get_by_workspace_provider_maps_domain() -> None:
    model = _window_state_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    state = _run(
        PostgresCRMSyncWindowStateRepository(cast(AsyncSession, session)).get_by_workspace_provider(
            WORKSPACE_ID,
            "follow_up_boss",
        )
    )

    assert state == _window_state()


def test_window_state_repository_save_upserts_state() -> None:
    state = _window_state()
    session = _FakeSession(_FakeResult(scalar_value=_window_state_model()))

    saved = _run(PostgresCRMSyncWindowStateRepository(cast(AsyncSession, session)).save(state))

    assert saved == state
    assert "ON CONFLICT (workspace_id, crm_provider) DO UPDATE" in str(session.statements[0])


def test_window_state_repository_delete_targets_workspace_provider() -> None:
    session = _FakeSession(_FakeResult())

    _run(
        PostgresCRMSyncWindowStateRepository(cast(AsyncSession, session)).delete(
            WORKSPACE_ID,
            "follow_up_boss",
        )
    )

    statement_str = str(session.statements[0])
    assert "DELETE FROM crm_sync_window_states" in statement_str
    assert "crm_sync_window_states.workspace_id" in statement_str


def test_external_event_repository_get_by_provider_event_id_maps_domain() -> None:
    model = _external_event_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    result = _run(
        PostgresExternalEventRepository(cast(AsyncSession, session)).get_by_provider_event_id(
            WORKSPACE_ID,
            "follow_up_boss",
            "evt-123",
        ),
    )

    assert result == _external_event()
    statement_str = str(session.statements[0])
    assert "external_events.workspace_id" in statement_str
    assert "external_events.provider" in statement_str
    assert "external_events.provider_event_id" in statement_str


def test_external_event_repository_save_uses_idempotent_upsert() -> None:
    event = _external_event()
    model = _external_event_model()
    session = _FakeSession(_FakeResult(scalar_value=model))

    saved = _run(PostgresExternalEventRepository(cast(AsyncSession, session)).save(event))

    assert saved == event
    statement_str = str(session.statements[0])
    assert "ON CONFLICT (workspace_id, provider, provider_event_id) DO UPDATE" in statement_str


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
