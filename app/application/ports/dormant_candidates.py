from datetime import datetime
from typing import Protocol

from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.leads import CanonicalLeadRecord


class DormantCandidateSelector(Protocol):
    async def select_candidates(
        self,
        *,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        threshold_days: int,
        limit: int,
        now: datetime,
    ) -> tuple[CanonicalLeadRecord, ...]:
        raise NotImplementedError
