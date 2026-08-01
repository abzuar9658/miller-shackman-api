from datetime import UTC, datetime
from uuid import UUID

from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewAction,
    PausedSearchReviewError,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
    apply_review_action,
)


def _review(kind: PausedSearchReviewKind) -> PausedSearchReview:
    return PausedSearchReview(
        review_id=UUID("00000000-0000-0000-0000-000000000701"),
        workspace_id=UUID("00000000-0000-0000-0000-000000000501"),
        lead_id=UUID("00000000-0000-0000-0000-000000000702"),
        workflow_id=UUID("00000000-0000-0000-0000-000000000703"),
        occurrence_id=None,
        kind=kind,
        status=PausedSearchReviewStatus.PENDING,
        reason="test",
        requested_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_message_review_can_be_approved() -> None:
    updated, error = apply_review_action(
        _review(PausedSearchReviewKind.MESSAGE),
        action=PausedSearchReviewAction.APPROVE,
        reviewer_user_id=UUID("00000000-0000-0000-0000-000000000704"),
        reason="Reviewed",
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert error is None
    assert updated is not None
    assert updated.status is PausedSearchReviewStatus.APPROVED


def test_policy_review_only_allows_resolution() -> None:
    updated, error = apply_review_action(
        _review(PausedSearchReviewKind.POLICY),
        action=PausedSearchReviewAction.APPROVE,
        reviewer_user_id=UUID("00000000-0000-0000-0000-000000000704"),
        reason="Not allowed",
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert updated is None
    assert error is PausedSearchReviewError.POLICY_ACTION_NOT_ALLOWED
