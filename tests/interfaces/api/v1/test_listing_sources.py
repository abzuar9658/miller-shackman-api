from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.listing_sources import ListingSource, ListingSourceType
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


def _client_for_role(role: WorkspaceMembershipRole) -> ListingSourceApiTestClient:
    app = create_app()
    repository = FakeListingSourceRepository()
    session = FakeSession()
    bundle = ListingSourceBundle(session=session, source_repository=repository)

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_listing_source_bundle] = lambda: bundle
    return ListingSourceApiTestClient(
        client=TestClient(app),
        repository=repository,
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


def _source(*, name: str, enabled: bool) -> ListingSource:
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

    async def save(self, source: ListingSource) -> ListingSource:
        self.sources[source.source_id] = source
        return source

    def save_sync(self, source: ListingSource) -> None:
        self.sources[source.source_id] = source


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1