from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads import (
    LeadRoutingReview,
    LeadRoutingReviewResolution,
    LeadRoutingReviewStatus,
)
from app.infrastructure.persistence.postgres.models import LeadRoutingReviewModel


class PostgresLeadRoutingReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> LeadRoutingReview | None:
        result = await self._session.execute(
            select(LeadRoutingReviewModel)
            .where(LeadRoutingReviewModel.workspace_id == workspace_id)
            .where(LeadRoutingReviewModel.review_id == review_id)
        )
        model = result.scalar_one_or_none()
        return _review_from_model(model) if model is not None else None

    async def get_by_artifact_id(
        self,
        workspace_id: WorkspaceId,
        artifact_id: UUID,
    ) -> LeadRoutingReview | None:
        result = await self._session.execute(
            select(LeadRoutingReviewModel)
            .where(LeadRoutingReviewModel.workspace_id == workspace_id)
            .where(LeadRoutingReviewModel.artifact_id == artifact_id)
        )
        model = result.scalar_one_or_none()
        return _review_from_model(model) if model is not None else None

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[LeadRoutingReview, ...]:
        result = await self._session.execute(
            select(LeadRoutingReviewModel)
            .where(LeadRoutingReviewModel.workspace_id == workspace_id)
            .where(LeadRoutingReviewModel.lead_id == lead_id)
            .order_by(
                LeadRoutingReviewModel.created_at.desc(),
                LeadRoutingReviewModel.review_id.desc(),
            )
            .limit(limit)
        )
        return tuple(_review_from_model(model) for model in result.scalars().all())

    async def list_pending_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[LeadRoutingReview, ...]:
        result = await self._session.execute(
            select(LeadRoutingReviewModel)
            .where(LeadRoutingReviewModel.workspace_id == workspace_id)
            .where(LeadRoutingReviewModel.status == LeadRoutingReviewStatus.PENDING.value)
            .order_by(
                LeadRoutingReviewModel.created_at.asc(),
                LeadRoutingReviewModel.review_id.asc(),
            )
            .limit(limit)
        )
        return tuple(_review_from_model(model) for model in result.scalars().all())

    async def save(self, review: LeadRoutingReview) -> LeadRoutingReview:
        values = _review_to_values(review)
        update_values = {
            key: value for key, value in values.items() if key not in {"review_id", "created_at"}
        }
        result = await self._session.execute(
            insert(LeadRoutingReviewModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "artifact_id"],
                set_=update_values,
            )
            .returning(LeadRoutingReviewModel)
        )
        return _review_from_model(result.scalar_one())


def _review_from_model(model: LeadRoutingReviewModel) -> LeadRoutingReview:
    return LeadRoutingReview(
        review_id=model.review_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        artifact_id=model.artifact_id,
        status=LeadRoutingReviewStatus(model.status),
        reason_codes=tuple(model.reason_codes),
        resolution=(LeadRoutingReviewResolution(model.resolution) if model.resolution else None),
        reviewed_by_user_id=model.reviewed_by_user_id,
        reviewed_at=model.reviewed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _review_to_values(review: LeadRoutingReview) -> dict[str, object | None]:
    return {
        "review_id": review.review_id,
        "workspace_id": review.workspace_id,
        "lead_id": review.lead_id,
        "artifact_id": review.artifact_id,
        "status": review.status.value,
        "reason_codes": list(review.reason_codes),
        "resolution": review.resolution.value if review.resolution is not None else None,
        "reviewed_by_user_id": review.reviewed_by_user_id,
        "reviewed_at": review.reviewed_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }
