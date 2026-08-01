from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId


class LeadActivityKind(StrEnum):
    INBOUND_MESSAGE = "inbound_message"
    OUTBOUND_MESSAGE = "outbound_message"
    CRM_CONVERSATION_EVENT = "crm_conversation_event"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class LeadActivitySummary:
    lead_id: LeadId
    inbound_message_count: int = 0
    outbound_message_count: int = 0
    crm_event_count: int = 0
    handoff_count: int = 0
    latest_activity_at: datetime | None = None
    latest_activity_preview: str | None = None
    latest_activity_kind: LeadActivityKind | None = None

    @property
    def activity_count(self) -> int:
        return (
            self.inbound_message_count
            + self.outbound_message_count
            + self.crm_event_count
            + self.handoff_count
        )


@dataclass(frozen=True)
class LeadActivityTranscriptSegment:
    text: str
    speaker_name: str | None = None
    speaker_role: str | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class LeadActivityItem:
    activity_id: UUID
    lead_id: LeadId
    kind: LeadActivityKind
    occurred_at: datetime
    title: str
    preview: str
    content: str | None = None
    channel: str | None = None
    direction: str | None = None
    status: str | None = None
    actor_name: str | None = None
    details: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    transcript_segments: tuple[LeadActivityTranscriptSegment, ...] = ()


class LeadActivityRepository(Protocol):
    async def list_summaries(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadActivitySummary, ...]:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[LeadActivityItem, ...]:
        raise NotImplementedError
