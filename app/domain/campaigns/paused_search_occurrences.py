from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrackStepPhase,
)
from app.domain.common.ids import PausedSearchTrackVersionId, WorkspaceId


class RecurringOccurrenceStatus(StrEnum):
    PLANNED = "planned"
    DEFERRED = "deferred"
    REVIEW_REQUESTED = "review_requested"
    APPROVED = "approved"
    SENT = "sent"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class RecurringOccurrenceOutcome(StrEnum):
    SEND = "send"
    HOLD = "hold"
    REVIEW = "review"
    DEFER = "defer"
    CANCEL = "cancel"
    TERMINALIZE = "terminalize"
    EXPIRED = "expired"
    OCCURRENCE_LIMIT_REACHED = "occurrence_limit_reached"
    DURATION_EXPIRED = "duration_expired"


@dataclass(frozen=True)
class RecurringOccurrence:
    occurrence_id: UUID
    workspace_id: WorkspaceId
    lead_id: UUID
    workflow_id: UUID
    track_version_id: PausedSearchTrackVersionId
    step_id: UUID
    phase: PausedSearchTrackStepPhase
    occurrence_number: int
    scheduled_for: datetime
    due_at: datetime
    status: RecurringOccurrenceStatus
    idempotency_key: str
    created_at: datetime
    logical_touch_count: int = 0
    fallback_used: bool = False
    provider_message_id: str | None = None
    provider_delivery_status: ProviderDeliveryStatus | None = None
    correlation_id: UUID | None = None
    closed_at: datetime | None = None
    failure_reason: str | None = None
    timezone_snapshot: str | None = None


def occurrence_idempotency_key(
    *,
    workflow_id: UUID,
    track_version_id: PausedSearchTrackVersionId,
    step_id: UUID,
    occurrence_number: int,
    channel: str,
    fallback: bool = False,
) -> str:
    parts = [
        str(workflow_id),
        str(track_version_id),
        str(step_id),
        str(occurrence_number),
        channel,
    ]
    if fallback:
        parts.append("fallback")
    return ":".join(parts)
