from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import CRMSyncJob, CRMSyncJobStatus, CRMSyncType
from app.domain.leads import CRMProvider
from app.domain.listing_sources import ListingCrawlRun, ListingCrawlStatus
from app.infrastructure.persistence.postgres.crm_sync_repository import PostgresCRMSyncJobRepository
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
)
from app.infrastructure.persistence.postgres.models import WorkspaceModel

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("22222222-2222-2222-2222-222222222222")
SOURCE_ID = UUID("22222222-2222-2222-2222-222222222223")


class _FakeResult:
    def scalar_one_or_none(self) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult()


def test_crm_sync_insert_pending_uses_literal_partial_index_predicate() -> None:
    session = _FakeSession()

    _run(
        PostgresCRMSyncJobRepository(cast(AsyncSession, session)).insert_pending_if_no_active(
            _pending_sync_job(),
        )
    )

    statement = cast(Any, session.statements[0])
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = str(statement.compile(dialect=dialect))
    assert "ON CONFLICT (workspace_id, crm_provider)" in compiled
    assert "WHERE status IN ('pending', 'running')" in compiled
    assert "POSTCOMPILE" not in compiled


def test_listing_crawl_insert_pending_uses_literal_partial_index_predicate() -> None:
    session = _FakeSession()

    _run(
        PostgresListingCrawlRunRepository(cast(AsyncSession, session)).insert_pending_if_no_active(
            _pending_crawl_run(),
        )
    )

    statement = cast(Any, session.statements[0])
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    compiled = str(statement.compile(dialect=dialect))
    assert "ON CONFLICT (workspace_id, source_id)" in compiled
    assert "WHERE status IN ('pending', 'running')" in compiled
    assert "POSTCOMPILE" not in compiled


@pytest.mark.asyncio
async def test_crm_sync_insert_pending_enforces_single_active_job(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    repository = PostgresCRMSyncJobRepository(postgres_session)

    first = await repository.insert_pending_if_no_active(_pending_sync_job())
    duplicate = await repository.insert_pending_if_no_active(_pending_sync_job(sync_job_id=uuid4()))
    active = await repository.get_active_for_workspace_provider(
        WORKSPACE_ID,
        CRMProvider.FOLLOW_UP_BOSS.value,
    )

    assert first is not None
    assert duplicate is None
    assert active == first


async def _seed_workspace(session: AsyncSession) -> None:
    session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="America/Chicago",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


def _pending_sync_job(*, sync_job_id: UUID | None = None) -> CRMSyncJob:
    return CRMSyncJob(
        sync_job_id=sync_job_id or uuid4(),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        sync_type=CRMSyncType.INCREMENTAL,
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


def _pending_crawl_run() -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        status=ListingCrawlStatus.PENDING,
        started_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)