from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import StrEnum
from uuid import uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignAdminAuditLogRepository,
    CampaignAdminRepository,
)
from app.domain.campaigns.admin import (
    CampaignAdminAuditAction,
    CampaignAdminAuditLog,
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminVersion,
    CampaignAdminView,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.outbound_drafting import (
    DEFAULT_EMAIL_PROMPT_TEXT,
    DEFAULT_SMS_PROMPT_TEXT,
    DormantStepTemplateProfile,
    WorkspaceOutboundDraftingConfig,
    dormant_template_profile_is_valid_for_channel,
    normalize_config_prompt_text,
    normalize_email_subject_template,
    normalize_email_template,
    normalize_enabled_extraction_fields,
    normalize_outbound_prompt_text,
    normalize_sms_template,
)


class CampaignAdminReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"
    CAMPAIGN_NAME_TAKEN = "campaign_name_taken"
    VERSION_NOT_FOUND = "version_not_found"
    VERSION_NOT_DRAFT = "version_not_draft"
    VERSION_NOT_IN_CAMPAIGN = "version_not_in_campaign"
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_CAMPAIGN_STATUS = "invalid_campaign_status"


class CreateDraftCampaignStatus(StrEnum):
    CREATED = "created"
    REJECTED = "rejected"


class UpdateDraftCampaignStatus(StrEnum):
    UPDATED = "updated"
    REJECTED = "rejected"


class PublishCampaignVersionStatus(StrEnum):
    PUBLISHED = "published"
    REJECTED = "rejected"


class PauseCampaignStatus(StrEnum):
    PAUSED = "paused"
    ALREADY_PAUSED = "already_paused"
    REJECTED = "rejected"


class ResumeCampaignStatus(StrEnum):
    RESUMED = "resumed"
    ALREADY_ACTIVE = "already_active"
    REJECTED = "rejected"


class CampaignReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CampaignCadenceStepInput:
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    template_profile: DormantStepTemplateProfile | None = None


@dataclass(frozen=True)
class CampaignConfigInput:
    enabled_channels: tuple[ContactChannel, ...]
    daily_start_cap: int
    dormant_threshold_days: int
    quiet_hours_start: time
    quiet_hours_end: time
    timezone: str
    preflight_digest_enabled: bool
    crm_enrollment_tag: str | None
    allow_assigned_agent_manual_enrollment: bool
    prompt_version: str
    approved_model: str
    cadence_steps: tuple[CampaignCadenceStepInput, ...]
    outbound_drafting_config: WorkspaceOutboundDraftingConfig | None = None


@dataclass(frozen=True)
class CreateDraftCampaignResult:
    status: CreateDraftCampaignStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class UpdateDraftCampaignResult:
    status: UpdateDraftCampaignStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class PublishCampaignVersionResult:
    status: PublishCampaignVersionStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class PauseCampaignResult:
    status: PauseCampaignStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class ResumeCampaignResult:
    status: ResumeCampaignStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class CampaignListResult:
    status: CampaignReadStatus
    views: tuple[CampaignAdminView, ...] = ()
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class CampaignDetailResult:
    status: CampaignReadStatus
    view: CampaignAdminView | None = None
    reasons: tuple[CampaignAdminReasonCode, ...] = ()


async def create_draft_campaign(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    name: str,
    config: CampaignConfigInput,
    campaign_admin_repository: CampaignAdminRepository,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> CreateDraftCampaignResult:
    if not _can_administer_campaigns(actor):
        return CreateDraftCampaignResult(
            status=CreateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )
    if not _configuration_is_valid(name=name, config=config):
        return CreateDraftCampaignResult(
            status=CreateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CONFIGURATION,),
        )
    existing_campaign = await campaign_admin_repository.get_campaign_by_name(
        workspace_id,
        name.strip(),
    )
    if existing_campaign is not None:
        return CreateDraftCampaignResult(
            status=CreateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NAME_TAKEN,),
        )

    campaign_id = uuid4()
    version_id = uuid4()
    campaign = CampaignAdminCampaign(
        campaign_id=campaign_id,
        workspace_id=workspace_id,
        name=name.strip(),
        status=CampaignStatus.DRAFT,
        active_version_id=None,
        created_by_user_id=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    version = _build_version(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=version_id,
        version_number=1,
        actor=actor,
        config=config,
        now=now,
    )
    steps = _build_steps(workspace_id=workspace_id, version_id=version_id, config=config, now=now)

    saved_campaign = await campaign_admin_repository.save_campaign(campaign)
    saved_version = await campaign_admin_repository.save_version(version)
    saved_steps = await campaign_admin_repository.replace_cadence_steps(
        workspace_id,
        version_id,
        steps,
    )
    view = CampaignAdminView(saved_campaign, saved_version, saved_steps)
    await _append_audit(
        audit_log_repository=audit_log_repository,
        action=CampaignAdminAuditAction.DRAFT_CREATED,
        actor=actor,
        view=view,
        now=now,
    )
    await _publish_event(
        event_bus=event_bus,
        event_type=DomainEventType.CAMPAIGN_DRAFT_CREATED,
        view=view,
        actor=actor,
    )
    return CreateDraftCampaignResult(status=CreateDraftCampaignStatus.CREATED, view=view)


async def update_draft_campaign(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    name: str,
    config: CampaignConfigInput,
    campaign_admin_repository: CampaignAdminRepository,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> UpdateDraftCampaignResult:
    if not _can_administer_campaigns(actor):
        return UpdateDraftCampaignResult(
            status=UpdateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )
    if not _configuration_is_valid(name=name, config=config):
        return UpdateDraftCampaignResult(
            status=UpdateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CONFIGURATION,),
        )

    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    if campaign is None:
        return UpdateDraftCampaignResult(
            status=UpdateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if campaign.status == CampaignStatus.INACTIVE:
        return UpdateDraftCampaignResult(
            status=UpdateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CAMPAIGN_STATUS,),
        )
    existing_campaign = await campaign_admin_repository.get_campaign_by_name(
        workspace_id,
        name.strip(),
    )
    if existing_campaign is not None and existing_campaign.campaign_id != campaign_id:
        return UpdateDraftCampaignResult(
            status=UpdateDraftCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NAME_TAKEN,),
        )

    draft_version = await campaign_admin_repository.get_latest_draft_version(
        workspace_id,
        campaign_id,
    )
    if draft_version is None:
        draft_version = _build_version(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=uuid4(),
            version_number=await campaign_admin_repository.get_latest_version_number(
                workspace_id,
                campaign_id,
            )
            + 1,
            actor=actor,
            config=config,
            now=now,
        )
    else:
        draft_version = _replace_version_config(draft_version, config)

    updated_campaign = replace(campaign, name=name.strip(), updated_at=now)
    steps = _build_steps(
        workspace_id=workspace_id,
        version_id=draft_version.campaign_version_id,
        config=config,
        now=now,
    )

    saved_campaign = await campaign_admin_repository.save_campaign(updated_campaign)
    saved_version = await campaign_admin_repository.save_version(draft_version)
    saved_steps = await campaign_admin_repository.replace_cadence_steps(
        workspace_id,
        draft_version.campaign_version_id,
        steps,
    )
    view = CampaignAdminView(saved_campaign, saved_version, saved_steps)
    await _append_audit(
        audit_log_repository=audit_log_repository,
        action=CampaignAdminAuditAction.DRAFT_UPDATED,
        actor=actor,
        view=view,
        now=now,
    )
    await _publish_event(
        event_bus=event_bus,
        event_type=DomainEventType.CAMPAIGN_DRAFT_UPDATED,
        view=view,
        actor=actor,
    )
    return UpdateDraftCampaignResult(status=UpdateDraftCampaignStatus.UPDATED, view=view)


