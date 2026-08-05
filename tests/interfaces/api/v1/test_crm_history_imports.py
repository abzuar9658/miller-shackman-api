from typing import cast

from fastapi.testclient import TestClient

from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CrmConversationEventRepository,
    LeadRepository,
)
from app.core.config import Settings
from app.domain.identity import AuthenticatedExtensionDevice, WorkspaceMembershipRole
from app.interfaces.api.dependencies.crm_history_imports import (
    CrmHistoryImportBundle,
    get_crm_history_import_bundle,
)
from app.interfaces.api.dependencies.extension_devices import get_extension_device_actor
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import app
from tests.application.use_cases._crm_history_import_fakes import (
    FakeAuthAuditLogRepository,
    FakeCrmConversationEventRepository,
    FakeCrmHistoryImportEventRepository,
    FakeCrmHistoryImportJobRepository,
    FakeLeadRepository,
)
from tests.application.use_cases.test_crm_history_imports import (
    LEAD_ID,
    OTHER_WORKSPACE_ID,
    WORKSPACE_ID,
    _actor,
    _lead,
)


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


def test_api_stages_deduplicates_and_completes_with_scoped_token_only() -> None:
    bundle = _bundle(enabled=True)
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(
        WorkspaceMembershipRole.MANAGER
    )
    app.dependency_overrides[get_crm_history_import_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            created = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports",
                json={"lead_id": str(LEAD_ID)},
            )
            assert created.status_code == 201
            body = created.json()
            assert "upload_token_hash" not in body["job"]
            job_id = body["job"]["job_id"]
            token = body["upload_token"]

            staged = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/{job_id}/events",
                headers={"X-CRM-History-Import-Token": token},
                json={"events": [_event_body(), _event_body()]},
            )
            wrong_token = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/{job_id}/events",
                headers={"X-CRM-History-Import-Token": "wrong"},
                json={"events": [_event_body()]},
            )
            wrong_workspace = client.post(
                f"/api/v1/workspaces/{OTHER_WORKSPACE_ID}/crm-history-imports/{job_id}/events",
                headers={"X-CRM-History-Import-Token": token},
                json={"events": [_event_body()]},
            )
            completed = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/{job_id}/complete",
                headers={"X-CRM-History-Import-Token": token},
            )

        assert staged.status_code == 200
        assert staged.json()["accepted_count"] == 1
        assert staged.json()["duplicate_count"] == 1
        assert wrong_token.status_code == 401
        assert wrong_workspace.status_code == 404
        assert completed.status_code == 200
        assert completed.json()["job"]["status"] == "ready"
    finally:
        app.dependency_overrides.clear()


def test_capability_and_create_report_disabled_or_disallowed() -> None:
    bundle = _bundle(enabled=False)
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(
        WorkspaceMembershipRole.ASSIGNED_AGENT
    )
    app.dependency_overrides[get_crm_history_import_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            capability = client.get(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/capability"
            )
            created = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports",
                json={"lead_id": str(LEAD_ID)},
            )
        assert capability.status_code == 200
        assert capability.json()["allowed"] is False
        assert "feature_disabled" in capability.json()["reasons"]
        assert created.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_extension_export_stages_dom_event_shape_and_source_url() -> None:
    bundle = _bundle(enabled=True)
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(
        WorkspaceMembershipRole.MANAGER
    )
    app.dependency_overrides[get_crm_history_import_bundle] = lambda: bundle
    events = [
        {
            "external_activity_id": "text-0",
            "fingerprint": "text-fingerprint-0",
            "activity_type": "text",
            "direction": "outbound",
            "content": "First outbound text",
            "occurred_at": "2026-06-30T12:00:00Z",
            "actor_name": "Agent One",
            "details": {"direction_basis": "avatar"},
        },
        {
            "external_activity_id": "text-1",
            "fingerprint": "text-fingerprint",
            "activity_type": "text",
            "direction": "inbound",
            "content": "Inbound text",
            "occurred_at": "2026-07-01T12:00:00Z",
            "actor_name": "Lead",
            "details": {"direction_basis": "lead_link"},
        },
        {
            "external_activity_id": "email-1",
            "fingerprint": "email-fingerprint",
            "activity_type": "email",
            "direction": "outbound",
            "content": "Email body",
            "occurred_at": "2026-07-02T12:00:00Z",
            "actor_name": "Agent One",
            "details": {"subject": "Follow-up"},
        },
        {
            "external_activity_id": "inquiry-1",
            "fingerprint": "inquiry-fingerprint",
            "activity_type": "Property Inquiry",
            "direction": None,
            "content": "Property inquiry details",
            "occurred_at": "2026-07-03T12:00:00Z",
            "details": {"direction_basis": "event"},
        },
        {
            "external_activity_id": "text-2",
            "fingerprint": "text-fingerprint-2",
            "activity_type": "text",
            "direction": "inbound",
            "content": "Second inbound text",
            "occurred_at": "2026-07-04T12:00:00Z",
            "actor_name": "Lead",
            "details": {"direction_basis": "lead_link"},
        },
        {
            "external_activity_id": "text-3",
            "fingerprint": "text-fingerprint-3",
            "activity_type": "text",
            "direction": "outbound",
            "content": "Second outbound text",
            "occurred_at": "2026-07-05T12:00:00Z",
            "actor_name": "Agent One",
            "details": {"direction_basis": "avatar"},
        },
        {
            "external_activity_id": "text-4",
            "fingerprint": "text-fingerprint-4",
            "activity_type": "text",
            "direction": "inbound",
            "content": "Third inbound text",
            "occurred_at": "2026-07-06T12:00:00Z",
            "actor_name": "Lead",
            "details": {"direction_basis": "lead_link"},
        },
    ]
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/export",
                json={
                    "crm_lead_id": "fub-lead-1",
                    "source_url": "https://app.followupboss.com/people/view/1",
                    "events": events,
                },
            )

        assert response.status_code == 201
        assert response.json()["job"]["status"] == "ready"
        assert response.json()["job"]["received_count"] == 7
        staged_repository = cast(
            FakeCrmHistoryImportEventRepository, bundle.event_repository
        )
        staged = tuple(staged_repository.events.values())
        assert len(staged) == 7
        assert all(
            event.details["source_url"]
            == "https://app.followupboss.com/people/view/1"
            for event in staged
        )
    finally:
        app.dependency_overrides.clear()


