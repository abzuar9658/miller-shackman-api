from temporalio.client import Client

from app.application.ports.temporal import TemporalWorkflowStarter
from app.core.config import Settings, get_settings
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.infrastructure.workflows.temporal.lead_nurture import (
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
)
from app.infrastructure.workflows.temporal.worker import connect_temporal_client


class TemporalClientWorkflowStarter:
    def __init__(self, client: Client, *, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_version_id: CampaignVersionId,
        temporal_workflow_id: str,
    ) -> None:
        await self._client.start_workflow(
            LeadNurtureWorkflow.run,
            LeadNurtureWorkflowInput(
                workspace_id=workspace_id,
                lead_id=lead_id,
                campaign_version_id=campaign_version_id,
            ),
            id=temporal_workflow_id,
            task_queue=self._task_queue,
        )


async def build_temporal_workflow_starter(
    settings: Settings | None = None,
) -> TemporalWorkflowStarter:
    resolved_settings = settings or get_settings()
    client = await connect_temporal_client(resolved_settings)
    return TemporalClientWorkflowStarter(
        client,
        task_queue=resolved_settings.temporal_task_queue,
    )
