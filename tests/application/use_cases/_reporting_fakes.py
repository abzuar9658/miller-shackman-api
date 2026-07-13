from uuid import UUID

from app.domain.reporting import (
    CampaignAuditLogEntry,
    CampaignOperationsSummary,
    WorkspaceOperationsSummary,
)


class FakeReportingRepository:
    def __init__(self) -> None:
        self.workspace_reports: dict[UUID, WorkspaceOperationsSummary] = {}
        self.campaign_reports: dict[tuple[UUID, UUID], CampaignOperationsSummary] = {}
        self.audit_logs: dict[tuple[UUID, UUID], tuple[CampaignAuditLogEntry, ...]] = {}

    async def get_workspace_operations_summary(
        self,
        workspace_id: UUID,
    ) -> WorkspaceOperationsSummary:
        return self.workspace_reports[workspace_id]

    async def get_campaign_operations_summary(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
    ) -> CampaignOperationsSummary | None:
        return self.campaign_reports.get((workspace_id, campaign_id))

    async def list_campaign_audit_logs(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CampaignAuditLogEntry, ...]:
        return self.audit_logs.get((workspace_id, campaign_id), ())[:limit]
