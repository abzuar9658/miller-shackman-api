from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.repositories import (
    PausedSearchOccurrenceRepository,
    PausedSearchReviewRepository,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
)


class PausedSearchMessageReviewGateStatus(StrEnum):
    ALLOWED = "allowed"
    REVIEW_REQUESTED = "review_requested"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PausedSearchMessageReviewGateResult:
    status: PausedSearchMessageReviewGateStatus
    review: PausedSearchReview | None = None
    occurrence: RecurringOccurrence | None = None
    reason: str | None = None


async def gate_paused_search_message_for_review(
    *,
    review_required: bool,
    occurrence: RecurringOccurrence,
    message: OutboundMessage,
    review_repository: PausedSearchReviewRepository,
    occurrence_repository: PausedSearchOccurrenceRepository,
    now: datetime,
) -> PausedSearchMessageReviewGateResult:
    if not review_required:
        return PausedSearchMessageReviewGateResult(
            status=PausedSearchMessageReviewGateStatus.ALLOWED,
            occurrence=occurrence,
        )

    review = await review_repository.get_by_occurrence(
        occurrence.workspace_id,
        occurrence.occurrence_id,
        PausedSearchReviewKind.MESSAGE.value,
    )
    if occurrence.status is RecurringOccurrenceStatus.APPROVED:
        if (
            review is not None
            and review.status is PausedSearchReviewStatus.APPROVED
            and review.outbound_message_id == message.message_id
            and review.outbound_message_version == message.message_version
        ):
            return PausedSearchMessageReviewGateResult(
                status=PausedSearchMessageReviewGateStatus.ALLOWED,
                review=review,
                occurrence=occurrence,
            )
        return PausedSearchMessageReviewGateResult(
            status=PausedSearchMessageReviewGateStatus.BLOCKED,
            review=review,
            occurrence=occurrence,
            reason="Approved occurrence does not reference the current approved message version.",
        )

    if review is None:
        review = await review_repository.create_or_get(
            PausedSearchReview(
                review_id=uuid4(),
                workspace_id=occurrence.workspace_id,
                lead_id=occurrence.lead_id,
                workflow_id=occurrence.workflow_id,
                occurrence_id=occurrence.occurrence_id,
                kind=PausedSearchReviewKind.MESSAGE,
                status=PausedSearchReviewStatus.PENDING,
                reason="Paused-search track step requires message review.",
                requested_at=now,
                outbound_message_id=message.message_id,
                outbound_message_version=message.message_version,
            )
        )

    if review.status is not PausedSearchReviewStatus.PENDING:
        return PausedSearchMessageReviewGateResult(
            status=PausedSearchMessageReviewGateStatus.BLOCKED,
            review=review,
            occurrence=occurrence,
            reason=f"Message review is already {review.status.value}.",
        )
    if (
        review.outbound_message_id != message.message_id
        or review.outbound_message_version != message.message_version
    ):
        return PausedSearchMessageReviewGateResult(
            status=PausedSearchMessageReviewGateStatus.BLOCKED,
            review=review,
            occurrence=occurrence,
            reason="Pending review references a different message version.",
        )

    updated_occurrence = occurrence
    if occurrence.status is not RecurringOccurrenceStatus.REVIEW_REQUESTED:
        updated = await occurrence_repository.update_status(
            workspace_id=occurrence.workspace_id,
            occurrence_id=occurrence.occurrence_id,
            status=RecurringOccurrenceStatus.REVIEW_REQUESTED.value,
            now=now,
        )
        if updated is None:
            return PausedSearchMessageReviewGateResult(
                status=PausedSearchMessageReviewGateStatus.BLOCKED,
                review=review,
                occurrence=occurrence,
                reason="Occurrence could not enter review-requested state.",
            )
        updated_occurrence = updated

    return PausedSearchMessageReviewGateResult(
        status=PausedSearchMessageReviewGateStatus.REVIEW_REQUESTED,
        review=review,
        occurrence=updated_occurrence,
    )