def test_device_extension_export_allows_unassigned_lead_and_deduplicates_batch() -> None:
    bundle = _bundle(enabled=True)
    actor = _actor(WorkspaceMembershipRole.ASSIGNED_AGENT)
    principal = AuthenticatedExtensionDevice(
        actor=actor,
        device_id=OTHER_WORKSPACE_ID,
    )
    app.dependency_overrides[get_extension_device_actor] = lambda: principal
    app.dependency_overrides[get_crm_history_import_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            first = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/extension-export",
                json={"crm_lead_id": "fub-lead-1", "events": [_event_body()]},
            )
            repeated = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/extension-export",
                json={"crm_lead_id": "fub-lead-1", "events": [_event_body()]},
            )
        assert first.status_code == 201
        assert repeated.status_code == 201
        assert repeated.json()["status"] == "duplicate"
        assert repeated.json()["upload_token"] is None
        assert repeated.json()["job"]["job_id"] == first.json()["job"]["job_id"]
        audit = cast(FakeAuthAuditLogRepository, bundle.audit_log_repository)
        assert audit.logs[0].event_details["source_device_id"] == str(principal.device_id)
    finally:
        app.dependency_overrides.clear()


def test_event_schema_rejects_nested_or_unbounded_details() -> None:
    bundle = _bundle(enabled=True)
    app.dependency_overrides[get_crm_history_import_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/crm-history-imports/{LEAD_ID}/events",
                headers={"X-CRM-History-Import-Token": "token"},
                json={"events": [{**_event_body(), "details": {"nested": {"no": "objects"}}}]},
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def _bundle(*, enabled: bool) -> CrmHistoryImportBundle:
    return CrmHistoryImportBundle(
        session=_FakeSession(),
        settings=Settings(fub_history_import_enabled=enabled),
        job_repository=FakeCrmHistoryImportJobRepository(),
        event_repository=FakeCrmHistoryImportEventRepository(),
        lead_repository=cast(LeadRepository, FakeLeadRepository((_lead(),))),
        conversation_event_repository=cast(
            CrmConversationEventRepository, FakeCrmConversationEventRepository()
        ),
        audit_log_repository=cast(AuthAuditLogRepository, FakeAuthAuditLogRepository()),
    )


def _event_body() -> dict[str, object]:
    return {
        "external_activity_id": "fub-activity-1",
        "fingerprint": "fingerprint-1",
        "activity_type": "Text",
        "direction": "inbound",
        "content": "Historical content",
        "occurred_at": "2026-07-01T12:00:00Z",
        "actor_agent_id": "agent-1",
        "actor_name": "Agent One",
        "details": {"source": "extension", "attempt": 1, "archived": False},
    }