async def publish_campaign_version(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    campaign_admin_repository: CampaignAdminRepository,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> PublishCampaignVersionResult:
    if not _can_administer_campaigns(actor):
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )
    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    if campaign is None:
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    version = await campaign_admin_repository.get_version(workspace_id, campaign_version_id)
    if version is None:
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_FOUND,),
        )
    if version.campaign_id != campaign_id:
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_IN_CAMPAIGN,),
        )
    if version.status != CampaignVersionStatus.DRAFT:
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_DRAFT,),
        )

    steps = await campaign_admin_repository.get_cadence_steps(workspace_id, campaign_version_id)
    if not steps or not version.enabled_channels:
        return PublishCampaignVersionResult(
            status=PublishCampaignVersionStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CONFIGURATION,),
        )

    await campaign_admin_repository.retire_published_versions(
        workspace_id,
        campaign_id,
        campaign_version_id,
    )
    published_version = await campaign_admin_repository.save_version(
        replace(version, status=CampaignVersionStatus.PUBLISHED, published_at=now),
    )
    active_campaign = await campaign_admin_repository.save_campaign(
        replace(
            campaign,
            status=CampaignStatus.ACTIVE,
            active_version_id=campaign_version_id,
            updated_at=now,
        ),
    )
    view = CampaignAdminView(active_campaign, published_version, steps)
    await _append_audit(
        audit_log_repository=audit_log_repository,
        action=CampaignAdminAuditAction.VERSION_PUBLISHED,
        actor=actor,
        view=view,
        now=now,
    )
    await _publish_event(
        event_bus=event_bus,
        event_type=DomainEventType.CAMPAIGN_PUBLISHED,
        view=view,
        actor=actor,
    )
    return PublishCampaignVersionResult(status=PublishCampaignVersionStatus.PUBLISHED, view=view)


