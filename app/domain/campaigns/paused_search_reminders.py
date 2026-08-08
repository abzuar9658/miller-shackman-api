from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, UserId, WorkspaceId


class PausedSearchReminderStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class PausedSearchAgentReminder:
    reminder_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    workflow_id: UUID
    occurrence_id: UUID
    assigned_user_id: UserId | None
    due_at: datetime
    status: PausedSearchReminderStatus
    title: str
    body: str
    idempotency_key: str
    created_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None