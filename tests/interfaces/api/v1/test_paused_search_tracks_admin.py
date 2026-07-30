from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.paused_search_tracks import (
    PausedSearchTrackReadBundle,
    PausedSearchTrackServiceBundle,
    get_paused_search_track_read_bundle,
    get_paused_search_track_service_bundle,
)
from app.main import create_app
from tests.application.use_cases.test_paused_search_track_admin import (
    FakeEventBus,
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAuditLogRepository,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


@dataclass
class PausedSearchTrackAdminTestClient:
    client: TestClient
    repository: FakePausedSearchTrackAdminRepository
    audit_repository: FakePausedSearchTrackAuditLogRepository
    event_bus: FakeEventBus
    session: object


@pytest.fixture
def paused_search_track_admin_client() -> PausedSearchTrackAdminTestClient:
    return _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)


def test_create_list_and_detail_paused_search_tracks(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    create_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )

    assert create_response.status_code == 201
    create_body = create_response.json()
    assert create_body["status"] == "created"
    assert create_body["track"]["track_key"] == "rate-watch"
    assert len(create_body["steps"]) == 1

    track_id = create_body["track"]["track_id"]
    version_id = create_body["version"]["track_version_id"]

    list_response = paused_search_track_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks"
    )
    detail_response = paused_search_track_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["tracks"][0]["track"]["track_id"] == track_id
    assert list_response.json()["tracks"][0]["step_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["version"]["track_version_id"] == version_id
    assert cast(_FakeSession, paused_search_track_admin_client.session).commits == 1


def test_publish_and_retire_paused_search_track(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    create_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )
    track_id = create_response.json()["track"]["track_id"]
    version_id = create_response.json()["version"]["track_version_id"]

    publish_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/versions/{version_id}/publish"
    )
    retire_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/retire"
    )

    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"
    assert retire_response.status_code == 200
    assert retire_response.json()["status"] == "retired"
    assert paused_search_track_admin_client.audit_repository.logs[-1].action.value == (
        "paused_search_track_retired"
    )
    assert paused_search_track_admin_client.event_bus.events[-1].event_type.value == (
        "paused_search_track.retired"
    )


def test_assigned_agent_cannot_view_or_create_paused_search_tracks() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks")
    create_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )

    assert list_response.status_code == 403
    assert list_response.json()["detail"] == ["permission_denied"]
    assert create_response.status_code == 403
    assert create_response.json()["detail"] == ["permission_denied"]


def test_detail_returns_404_for_missing_track(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    response = paused_search_track_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{UUID(int=123)}"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ["track_not_found"]


def _client_for_role(role: WorkspaceMembershipRole) -> PausedSearchTrackAdminTestClient:
    repository = FakePausedSearchTrackAdminRepository()
    audit_repository = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()
    session = _FakeSession()
    actor = _actor(role=role)
    app = create_app()
    app.dependency_overrides[get_workspace_actor] = lambda: actor
    app.dependency_overrides[get_paused_search_track_read_bundle] = (
        lambda: PausedSearchTrackReadBundle(track_repository=repository)
    )
    app.dependency_overrides[get_paused_search_track_service_bundle] = (
        lambda: PausedSearchTrackServiceBundle(
            session=session,
            track_repository=repository,
            audit_log_repository=audit_repository,
            event_bus=event_bus,
        )
    )
    return PausedSearchTrackAdminTestClient(
        client=TestClient(app),
        repository=repository,
        audit_repository=audit_repository,
        event_bus=event_bus,
        session=session,
    )


def _payload() -> dict[str, Any]:
    return {
        "track_key": "rate-watch",
        "display_name": "Rate Watch",
        "track_family": "maintenance",
        "enabled": True,
        "allowed_channels": ["email"],
        "default_for_reason_codes": ["waiting_for_rates"],
        "fallback_timing_policy": "use_maintenance_interval",
        "maintenance_interval_days": 60,
        "reactivation_window_days": 30,
        "max_total_touches": 4,
        "requires_review_before_publish": False,
        "steps": [
            {
                "phase": "maintenance",
                "channel": "email",
                "delay_hours": 0,
                "message_goal": "Check in about home search timing.",
                "template_key": "paused-search-email-1",
                "max_attempts": 1,
                "review_required": False,
            }
        ],
    }


def _actor(
    *,
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.BROKERAGE_ADMIN,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1