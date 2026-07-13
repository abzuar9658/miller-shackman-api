from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.domain.campaigns.admin import CampaignAdminAuditAction
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.reporting import (
    CampaignAuditLogEntry,
    CampaignOperationsSummary,
    EnrollmentStatusCounts,
    HandoffStatusCounts,
    MessageStatusCounts,
    WorkflowStateCounts,
    WorkspaceOperationsSummary,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.reporting import (
    ReportingServiceBundle,
    get_reporting_service_bundle,
)
from app.main import create_app
from tests.application.use_cases._reporting_fakes import FakeReportingRepository

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000003")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000004")
AUDIT_ID = UUID("00000000-0000-0000-0000-000000000005")


@dataclass
class ReportingTestClient:
    client: TestClient
    reporting_repository: FakeReportingRepository


@pytest.fixture
def reporting_client() -> ReportingTestClient:
    return _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)


def test_workspace_operations_route_returns_200(reporting_client: ReportingTestClient) -> None:
    response = reporting_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/reporting/operations"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["report"]["active_campaigns"] == 1
    assert body["report"]["message_counts"]["delivered"] == 3


def test_assigned_agent_cannot_view_reporting() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/reporting/operations")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_campaign_report_and_audit_routes_return_200(reporting_client: ReportingTestClient) -> None:
    response = reporting_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/reporting/campaigns/{CAMPAIGN_ID}"
    )
    assert response.status_code == 200
    assert response.json()["report"]["campaign_status"] == CampaignStatus.ACTIVE.value

    audit_response = reporting_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/reporting/campaigns/{CAMPAIGN_ID}/audit-logs"
    )
    assert audit_response.status_code == 200
    assert (
        audit_response.json()["entries"][0]["action"]
        == CampaignAdminAuditAction.VERSION_PUBLISHED.value
    )


def _client_for_role(role: WorkspaceMembershipRole) -> ReportingTestClient:
    app = create_app()
    reporting_repository = FakeReportingRepository()
    reporting_repository.workspace_reports[WORKSPACE_ID] = WorkspaceOperationsSummary(
        workspace_id=WORKSPACE_ID,
        active_campaigns=1,
        paused_campaigns=0,
        last_successful_sync_at=NOW,
        workflow_counts=WorkflowStateCounts(active_nurture=2, waiting_for_response=1),
        message_counts=MessageStatusCounts(sent=4, delivered=3),
        handoff_counts=HandoffStatusCounts(notified=1),
        pending_external_events=0,
        failed_external_events=0,
        pending_outbox_events=1,
        failed_outbox_events=0,
    )
    reporting_repository.campaign_reports[(WORKSPACE_ID, CAMPAIGN_ID)] = CampaignOperationsSummary(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        active_version_id=None,
        latest_audit_at=NOW,
        enrollment_counts=EnrollmentStatusCounts(active=2),
        workflow_counts=WorkflowStateCounts(waiting_for_response=2),
        message_counts=MessageStatusCounts(sent=2, delivered=2),
        handoff_counts=HandoffStatusCounts(),
    )
    reporting_repository.audit_logs[(WORKSPACE_ID, CAMPAIGN_ID)] = (
        CampaignAuditLogEntry(
            audit_log_id=AUDIT_ID,
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            campaign_version_id=None,
            action=CampaignAdminAuditAction.VERSION_PUBLISHED,
            actor_user_id=ACTOR_ID,
            details={"version_number": 1},
            created_at=NOW,
        ),
    )

    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role)
    app.dependency_overrides[get_reporting_service_bundle] = lambda: ReportingServiceBundle(
        reporting_repository=reporting_repository
    )
    return ReportingTestClient(client=TestClient(app), reporting_repository=reporting_repository)


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
