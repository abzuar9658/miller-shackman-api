from typing import Protocol
from uuid import UUID

from app.domain.common.ids import WorkspaceId
from app.domain.reporting import (
    CampaignAuditLogEntry,
    CampaignOperationsSummary,
    WorkspaceOperationsSummary,
)


class ReportingRepository(Protocol):
    async def get_workspace_operations_summary(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOperationsSummary: ...

    async def get_campaign_operations_summary(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
    ) -> CampaignOperationsSummary | None: ...

    async def list_campaign_audit_logs(
        self,
        workspace_id: WorkspaceId,
        campaign_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[CampaignAuditLogEntry, ...]: ...
