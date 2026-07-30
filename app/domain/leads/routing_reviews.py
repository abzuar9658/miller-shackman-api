from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, UserId, WorkspaceId


class LeadRoutingReviewStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class LeadRoutingReviewResolution(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


@dataclass(frozen=True)
class LeadRoutingReview:
    review_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    artifact_id: UUID
    status: LeadRoutingReviewStatus
    reason_codes: tuple[str, ...]
    resolution: LeadRoutingReviewResolution | None = None
    reviewed_by_user_id: UserId | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = datetime.min
    updated_at: datetime = datetime.min