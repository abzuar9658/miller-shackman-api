from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.rejected_draft_review import (
    RejectedDraftReview,
    RejectedDraftReviewStatus,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.workflow_models import RejectedDraftReviewModel


class PostgresRejectedDraftReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        result = await self._session.execute(
            select(RejectedDraftReviewModel)
            .where(RejectedDraftReviewModel.workspace_id == workspace_id)
            .where(RejectedDraftReviewModel.review_id == review_id)
        )
        model = result.scalar_one_or_none()
        return _review_from_model(model) if model is not None else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        result = await self._session.execute(
            select(RejectedDraftReviewModel)
            .where(RejectedDraftReviewModel.workspace_id == workspace_id)
            .where(RejectedDraftReviewModel.review_id == review_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _review_from_model(model) if model is not None else None

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[RejectedDraftReview, ...]:
        result = await self._session.execute(
            select(RejectedDraftReviewModel)
            .where(RejectedDraftReviewModel.workspace_id == workspace_id)
            .where(RejectedDraftReviewModel.lead_id == lead_id)
            .order_by(
                RejectedDraftReviewModel.created_at.desc(),
                RejectedDraftReviewModel.review_id.desc(),
            )
            .limit(limit)
        )
        return tuple(_review_from_model(model) for model in result.scalars().all())

    async def save(self, review: RejectedDraftReview) -> RejectedDraftReview:
        values = _review_to_values(review)
        update_values = {key: value for key, value in values.items() if key != "review_id"}
        result = await self._session.execute(
            insert(RejectedDraftReviewModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["review_id"], set_=update_values)
            .returning(RejectedDraftReviewModel)
        )
        return _review_from_model(result.scalar_one())


def _review_from_model(model: RejectedDraftReviewModel) -> RejectedDraftReview:
    return RejectedDraftReview(
        review_id=model.review_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        workflow_transition_id=model.workflow_transition_id,
        campaign_id=model.campaign_id,
        campaign_version_id=model.campaign_version_id,
        cadence_step_id=model.cadence_step_id,
        channel=ContactChannel(model.channel),
        status=RejectedDraftReviewStatus(model.status),
        reason_codes=tuple(model.reason_codes),
        draft_reason_codes=tuple(model.draft_reason_codes),
        review_blockers=tuple(model.review_blockers),
        draft_safety_flags=tuple(model.draft_safety_flags),
        draft_personalization_notes=tuple(model.draft_personalization_notes),
        draft_body=model.draft_body,
        draft_subject=model.draft_subject,
        raw_llm_response_text=model.raw_llm_response_text,
        validation_error=model.validation_error,
        explanation=model.explanation,
        draft_confidence=model.draft_confidence,
        draft_model=model.draft_model,
        draft_prompt_version=model.draft_prompt_version,
        draft_latency_ms=model.draft_latency_ms,
        draft_usage_tokens=model.draft_usage_tokens,
        message_version=model.message_version,
        can_approve_send=model.can_approve_send,
        reviewed_by_user_id=model.reviewed_by_user_id,
        reviewed_at=model.reviewed_at,
        review_note=model.review_note,
        outbound_message_id=model.outbound_message_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _review_to_values(review: RejectedDraftReview) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "workspace_id": review.workspace_id,
        "lead_id": review.lead_id,
        "workflow_id": review.workflow_id,
        "workflow_transition_id": review.workflow_transition_id,
        "campaign_id": review.campaign_id,
        "campaign_version_id": review.campaign_version_id,
        "cadence_step_id": review.cadence_step_id,
        "channel": review.channel.value,
        "status": review.status.value,
        "reason_codes": list(review.reason_codes),
        "draft_reason_codes": list(review.draft_reason_codes),
        "review_blockers": list(review.review_blockers),
        "draft_safety_flags": list(review.draft_safety_flags),
        "draft_personalization_notes": list(review.draft_personalization_notes),
        "draft_body": review.draft_body,
        "draft_subject": review.draft_subject,
        "raw_llm_response_text": review.raw_llm_response_text,
        "validation_error": review.validation_error,
        "explanation": review.explanation,
        "draft_confidence": review.draft_confidence,
        "draft_model": review.draft_model,
        "draft_prompt_version": review.draft_prompt_version,
        "draft_latency_ms": review.draft_latency_ms,
        "draft_usage_tokens": review.draft_usage_tokens,
        "message_version": review.message_version,
        "can_approve_send": review.can_approve_send,
        "reviewed_by_user_id": review.reviewed_by_user_id,
        "reviewed_at": review.reviewed_at,
        "review_note": review.review_note,
        "outbound_message_id": review.outbound_message_id,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }
