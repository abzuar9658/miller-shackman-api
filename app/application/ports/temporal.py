from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

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


@dataclass(frozen=True)
class PauseLeadNurtureWorkflowSignal:
    workspace_id: WorkspaceId
    lead_id: LeadId
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


class LeadNurtureWorkflowSignaler(Protocol):
    async def signal_pause_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: PauseLeadNurtureWorkflowSignal,
    ) -> None:
        raise NotImplementedError
