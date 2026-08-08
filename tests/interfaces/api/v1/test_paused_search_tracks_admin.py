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
    FakeTemplateRepository,
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


def test_create_generates_track_key_when_omitted(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload.pop("track_key")

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["track"]["track_key"] == "rate-watch"


def test_policy_contract_round_trips_through_admin_api(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload.update(
        {
            "track_mode": "permission_based_interim_contact",
            "interim_contact_policy": "requires_explicit_lead_permission",
            "reply_policy": "continue",
            "channel_sequence": "sequential",
            "max_cycles": 6,
            "max_ai_interactions": 4,
            "restart_delay_days": 45,
        }
    )
    payload["steps"][0]["action"] = "send"

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["version"]["track_mode"] == "permission_based_interim_contact"
    assert body["version"]["interim_contact_policy"] == "requires_explicit_lead_permission"
    assert body["version"]["reply_policy"] == "continue"
    assert body["version"]["max_cycles"] == 6
    assert body["version"]["max_ai_interactions"] == 4
    assert body["version"]["restart_delay_days"] == 45
    assert body["steps"][0]["action"] == "send"


def test_admin_configured_interim_contact_policy_round_trips_through_admin_api(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload.update(
        {
            "track_mode": "permission_based_interim_contact",
            "interim_contact_policy": "allowed_by_published_track",
        }
    )

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 201
    assert response.json()["version"]["interim_contact_policy"] == (
        "allowed_by_published_track"
    )


def test_policy_contract_rejects_cycle_limit_above_code_bound(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload["max_cycles"] = 13

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("legacy_field", ["maintenance_interval_days"])
def test_draft_rejects_removed_legacy_request_fields(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
    legacy_field: str,
) -> None:
    payload = _payload()
    payload[legacy_field] = 30

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == legacy_field for error in response.json()["detail"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fallback_timing_policy", "use_maintenance_interval"),
        ("reply_policy", "restart_after_delay"),
        ("reply_policy", "review_or_remind"),
        ("channel_sequence", "simultaneous"),
    ],
)
def test_draft_rejects_deprecated_policy_choices(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
    field: str,
    value: str,
) -> None:
    payload = _payload()
    payload[field] = value

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ["legacy_configuration_not_allowed"]


def test_draft_rejects_deprecated_step_actions(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload["steps"][0]["action"] = "review"

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ["legacy_configuration_not_allowed"]


def test_invalid_configuration_returns_validation_findings(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    payload = _payload()
    payload["steps"][0]["channel"] = "sms"

    response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=payload,
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["reasons"] == ["invalid_configuration"]
    assert any(
        finding["code"] == "step_channel_not_allowed"
        for finding in detail["validation"]["errors"]
    )


def test_publish_and_retire_paused_search_track(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    create_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )
    track_id = create_response.json()["track"]["track_id"]
    version_id = create_response.json()["version"]["track_version_id"]
    version_number = create_response.json()["version"]["version_number"]

    preview_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/draft/preview",
        json={**_payload(), "as_of": "2026-01-01T12:00:00Z", "timezone": "UTC"},
    )

    publish_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/versions/{version_id}/publish",
        json={
            "draft_version_number": version_number,
            "preview_reference": preview_response.json()["preview_reference"],
            "confirm_warnings": True,
        },
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


def test_validate_and_preview_unsaved_draft_do_not_persist(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    create_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )
    track_id = create_response.json()["track"]["track_id"]
    session = cast(_FakeSession, paused_search_track_admin_client.session)
    commits_before_preview = session.commits

    validate_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/draft/validate",
        json=_payload(),
    )
    preview_response = paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{track_id}/draft/preview",
        json={**_payload(), "as_of": "2026-01-01T12:00:00Z", "timezone": "UTC"},
    )

    assert validate_response.status_code == 200
    assert validate_response.json()["validation"]["publishable"] is True
    assert preview_response.status_code == 200
    preview_body = preview_response.json()
    assert preview_body["status"] == "ready"
    assert preview_body["preview_reference"]
    assert preview_body["occurrences"]
    assert all(
        occurrence["reason_code"] == "scheduled"
        for occurrence in preview_body["occurrences"]
    )
    assert session.commits == commits_before_preview


def test_preview_requires_admin_role() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)
    response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{UUID(int=123)}/draft/preview",
        json={**_payload(), "as_of": "2026-01-01T12:00:00Z", "timezone": "UTC"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_templates_are_readable_before_track_id_route(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    paused_search_track_admin_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )
    templates_response = paused_search_track_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/templates"
    )
    assert templates_response.status_code == 200
    assert templates_response.json()["templates"]


def test_assigned_agent_cannot_view_or_create_paused_search_tracks() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks")
    create_response = client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks",
        json=_payload(),
    )
    delete_response = client.client.delete(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{UUID(int=123)}"
    )

    assert list_response.status_code == 403
    assert list_response.json()["detail"] == ["permission_denied"]
    assert create_response.status_code == 403
    assert create_response.json()["detail"] == ["permission_denied"]
    assert delete_response.status_code == 403
    assert delete_response.json()["detail"] == ["permission_denied"]


def test_detail_returns_404_for_missing_track(
    paused_search_track_admin_client: PausedSearchTrackAdminTestClient,
) -> None:
    response = paused_search_track_admin_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/paused-search-tracks/{UUID(int=123)}"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ["track_not_found"]


def test_uncertain_occurrence_resolution_route_is_registered() -> None:
    paths = create_app().openapi()["paths"]

    expected_paths = (
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/occurrences",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}/resolve",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/reviews",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/reviews/{review_id}",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/reviews/{review_id}/approve",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/reviews/{review_id}/reject",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/reviews/{review_id}/resolve",
        "/api/v1/workspaces/{workspace_id}/paused-search-tracks/{track_id}",
    )
    assert all(path in paths for path in expected_paths)
    assert (
        "/api/v1/workspaces/{workspace_id}/paused-search/occurrences/{occurrence_id}/resolve"
        not in paths
    )


def _client_for_role(role: WorkspaceMembershipRole) -> PausedSearchTrackAdminTestClient:
    repository = FakePausedSearchTrackAdminRepository()
    audit_repository = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()
    template_repository = FakeTemplateRepository()
    session = _FakeSession()
    actor = _actor(role=role)
    app = create_app()
    app.dependency_overrides[get_workspace_actor] = lambda: actor
    app.dependency_overrides[get_paused_search_track_read_bundle] = lambda: (
        PausedSearchTrackReadBundle(track_repository=repository)
    )
    app.dependency_overrides[get_paused_search_track_service_bundle] = lambda: (
        PausedSearchTrackServiceBundle(
            session=session,
            track_repository=repository,
            audit_log_repository=audit_repository,
            event_bus=event_bus,
            template_repository=template_repository,
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
        "selection_guidance": "Select when a lead waits for mortgage rates to improve.",
        "enabled": True,
        "allowed_channels": ["email"],
        "fallback_timing_policy": "use_default_pause_duration",
        "reactivation_window_days": 30,
        "max_total_touches": 4,
        "restart_delay_days": 30,
        "steps": [
            {
                "phase": "maintenance",
                "channel": "email",
                "delay_hours": 0,
                "message_goal": "Check in about home search timing.",
                "template_key": "paused-search-email-1",
                "max_attempts": 1,
                "action": "send",
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
