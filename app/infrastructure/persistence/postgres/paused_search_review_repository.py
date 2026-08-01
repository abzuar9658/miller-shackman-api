from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import PausedSearchReviewModel


class PostgresPausedSearchReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[PausedSearchReview, ...]:
        statement = (
            select(PausedSearchReviewModel)
            .where(PausedSearchReviewModel.workspace_id == workspace_id)
            .order_by(
                PausedSearchReviewModel.requested_at.asc(),
                PausedSearchReviewModel.review_id.asc(),
            )
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(PausedSearchReviewModel.status == status)
        result = await self._session.execute(statement)
        return tuple(_from_model(model) for model in result.scalars().all())

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> PausedSearchReview | None:
        result = await self._session.execute(
            select(PausedSearchReviewModel).where(
                PausedSearchReviewModel.workspace_id == workspace_id,
                PausedSearchReviewModel.review_id == review_id,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> PausedSearchReview | None:
        result = await self._session.execute(
            select(PausedSearchReviewModel)
            .where(
                PausedSearchReviewModel.workspace_id == workspace_id,
                PausedSearchReviewModel.review_id == review_id,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_by_occurrence(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        kind: str,
    ) -> PausedSearchReview | None:
        result = await self._session.execute(
            select(PausedSearchReviewModel).where(
                PausedSearchReviewModel.workspace_id == workspace_id,
                PausedSearchReviewModel.occurrence_id == occurrence_id,
                PausedSearchReviewModel.kind == kind,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def create_or_get(self, review: PausedSearchReview) -> PausedSearchReview:
        await self._session.execute(
            insert(PausedSearchReviewModel)
            .values(**_to_values(review))
            .on_conflict_do_nothing(
                constraint="uq_paused_search_reviews_workspace_occurrence_kind"
            )
        )
        assert review.occurrence_id is not None
        saved = await self.get_by_occurrence(
            review.workspace_id,
            review.occurrence_id,
            review.kind.value,
        )
        assert saved is not None
        return saved

    async def save(self, review: PausedSearchReview) -> PausedSearchReview:
        values = _to_values(review)
        await self._session.execute(
            insert(PausedSearchReviewModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["review_id"],
                set_={key: value for key, value in values.items() if key != "review_id"},
            )
        )
        saved = await self.get_by_id(review.workspace_id, review.review_id)
        assert saved is not None
        return saved


def _to_values(review: PausedSearchReview) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "workspace_id": review.workspace_id,
        "lead_id": review.lead_id,
        "workflow_id": review.workflow_id,
        "occurrence_id": review.occurrence_id,
        "kind": review.kind.value,
        "status": review.status.value,
        "reason": review.reason,
        "requested_at": review.requested_at,
        "review_expiry_at": review.review_expiry_at,
        "reviewer_user_id": review.reviewer_user_id,
        "acted_at": review.acted_at,
        "action_reason": review.action_reason,
        "outbound_message_id": review.outbound_message_id,
        "outbound_message_version": review.outbound_message_version,
    }


def _from_model(model: PausedSearchReviewModel) -> PausedSearchReview:
    return PausedSearchReview(
        review_id=model.review_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        occurrence_id=model.occurrence_id,
        kind=PausedSearchReviewKind(model.kind),
        status=PausedSearchReviewStatus(model.status),
        reason=model.reason,
        requested_at=model.requested_at,
        review_expiry_at=model.review_expiry_at,
        reviewer_user_id=model.reviewer_user_id,
        acted_at=model.acted_at,
        action_reason=model.action_reason,
        outbound_message_id=model.outbound_message_id,
        outbound_message_version=model.outbound_message_version,
    )
