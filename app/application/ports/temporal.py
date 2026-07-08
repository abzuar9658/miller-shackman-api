from typing import Protocol

from app.domain.common.ids import LeadId, WorkspaceId


class TemporalWorkflowStarter(Protocol):
    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        temporal_workflow_id: str,
    ) -> None:
        raise NotImplementedError
