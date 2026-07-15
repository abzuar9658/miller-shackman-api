from typing import Protocol
from uuid import UUID

from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.common.ids import LeadId, WorkspaceId


class RejectedDraftReviewRepository(Protocol):
    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        raise NotImplementedError

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        review_id: UUID,
    ) -> RejectedDraftReview | None:
        raise NotImplementedError

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 20,
    ) -> tuple[RejectedDraftReview, ...]:
        raise NotImplementedError

    async def save(self, review: RejectedDraftReview) -> RejectedDraftReview:
        raise NotImplementedError