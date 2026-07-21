from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.application.use_cases.listing_sources import (
    ListingSearchScopeReasonCode,
    ListingSearchScopeStatus,
    create_listing_search_scope,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.listing_sources import (
    ListingSearchScope,
    ListingSearchScopeType,
    ListingSource,
    ListingSourceType,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
ACTOR_ID = UUID("22222222-2222-2222-2222-222222222222")
SOURCE_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeListingSourceRepository:
    def __init__(self, source: ListingSource | None) -> None:
        self.source = source

    async def get_by_id(self, workspace_id: UUID, source_id: UUID) -> ListingSource | None:
        if self.source is None:
            return None
        if self.source.workspace_id != workspace_id or self.source.source_id != source_id:
            return None
        return self.source

    async def get_by_name(self, workspace_id: UUID, name: str) -> ListingSource | None:
        _ = workspace_id, name
        return None

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[ListingSource, ...]:
        _ = workspace_id
        return ()

    async def list_enabled(self, *, limit: int = 100) -> tuple[ListingSource, ...]:
        _ = limit
        return ()

    async def save(self, source: ListingSource) -> ListingSource:
        self.source = source
        return source


class FakeListingSearchScopeRepository:
    def __init__(self) -> None:
        self.saved: list[ListingSearchScope] = []

    async def get_by_id(self, workspace_id: UUID, scope_id: UUID) -> ListingSearchScope | None:
        _ = workspace_id, scope_id
        return None

    async def list_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> tuple[ListingSearchScope, ...]:
        _ = workspace_id, source_id
        return ()

    async def save(self, scope: ListingSearchScope) -> ListingSearchScope:
        self.saved.append(scope)
        return scope


@pytest.mark.asyncio
async def test_create_listing_search_scope_requires_search_criteria() -> None:
    result = await create_listing_search_scope(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        search_type=ListingSearchScopeType.SALE,
        locations=(),
        addresses=(),
        keywords=(),
        min_price=None,
        max_price=None,
        min_beds=None,
        limit=10,
        enabled=True,
        source_repository=FakeListingSourceRepository(_source()),
        scope_repository=FakeListingSearchScopeRepository(),
        now=NOW,
    )

    assert result.status == ListingSearchScopeStatus.REJECTED
    assert result.reasons == (ListingSearchScopeReasonCode.SEARCH_CRITERIA_REQUIRED,)


@pytest.mark.asyncio
async def test_create_listing_search_scope_rejects_invalid_price_range() -> None:
    result = await create_listing_search_scope(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        search_type=ListingSearchScopeType.SALE,
        locations=("Bronx",),
        addresses=(),
        keywords=(),
        min_price=Decimal("900000"),
        max_price=Decimal("500000"),
        min_beds=None,
        limit=10,
        enabled=True,
        source_repository=FakeListingSourceRepository(_source()),
        scope_repository=FakeListingSearchScopeRepository(),
        now=NOW,
    )

    assert result.status == ListingSearchScopeStatus.REJECTED
    assert result.reasons == (ListingSearchScopeReasonCode.INVALID_PRICE_RANGE,)


@pytest.mark.asyncio
async def test_create_listing_search_scope_saves_scope() -> None:
    scope_repository = FakeListingSearchScopeRepository()

    result = await create_listing_search_scope(
        actor=_actor(),
        workspace_id=WORKSPACE_ID,
        source_id=SOURCE_ID,
        search_type=ListingSearchScopeType.SALE,
        locations=("Bronx",),
        addresses=(),
        keywords=("condo",),
        min_price=Decimal("500000"),
        max_price=Decimal("800000"),
        min_beds=Decimal("2"),
        limit=10,
        enabled=True,
        source_repository=FakeListingSourceRepository(_source()),
        scope_repository=scope_repository,
        now=NOW,
    )

    assert result.status == ListingSearchScopeStatus.CREATED
    assert result.scope is not None
    assert result.scope.locations == ("Bronx",)
    assert scope_repository.saved[0].keywords == ("condo",)


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=uuid4(),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _source() -> ListingSource:
    return ListingSource(
        source_id=SOURCE_ID,
        workspace_id=WORKSPACE_ID,
        name="StreetEasy NYC",
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        enabled=True,
        requires_auth=False,
        terms_reviewed_at=NOW,
        data_use_policy="Approved for listing enrichment.",
        created_at=NOW,
        updated_at=NOW,
    )