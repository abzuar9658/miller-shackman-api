from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.admin import (
    CampaignAdminAuditAction,
    CampaignAdminAuditLog,
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.outbound_drafting import (
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
    dormant_step_template_profile_from_mapping,
    dormant_step_template_profile_to_mapping,
)
from app.infrastructure.persistence.postgres.models import (
    CampaignAdminAuditLogModel,
    CampaignCadenceStepModel,
    CampaignModel,
    CampaignVersionModel,
)


class PostgresCampaignAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_campaigns(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[CampaignAdminCampaign, ...]:
        result = await self._session.execute(
            select(CampaignModel)
            .where(CampaignModel.workspace_id == workspace_id)
            .order_by(CampaignModel.updated_at.desc(), CampaignModel.name.asc()),
        )
        return tuple(_campaign_from_model(model) for model in result.scalars().all())

    async def get_campaign(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminCampaign | None:
        result = await self._session.execute(
            select(CampaignModel)
            .where(CampaignModel.workspace_id == workspace_id)
            .where(CampaignModel.campaign_id == campaign_id),
        )
        model = result.scalar_one_or_none()
        return _campaign_from_model(model) if model is not None else None

    async def get_campaign_by_name(
        self,
        workspace_id: WorkspaceId,
        name: str,
    ) -> CampaignAdminCampaign | None:
        result = await self._session.execute(
            select(CampaignModel)
            .where(CampaignModel.workspace_id == workspace_id)
            .where(CampaignModel.name == name),
        )
        model = result.scalar_one_or_none()
        return _campaign_from_model(model) if model is not None else None

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
    ) -> CampaignAdminVersion | None:
        result = await self._session.execute(
            select(CampaignVersionModel)
            .where(CampaignVersionModel.workspace_id == workspace_id)
            .where(CampaignVersionModel.campaign_version_id == campaign_version_id),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminVersion | None:
        result = await self._session.execute(
            select(CampaignVersionModel)
            .where(CampaignVersionModel.workspace_id == workspace_id)
            .where(CampaignVersionModel.campaign_id == campaign_id)
            .where(CampaignVersionModel.status == CampaignVersionStatus.DRAFT.value)
            .order_by(CampaignVersionModel.version_number.desc())
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> CampaignAdminVersion | None:
        result = await self._session.execute(
            select(CampaignVersionModel)
            .where(CampaignVersionModel.workspace_id == workspace_id)
            .where(CampaignVersionModel.campaign_id == campaign_id)
            .order_by(CampaignVersionModel.version_number.desc())
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _version_from_model(model) if model is not None else None

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
    ) -> int:
        result = await self._session.execute(
            select(func.max(CampaignVersionModel.version_number))
            .where(CampaignVersionModel.workspace_id == workspace_id)
            .where(CampaignVersionModel.campaign_id == campaign_id),
        )
        value = result.scalar()
        return int(value or 0)

    async def get_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
    ) -> tuple[CampaignAdminCadenceStep, ...]:
        result = await self._session.execute(
            select(CampaignCadenceStepModel)
            .where(CampaignCadenceStepModel.workspace_id == workspace_id)
            .where(CampaignCadenceStepModel.campaign_version_id == campaign_version_id)
            .order_by(CampaignCadenceStepModel.step_order.asc()),
        )
        return tuple(_step_from_model(model) for model in result.scalars().all())

    async def save_campaign(self, campaign: CampaignAdminCampaign) -> CampaignAdminCampaign:
        values = _campaign_to_values(campaign)
        update_values = {key: value for key, value in values.items() if key != "campaign_id"}
        result = await self._session.execute(
            insert(CampaignModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["campaign_id"], set_=update_values)
            .returning(CampaignModel),
        )
        return _campaign_from_model(result.scalar_one())

    async def save_version(self, version: CampaignAdminVersion) -> CampaignAdminVersion:
        values = _version_to_values(version)
        update_values = {
            key: value for key, value in values.items() if key != "campaign_version_id"
        }
        result = await self._session.execute(
            insert(CampaignVersionModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["campaign_version_id"],
                set_=update_values,
            )
            .returning(CampaignVersionModel),
        )
        return _version_from_model(result.scalar_one())

    async def replace_cadence_steps(
        self,
        workspace_id: WorkspaceId,
        campaign_version_id: CampaignVersionId,
        steps: tuple[CampaignAdminCadenceStep, ...],
    ) -> tuple[CampaignAdminCadenceStep, ...]:
        await self._session.execute(
            delete(CampaignCadenceStepModel)
            .where(CampaignCadenceStepModel.workspace_id == workspace_id)
            .where(CampaignCadenceStepModel.campaign_version_id == campaign_version_id),
        )
        saved_steps: list[CampaignAdminCadenceStep] = []
        for step in steps:
            result = await self._session.execute(
                insert(CampaignCadenceStepModel)
                .values(**_step_to_values(step))
                .returning(CampaignCadenceStepModel),
            )
            saved_steps.append(_step_from_model(result.scalar_one()))
        return tuple(saved_steps)

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        except_version_id: CampaignVersionId,
    ) -> None:
        await self._session.execute(
            update(CampaignVersionModel)
            .where(CampaignVersionModel.workspace_id == workspace_id)
            .where(CampaignVersionModel.campaign_id == campaign_id)
            .where(CampaignVersionModel.campaign_version_id != except_version_id)
            .where(CampaignVersionModel.status == CampaignVersionStatus.PUBLISHED.value)
            .values(status=CampaignVersionStatus.RETIRED.value),
        )


class PostgresCampaignAdminAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, audit_log: CampaignAdminAuditLog) -> CampaignAdminAuditLog:
        result = await self._session.execute(
            insert(CampaignAdminAuditLogModel)
            .values(**_audit_to_values(audit_log))
            .returning(CampaignAdminAuditLogModel),
        )
        return _audit_from_model(result.scalar_one())


def _campaign_to_values(campaign: CampaignAdminCampaign) -> dict[str, object]:
    return {
        "campaign_id": campaign.campaign_id,
        "workspace_id": campaign.workspace_id,
        "name": campaign.name,
        "status": campaign.status.value,
        "active_version_id": campaign.active_version_id,
        "created_by_user_id": campaign.created_by_user_id,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
    }


def _campaign_from_model(model: CampaignModel) -> CampaignAdminCampaign:
    return CampaignAdminCampaign(
        campaign_id=model.campaign_id,
        workspace_id=model.workspace_id,
        name=model.name,
        status=CampaignStatus(model.status),
        active_version_id=model.active_version_id,
        created_by_user_id=model.created_by_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _version_to_values(version: CampaignAdminVersion) -> dict[str, object]:
    drafting_config = version.outbound_drafting_config or (
        default_workspace_outbound_drafting_config(version.workspace_id)
    )
    return {
        "campaign_version_id": version.campaign_version_id,
        "workspace_id": version.workspace_id,
        "campaign_id": version.campaign_id,
        "version_number": version.version_number,
        "status": version.status.value,
        "enabled_channels": [channel.value for channel in version.enabled_channels],
        "daily_start_cap": version.daily_start_cap,
        "dormant_threshold_days": version.dormant_threshold_days,
        "quiet_hours_start": version.quiet_hours_start,
        "quiet_hours_end": version.quiet_hours_end,
        "timezone": version.timezone,
        "sms_compliance_required": version.sms_compliance_required,
        "preflight_digest_enabled": version.preflight_digest_enabled,
        "crm_enrollment_tag": version.crm_enrollment_tag,
        "allow_assigned_agent_manual_enrollment": version.allow_assigned_agent_manual_enrollment,
        "prompt_version": version.prompt_version,
        "approved_model": version.approved_model,
        "prompt_text": drafting_config.prompt_text,
        "sms_prompt_text": drafting_config.sms_prompt_text,
        "sms_template": drafting_config.sms_template,
        "email_prompt_text": drafting_config.email_prompt_text,
        "email_template": drafting_config.email_template,
        "email_subject_template": drafting_config.email_subject_template,
        "enabled_extraction_fields": list(drafting_config.enabled_extraction_fields),
        "created_by_user_id": version.created_by_user_id,
        "published_at": version.published_at,
        "created_at": version.created_at,
    }


def _version_from_model(model: CampaignVersionModel) -> CampaignAdminVersion:
    return CampaignAdminVersion(
        campaign_version_id=model.campaign_version_id,
        workspace_id=model.workspace_id,
        campaign_id=model.campaign_id,
        version_number=model.version_number,
        status=CampaignVersionStatus(model.status),
        enabled_channels=tuple(ContactChannel(channel) for channel in model.enabled_channels),
        daily_start_cap=model.daily_start_cap,
        dormant_threshold_days=model.dormant_threshold_days,
        quiet_hours_start=model.quiet_hours_start,
        quiet_hours_end=model.quiet_hours_end,
        timezone=model.timezone,
        sms_compliance_required=model.sms_compliance_required,
        preflight_digest_enabled=model.preflight_digest_enabled,
        crm_enrollment_tag=model.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=model.allow_assigned_agent_manual_enrollment,
        prompt_version=model.prompt_version,
        approved_model=model.approved_model,
        created_by_user_id=model.created_by_user_id,
        published_at=model.published_at,
        created_at=model.created_at,
        outbound_drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=model.workspace_id,
            revision=model.version_number,
            prompt_text=model.prompt_text,
            sms_prompt_text=model.sms_prompt_text,
            sms_template=model.sms_template,
            email_prompt_text=model.email_prompt_text,
            email_template=model.email_template,
            email_subject_template=model.email_subject_template,
            enabled_extraction_fields=tuple(model.enabled_extraction_fields),
        ),
    )


def _step_to_values(step: CampaignAdminCadenceStep) -> dict[str, object]:
    return {
        "cadence_step_id": step.cadence_step_id,
        "workspace_id": step.workspace_id,
        "campaign_version_id": step.campaign_version_id,
        "step_order": step.step_order,
        "channel": step.channel.value,
        "delay_hours": step.delay_hours,
        "message_goal": step.message_goal,
        "template_key": step.template_key,
        "template_profile": (
            dormant_step_template_profile_to_mapping(step.template_profile)
            if step.template_profile is not None
            else None
        ),
        "max_attempts": step.max_attempts,
        "created_at": step.created_at,
    }


def _step_from_model(model: CampaignCadenceStepModel) -> CampaignAdminCadenceStep:
    return CampaignAdminCadenceStep(
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
        template_profile=dormant_step_template_profile_from_mapping(model.template_profile),
    )


def _audit_to_values(audit_log: CampaignAdminAuditLog) -> dict[str, object]:
    return {
        "audit_log_id": audit_log.audit_log_id,
        "workspace_id": audit_log.workspace_id,
        "campaign_id": audit_log.campaign_id,
        "campaign_version_id": audit_log.campaign_version_id,
        "actor_user_id": audit_log.actor_user_id,
        "action": audit_log.action.value,
        "details": dict(audit_log.details),
        "created_at": audit_log.created_at,
    }


def _audit_from_model(model: CampaignAdminAuditLogModel) -> CampaignAdminAuditLog:
    return CampaignAdminAuditLog(
        audit_log_id=model.audit_log_id,
        workspace_id=model.workspace_id,
        campaign_id=model.campaign_id,
        campaign_version_id=model.campaign_version_id,
        actor_user_id=model.actor_user_id,
        action=CampaignAdminAuditAction(model.action),
        details=dict(model.details),
        created_at=model.created_at,
    )
