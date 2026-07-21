from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import WorkspaceId


class TemporalSignalName(StrEnum):
    INBOUND_PROCESSED = "inbound_processed"
    PAUSE_REQUESTED = "pause_requested"
    RESUME_REQUESTED = "resume_requested"
    BLOCKED_REVIEW_COMPLETED = "blocked_review_completed"


class TemporalSignalOutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    SENT = "sent"
    FAILED = "failed"
    TERMINAL_FAILURE = "terminal_failure"


def _empty_payload() -> dict[str, object]:
    return {}


@dataclass(frozen=True)
class TemporalSignalOutboxEntry:
    temporal_signal_id: UUID
    workspace_id: WorkspaceId
    workflow_id: UUID
    temporal_workflow_id: str
    signal_name: TemporalSignalName
    payload: dict[str, object] = field(default_factory=_empty_payload)
    idempotency_key: str = ""
    status: TemporalSignalOutboxStatus = TemporalSignalOutboxStatus.PENDING
    attempt_count: int = 0
    available_at: datetime | None = None
    claimed_until: datetime | None = None
    sent_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None