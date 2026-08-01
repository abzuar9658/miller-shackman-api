from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.events import DomainEvent
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.listing_sources import (
    ListingCrawlRun,
    ListingCrawlStatus,
    ListingSearchScope,
    ListingSearchScopeType,
    ListingSource,
    ListingSourceType,
)
from app.interfaces.api.dependencies.listing_sources import (
    ListingSourceBundle,
    get_listing_source_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000101")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000102")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000103")
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


@dataclass
class ListingSourceApiTestClient:
    client: TestClient
    repository: "FakeListingSourceRepository"
    scope_repository: "FakeListingSearchScopeRepository"
    crawl_run_repository: "FakeListingCrawlRunRepository"
    event_bus: "FakeEventBus"
    session: "FakeSession"


@pytest.fixture
def listing_source_client() -> ListingSourceApiTestClient:
    return _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)


def test_create_and_list_listing_sources(listing_source_client: ListingSourceApiTestClient) -> None:
    create_response = listing_source_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources",
        json={
            "name": "StreetEasy",
            "source_type": "website",
            "base_url": "https://streeteasy.com",
            "allowed_url_patterns": ["/for-sale/"],
            "disallowed_url_patterns": ["/agents/"],
            "crawl_frequency_minutes": 1440,
            "enabled": False,
            "requires_auth": False,
        },
    )

    assert create_response.status_code == 201
    created_body = create_response.json()
    assert created_body["status"] == "created"
    assert created_body["source"]["name"] == "StreetEasy"
    assert created_body["source"]["base_url"] == "https://streeteasy.com/"
    assert listing_source_client.session.commits == 1

    list_response = listing_source_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources"
    )

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["status"] == "ok"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["allowed_url_patterns"] == ["/for-sale/"]
    assert body["sources"][0]["scopes"] == []
    assert body["sources"][0]["latest_crawl_run"] is None
    assert body["sources"][0]["recent_crawl_runs"] == []
    assert body["sources"][0]["next_due_at"] is None


def test_update_listing_source_requires_review_before_enable(
    listing_source_client: ListingSourceApiTestClient,
) -> None:
    source = _source(name="StreetEasy", enabled=False)
    listing_source_client.repository.save_sync(source)

    response = listing_source_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}",
        json={"enabled": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == [
        "review_required_to_enable",
        "data_use_policy_required",
    ]


def test_update_listing_source_succeeds_with_review_fields(
    listing_source_client: ListingSourceApiTestClient,
) -> None:
    source = _source(name="StreetEasy", enabled=False)
    listing_source_client.repository.save_sync(source)

    response = listing_source_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}",
        json={
            "enabled": True,
            "terms_reviewed_at": NOW.isoformat(),
            "data_use_policy": "Approved for internal review only.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["source"]["enabled"] is True
    assert body["source"]["data_use_policy"] == "Approved for internal review only."
    assert listing_source_client.session.commits == 1


def test_manager_cannot_manage_listing_sources() -> None:
    client = _client_for_role(WorkspaceMembershipRole.MANAGER)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_create_and_update_listing_search_scope(
    listing_source_client: ListingSourceApiTestClient,
) -> None:
    source = _source(name="StreetEasy", enabled=True)
    listing_source_client.repository.save_sync(source)
    listing_source_client.crawl_run_repository.runs_by_source[source.source_id] = [
        _crawl_run(source.source_id)
    ]

    create_response = listing_source_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}/scopes",
        json={
            "search_type": "sale",
            "locations": ["Bronx"],
            "keywords": ["condo"],
            "min_price": "500000",
            "max_price": "900000",
            "min_beds": "2",
            "limit": 10,
            "enabled": True,
        },
    )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["status"] == "created"
    scope_id = body["scope"]["scope_id"]

    update_response = listing_source_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}/scopes/{scope_id}",
        json={"enabled": False},
    )

    assert update_response.status_code == 200
    assert update_response.json()["scope"]["enabled"] is False

    list_response = listing_source_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}/scopes"
    )

    assert list_response.status_code == 200
    assert len(list_response.json()["scopes"]) == 1


def test_request_listing_source_crawl_route_requests_pending_run(
    listing_source_client: ListingSourceApiTestClient,
) -> None:
    source = _source(name="StreetEasy", enabled=True, reviewed=True)
    listing_source_client.repository.save_sync(source)
    scope = _scope(source_id=source.source_id)
    listing_source_client.scope_repository.scopes[scope.scope_id] = scope

    response = listing_source_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/listing-sources/{source.source_id}/request-crawl"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "requested"
    assert body["crawl_run"]["status"] == "pending"
    assert listing_source_client.session.commits == 1
    assert (
        listing_source_client.event_bus.events[-1].event_type.value
        == "listing_source_crawl.requested"
    )


