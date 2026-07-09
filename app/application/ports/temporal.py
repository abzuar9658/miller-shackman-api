from typing import Protocol

from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId


class TemporalWorkflowStarter(Protocol):
    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_version_id: CampaignVersionId,
        temporal_workflow_id: str,
    ) -> None:
        raise NotImplementedError
