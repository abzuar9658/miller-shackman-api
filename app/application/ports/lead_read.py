from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrack,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    WorkspaceId,
)
from app.domain.conversations import CrmConversationEvent, Handoff, InboundMessage
from app.domain.identity import User
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
)
from app.domain.workflows import LeadWorkflow, LeadWorkflowOverrideAuditLog, WorkflowTransition


@dataclass(frozen=True)
class LeadReadConversationSummary:
    lead_id: LeadId
    inbound_message_count: int
    latest_inbound_at: datetime
    latest_inbound_preview: str


class LeadSavedView(StrEnum):
    NEEDS_HUMAN = "needs_human"
    BLOCKED = "blocked"
    NO_OWNER = "no_owner"
    PAUSED_STALE = "paused_stale"


# A paused workflow older than this is considered stale and needs intervention;
# mirrored by the saved-view tabs in the web lead workspace.
PAUSED_STALE_THRESHOLD_HOURS = 24


@dataclass(frozen=True)
class LeadWorkspaceViewCounts:
    total: int = 0
    needs_human: int = 0
    blocked: int = 0
    no_owner: int = 0
    paused_stale: int = 0
    # Not a filterable saved view: workspace-wide count of leads with no
    # workflow at all (mirrors the UI's "not enrolled" journey node, where
    # latest_workflow is null), consumed by the home dashboards' inventory.
    not_enrolled: int = 0


class LeadReadLeadRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        raise NotImplementedError

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
        offset: int = 0,
        owner_user_id: UUID | None = None,
        search: str | None = None,
        view: LeadSavedView | None = None,
    ) -> tuple[CanonicalLeadRecord, ...]:
        raise NotImplementedError

    async def count_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        owner_user_id: UUID | None = None,
        search: str | None = None,
        view: LeadSavedView | None = None,
    ) -> int:
        raise NotImplementedError

    async def count_views_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        owner_user_id: UUID | None = None,
        search: str | None = None,
    ) -> LeadWorkspaceViewCounts:
        raise NotImplementedError


class LeadReadPausedSearchHistoryRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadPausedSearchHistoryEntry, ...]:
        raise NotImplementedError


class LeadReadClassificationArtifactRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadClassificationArtifact | None:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadClassificationArtifact, ...]:
        raise NotImplementedError


class LeadReadWorkflowRepository(Protocol):
    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> LeadWorkflow | None:
        raise NotImplementedError

    async def list_active_paused_search_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError

    async def list_latest_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError

    async def list_latest_for_leads(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadWorkflow, ...]:
        raise NotImplementedError


class LeadReadWorkflowTransitionRepository(Protocol):
    async def list_for_workflow(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[WorkflowTransition, ...]:
        raise NotImplementedError


class LeadReadWorkflowOverrideAuditRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflowOverrideAuditLog, ...]:
        raise NotImplementedError


class LeadReadInboundMessageRepository(Protocol):
    async def list_lead_summaries(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadReadConversationSummary, ...]:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        raise NotImplementedError


class LeadReadOutboundMessageRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        raise NotImplementedError


class LeadReadHandoffRepository(Protocol):
    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError

    async def list_latest_for_leads(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        raise NotImplementedError


class LeadReadCrmConversationEventRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        raise NotImplementedError


class LeadReadPausedSearchTrackRepository(Protocol):
    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        raise NotImplementedError

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        raise NotImplementedError

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        raise NotImplementedError

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        raise NotImplementedError


class LeadReadUserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None:
        raise NotImplementedError
