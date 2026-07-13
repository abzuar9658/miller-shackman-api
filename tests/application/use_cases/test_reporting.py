from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.use_cases.reporting import (
    ReportingReadStatus,
    get_campaign_operations_report,
    get_workspace_operations_report,
    list_campaign_audit_logs,
)
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
from tests.application.use_cases._reporting_fakes import FakeReportingRepository

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000003")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000004")
AUDIT_ID = UUID("00000000-0000-0000-0000-000000000005")


def test_brokerage_admin_can_read_workspace_reporting() -> None:
    repo = FakeReportingRepository()
    repo.workspace_reports[WORKSPACE_ID] = _workspace_report()

    result = _run(
        get_workspace_operations_report(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            reporting_repository=repo,
        )
    )

    assert result.status == ReportingReadStatus.OK
    assert result.report is not None
    assert result.report.message_counts.delivered == 3


def test_assigned_agent_cannot_read_workspace_reporting() -> None:
    result = _run(
        get_workspace_operations_report(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            reporting_repository=FakeReportingRepository(),
        )
    )

    assert result.status == ReportingReadStatus.REJECTED
    assert result.reasons[0].value == "permission_denied"


def test_campaign_reporting_returns_not_found_when_campaign_missing() -> None:
    result = _run(
        get_campaign_operations_report(
            actor=_actor(WorkspaceMembershipRole.MANAGER),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            reporting_repository=FakeReportingRepository(),
        )
    )

    assert result.status == ReportingReadStatus.NOT_FOUND
    assert result.reasons[0].value == "campaign_not_found"


def test_campaign_audit_logs_return_entries() -> None:
    repo = FakeReportingRepository()
    repo.campaign_reports[(WORKSPACE_ID, CAMPAIGN_ID)] = _campaign_report()
    repo.audit_logs[(WORKSPACE_ID, CAMPAIGN_ID)] = (_audit_entry(),)

    result = _run(
        list_campaign_audit_logs(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            campaign_id=CAMPAIGN_ID,
            reporting_repository=repo,
        )
    )

    assert result.status == ReportingReadStatus.OK
    assert len(result.entries) == 1
    assert result.entries[0].action == CampaignAdminAuditAction.VERSION_PUBLISHED


def _workspace_report() -> WorkspaceOperationsSummary:
    return WorkspaceOperationsSummary(
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


def _campaign_report() -> CampaignOperationsSummary:
    return CampaignOperationsSummary(
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


def _audit_entry() -> CampaignAuditLogEntry:
    return CampaignAuditLogEntry(
        audit_log_id=AUDIT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=None,
        action=CampaignAdminAuditAction.VERSION_PUBLISHED,
        actor_user_id=ACTOR_ID,
        details={"version_number": 1},
        created_at=NOW,
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


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
