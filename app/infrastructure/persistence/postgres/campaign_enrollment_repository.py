from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.infrastructure.persistence.postgres.workflow_models import CampaignEnrollmentModel


class PostgresCampaignEnrollmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_lead_and_campaign(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_id: CampaignId,
    ) -> CampaignEnrollment | None:
        result = await self._session.execute(
            _by_lead_and_campaign_statement(workspace_id, lead_id, campaign_id),
        )
        model = result.scalar_one_or_none()
        return _model_to_enrollment(model) if model is not None else None

    async def count_started_today(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        now: datetime,
    ) -> int:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        result = await self._session.execute(
            select(func.count())
            .select_from(CampaignEnrollmentModel)
            .where(CampaignEnrollmentModel.workspace_id == workspace_id)
            .where(CampaignEnrollmentModel.campaign_id == campaign_id)
            .where(CampaignEnrollmentModel.started_at >= today_start)
            .where(CampaignEnrollmentModel.started_at < tomorrow_start),
        )
        return result.scalar() or 0

    async def save(self, enrollment: CampaignEnrollment) -> CampaignEnrollment:
        now = datetime.now(UTC)
        values = _enrollment_to_values(enrollment, created_at=now, updated_at=now)
        update_values = {
            key: value for key, value in values.items() if key != "campaign_enrollment_id"
        }
        update_values["updated_at"] = now
        statement = (
            insert(CampaignEnrollmentModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "campaign_id", "lead_id"],
                index_where=text(
                    "status IN ('candidate', 'queued', 'active', 'paused', 'handoff')",
                ),
                set_=update_values,
            )
            .returning(CampaignEnrollmentModel)
        )
        result = await self._session.execute(statement)
        return _model_to_enrollment(result.scalar_one())


def _by_lead_and_campaign_statement(
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
) -> Select[tuple[CampaignEnrollmentModel]]:
    return (
        select(CampaignEnrollmentModel)
        .where(CampaignEnrollmentModel.workspace_id == workspace_id)
        .where(CampaignEnrollmentModel.lead_id == lead_id)
        .where(CampaignEnrollmentModel.campaign_id == campaign_id)
    )


def _enrollment_to_values(
    enrollment: CampaignEnrollment,
    *,
    created_at: datetime,
    updated_at: datetime,
) -> dict[str, object]:
    return {
        "campaign_enrollment_id": enrollment.campaign_enrollment_id,
        "workspace_id": enrollment.workspace_id,
        "campaign_id": enrollment.campaign_id,
        "campaign_version_id": enrollment.campaign_version_id,
        "lead_id": enrollment.lead_id,
        "source": enrollment.source.value,
        "status": enrollment.status.value,
        "eligible_at": enrollment.eligible_at,
        "enrolled_at": enrollment.enrolled_at,
        "started_at": enrollment.started_at,
        "ended_at": enrollment.ended_at,
        "created_by_user_id": enrollment.created_by_user_id,
        "reason_codes": list(enrollment.reason_codes),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _model_to_enrollment(model: CampaignEnrollmentModel) -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=model.campaign_enrollment_id,
        workspace_id=model.workspace_id,
        campaign_id=model.campaign_id,
        campaign_version_id=model.campaign_version_id,
        lead_id=model.lead_id,
        source=CampaignEnrollmentSource(model.source),
        status=CampaignEnrollmentStatus(model.status),
        eligible_at=model.eligible_at,
        enrolled_at=model.enrolled_at,
        started_at=model.started_at,
        ended_at=model.ended_at,
        created_by_user_id=model.created_by_user_id,
        reason_codes=tuple(model.reason_codes),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