async def pause_campaign(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_admin_repository: CampaignAdminRepository,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    reason: str | None = None,
    event_bus: EventBus | None = None,
) -> PauseCampaignResult:
    permission = evaluate_permission(actor, PermissionCapability.PAUSE_CAMPAIGN)
    if not permission.allowed:
        return PauseCampaignResult(
            status=PauseCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )
    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    if campaign is None:
        return PauseCampaignResult(
            status=PauseCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if campaign.status == CampaignStatus.PAUSED:
        return PauseCampaignResult(
            status=PauseCampaignStatus.ALREADY_PAUSED,
            view=await _active_view(campaign_admin_repository, campaign),
        )
    if campaign.status != CampaignStatus.ACTIVE or campaign.active_version_id is None:
        return PauseCampaignResult(
            status=PauseCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CAMPAIGN_STATUS,),
        )

    paused_campaign = await campaign_admin_repository.save_campaign(
        replace(campaign, status=CampaignStatus.PAUSED, updated_at=now),
    )
    view = await _active_view(campaign_admin_repository, paused_campaign)
    if view is None:
        return PauseCampaignResult(
            status=PauseCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_FOUND,),
        )
    await _append_audit(
        audit_log_repository=audit_log_repository,
        action=CampaignAdminAuditAction.CAMPAIGN_PAUSED,
        actor=actor,
        view=view,
        now=now,
        extra_details={"reason": reason.strip()} if reason and reason.strip() else None,
    )
    await _publish_event(
        event_bus=event_bus,
        event_type=DomainEventType.CAMPAIGN_PAUSED,
        view=view,
        actor=actor,
        extra_payload={"reason": reason.strip()} if reason and reason.strip() else None,
    )
    return PauseCampaignResult(status=PauseCampaignStatus.PAUSED, view=view)


