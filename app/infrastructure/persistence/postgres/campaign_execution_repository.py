from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.execution import (
    CampaignCadenceStep,
    CampaignExecutionConfig,
    CampaignVersionStatus,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import (
    CampaignCadenceStepModel,
    CampaignModel,
    CampaignVersionModel,
)


class PostgresCampaignExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_version_id(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
    ) -> CampaignExecutionConfig | None:
        version_result = await self._session.execute(
            _version_statement(workspace_id=workspace_id, campaign_version_id=campaign_version_id)
        )
        row = version_result.one_or_none()
        if row is None:
            return None

        version, campaign = row
        return await self._build_config(version=version, campaign=campaign)

    async def get_active_for_campaign(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignExecutionConfig | None:
        campaign_result = await self._session.execute(
            select(CampaignModel)
            .where(CampaignModel.workspace_id == workspace_id)
            .where(CampaignModel.campaign_id == campaign_id)
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign is None or campaign.active_version_id is None:
            return None
        return await self.get_by_version_id(
            workspace_id=workspace_id,
            campaign_version_id=campaign.active_version_id,
        )

    async def _build_config(
        self,
        *,
        version: CampaignVersionModel,
        campaign: CampaignModel,
        steps: tuple[CampaignCadenceStep, ...] | None = None,
    ) -> CampaignExecutionConfig:
        if steps is None:
            steps_result = await self._session.execute(
                _steps_statement(
                    workspace_id=version.workspace_id,
                    campaign_version_id=version.campaign_version_id,
                )
            )
            steps = tuple(_model_to_step(model) for model in steps_result.scalars().all())
        return CampaignExecutionConfig(
            campaign_id=campaign.campaign_id,
            campaign_version_id=version.campaign_version_id,
            workspace_id=version.workspace_id,
            campaign_name=campaign.name,
            campaign_status=_campaign_status(campaign.status),
            version_status=CampaignVersionStatus(version.status),
            enabled_channels=tuple(ContactChannel(channel) for channel in version.enabled_channels),
            daily_start_cap=version.daily_start_cap,
            dormant_threshold_days=version.dormant_threshold_days,
            quiet_hours_start=version.quiet_hours_start,
            quiet_hours_end=version.quiet_hours_end,
            timezone=version.timezone,
            sms_compliance_required=version.sms_compliance_required,
            preflight_digest_enabled=version.preflight_digest_enabled,
            prompt_version=version.prompt_version,
            approved_model=version.approved_model,
            cadence_steps=steps,
            created_at=version.created_at,
            published_at=version.published_at,
        )


def _version_statement(
    *,
    workspace_id: WorkspaceId,
    campaign_version_id: CampaignVersionId,
) -> Select[tuple[CampaignVersionModel, CampaignModel]]:
    return (
        select(CampaignVersionModel, CampaignModel)
        .join(CampaignModel, CampaignModel.campaign_id == CampaignVersionModel.campaign_id)
        .where(CampaignVersionModel.workspace_id == workspace_id)
        .where(CampaignVersionModel.campaign_version_id == campaign_version_id)
        .where(CampaignModel.workspace_id == workspace_id)
    )


def _steps_statement(
    *,
    workspace_id: WorkspaceId,
    campaign_version_id: CampaignVersionId,
) -> Select[tuple[CampaignCadenceStepModel]]:
    return (
        select(CampaignCadenceStepModel)
        .where(CampaignCadenceStepModel.workspace_id == workspace_id)
        .where(CampaignCadenceStepModel.campaign_version_id == campaign_version_id)
        .order_by(CampaignCadenceStepModel.step_order.asc())
    )


def _model_to_step(model: CampaignCadenceStepModel) -> CampaignCadenceStep:
    return CampaignCadenceStep(
        cadence_step_id=model.cadence_step_id,
        workspace_id=model.workspace_id,
        campaign_version_id=model.campaign_version_id,
        step_order=model.step_order,
        channel=ContactChannel(model.channel),
        delay_hours=model.delay_hours,
        message_goal=model.message_goal,
        template_key=model.template_key,
        max_attempts=model.max_attempts,
        created_at=model.created_at,
    )


def _campaign_status(raw_status: str) -> CampaignStatus:
    if raw_status == "archived":
        return CampaignStatus.INACTIVE
    return CampaignStatus(raw_status)
