from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.ports.listing_search import ListingSearchQuery
from app.application.use_cases.listing_source_crawls import (
    ExecuteQueuedListingSourceCrawlStatus,
    RequestListingSourceCrawlStatus,
    enqueue_due_listing_source_crawls,
    execute_queued_listing_source_crawl,
    request_listing_source_crawl,
)
from app.domain.events import DomainEvent, DomainEventType
from app.domain.listing_sources import (
    CanonicalListingSnapshot,
    ListingCrawlRun,
    ListingCrawlStatus,
    ListingSearchScope,
    ListingSearchScopeType,
    ListingSnapshotStatus,
    ListingSource,
    ListingSourceType,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
SOURCE_ID = UUID("22222222-2222-2222-2222-222222222222")
SCOPE_ID = UUID("33333333-3333-3333-3333-333333333333")
CRAWL_RUN_ID = UUID("44444444-4444-4444-4444-444444444444")
SNAPSHOT_ID = UUID("55555555-5555-5555-5555-555555555555")


class FakeListingSourceRepository:
    def __init__(self, sources: tuple[ListingSource, ...]) -> None:
        self.sources = {source.source_id: source for source in sources}

    async def get_by_id(self, workspace_id: UUID, source_id: UUID) -> ListingSource | None:
        source = self.sources.get(source_id)
        if source is None or source.workspace_id != workspace_id:
            return None
        return source

    async def get_by_name(self, workspace_id: UUID, name: str) -> ListingSource | None:
        for source in self.sources.values():
            if source.workspace_id == workspace_id and source.name == name:
                return source
        return None

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[ListingSource, ...]:
        return tuple(
            source for source in self.sources.values() if source.workspace_id == workspace_id
        )

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        enabled = [source for source in self.sources.values() if source.enabled]
        return tuple(enabled[:limit])

    async def save(self, source: ListingSource) -> ListingSource:
        self.sources[source.source_id] = source
        return source


class FakeListingSearchScopeRepository:
    def __init__(self, scopes: tuple[ListingSearchScope, ...]) -> None:
        self.scopes = {scope.scope_id: scope for scope in scopes}

    async def get_by_id(self, workspace_id: UUID, scope_id: UUID) -> ListingSearchScope | None:
        scope = self.scopes.get(scope_id)
        if scope is None or scope.workspace_id != workspace_id:
            return None
        return scope

    async def list_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> tuple[ListingSearchScope, ...]:
        return tuple(
            scope
            for scope in self.scopes.values()
            if scope.workspace_id == workspace_id and scope.source_id == source_id
        )

    async def save(self, scope: ListingSearchScope) -> ListingSearchScope:
        self.scopes[scope.scope_id] = scope
        return scope


class FakeListingCrawlRunRepository:
    def __init__(self, runs: tuple[ListingCrawlRun, ...] = ()) -> None:
        self.runs = {run.crawl_run_id: run for run in runs}

    async def get_by_id(self, workspace_id: UUID, crawl_run_id: UUID) -> ListingCrawlRun | None:
        run = self.runs.get(crawl_run_id)
        if run is None or run.workspace_id != workspace_id:
            return None
        return run

    async def list_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[ListingCrawlRun, ...]:
        matches = [
            run
            for run in self.runs.values()
            if run.workspace_id == workspace_id and run.source_id == source_id
        ]
        matches.sort(key=lambda run: run.started_at, reverse=True)
        return tuple(matches[:limit])

    async def get_latest_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> ListingCrawlRun | None:
        runs = await self.list_for_source(workspace_id, source_id, limit=1)
        return runs[0] if runs else None

    async def get_active_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> ListingCrawlRun | None:
        for run in self.runs.values():
            if (
                run.workspace_id == workspace_id
                and run.source_id == source_id
                and run.status in {ListingCrawlStatus.PENDING, ListingCrawlStatus.RUNNING}
            ):
                return run
        return None

    async def insert_pending_if_no_active(
        self,
        crawl_run: ListingCrawlRun,
    ) -> ListingCrawlRun | None:
        active = await self.get_active_for_source(crawl_run.workspace_id, crawl_run.source_id)
        if active is not None:
            return None
        self.runs[crawl_run.crawl_run_id] = crawl_run
        return crawl_run

    async def claim_pending_by_id(
        self,
        workspace_id: UUID,
        crawl_run_id: UUID,
        *,
        now: datetime,
    ) -> ListingCrawlRun | None:
        run = await self.get_by_id(workspace_id, crawl_run_id)
        if run is None or run.status != ListingCrawlStatus.PENDING:
            return None
        claimed = replace(run, status=ListingCrawlStatus.RUNNING, started_at=now, updated_at=now)
        self.runs[crawl_run_id] = claimed
        return claimed

    async def save(self, crawl_run: ListingCrawlRun) -> ListingCrawlRun:
        self.runs[crawl_run.crawl_run_id] = crawl_run
        return crawl_run


class FakeListingSnapshotRepository:
    def __init__(self) -> None:
        self.snapshots: dict[UUID, CanonicalListingSnapshot] = {}

    async def get_by_id(
        self,
        workspace_id: UUID,
        snapshot_id: UUID,
    ) -> CanonicalListingSnapshot | None:
        snapshot = self.snapshots.get(snapshot_id)
        if snapshot is None or snapshot.workspace_id != workspace_id:
            return None
        return snapshot

    async def get_current_by_external_id(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
    ) -> CanonicalListingSnapshot | None:
        for snapshot in self.snapshots.values():
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.external_listing_id == external_listing_id
                and snapshot.is_current
            ):
                return snapshot
        return None

    async def list_current_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        matches = [
            snapshot
            for snapshot in self.snapshots.values()
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.is_current
            )
        ]
        matches.sort(key=lambda snapshot: snapshot.scraped_at, reverse=True)
        return tuple(matches[:limit])

    async def save(self, snapshot: CanonicalListingSnapshot) -> CanonicalListingSnapshot:
        current = await self.get_current_by_external_id(
            snapshot.workspace_id,
            snapshot.source_id,
            snapshot.external_listing_id,
        )
        if current is not None and current.source_payload_hash == snapshot.source_payload_hash:
            updated = replace(
                current,
                valid_until=snapshot.valid_until,
                updated_at=snapshot.updated_at,
            )
            self.snapshots[current.snapshot_id] = updated
            return updated
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    async def mark_other_versions_not_current(
        self,
        workspace_id: UUID,
        source_id: UUID,
        external_listing_id: str,
        except_snapshot_id: UUID,
    ) -> None:
        for snapshot_id, snapshot in tuple(self.snapshots.items()):
            if (
                snapshot.workspace_id == workspace_id
                and snapshot.source_id == source_id
                and snapshot.external_listing_id == external_listing_id
                and snapshot.snapshot_id != except_snapshot_id
            ):
                self.snapshots[snapshot_id] = replace(snapshot, is_current=False)