async def resume_campaign(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_admin_repository: CampaignAdminRepository,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    reason: str | None = None,
    event_bus: EventBus | None = None,
) -> ResumeCampaignResult:
    permission = evaluate_permission(actor, PermissionCapability.PAUSE_CAMPAIGN)
    if not permission.allowed:
        return ResumeCampaignResult(
            status=ResumeCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )
    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    if campaign is None:
        return ResumeCampaignResult(
            status=ResumeCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if campaign.status == CampaignStatus.ACTIVE:
        return ResumeCampaignResult(
            status=ResumeCampaignStatus.ALREADY_ACTIVE,
            view=await _active_view(campaign_admin_repository, campaign),
        )
    if campaign.status != CampaignStatus.PAUSED or campaign.active_version_id is None:
        return ResumeCampaignResult(
            status=ResumeCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.INVALID_CAMPAIGN_STATUS,),
        )

    resumed_campaign = await campaign_admin_repository.save_campaign(
        replace(campaign, status=CampaignStatus.ACTIVE, updated_at=now),
    )
    view = await _active_view(campaign_admin_repository, resumed_campaign)
    if view is None:
        return ResumeCampaignResult(
            status=ResumeCampaignStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_FOUND,),
        )
    await _append_audit(
        audit_log_repository=audit_log_repository,
        action=CampaignAdminAuditAction.CAMPAIGN_RESUMED,
        actor=actor,
        view=view,
        now=now,
        extra_details={"reason": reason.strip()} if reason and reason.strip() else None,
    )
    await _publish_event(
        event_bus=event_bus,
        event_type=DomainEventType.CAMPAIGN_RESUMED,
        view=view,
        actor=actor,
        extra_payload={"reason": reason.strip()} if reason and reason.strip() else None,
    )
    return ResumeCampaignResult(status=ResumeCampaignStatus.RESUMED, view=view)


async def list_campaign_admin_views(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_admin_repository: CampaignAdminRepository,
) -> CampaignListResult:
    if not _can_view_campaigns(actor):
        return CampaignListResult(
            status=CampaignReadStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )

    campaigns = await campaign_admin_repository.list_campaigns(workspace_id)
    views: list[CampaignAdminView] = []
    for campaign in campaigns:
        view = await _view_for_campaign(campaign_admin_repository, campaign)
        if view is not None:
            views.append(view)
    return CampaignListResult(status=CampaignReadStatus.OK, views=tuple(views))


async def get_campaign_admin_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_admin_repository: CampaignAdminRepository,
) -> CampaignDetailResult:
    if not _can_view_campaigns(actor):
        return CampaignDetailResult(
            status=CampaignReadStatus.REJECTED,
            reasons=(CampaignAdminReasonCode.PERMISSION_DENIED,),
        )

    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    if campaign is None:
        return CampaignDetailResult(
            status=CampaignReadStatus.NOT_FOUND,
            reasons=(CampaignAdminReasonCode.CAMPAIGN_NOT_FOUND,),
        )

    view = await _view_for_campaign(campaign_admin_repository, campaign)
    if view is None:
        return CampaignDetailResult(
            status=CampaignReadStatus.NOT_FOUND,
            reasons=(CampaignAdminReasonCode.VERSION_NOT_FOUND,),
        )
    return CampaignDetailResult(status=CampaignReadStatus.OK, view=view)


