from dataclasses import dataclass
from enum import StrEnum

from app.application.ports.lead_read import (
    LeadReadClassificationArtifactRepository,
    LeadReadLeadRepository,
)
from app.application.ports.repositories import LeadRoutingReviewRepository
from app.domain.common.ids import WorkspaceId
from app.domain.identity import AuthenticatedActor
from app.domain.identity.permissions import (
    PermissionCapability,
    PermissionReasonCode,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord, LeadClassificationArtifact, LeadRoutingReview


class ReviewQueueReadStatus(StrEnum):
    OK = "ok"
    REJECTED = "rejected"


class ReviewQueueReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"


@dataclass(frozen=True)
class PendingRoutingReviewView:
    review: LeadRoutingReview
    lead: CanonicalLeadRecord
    artifact: LeadClassificationArtifact


@dataclass(frozen=True)
class PendingRoutingReviewListResult:
    status: ReviewQueueReadStatus
    views: tuple[PendingRoutingReviewView, ...] = ()
    reasons: tuple[ReviewQueueReadReasonCode, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


async def list_pending_routing_reviews(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_repository: LeadReadLeadRepository,
    artifact_repository: LeadReadClassificationArtifactRepository,
    routing_review_repository: LeadRoutingReviewRepository,
    limit: int = 100,
) -> PendingRoutingReviewListResult:
    decision = evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING)
    if not decision.allowed:
        return PendingRoutingReviewListResult(
            status=ReviewQueueReadStatus.REJECTED,
            reasons=(ReviewQueueReadReasonCode.PERMISSION_DENIED,),
            permission_reasons=decision.reasons,
        )

    reviews = await routing_review_repository.list_pending_for_workspace(workspace_id, limit=limit)
    views: list[PendingRoutingReviewView] = []
    for review in reviews:
        lead = await lead_repository.get_by_id(workspace_id, review.lead_id)
        artifact = await artifact_repository.get_by_id(workspace_id, review.artifact_id)
        if lead is None or artifact is None:
            continue
        views.append(PendingRoutingReviewView(review=review, lead=lead, artifact=artifact))
    return PendingRoutingReviewListResult(status=ReviewQueueReadStatus.OK, views=tuple(views))