from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.repositories import LeadRoutingReviewRepository
from app.domain.common.ids import LeadId, UserId, WorkspaceId
from app.domain.leads import (
    LeadClassificationArtifact,
    LeadRoutingReview,
    LeadRoutingReviewResolution,
    LeadRoutingReviewStatus,
)


async def create_or_refresh_pending_routing_review(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    artifact: LeadClassificationArtifact,
    reason_codes: tuple[str, ...],
    routing_review_repository: LeadRoutingReviewRepository,
    now: datetime,
) -> LeadRoutingReview:
    existing = await routing_review_repository.get_by_artifact_id(
        workspace_id,
        artifact.artifact_id,
    )
    review = (
        replace(
            existing,
            status=LeadRoutingReviewStatus.PENDING,
            reason_codes=reason_codes,
            resolution=None,
            reviewed_by_user_id=None,
            reviewed_at=None,
            updated_at=now,
        )
        if existing is not None
        else LeadRoutingReview(
            review_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            artifact_id=artifact.artifact_id,
            status=LeadRoutingReviewStatus.PENDING,
            reason_codes=reason_codes,
            created_at=now,
            updated_at=now,
        )
    )
    await supersede_pending_routing_reviews_for_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        routing_review_repository=routing_review_repository,
        now=now,
        excluding_review_id=review.review_id,
    )
    return await routing_review_repository.save(review)


async def supersede_pending_routing_reviews_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    routing_review_repository: LeadRoutingReviewRepository,
    now: datetime,
    excluding_review_id: UUID | None = None,
) -> None:
    existing_reviews = await routing_review_repository.list_for_lead(workspace_id, lead_id)
    for review in existing_reviews:
        if review.status != LeadRoutingReviewStatus.PENDING:
            continue
        if excluding_review_id is not None and review.review_id == excluding_review_id:
            continue
        await routing_review_repository.save(
            replace(
                review,
                status=LeadRoutingReviewStatus.SUPERSEDED,
                updated_at=now,
            )
        )


async def resolve_pending_routing_reviews_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    resolution: LeadRoutingReviewResolution,
    reviewed_by_user_id: UserId,
    routing_review_repository: LeadRoutingReviewRepository,
    now: datetime,
) -> None:
    existing_reviews = await routing_review_repository.list_for_lead(workspace_id, lead_id)
    for review in existing_reviews:
        if review.status != LeadRoutingReviewStatus.PENDING:
            continue
        await routing_review_repository.save(
            replace(
                review,
                status=LeadRoutingReviewStatus.RESOLVED,
                resolution=resolution,
                reviewed_by_user_id=reviewed_by_user_id,
                reviewed_at=now,
                updated_at=now,
            )
        )