class FakeListingSearchClient:
    def __init__(
        self,
        results_by_location: dict[str, tuple[CanonicalListingSnapshot, ...] | Exception],
    ) -> None:
        self.results_by_location = results_by_location
        self.calls: list[ListingSearchQuery] = []

    async def search(
        self,
        *,
        source: ListingSource,
        query: ListingSearchQuery,
    ) -> tuple[CanonicalListingSnapshot, ...]:
        _ = source
        self.calls.append(query)
        key = query.locations[0] if query.locations else query.addresses[0]
        result = self.results_by_location.get(key, ())
        if isinstance(result, Exception):
            raise result
        return result


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_request_listing_source_crawl_creates_pending_run_and_event() -> None:
    source_repository = FakeListingSourceRepository((_source(),))
    scope_repository = FakeListingSearchScopeRepository((_scope(),))
    crawl_run_repository = FakeListingCrawlRunRepository()
    event_bus = FakeEventBus()

    result = await request_listing_source_crawl(
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        source_repository=source_repository,
        scope_repository=scope_repository,
        crawl_run_repository=crawl_run_repository,
        event_bus=event_bus,
        now=NOW,
    )

    assert result.status == RequestListingSourceCrawlStatus.REQUESTED
    assert result.crawl_run is not None
    assert result.crawl_run.status == ListingCrawlStatus.PENDING
    assert event_bus.events[0].event_type == DomainEventType.LISTING_SOURCE_CRAWL_REQUESTED


@pytest.mark.asyncio
async def test_scheduler_requests_only_due_supported_sources_with_scopes() -> None:
    due_source = _source()
    active_source = _source(source_id=uuid4(), name="StreetEasy Active")
    not_ready_source = replace(_source(source_id=uuid4(), name="Not Ready"), data_use_policy=None)
    unsupported_source = replace(
        _source(source_id=uuid4(), name="Other Source"),
        base_url="https://example.com",
    )
    no_scope_source = _source(source_id=uuid4(), name="No Scope")
    recent_run = _crawl_run(
        crawl_run_id=uuid4(),
        source_id=no_scope_source.source_id,
        status=ListingCrawlStatus.COMPLETED,
        started_at=NOW - timedelta(minutes=10),
        finished_at=NOW - timedelta(minutes=10),
    )
    active_run = _crawl_run(
        crawl_run_id=uuid4(),
        source_id=active_source.source_id,
        status=ListingCrawlStatus.RUNNING,
    )

    result = await enqueue_due_listing_source_crawls(
        source_repository=FakeListingSourceRepository(
            (due_source, active_source, not_ready_source, unsupported_source, no_scope_source)
        ),
        scope_repository=FakeListingSearchScopeRepository(
            (
                _scope(source_id=due_source.source_id),
                _scope(scope_id=uuid4(), source_id=active_source.source_id),
                _scope(scope_id=uuid4(), source_id=unsupported_source.source_id),
            )
        ),
        crawl_run_repository=FakeListingCrawlRunRepository((active_run, recent_run)),
        event_bus=FakeEventBus(),
        now=NOW,
        source_limit=10,
    )

    assert result.scanned_count == 5
    assert result.requested_count == 1
    assert result.skipped_active_count == 1
    assert result.skipped_not_ready_count == 1
    assert result.skipped_unsupported_count == 1
    assert result.skipped_no_scopes_count == 1


