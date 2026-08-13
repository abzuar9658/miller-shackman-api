from datetime import datetime, timedelta

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.leads.canonical import ActivityReliability
from app.infrastructure.persistence.postgres.lead_repository import _model_to_record
from app.infrastructure.persistence.postgres.models import (
    LeadModel,
    PausedSearchTrackAssignmentModel,
)
from app.infrastructure.persistence.postgres.workflow_models import (
    CampaignEnrollmentModel,
    LeadWorkflowModel,
)


class PostgresDormantCandidateSelector(DormantCandidateSelector):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def select_candidates(
        self,
        *,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        threshold_days: int,
        limit: int,
        now: datetime,
    ) -> tuple[CanonicalLeadRecord, ...]:
        result = await self._session.execute(
            _select_candidates_statement(
                workspace_id=workspace_id,
                campaign_id=campaign_id,
                threshold_days=threshold_days,
                limit=limit,
                now=now,
            ),
        )
        return tuple(
            _model_to_record(model)
            for model in result.scalars().all()
            if _model_has_reliable_crm_provider(model)
        )


def _model_has_reliable_crm_provider(model: LeadModel) -> bool:
    try:
        CRMProvider(model.crm_provider)
    except ValueError:
        return False
    return True


def _select_candidates_statement(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    threshold_days: int,
    limit: int,
    now: datetime,
) -> Select[tuple[LeadModel]]:
    cutoff = now - timedelta(days=threshold_days)
    already_enrolled = (
        select(CampaignEnrollmentModel)
        .where(
            CampaignEnrollmentModel.workspace_id == workspace_id,
            CampaignEnrollmentModel.campaign_id == campaign_id,
            CampaignEnrollmentModel.lead_id == LeadModel.lead_id,
        )
        .correlate(LeadModel)
    )
    has_any_workflow = (
        select(LeadWorkflowModel)
        .where(
            LeadWorkflowModel.workspace_id == workspace_id,
            LeadWorkflowModel.lead_id == LeadModel.lead_id,
        )
        .correlate(LeadModel)
    )
    has_active_paused_search_assignment = (
        select(PausedSearchTrackAssignmentModel)
        .where(
            PausedSearchTrackAssignmentModel.workspace_id == workspace_id,
            PausedSearchTrackAssignmentModel.lead_id == LeadModel.lead_id,
            PausedSearchTrackAssignmentModel.released_at.is_(None),
        )
        .correlate(LeadModel)
    )
    return (
        select(LeadModel)
        .where(
            LeadModel.workspace_id == workspace_id,
            LeadModel.activity_reliability == ActivityReliability.RELIABLE.value,
            LeadModel.last_meaningful_communication_at.is_not(None),
            LeadModel.last_meaningful_communication_at <= cutoff,
            LeadModel.paused_search_active.is_(False),
            ~exists(already_enrolled),
            ~exists(has_any_workflow),
            ~exists(has_active_paused_search_assignment),
        )
        .order_by(LeadModel.last_meaningful_communication_at.asc())
        .limit(limit)
    )
