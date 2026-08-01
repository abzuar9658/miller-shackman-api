from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class PausedSearchReviewKind(StrEnum):
    MESSAGE = "message"
    TERMINAL = "terminal"
    POLICY = "policy"


class PausedSearchReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class PausedSearchReviewAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    RESOLVE = "resolve"


class PausedSearchReviewError(StrEnum):
    INVALID_TRANSITION = "invalid_transition"
    POLICY_ACTION_NOT_ALLOWED = "policy_action_not_allowed"


@dataclass(frozen=True)
class PausedSearchReview:
    review_id: UUID
    workspace_id: UUID
    lead_id: UUID
    workflow_id: UUID
    occurrence_id: UUID | None
    kind: PausedSearchReviewKind
    status: PausedSearchReviewStatus
    reason: str
    requested_at: datetime
    review_expiry_at: datetime | None = None
    reviewer_user_id: UUID | None = None
    acted_at: datetime | None = None
    action_reason: str | None = None
    outbound_message_id: UUID | None = None
    outbound_message_version: int | None = None


def apply_review_action(
    review: PausedSearchReview,
    *,
    action: PausedSearchReviewAction,
    reviewer_user_id: UUID,
    reason: str,
    now: datetime,
) -> tuple[PausedSearchReview | None, PausedSearchReviewError | None]:
    if review.status is not PausedSearchReviewStatus.PENDING:
        return None, PausedSearchReviewError.INVALID_TRANSITION
    if (
        review.kind is PausedSearchReviewKind.POLICY
        and action is not PausedSearchReviewAction.RESOLVE
    ):
        return None, PausedSearchReviewError.POLICY_ACTION_NOT_ALLOWED
    status = {
        PausedSearchReviewAction.APPROVE: PausedSearchReviewStatus.APPROVED,
        PausedSearchReviewAction.REJECT: PausedSearchReviewStatus.REJECTED,
        PausedSearchReviewAction.RESOLVE: PausedSearchReviewStatus.RESOLVED,
    }[action]
    return (
        replace(
            review,
            status=status,
            reviewer_user_id=reviewer_user_id,
            acted_at=now,
            action_reason=reason,
        ),
        None,
    )