def _client_for_role(role: WorkspaceMembershipRole) -> ListingSourceApiTestClient:
    app = create_app()
    repository = FakeListingSourceRepository()
    scope_repository = FakeListingSearchScopeRepository()
    crawl_run_repository = FakeListingCrawlRunRepository()
    event_bus = FakeEventBus()
    session = FakeSession()
    bundle = ListingSourceBundle(
        session=session,
        source_repository=repository,
        scope_repository=scope_repository,
        crawl_run_repository=crawl_run_repository,
        event_bus=event_bus,
    )

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_listing_source_bundle] = lambda: bundle
    return ListingSourceApiTestClient(
        client=TestClient(app),
        repository=repository,
        scope_repository=scope_repository,
        crawl_run_repository=crawl_run_repository,
        event_bus=event_bus,
        session=session,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _source(*, name: str, enabled: bool, reviewed: bool = False) -> ListingSource:
    return ListingSource(
        source_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        name=name,
        source_type=ListingSourceType.WEBSITE,
        base_url="https://streeteasy.com",
        allowed_url_patterns=("/for-sale/",),
        disallowed_url_patterns=(),
        crawl_frequency_minutes=1440,
        enabled=enabled,
        requires_auth=False,
        terms_reviewed_at=NOW if reviewed else None,
        data_use_policy="Approved for listing enrichment." if reviewed else None,
        created_at=NOW,
        updated_at=NOW,
    )


def _scope(*, source_id: UUID) -> ListingSearchScope:
    return ListingSearchScope(
        scope_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        search_type=ListingSearchScopeType.SALE,
        locations=("Bronx",),
        addresses=(),
        keywords=(),
        limit=10,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeListingSourceRepository:
    def __init__(self) -> None:
        self.sources: dict[UUID, ListingSource] = {}

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

    def save_sync(self, source: ListingSource) -> None:
        self.sources[source.source_id] = source


class FakeListingSearchScopeRepository:
    def __init__(self) -> None:
        self.scopes: dict[UUID, ListingSearchScope] = {}

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
    def __init__(self) -> None:
        self.runs_by_source: dict[UUID, list[ListingCrawlRun]] = {}

    async def get_by_id(self, workspace_id: UUID, crawl_run_id: UUID) -> ListingCrawlRun | None:
        _ = workspace_id, crawl_run_id
        return None

    async def list_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[ListingCrawlRun, ...]:
        _ = workspace_id, limit
        runs = self.runs_by_source.get(source_id, [])
        return tuple(runs[:limit])

    async def get_latest_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> ListingCrawlRun | None:
        _ = workspace_id
        runs = self.runs_by_source.get(source_id, [])
        return runs[0] if runs else None

    async def get_active_for_source(
        self,
        workspace_id: UUID,
        source_id: UUID,
    ) -> ListingCrawlRun | None:
        _ = workspace_id
        runs = self.runs_by_source.get(source_id, [])
        for run in runs:
            if run.status in {ListingCrawlStatus.PENDING, ListingCrawlStatus.RUNNING}:
                return run
        return None

    async def insert_pending_if_no_active(
        self,
        crawl_run: ListingCrawlRun,
    ) -> ListingCrawlRun | None:
        runs = self.runs_by_source.setdefault(crawl_run.source_id, [])
        runs.insert(0, crawl_run)
        return crawl_run

    async def claim_pending_by_id(
        self,
        workspace_id: UUID,
        crawl_run_id: UUID,
        *,
        now: datetime,
    ) -> ListingCrawlRun | None:
        _ = workspace_id, crawl_run_id, now
        return None

    async def save(self, crawl_run: ListingCrawlRun) -> ListingCrawlRun:
        runs = self.runs_by_source.setdefault(crawl_run.source_id, [])
        for index, existing in enumerate(runs):
            if existing.crawl_run_id == crawl_run.crawl_run_id:
                runs[index] = crawl_run
                break
        else:
            runs.insert(0, crawl_run)
        return crawl_run


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _crawl_run(source_id: UUID) -> ListingCrawlRun:
    return ListingCrawlRun(
        crawl_run_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        source_id=source_id,
        status=ListingCrawlStatus.COMPLETED,
        started_at=NOW,
        finished_at=NOW,
        inserted_count=3,
        unchanged_count=1,
        failed_count=0,
        created_at=NOW,
        updated_at=NOW,
    )
