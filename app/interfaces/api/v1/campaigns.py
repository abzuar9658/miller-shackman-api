from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.repositories import CampaignAdminRepository
from app.application.use_cases.campaign_admin import (
    CampaignAdminReasonCode,
    CampaignCadenceStepInput,
    CampaignConfigInput,
    CampaignReadStatus,
    CreateDraftCampaignStatus,
    PauseCampaignStatus,
    PublishCampaignVersionStatus,
    ResumeCampaignStatus,
    UpdateDraftCampaignStatus,
    create_draft_campaign,
    get_campaign_admin_view,
    list_campaign_admin_views,
    pause_campaign,
    publish_campaign_version,
    record_campaign_batch_launch_audit,
    resume_campaign,
    update_draft_campaign,
)
from app.application.use_cases.preflight_digest import (
    PreflightVetoPolicy,
    PreflightVetoStatus,
    VetoActorRole,
    record_preflight_veto,
)
from app.application.use_cases.run_dormant_selector_batch import (
    DormantSelectorBatchStatus,
    run_dormant_selector_batch,
)
from app.domain.campaigns.admin import (
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminView,
)
from app.domain.identity import AuthenticatedActor, WorkspaceMembershipRole
from app.domain.identity.permissions import PermissionCapability, evaluate_permission
from app.interfaces.api.dependencies.campaign import (
    CampaignReadBundle,
    CampaignServiceBundle,
    get_campaign_read_bundle,
    get_campaign_service_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.campaigns import (
    CampaignAdminResponse,
    CampaignCadenceStepResponse,
    CampaignConfigRequest,
    CampaignDetailResponse,
    CampaignDraftRequest,
    CampaignListResponse,
    CampaignResponse,
    CampaignSummaryResponse,
    CampaignVersionResponse,
    NurtureCadenceStepResponse,
    NurtureSettingsAdminResponse,
    NurtureSettingsConfigResponse,
    NurtureSettingsDetailResponse,
    NurtureSettingsDraftRequest,
    NurtureSettingsPolicyResponse,
    PauseCampaignRequest,
    RecordPreflightVetoRequest,
    RecordPreflightVetoResponse,
    ResumeCampaignRequest,
    RunDormantSelectorRequest,
    RunDormantSelectorResponse,
)

router = APIRouter(tags=["campaigns"])

_ALLOWED_DORMANT_SELECTOR_ROLES: frozenset[WorkspaceMembershipRole] = frozenset(
    {WorkspaceMembershipRole.BROKERAGE_ADMIN, WorkspaceMembershipRole.MANAGER},
)
_WORKSPACE_NURTURE_POLICY_NAME = "Workspace Nurture Settings"


@router.get(
    "/{workspace_id}/campaigns",
    response_model=CampaignListResponse,
)
async def list_campaigns_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignReadBundle, Depends(get_campaign_read_bundle)],
) -> CampaignListResponse:
    result = await list_campaign_admin_views(
        actor=actor,
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    if result.status == CampaignReadStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return CampaignListResponse(
        status=result.status.value,
        campaigns=[_campaign_summary_response(view) for view in result.views],
    )


@router.get(
    "/{workspace_id}/campaigns/{campaign_id}",
    response_model=CampaignDetailResponse,
)
async def get_campaign_route(
    workspace_id: UUID,
    campaign_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignReadBundle, Depends(get_campaign_read_bundle)],
) -> CampaignDetailResponse:
    result = await get_campaign_admin_view(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    if result.status == CampaignReadStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    if result.status == CampaignReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.view is not None
    return _campaign_detail_response(result.status.value, result.view)


@router.get(
    "/{workspace_id}/nurture-settings",
    response_model=NurtureSettingsDetailResponse,
)
async def get_nurture_settings_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignReadBundle, Depends(get_campaign_read_bundle)],
) -> NurtureSettingsDetailResponse:
    _require_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING)
    campaign = await _require_single_workspace_nurture_campaign(
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    view = await _current_nurture_settings_view(
        actor=actor,
        workspace_id=workspace_id,
        campaign=campaign,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    return _nurture_settings_detail_response(CampaignReadStatus.OK.value, view)


@router.put(
    "/{workspace_id}/nurture-settings/draft",
    response_model=NurtureSettingsAdminResponse,
)
async def upsert_nurture_settings_draft_route(
    workspace_id: UUID,
    request: NurtureSettingsDraftRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> NurtureSettingsAdminResponse:
    _require_permission(actor, PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN)
    campaign = await _single_workspace_nurture_campaign_or_none(
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    if campaign is None:
        create_result = await create_draft_campaign(
            actor=actor,
            workspace_id=workspace_id,
            name=_WORKSPACE_NURTURE_POLICY_NAME,
            config=_config_from_request(request),
            campaign_admin_repository=bundle.campaign_admin_repository,
            audit_log_repository=bundle.campaign_admin_audit_log_repository,
            event_bus=bundle.event_bus,
            now=datetime.now(UTC),
        )
        await bundle.session.commit()
        if create_result.status == CreateDraftCampaignStatus.REJECTED:
            _raise_campaign_admin_rejection(create_result.reasons)
        return _nurture_settings_admin_response(
            create_result.status.value,
            create_result.view,
            create_result.reasons,
        )

    update_result = await update_draft_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign.campaign_id,
        name=_WORKSPACE_NURTURE_POLICY_NAME,
        config=_config_from_request(request),
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if update_result.status == UpdateDraftCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(update_result.reasons)
    return _nurture_settings_admin_response(
        update_result.status.value,
        update_result.view,
        update_result.reasons,
    )


@router.post(
    "/{workspace_id}/nurture-settings/publish",
    response_model=NurtureSettingsAdminResponse,
)
async def publish_nurture_settings_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> NurtureSettingsAdminResponse:
    _require_permission(actor, PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN)
    campaign = await _require_single_workspace_nurture_campaign(
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    draft_version = await bundle.campaign_admin_repository.get_latest_draft_version(
        workspace_id,
        campaign.campaign_id,
    )
    if draft_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[CampaignAdminReasonCode.VERSION_NOT_FOUND.value],
        )
    result = await publish_campaign_version(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign.campaign_id,
        campaign_version_id=draft_version.campaign_version_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == PublishCampaignVersionStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _nurture_settings_admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/nurture-settings/pause",
    response_model=NurtureSettingsAdminResponse,
)
async def pause_nurture_settings_route(
    workspace_id: UUID,
    request: PauseCampaignRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> NurtureSettingsAdminResponse:
    _require_permission(actor, PermissionCapability.PAUSE_CAMPAIGN)
    campaign = await _require_single_workspace_nurture_campaign(
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    result = await pause_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign.campaign_id,
        reason=request.reason,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == PauseCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _nurture_settings_admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/nurture-settings/resume",
    response_model=NurtureSettingsAdminResponse,
)
async def resume_nurture_settings_route(
    workspace_id: UUID,
    request: ResumeCampaignRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> NurtureSettingsAdminResponse:
    _require_permission(actor, PermissionCapability.PAUSE_CAMPAIGN)
    campaign = await _require_single_workspace_nurture_campaign(
        workspace_id=workspace_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
    )
    result = await resume_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign.campaign_id,
        reason=request.reason,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == ResumeCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _nurture_settings_admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/campaigns",
    response_model=CampaignAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_campaign_route(
    workspace_id: UUID,
    request: CampaignDraftRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> CampaignAdminResponse:
    result = await create_draft_campaign(
        actor=actor,
        workspace_id=workspace_id,
        name=request.name,
        config=_config_from_request(request),
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == CreateDraftCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _admin_response(result.status.value, result.view, result.reasons)


@router.put(
    "/{workspace_id}/campaigns/{campaign_id}/draft",
    response_model=CampaignAdminResponse,
)
async def update_draft_campaign_route(
    workspace_id: UUID,
    campaign_id: UUID,
    request: CampaignDraftRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> CampaignAdminResponse:
    result = await update_draft_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        name=request.name,
        config=_config_from_request(request),
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == UpdateDraftCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/versions/{campaign_version_id}/publish",
    response_model=CampaignAdminResponse,
)
async def publish_campaign_version_route(
    workspace_id: UUID,
    campaign_id: UUID,
    campaign_version_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> CampaignAdminResponse:
    result = await publish_campaign_version(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == PublishCampaignVersionStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/pause",
    response_model=CampaignAdminResponse,
)
async def pause_campaign_route(
    workspace_id: UUID,
    campaign_id: UUID,
    request: PauseCampaignRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> CampaignAdminResponse:
    result = await pause_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        reason=request.reason,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == PauseCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/resume",
    response_model=CampaignAdminResponse,
)
async def resume_campaign_route(
    workspace_id: UUID,
    campaign_id: UUID,
    request: ResumeCampaignRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> CampaignAdminResponse:
    result = await resume_campaign(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        reason=request.reason,
        campaign_admin_repository=bundle.campaign_admin_repository,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    if result.status == ResumeCampaignStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    return _admin_response(result.status.value, result.view, result.reasons)


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/dormant-selector-runs",
    response_model=RunDormantSelectorResponse,
)
async def run_dormant_selector_route(
    workspace_id: UUID,
    campaign_id: UUID,
    request: RunDormantSelectorRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> RunDormantSelectorResponse:
    permission = evaluate_permission(actor, PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD)
    if not permission.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only brokerage admins and managers may run the dormant selector.",
        )

    result = await run_dormant_selector_batch(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=request.batch_id,
        campaign_execution_repository=bundle.campaign_execution_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        dormant_candidate_selector=bundle.dormant_candidate_selector,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_workflow_starter=bundle.temporal_workflow_starter,
        commit=bundle.session.commit,
        preflight_digest_repository=bundle.preflight_digest_repository,
        notification_provider=bundle.notification_provider,
        crm_client=bundle.crm_client,
        event_bus=bundle.event_bus,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        now=datetime.now(UTC),
    )
    if result.status == DormantSelectorBatchStatus.CAMPAIGN_INACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.reason or "Campaign is not active",
        )
    if result.status == DormantSelectorBatchStatus.MISSING_CONTACT_POLICY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.reason or "Missing workspace contact policy",
        )
    config = await bundle.campaign_execution_repository.get_active_for_campaign(
        workspace_id,
        campaign_id,
    )
    await record_campaign_batch_launch_audit(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=config.campaign_version_id if config is not None else None,
        batch_id=result.batch_id,
        selected_count=result.selected_count,
        started_count=result.started_count,
        audit_log_repository=bundle.campaign_admin_audit_log_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()

    return RunDormantSelectorResponse(
        status=result.status.value,
        workspace_id=result.workspace_id,
        campaign_id=result.campaign_id,
        batch_id=result.batch_id,
        digest_required=result.digest_required,
        digest_id=result.digest_id,
        digest_status=result.digest_status,
        selected_count=result.selected_count,
        held_back_count=result.held_back_count,
        started_count=result.started_count,
        veto_window_expires_at=result.veto_window_expires_at,
        reason=result.reason,
    )


@router.post(
    "/{workspace_id}/campaigns/{campaign_id}/batches/{batch_id}/preflight-vetoes",
    response_model=RecordPreflightVetoResponse,
)
async def record_preflight_veto_route(
    workspace_id: UUID,
    campaign_id: UUID,
    batch_id: str,
    request: RecordPreflightVetoRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[CampaignServiceBundle, Depends(get_campaign_service_bundle)],
) -> RecordPreflightVetoResponse:
    if actor.active_role not in _ALLOWED_DORMANT_SELECTOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only brokerage admins and managers may record preflight vetoes.",
        )

    actor_role = _veto_role_from_membership(actor.active_role)
    result = await record_preflight_veto(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        lead_id=request.lead_id,
        actor_id=str(actor.user_id),
        actor_role=actor_role,
        reason=request.reason,
        policy=PreflightVetoPolicy(),
        repository=bundle.preflight_digest_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()

    if result.status == PreflightVetoStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=[reason.value for reason in result.reasons],
        )

    return RecordPreflightVetoResponse(
        status=result.status.value,
        digest_id=result.digest_id,
        lead_id=result.lead_id,
        recorded=result.recorded,
        recorded_at=result.recorded_at,
        actor_id=UUID(result.actor_id),
        duplicate=result.duplicate,
        reasons=[reason.value for reason in result.reasons],
    )


def _veto_role_from_membership(role: WorkspaceMembershipRole) -> VetoActorRole:
    if role == WorkspaceMembershipRole.BROKERAGE_ADMIN:
        return VetoActorRole.BROKERAGE_ADMIN
    if role == WorkspaceMembershipRole.MANAGER:
        return VetoActorRole.MANAGER
    return VetoActorRole.UNAUTHORIZED


def _raise_campaign_admin_rejection(reasons: tuple[CampaignAdminReasonCode, ...]) -> None:
    status_code = (
        status.HTTP_403_FORBIDDEN
        if CampaignAdminReasonCode.PERMISSION_DENIED in reasons
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=status_code, detail=[reason.value for reason in reasons])


def _require_permission(actor: AuthenticatedActor, capability: PermissionCapability) -> None:
    if evaluate_permission(actor, capability).allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=[CampaignAdminReasonCode.PERMISSION_DENIED.value],
    )


async def _single_workspace_nurture_campaign_or_none(
    *,
    workspace_id: UUID,
    campaign_admin_repository: CampaignAdminRepository,
) -> CampaignAdminCampaign | None:
    campaigns = await campaign_admin_repository.list_campaigns(workspace_id)
    if len(campaigns) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=["multiple_nurture_policies_configured"],
        )
    return campaigns[0] if campaigns else None


async def _require_single_workspace_nurture_campaign(
    *,
    workspace_id: UUID,
    campaign_admin_repository: CampaignAdminRepository,
) -> CampaignAdminCampaign:
    campaign = await _single_workspace_nurture_campaign_or_none(
        workspace_id=workspace_id,
        campaign_admin_repository=campaign_admin_repository,
    )
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=["nurture_settings_not_found"],
        )
    return campaign


async def _current_nurture_settings_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    campaign: CampaignAdminCampaign,
    campaign_admin_repository: CampaignAdminRepository,
) -> CampaignAdminView:
    result = await get_campaign_admin_view(
        actor=actor,
        workspace_id=workspace_id,
        campaign_id=campaign.campaign_id,
        campaign_admin_repository=campaign_admin_repository,
    )
    if result.status == CampaignReadStatus.REJECTED:
        _raise_campaign_admin_rejection(result.reasons)
    if result.status == CampaignReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.view is not None
    draft_version = await campaign_admin_repository.get_latest_draft_version(
        workspace_id,
        campaign.campaign_id,
    )
    if draft_version is None:
        return result.view
    steps = await campaign_admin_repository.get_cadence_steps(
        workspace_id,
        draft_version.campaign_version_id,
    )
    return CampaignAdminView(
        campaign=result.view.campaign,
        version=draft_version,
        cadence_steps=steps,
    )


def _config_from_request(request: CampaignConfigRequest) -> CampaignConfigInput:
    return CampaignConfigInput(
        enabled_channels=tuple(request.enabled_channels),
        daily_start_cap=request.daily_start_cap,
        dormant_threshold_days=request.dormant_threshold_days,
        quiet_hours_start=request.quiet_hours_start,
        quiet_hours_end=request.quiet_hours_end,
        timezone=request.timezone,
        sms_compliance_required=request.sms_compliance_required,
        preflight_digest_enabled=request.preflight_digest_enabled,
        crm_enrollment_tag=request.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=request.allow_assigned_agent_manual_enrollment,
        prompt_version=request.prompt_version,
        approved_model=request.approved_model,
        cadence_steps=tuple(
            CampaignCadenceStepInput(
                channel=step.channel,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                template_key=step.template_key,
                max_attempts=step.max_attempts,
            )
            for step in request.cadence_steps
        ),
    )


def _campaign_summary_response(view: CampaignAdminView) -> CampaignSummaryResponse:
    return CampaignSummaryResponse(
        campaign=_campaign_response(view),
        latest_version=_version_response(view),
        cadence_step_count=len(view.cadence_steps),
    )


def _campaign_detail_response(status_value: str, view: CampaignAdminView) -> CampaignDetailResponse:
    return CampaignDetailResponse(
        status=status_value,
        campaign=_campaign_response(view),
        version=_version_response(view),
        cadence_steps=[_cadence_step_response(step) for step in view.cadence_steps],
    )


def _nurture_settings_detail_response(
    status_value: str,
    view: CampaignAdminView,
) -> NurtureSettingsDetailResponse:
    return NurtureSettingsDetailResponse(
        status=status_value,
        nurture_settings=_nurture_settings_policy_response(view),
        settings=_nurture_settings_config_response(view),
        cadence=[_nurture_cadence_step_response(step) for step in view.cadence_steps],
    )


def _campaign_response(view: CampaignAdminView) -> CampaignResponse:
    campaign = view.campaign
    return CampaignResponse(
        campaign_id=campaign.campaign_id,
        workspace_id=campaign.workspace_id,
        name=campaign.name,
        status=campaign.status.value,
        active_version_id=campaign.active_version_id,
        created_by_user_id=campaign.created_by_user_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _version_response(view: CampaignAdminView) -> CampaignVersionResponse:
    version = view.version
    return CampaignVersionResponse(
        campaign_version_id=version.campaign_version_id,
        campaign_id=version.campaign_id,
        workspace_id=version.workspace_id,
        version_number=version.version_number,
        status=version.status.value,
        enabled_channels=[channel.value for channel in version.enabled_channels],
        daily_start_cap=version.daily_start_cap,
        dormant_threshold_days=version.dormant_threshold_days,
        quiet_hours_start=version.quiet_hours_start,
        quiet_hours_end=version.quiet_hours_end,
        timezone=version.timezone,
        sms_compliance_required=version.sms_compliance_required,
        preflight_digest_enabled=version.preflight_digest_enabled,
        crm_enrollment_tag=version.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
        prompt_version=version.prompt_version,
        approved_model=version.approved_model,
        created_by_user_id=version.created_by_user_id,
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _nurture_settings_policy_response(
    view: CampaignAdminView,
) -> NurtureSettingsPolicyResponse:
    campaign = view.campaign
    return NurtureSettingsPolicyResponse(
        nurture_settings_id=campaign.campaign_id,
        workspace_id=campaign.workspace_id,
        name=campaign.name,
        status=campaign.status.value,
        active_settings_version_id=campaign.active_version_id,
        created_by_user_id=campaign.created_by_user_id,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


def _nurture_settings_config_response(
    view: CampaignAdminView,
) -> NurtureSettingsConfigResponse:
    version = view.version
    return NurtureSettingsConfigResponse(
        settings_version_id=version.campaign_version_id,
        nurture_settings_id=version.campaign_id,
        workspace_id=version.workspace_id,
        revision=version.version_number,
        status=version.status.value,
        enabled_channels=[channel.value for channel in version.enabled_channels],
        daily_start_cap=version.daily_start_cap,
        dormant_threshold_days=version.dormant_threshold_days,
        quiet_hours_start=version.quiet_hours_start,
        quiet_hours_end=version.quiet_hours_end,
        timezone=version.timezone,
        sms_compliance_required=version.sms_compliance_required,
        preflight_digest_enabled=version.preflight_digest_enabled,
        crm_enrollment_tag=version.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
        prompt_version=version.prompt_version,
        approved_model=version.approved_model,
        created_by_user_id=version.created_by_user_id,
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _cadence_step_response(step: CampaignAdminCadenceStep) -> CampaignCadenceStepResponse:
    return CampaignCadenceStepResponse(
        cadence_step_id=step.cadence_step_id,
        campaign_version_id=step.campaign_version_id,
        step_order=step.step_order,
        channel=step.channel.value,
        delay_hours=step.delay_hours,
        message_goal=step.message_goal,
        template_key=step.template_key,
        max_attempts=step.max_attempts,
        created_at=step.created_at,
    )


def _nurture_cadence_step_response(
    step: CampaignAdminCadenceStep,
) -> NurtureCadenceStepResponse:
    return NurtureCadenceStepResponse(
        step_id=step.cadence_step_id,
        settings_version_id=step.campaign_version_id,
        step_order=step.step_order,
        channel=step.channel.value,
        delay_hours=step.delay_hours,
        message_goal=step.message_goal,
        template_key=step.template_key,
        max_attempts=step.max_attempts,
        created_at=step.created_at,
    )


def _admin_response(
    status_value: str,
    view: CampaignAdminView | None,
    reasons: tuple[object, ...],
) -> CampaignAdminResponse:
    if view is None:
        return CampaignAdminResponse(
            status=status_value,
            campaign=None,
            version=None,
            cadence_steps=[],
            reasons=[str(reason) for reason in reasons],
        )
    campaign = view.campaign
    version = view.version
    return CampaignAdminResponse(
        status=status_value,
        campaign=CampaignResponse(
            campaign_id=campaign.campaign_id,
            workspace_id=campaign.workspace_id,
            name=campaign.name,
            status=campaign.status.value,
            active_version_id=campaign.active_version_id,
            created_by_user_id=campaign.created_by_user_id,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
        ),
        version=CampaignVersionResponse(
            campaign_version_id=version.campaign_version_id,
            campaign_id=version.campaign_id,
            workspace_id=version.workspace_id,
            version_number=version.version_number,
            status=version.status.value,
            enabled_channels=[channel.value for channel in version.enabled_channels],
            daily_start_cap=version.daily_start_cap,
            dormant_threshold_days=version.dormant_threshold_days,
            quiet_hours_start=version.quiet_hours_start,
            quiet_hours_end=version.quiet_hours_end,
            timezone=version.timezone,
            sms_compliance_required=version.sms_compliance_required,
            preflight_digest_enabled=version.preflight_digest_enabled,
            crm_enrollment_tag=version.crm_enrollment_tag,
            allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
            prompt_version=version.prompt_version,
            approved_model=version.approved_model,
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at,
            published_at=version.published_at,
        ),
        cadence_steps=[
            CampaignCadenceStepResponse(
                cadence_step_id=step.cadence_step_id,
                campaign_version_id=step.campaign_version_id,
                step_order=step.step_order,
                channel=step.channel.value,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                template_key=step.template_key,
                max_attempts=step.max_attempts,
                created_at=step.created_at,
            )
            for step in view.cadence_steps
        ],
        reasons=[str(reason) for reason in reasons],
    )


def _nurture_settings_admin_response(
    status_value: str,
    view: CampaignAdminView | None,
    reasons: tuple[object, ...],
) -> NurtureSettingsAdminResponse:
    if view is None:
        return NurtureSettingsAdminResponse(
            status=status_value,
            nurture_settings=None,
            settings=None,
            cadence=[],
            reasons=[str(reason) for reason in reasons],
        )
    return NurtureSettingsAdminResponse(
        status=status_value,
        nurture_settings=_nurture_settings_policy_response(view),
        settings=_nurture_settings_config_response(view),
        cadence=[_nurture_cadence_step_response(step) for step in view.cadence_steps],
        reasons=[str(reason) for reason in reasons],
    )