@pytest.mark.asyncio
async def test_execute_listing_source_crawl_persists_snapshots_and_marks_completed() -> None:
    crawl_run_repository = FakeListingCrawlRunRepository(
        (_crawl_run(status=ListingCrawlStatus.PENDING),)
    )
    snapshot_repository = FakeListingSnapshotRepository()
    event_bus = FakeEventBus()

    result = await execute_queued_listing_source_crawl(
        workspace_id=WORKSPACE_ID,
        crawl_run_id=CRAWL_RUN_ID,
        source_repository=FakeListingSourceRepository((_source(),)),
        scope_repository=FakeListingSearchScopeRepository((_scope(),)),
        crawl_run_repository=crawl_run_repository,
        snapshot_repository=snapshot_repository,
        listing_search_client=FakeListingSearchClient({"Bronx": (_snapshot(),)}),
        now=NOW,
        cache_ttl=timedelta(hours=6),
        event_bus=event_bus,
    )

    assert result.status == ExecuteQueuedListingSourceCrawlStatus.COMPLETED
    assert result.crawl_run is not None
    assert result.crawl_run.inserted_count == 1
    assert result.crawl_run.unchanged_count == 0
    assert result.crawl_run.failed_count == 0
    assert len(snapshot_repository.snapshots) == 1
    assert event_bus.events[-1].event_type == DomainEventType.LISTING_SNAPSHOT_CREATED


@pytest.mark.asyncio
async def test_execute_listing_source_crawl_marks_completed_with_errors_for_partial_failures(
) -> None:
    crawl_run_repository = FakeListingCrawlRunRepository(
        (_crawl_run(status=ListingCrawlStatus.PENDING),)
    )

    result = await execute_queued_listing_source_crawl(
        workspace_id=WORKSPACE_ID,
        crawl_run_id=CRAWL_RUN_ID,
        source_repository=FakeListingSourceRepository((_source(),)),
        scope_repository=FakeListingSearchScopeRepository(
            (
                _scope(),
                _scope(scope_id=uuid4(), locations=("Queens",)),
            )
        ),
        crawl_run_repository=crawl_run_repository,
        snapshot_repository=FakeListingSnapshotRepository(),
        listing_search_client=FakeListingSearchClient(
            {
                "Bronx": (_snapshot(),),
                "Queens": RuntimeError("blocked"),
            }
        ),
        now=NOW,
        cache_ttl=timedelta(hours=6),
    )

    assert result.status == ExecuteQueuedListingSourceCrawlStatus.COMPLETED_WITH_ERRORS
    assert result.crawl_run is not None
    assert result.crawl_run.inserted_count == 1
    assert result.crawl_run.failed_count == 1
    assert result.crawl_run.error_summary is not None


def _source(*, source_id: UUID = SOURCE_ID, name: str = "StreetEasy NYC") -> ListingSource:
    return ListingSource(
        source_id=source_id,
        workspace_id=WORKSPACE_ID,
        name=name,
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        crawl_frequency_minutes=1440,
        enabled=True,
        requires_auth=False,
        terms_reviewed_at=NOW,
        data_use_policy="Approved for listing enrichment.",
        created_at=NOW,
        updated_at=NOW,
    )


def _scope(
    *,
    scope_id: UUID = SCOPE_ID,
    source_id: UUID = SOURCE_ID,
    locations: tuple[str, ...] = ("Bronx",),
) -> ListingSearchScope:
    return ListingSearchScope(
        scope_id=scope_id,
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        search_type=ListingSearchScopeType.SALE,
        locations=locations,
        min_price=Decimal("500000"),
        min_beds=Decimal("2"),
        limit=5,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _crawl_run(
    *,
    crawl_run_id: UUID = CRAWL_RUN_ID,
    source_id: UUID = SOURCE_ID,
    status: ListingCrawlStatus,
    started_at: datetime = NOW,
    finished_at: datetime | None = None,
) -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=crawl_run_id,
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot() -> CanonicalListingSnapshot:
    return CanonicalListingSnapshot(
        snapshot_id=SNAPSHOT_ID,
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        external_listing_id="listing-123",
        source_url="https://streeteasy.com/building/listing-123",
        source_payload_hash="hash-1",
        scraped_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        title="Bronx Condo",
        address_text="2738 Miles Avenue, Bronx, NY, 10465",
        city="New York",
        state="NY",
        neighborhood="Bronx",
        price=Decimal("750000"),
        beds=Decimal("2"),
        baths=Decimal("2"),
        property_type="condo",
        status=ListingSnapshotStatus.ACTIVE,
        source_payload={"id": "listing-123"},
    )