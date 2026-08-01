from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.repositories import (
    PausedSearchOccurrenceRepository,
    PausedSearchReviewRepository,
)
from app.application.use_cases.paused_search_message_review import (
    PausedSearchMessageReviewGateStatus,
    gate_paused_search_message_for_review,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewStatus,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.compliance.contactability import ContactChannel

NOW = datetime(2026, 7, 30, 16, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("10000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("10000000-0000-0000-0000-000000000003")
OCCURRENCE_ID = UUID("10000000-0000-0000-0000-000000000004")
MESSAGE_ID = UUID("10000000-0000-0000-0000-000000000005")


async def test_gate_creates_one_review_and_holds_occurrence() -> None:
    occurrence_repository = _OccurrenceRepository(_occurrence())
    review_repository = _ReviewRepository()

    result = await gate_paused_search_message_for_review(
        review_required=True,
        occurrence=occurrence_repository.occurrence,
        message=_message(),
        review_repository=cast(PausedSearchReviewRepository, review_repository),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        now=NOW,
    )
    duplicate = await gate_paused_search_message_for_review(
        review_required=True,
        occurrence=occurrence_repository.occurrence,
        message=_message(),
        review_repository=cast(PausedSearchReviewRepository, review_repository),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        now=NOW + timedelta(minutes=1),
    )

    assert result.status is PausedSearchMessageReviewGateStatus.REVIEW_REQUESTED
    assert duplicate.status is PausedSearchMessageReviewGateStatus.REVIEW_REQUESTED
    assert len(review_repository.created) == 1
    assert review_repository.review is not None
    assert review_repository.review.outbound_message_id == MESSAGE_ID
    assert occurrence_repository.occurrence.status is RecurringOccurrenceStatus.REVIEW_REQUESTED


async def test_gate_allows_only_the_exact_approved_message_version() -> None:
    occurrence_repository = _OccurrenceRepository(_occurrence())
    review_repository = _ReviewRepository()
    await gate_paused_search_message_for_review(
        review_required=True,
        occurrence=occurrence_repository.occurrence,
        message=_message(),
        review_repository=cast(PausedSearchReviewRepository, review_repository),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        now=NOW,
    )
    assert review_repository.review is not None
    review_repository.review = replace(
        review_repository.review,
        status=PausedSearchReviewStatus.APPROVED,
    )
    approved_occurrence = replace(
        occurrence_repository.occurrence,
        status=RecurringOccurrenceStatus.APPROVED,
    )

    allowed = await gate_paused_search_message_for_review(
        review_required=True,
        occurrence=approved_occurrence,
        message=_message(),
        review_repository=cast(PausedSearchReviewRepository, review_repository),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        now=NOW,
    )
    blocked = await gate_paused_search_message_for_review(
        review_required=True,
        occurrence=approved_occurrence,
        message=replace(_message(), message_id=UUID(int=99), message_version=2),
        review_repository=cast(PausedSearchReviewRepository, review_repository),
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repository),
        now=NOW,
    )

    assert allowed.status is PausedSearchMessageReviewGateStatus.ALLOWED
    assert blocked.status is PausedSearchMessageReviewGateStatus.BLOCKED


def _occurrence() -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=OCCURRENCE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=UUID("10000000-0000-0000-0000-000000000006"),
        step_id=UUID("10000000-0000-0000-0000-000000000007"),
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=1,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.PLANNED,
        idempotency_key="occurrence-1",
        created_at=NOW,
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("10000000-0000-0000-0000-000000000008"),
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="message-1",
        body="Draft for review",
        created_at=NOW,
        updated_at=NOW,
    )


class _ReviewRepository:
    def __init__(self) -> None:
        self.review: PausedSearchReview | None = None
        self.created: list[PausedSearchReview] = []

    async def get_by_occurrence(
        self, workspace_id: UUID, occurrence_id: UUID, kind: str
    ) -> PausedSearchReview | None:
        return self.review

    async def create_or_get(self, review: PausedSearchReview) -> PausedSearchReview:
        if self.review is None:
            self.review = review
            self.created.append(review)
        return self.review


class _OccurrenceRepository:
    def __init__(self, occurrence: RecurringOccurrence) -> None:
        self.occurrence = occurrence

    async def update_status(
        self,
        *,
        workspace_id: UUID,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        **kwargs: object,
    ) -> RecurringOccurrence:
        self.occurrence = replace(
            self.occurrence,
            status=RecurringOccurrenceStatus(status),
        )
        return self.occurrence