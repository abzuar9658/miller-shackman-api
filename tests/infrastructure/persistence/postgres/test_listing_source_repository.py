from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
    PostgresListingSearchScopeRepository,
    PostgresListingSnapshotRepository,
    PostgresListingSourceRepository,
)
from app.infrastructure.persistence.postgres.models import UserModel, WorkspaceModel

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111101")
USER_ID = UUID("11111111-1111-1111-1111-111111111102")


@pytest.mark.asyncio
async def test_listing_source_repository_saves_and_lists_sources(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    repository = PostgresListingSourceRepository(postgres_session)

    saved = await repository.save(_source(name="StreetEasy"))
    fetched = await repository.get_by_id(WORKSPACE_ID, saved.source_id)
    listed = await repository.list_for_workspace(WORKSPACE_ID)

    assert fetched == saved
    assert len(listed) == 1
    assert listed[0].name == "StreetEasy"


@pytest.mark.asyncio
async def test_listing_snapshot_repository_deduplicates_by_identity_and_payload(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    source_repository = PostgresListingSourceRepository(postgres_session)
    source = await source_repository.save(_source(name="StreetEasy"))
    snapshot_repository = PostgresListingSnapshotRepository(postgres_session)

    first = await snapshot_repository.save(
        _snapshot(source_id=source.source_id, payload_hash="hash-1")
    )
    duplicate = await snapshot_repository.save(
        _snapshot(source_id=source.source_id, payload_hash="hash-1")
    )

    current = await snapshot_repository.get_current_by_external_id(
        WORKSPACE_ID,
        source.source_id,
        "listing-123",
    )

    assert duplicate.snapshot_id == first.snapshot_id
    assert current is not None
    assert current.snapshot_id == first.snapshot_id


@pytest.mark.asyncio
async def test_listing_snapshot_repository_marks_previous_versions_not_current(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    source_repository = PostgresListingSourceRepository(postgres_session)
    source = await source_repository.save(_source(name="StreetEasy"))
    snapshot_repository = PostgresListingSnapshotRepository(postgres_session)

    first = await snapshot_repository.save(
        _snapshot(source_id=source.source_id, payload_hash="hash-1")
    )
    second = await snapshot_repository.save(
        _snapshot(source_id=source.source_id, payload_hash="hash-2")
    )
    await snapshot_repository.mark_other_versions_not_current(
        WORKSPACE_ID,
        source.source_id,
        "listing-123",
        second.snapshot_id,
    )

    current_list = await snapshot_repository.list_current_for_source(WORKSPACE_ID, source.source_id)
    first_reloaded = await snapshot_repository.get_by_id(WORKSPACE_ID, first.snapshot_id)

    assert len(current_list) == 1
    assert current_list[0].snapshot_id == second.snapshot_id
    assert first_reloaded is not None
    assert first_reloaded.is_current is False


@pytest.mark.asyncio
async def test_listing_search_scope_repository_saves_and_lists_scopes(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    source_repository = PostgresListingSourceRepository(postgres_session)
    source = await source_repository.save(_source(name="StreetEasy"))
    repository = PostgresListingSearchScopeRepository(postgres_session)

    saved = await repository.save(_scope(source_id=source.source_id))
    fetched = await repository.get_by_id(WORKSPACE_ID, saved.scope_id)
    listed = await repository.list_for_source(WORKSPACE_ID, source.source_id)

    assert fetched == saved
    assert listed == (saved,)


@pytest.mark.asyncio
async def test_listing_crawl_run_repository_claims_pending_and_enforces_single_active_run(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    source_repository = PostgresListingSourceRepository(postgres_session)
    source = await source_repository.save(_source(name="StreetEasy"))
    repository = PostgresListingCrawlRunRepository(postgres_session)

    pending = await repository.insert_pending_if_no_active(_crawl_run(source_id=source.source_id))
    duplicate = await repository.insert_pending_if_no_active(
        _crawl_run(source_id=source.source_id, crawl_run_id=uuid4())
    )
    claimed = await repository.claim_pending_by_id(
        WORKSPACE_ID,
        pending.crawl_run_id if pending is not None else uuid4(),
        now=NOW,
    )

    assert pending is not None
    assert duplicate is None
    assert claimed is not None
    assert claimed.status == ListingCrawlStatus.RUNNING
    assert await repository.get_active_for_source(WORKSPACE_ID, source.source_id) == claimed


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
    session.add(
        UserModel(
            user_id=USER_ID,
            email="admin@example.com",
            email_normalized="admin@example.com",
            full_name="Admin User",
            status="active",
            email_verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()


def _source(*, name: str) -> ListingSource:
    return ListingSource(
        source_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        name=name,
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        allowed_url_patterns=("/for-sale/",),
        disallowed_url_patterns=(),
        crawl_frequency_minutes=1440,
        enabled=False,
        requires_auth=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(*, source_id: UUID, payload_hash: str) -> CanonicalListingSnapshot:
    return CanonicalListingSnapshot(
        snapshot_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        external_listing_id="listing-123",
        source_url="https://streeteasy.com/building/listing-123",
        source_payload_hash=payload_hash,
        scraped_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        title="Upper East Side Condo",
        city="New York",
        neighborhood="Upper East Side",
        price=Decimal("1250000.00"),
        beds=Decimal("2.00"),
        baths=Decimal("2.00"),
        property_type="condo",
        status=ListingSnapshotStatus.ACTIVE,
        source_payload={"id": "listing-123", "hash": payload_hash},
    )


def _scope(*, source_id: UUID) -> ListingSearchScope:
    return ListingSearchScope(
        scope_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        search_type=ListingSearchScopeType.SALE,
        locations=("Bronx",),
        min_price=Decimal("500000.00"),
        min_beds=Decimal("2.00"),
        limit=10,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _crawl_run(*, source_id: UUID, crawl_run_id: UUID | None = None) -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=crawl_run_id or uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        status=ListingCrawlStatus.PENDING,
        started_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )