from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId


class TemporalWorkflowSignalError(RuntimeError):
    pass


class TemporalWorkflowNotFoundError(TemporalWorkflowSignalError):
    pass


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


@dataclass(frozen=True)
class ResumeLeadNurtureWorkflowSignal:
    workspace_id: WorkspaceId
    lead_id: LeadId
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class UnblockLeadNurtureWorkflowSignal:
    workspace_id: WorkspaceId
    lead_id: LeadId
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class InboundProcessedLeadNurtureWorkflowSignal:
    workspace_id: WorkspaceId
    lead_id: LeadId
    occurred_at: datetime
    external_event_id: UUID | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    inbound_action: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RescheduleLeadNurtureWorkflowSignal:
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

    async def signal_resume_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: ResumeLeadNurtureWorkflowSignal,
    ) -> None:
        raise NotImplementedError

    async def signal_unblock_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: UnblockLeadNurtureWorkflowSignal,
    ) -> None:
        raise NotImplementedError

    async def signal_inbound_processed_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: InboundProcessedLeadNurtureWorkflowSignal,
    ) -> None:
        raise NotImplementedError

    async def signal_reschedule_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: RescheduleLeadNurtureWorkflowSignal,
    ) -> None:
        raise NotImplementedError