async def record_campaign_batch_launch_audit(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId | None,
    batch_id: str,
    selected_count: int,
    started_count: int,
    audit_log_repository: CampaignAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> None:
    details = {
        "batch_id": batch_id,
        "selected_count": selected_count,
        "started_count": started_count,
    }
    await audit_log_repository.append(
        CampaignAdminAuditLog(
            audit_log_id=uuid4(),
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=campaign_version_id,
            action=CampaignAdminAuditAction.BATCH_LAUNCHED,
            actor_user_id=actor.user_id,
            details=details,
            created_at=now,
        ),
    )
    if event_bus is not None:
        await event_bus.publish(
            DomainEvent(
                workspace_id=workspace_id,
                aggregate_type=AggregateType.CAMPAIGN,
                aggregate_id=campaign_id,
                event_type=DomainEventType.CAMPAIGN_BATCH_LAUNCHED,
                payload={
                    **details,
                    "campaign_id": str(campaign_id),
                    "campaign_version_id": str(campaign_version_id)
                    if campaign_version_id is not None
                    else None,
                    "actor_user_id": str(actor.user_id),
                },
            ),
        )


def _can_administer_campaigns(actor: AuthenticatedActor) -> bool:
    return evaluate_permission(actor, PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN).allowed


def _can_view_campaigns(actor: AuthenticatedActor) -> bool:
    return evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed


def _configuration_is_valid(*, name: str, config: CampaignConfigInput) -> bool:
    normalized_template_keys = {
        step.template_key.strip() for step in config.cadence_steps
    }
    return (
        bool(name.strip())
        and bool(config.enabled_channels)
        and config.daily_start_cap > 0
        and config.dormant_threshold_days > 0
        and config.quiet_hours_start < config.quiet_hours_end
        and bool(config.timezone.strip())
        and bool(config.prompt_version.strip())
        and bool(config.approved_model.strip())
        and config.outbound_drafting_config is not None
        and bool(config.cadence_steps)
        and len(normalized_template_keys) == len(config.cadence_steps)
        and all(_step_is_valid(step) for step in config.cadence_steps)
    )


def _step_is_valid(step: CampaignCadenceStepInput) -> bool:
    return (
        step.delay_hours >= 0
        and bool(step.message_goal.strip())
        and bool(step.template_key.strip())
        and step.max_attempts > 0
        and dormant_template_profile_is_valid_for_channel(
            step.template_profile,
            channel=step.channel.value,
        )
    )


def _build_version(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    version_number: int,
    actor: AuthenticatedActor,
    config: CampaignConfigInput,
    now: datetime,
) -> CampaignAdminVersion:
    drafting_config = _resolved_drafting_config(
        config.outbound_drafting_config,
        workspace_id=workspace_id,
        revision=version_number,
    )
    return CampaignAdminVersion(
        campaign_version_id=campaign_version_id,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        version_number=version_number,
        status=CampaignVersionStatus.DRAFT,
        enabled_channels=tuple(config.enabled_channels),
        daily_start_cap=config.daily_start_cap,
        dormant_threshold_days=config.dormant_threshold_days,
        quiet_hours_start=config.quiet_hours_start,
        quiet_hours_end=config.quiet_hours_end,
        timezone=config.timezone.strip(),
        preflight_digest_enabled=config.preflight_digest_enabled,
        crm_enrollment_tag=_normalized_optional_tag(config.crm_enrollment_tag),
        allow_assigned_agent_manual_enrollment=config.allow_assigned_agent_manual_enrollment,
        prompt_version=config.prompt_version.strip(),
        approved_model=config.approved_model.strip(),
        created_by_user_id=actor.user_id,
        created_at=now,
        outbound_drafting_config=drafting_config,
    )


def _replace_version_config(
    version: CampaignAdminVersion,
    config: CampaignConfigInput,
) -> CampaignAdminVersion:
    drafting_config = _resolved_drafting_config(
        config.outbound_drafting_config,
        workspace_id=version.workspace_id,
        revision=version.version_number,
    )
    return replace(
        version,
        enabled_channels=tuple(config.enabled_channels),
        daily_start_cap=config.daily_start_cap,
        dormant_threshold_days=config.dormant_threshold_days,
        quiet_hours_start=config.quiet_hours_start,
        quiet_hours_end=config.quiet_hours_end,
        timezone=config.timezone.strip(),
        preflight_digest_enabled=config.preflight_digest_enabled,
        crm_enrollment_tag=_normalized_optional_tag(config.crm_enrollment_tag),
        allow_assigned_agent_manual_enrollment=config.allow_assigned_agent_manual_enrollment,
        prompt_version=config.prompt_version.strip(),
        approved_model=config.approved_model.strip(),
        outbound_drafting_config=drafting_config,
    )


def _resolved_drafting_config(
    config: WorkspaceOutboundDraftingConfig | None,
    *,
    workspace_id: WorkspaceId,
    revision: int,
) -> WorkspaceOutboundDraftingConfig:
    if config is None:
        raise ValueError("Admin outbound drafting configuration is required.")
    resolved = config
    return WorkspaceOutboundDraftingConfig(
        workspace_id=workspace_id,
        revision=revision,
        prompt_text=normalize_config_prompt_text(resolved.prompt_text),
        sms_prompt_text=normalize_outbound_prompt_text(
            resolved.sms_prompt_text,
            default_text=DEFAULT_SMS_PROMPT_TEXT,
        ),
        sms_template=normalize_sms_template(resolved.sms_template),
        email_prompt_text=normalize_outbound_prompt_text(
            resolved.email_prompt_text,
            default_text=DEFAULT_EMAIL_PROMPT_TEXT,
        ),
        email_template=normalize_email_template(resolved.email_template),
        email_subject_template=normalize_email_subject_template(
            resolved.email_subject_template,
        ),
        enabled_extraction_fields=normalize_enabled_extraction_fields(
            resolved.enabled_extraction_fields,
        ),
    )


def _normalized_optional_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _build_steps(
    *,
    workspace_id: WorkspaceId,
    version_id: CampaignVersionId,
    config: CampaignConfigInput,
    now: datetime,
) -> tuple[CampaignAdminCadenceStep, ...]:
    return tuple(
        CampaignAdminCadenceStep(
            cadence_step_id=uuid4(),
            workspace_id=workspace_id,
            campaign_version_id=version_id,
            step_order=index + 1,
            channel=step.channel,
            delay_hours=step.delay_hours,
            message_goal=step.message_goal.strip(),
            template_key=step.template_key.strip(),
            max_attempts=step.max_attempts,
            created_at=now,
            template_profile=step.template_profile,
        )
        for index, step in enumerate(config.cadence_steps)
    )


async def _view_for_campaign(
    repository: CampaignAdminRepository,
    campaign: CampaignAdminCampaign,
) -> CampaignAdminView | None:
    version = None
    if campaign.active_version_id is not None:
        version = await repository.get_version(campaign.workspace_id, campaign.active_version_id)
    if version is None:
        version = await repository.get_latest_version(campaign.workspace_id, campaign.campaign_id)
    if version is None:
        return None
    steps = await repository.get_cadence_steps(campaign.workspace_id, version.campaign_version_id)
    return CampaignAdminView(campaign, version, steps)


async def _active_view(
    repository: CampaignAdminRepository,
    campaign: CampaignAdminCampaign,
) -> CampaignAdminView | None:
    if campaign.active_version_id is None:
        return None
    version = await repository.get_version(campaign.workspace_id, campaign.active_version_id)
    if version is None:
        return None
    steps = await repository.get_cadence_steps(campaign.workspace_id, version.campaign_version_id)
    return CampaignAdminView(campaign, version, steps)


async def _append_audit(
    *,
    audit_log_repository: CampaignAdminAuditLogRepository,
    action: CampaignAdminAuditAction,
    actor: AuthenticatedActor,
    view: CampaignAdminView,
    now: datetime,
    extra_details: dict[str, object] | None = None,
) -> None:
    await audit_log_repository.append(
        CampaignAdminAuditLog(
            audit_log_id=uuid4(),
            workspace_id=view.campaign.workspace_id,
            campaign_id=view.campaign.campaign_id,
            campaign_version_id=view.version.campaign_version_id,
            action=action,
            actor_user_id=actor.user_id,
            details={**_details_for_view(view), **(extra_details or {})},
            created_at=now,
        ),
    )


async def _publish_event(
    *,
    event_bus: EventBus | None,
    event_type: DomainEventType,
    view: CampaignAdminView,
    actor: AuthenticatedActor,
    extra_payload: dict[str, object] | None = None,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=view.campaign.workspace_id,
            aggregate_type=AggregateType.CAMPAIGN,
            aggregate_id=view.campaign.campaign_id,
            event_type=event_type,
            payload={
                **_details_for_view(view),
                **(extra_payload or {}),
                "campaign_id": str(view.campaign.campaign_id),
                "campaign_version_id": str(view.version.campaign_version_id),
                "actor_user_id": str(actor.user_id),
            },
        ),
    )


def _details_for_view(view: CampaignAdminView) -> dict[str, object]:
    return {
        "campaign_name": view.campaign.name,
        "campaign_status": view.campaign.status.value,
        "version_number": view.version.version_number,
        "version_status": view.version.status.value,
        "enabled_channels": [channel.value for channel in view.version.enabled_channels],
        "cadence_step_count": len(view.cadence_steps),
    }
