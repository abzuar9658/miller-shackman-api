from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.application.services.preflight_actor_resolution import actor_preflight_recipient_ids
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
from app.application.use_cases.workspace_outbound_drafting import (
    OutboundDraftingPreviewResult,
    OutboundDraftingPreviewStatus,
    preview_workspace_outbound_drafting,
)
from app.domain.campaigns.admin import (
    CampaignAdminCadenceStep,
    CampaignAdminCampaign,
    CampaignAdminView,
)
from app.domain.identity import AuthenticatedActor, WorkspaceMembershipRole
from app.domain.identity.permissions import PermissionCapability, evaluate_permission
from app.domain.outbound_drafting import (
    SUPPORTED_QUERY_EXTRACTION_FIELDS,
    SUPPORTED_TEMPLATE_PLACEHOLDERS,
    DormantStepTemplateProfile,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
)
from app.interfaces.api.dependencies.campaign import (
    CampaignReadBundle,
    CampaignServiceBundle,
    get_campaign_read_bundle,
    get_campaign_service_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.workspace_settings import (
    WorkspaceOutboundDraftingPreviewBundle,
    get_workspace_outbound_drafting_preview_bundle,
)
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
    DormantStepTemplateProfileSchema,
    NurtureCadenceStepResponse,
    NurtureSettingsAdminResponse,
    NurtureSettingsConfigResponse,
    NurtureSettingsDetailResponse,
    NurtureSettingsDraftRequest,
    NurtureSettingsPolicyResponse,
    NurtureSettingsPreviewRequest,
    PauseCampaignRequest,
    RecordPreflightVetoRequest,
    RecordPreflightVetoResponse,
    ResumeCampaignRequest,
    RunDormantSelectorRequest,
    RunDormantSelectorResponse,
)
from app.interfaces.api.schemas.workspace import WorkspaceOutboundDraftingPreviewResponse

router = APIRouter(tags=["campaigns"])

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


@router.post(
    "/{workspace_id}/nurture-settings/preview",
    response_model=WorkspaceOutboundDraftingPreviewResponse,
)
async def preview_nurture_settings_route(
    workspace_id: UUID,
    request: NurtureSettingsPreviewRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        WorkspaceOutboundDraftingPreviewBundle,
        Depends(get_workspace_outbound_drafting_preview_bundle),
    ],
) -> WorkspaceOutboundDraftingPreviewResponse:
    if request.draft is not None:
        if request.template_key is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A dormant cadence step is required when previewing a draft",
            )
        draft_config = _config_from_request(workspace_id, request.draft)
        preview_step = next(
            (
                step
                for step in draft_config.cadence_steps
                if step.template_key == request.template_key
            ),
            None,
        )
        if preview_step is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dormant cadence step not found in draft",
            )
        drafting_config = draft_config.outbound_drafting_config
    else:
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
        drafting_config = view.version.outbound_drafting_config or (
            default_workspace_outbound_drafting_config(workspace_id)
        )
        preview_step = None
        if request.template_key is not None:
            preview_step = next(
                (
                    CampaignCadenceStepInput(
                        channel=step.channel,
                        delay_hours=step.delay_hours,
                        message_goal=step.message_goal,
                        template_key=step.template_key,
                        max_attempts=step.max_attempts,
                        template_profile=step.template_profile,
                    )
                    for step in view.cadence_steps
                    if step.template_key == request.template_key
                ),
                None,
            )
            if preview_step is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dormant cadence step not found",
                )
    result = await preview_workspace_outbound_drafting(
        actor=actor,
        workspace_id=workspace_id,
        query=request.query,
        agent_name=request.agent_name,
        brokerage_name=request.brokerage_name,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        workspace_outbound_drafting_config_repository=(
            bundle.workspace_outbound_drafting_config_repository
        ),
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        llm_client=bundle.llm_client,
        listing_source_repository=bundle.listing_source_repository,
        listing_snapshot_repository=bundle.listing_snapshot_repository,
        listing_search_client=bundle.listing_search_client,
        listing_cache_ttl=bundle.listing_cache_ttl,
        now=datetime.now(UTC),
        default_openrouter_model=bundle.default_openrouter_model,
        drafting_config=drafting_config,
        journey_kind=OutboundJourneyKind.DORMANT,
        template_profile=(preview_step.template_profile if preview_step is not None else None),
        template_channel=(preview_step.channel if preview_step is not None else None),
        campaign_goal=(
            preview_step.message_goal if preview_step is not None else "Preview dormant follow-up."
        ),
    )
    if result.status == OutboundDraftingPreviewStatus.REJECTED:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if any(reason.value == "permission_denied" for reason in result.reasons)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=[reason.value for reason in result.reasons],
        )
    return _outbound_drafting_preview_response(result)


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
            config=_config_from_request(workspace_id, request),
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
        config=_config_from_request(workspace_id, request),
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
        config=_config_from_request(workspace_id, request),
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
        config=_config_from_request(workspace_id, request),
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
            detail="You do not have permission to run the dormant selector.",
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
        rollback=bundle.rollback,
        preflight_digest_repository=bundle.preflight_digest_repository,
        notification_provider=bundle.notification_provider,
        crm_client=bundle.crm_client,
        lead_repository=bundle.lead_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        artifact_repository=bundle.artifact_repository,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        llm_client=bundle.llm_client,
        default_openrouter_model=bundle.default_openrouter_model,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        event_bus=bundle.event_bus,
        routing_review_repository=bundle.routing_review_repository,
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
        paused_search_started_count=result.paused_search_started_count,
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
    if actor.active_role not in _ALLOWED_PREFLIGHT_VETO_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only assigned agents, managers, and brokerage admins may record preflight vetoes.",  # noqa: E501
        )

    actor_role = _veto_role_from_membership(actor.active_role)
    actor_id = str(actor.user_id)

    if actor_role == VetoActorRole.ASSIGNED_AGENT:
        resolved_actor_id = await _resolve_assigned_agent_veto_actor_id(
            actor=actor,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            lead_id=request.lead_id,
            preflight_digest_repository=bundle.preflight_digest_repository,
            crm_agent_repository=bundle.crm_agent_repository,
            workspace_agent_crm_mapping_repository=bundle.workspace_agent_crm_mapping_repository,
        )
        if resolved_actor_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=["unauthorized_veto_actor"],
            )
        actor_id = resolved_actor_id

    result = await record_preflight_veto(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        lead_id=request.lead_id,
        actor_id=actor_id,
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
        actor_id=result.actor_id,
        duplicate=result.duplicate,
        reasons=[reason.value for reason in result.reasons],
    )


_ALLOWED_PREFLIGHT_VETO_ROLES: frozenset[WorkspaceMembershipRole] = frozenset(
    {
        WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN,
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        WorkspaceMembershipRole.MANAGER,
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
    }
)


async def _resolve_assigned_agent_veto_actor_id(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    campaign_id: UUID,
    batch_id: str,
    lead_id: UUID,
    preflight_digest_repository: PreflightDigestRepository,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
) -> str | None:
    digest = await preflight_digest_repository.get_digest(workspace_id, campaign_id, batch_id)
    if digest is None:
        return None
    matching_entry = next(
        (entry for entry in digest.entries if entry.lead_id == lead_id),
        None,
    )
    if matching_entry is None:
        return None
    recipient_ids = await actor_preflight_recipient_ids(
        actor=actor,
        workspace_id=workspace_id,
        crm_agent_repository=crm_agent_repository,
        workspace_agent_crm_mapping_repository=workspace_agent_crm_mapping_repository,
    )
    if matching_entry.recipient_id not in recipient_ids:
        return None
    return matching_entry.recipient_id


def _veto_role_from_membership(role: WorkspaceMembershipRole) -> VetoActorRole:
    if role in {
        WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN,
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
    }:
        return VetoActorRole.BROKERAGE_ADMIN
    if role == WorkspaceMembershipRole.MANAGER:
        return VetoActorRole.MANAGER
    if role == WorkspaceMembershipRole.ASSIGNED_AGENT:
        return VetoActorRole.ASSIGNED_AGENT
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


def _config_from_request(
    workspace_id: UUID,
    request: CampaignConfigRequest,
) -> CampaignConfigInput:
    return CampaignConfigInput(
        enabled_channels=tuple(request.enabled_channels),
        daily_start_cap=request.daily_start_cap,
        dormant_threshold_days=request.dormant_threshold_days,
        quiet_hours_start=request.quiet_hours_start,
        quiet_hours_end=request.quiet_hours_end,
        timezone=request.timezone,
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
                template_profile=_template_profile_from_schema(step.template_profile),
            )
            for step in request.cadence_steps
        ),
        outbound_drafting_config=WorkspaceOutboundDraftingConfig(
            workspace_id=workspace_id,
            prompt_text=request.prompt_text,
            sms_prompt_text=request.sms_prompt_text,
            sms_template=request.sms_template,
            email_prompt_text=request.email_prompt_text,
            email_template=request.email_template,
            email_subject_template=request.email_subject_template,
            enabled_extraction_fields=tuple(request.enabled_extraction_fields),
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
    drafting_config = version.outbound_drafting_config or (
        default_workspace_outbound_drafting_config(version.workspace_id)
    )
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
        preflight_digest_enabled=version.preflight_digest_enabled,
        crm_enrollment_tag=version.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
        prompt_version=version.prompt_version,
        approved_model=version.approved_model,
        prompt_text=drafting_config.prompt_text,
        sms_prompt_text=drafting_config.sms_prompt_text,
        sms_template=drafting_config.sms_template,
        email_prompt_text=drafting_config.email_prompt_text,
        email_template=drafting_config.email_template,
        email_subject_template=drafting_config.email_subject_template,
        enabled_extraction_fields=list(drafting_config.enabled_extraction_fields),
        supported_extraction_fields=list(SUPPORTED_QUERY_EXTRACTION_FIELDS),
        supported_template_placeholders=list(SUPPORTED_TEMPLATE_PLACEHOLDERS),
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
    drafting_config = version.outbound_drafting_config or (
        default_workspace_outbound_drafting_config(version.workspace_id)
    )
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
        preflight_digest_enabled=version.preflight_digest_enabled,
        crm_enrollment_tag=version.crm_enrollment_tag,
        allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
        prompt_version=version.prompt_version,
        approved_model=version.approved_model,
        prompt_text=drafting_config.prompt_text,
        sms_prompt_text=drafting_config.sms_prompt_text,
        sms_template=drafting_config.sms_template,
        email_prompt_text=drafting_config.email_prompt_text,
        email_template=drafting_config.email_template,
        email_subject_template=drafting_config.email_subject_template,
        enabled_extraction_fields=list(drafting_config.enabled_extraction_fields),
        supported_extraction_fields=list(SUPPORTED_QUERY_EXTRACTION_FIELDS),
        supported_template_placeholders=list(SUPPORTED_TEMPLATE_PLACEHOLDERS),
        created_by_user_id=version.created_by_user_id,
        created_at=version.created_at,
        published_at=version.published_at,
    )


def _outbound_drafting_preview_response(
    result: OutboundDraftingPreviewResult,
) -> WorkspaceOutboundDraftingPreviewResponse:
    return WorkspaceOutboundDraftingPreviewResponse(
        status=result.status.value,
        parsed_preferences=result.parsed_preferences or {},
        extraction_method=result.extraction_method.value,
        extraction_confidence=result.extraction_confidence,
        extraction_reasons=[reason.value for reason in result.extraction_reasons],
        listing_context_found=result.listing_relevance_brief is not None,
        listing_relevance_brief=result.listing_relevance_brief,
        sms_preview=(
            {
                "status": result.sms_preview.status,
                "body": result.sms_preview.body,
                "subject": result.sms_preview.subject,
                "prompt_version": result.sms_preview.prompt_version,
                "model": result.sms_preview.model,
                "reasons": list(result.sms_preview.reasons),
            }
            if result.sms_preview is not None
            else None
        ),
        email_preview=(
            {
                "status": result.email_preview.status,
                "body": result.email_preview.body,
                "subject": result.email_preview.subject,
                "prompt_version": result.email_preview.prompt_version,
                "model": result.email_preview.model,
                "reasons": list(result.email_preview.reasons),
            }
            if result.email_preview is not None
            else None
        ),
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
        template_profile=_template_profile_schema(step.template_profile),
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
        template_profile=_template_profile_schema(step.template_profile),
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
    drafting_config = version.outbound_drafting_config or (
        default_workspace_outbound_drafting_config(version.workspace_id)
    )
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
            preflight_digest_enabled=version.preflight_digest_enabled,
            crm_enrollment_tag=version.crm_enrollment_tag,
            allow_assigned_agent_manual_enrollment=version.allow_assigned_agent_manual_enrollment,
            prompt_version=version.prompt_version,
            approved_model=version.approved_model,
            prompt_text=drafting_config.prompt_text,
            sms_prompt_text=drafting_config.sms_prompt_text,
            sms_template=drafting_config.sms_template,
            email_prompt_text=drafting_config.email_prompt_text,
            email_template=drafting_config.email_template,
            email_subject_template=drafting_config.email_subject_template,
            enabled_extraction_fields=list(drafting_config.enabled_extraction_fields),
            supported_extraction_fields=list(SUPPORTED_QUERY_EXTRACTION_FIELDS),
            supported_template_placeholders=list(SUPPORTED_TEMPLATE_PLACEHOLDERS),
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
                template_profile=_template_profile_schema(step.template_profile),
            )
            for step in view.cadence_steps
        ],
        reasons=[str(reason) for reason in reasons],
    )


def _template_profile_from_schema(
    profile: DormantStepTemplateProfileSchema | None,
) -> DormantStepTemplateProfile | None:
    if profile is None:
        return None
    return DormantStepTemplateProfile(
        tone=profile.tone,
        style=profile.style,
        length=profile.length,
        call_to_action=profile.call_to_action,
        greeting=profile.greeting,
        sign_off=profile.sign_off,
        listing_context=profile.listing_context,
        personalization_fields=tuple(profile.personalization_fields),
        custom_instructions=profile.custom_instructions,
        custom_sign_off_text=profile.custom_sign_off_text,
    )


def _template_profile_schema(
    profile: DormantStepTemplateProfile | None,
) -> DormantStepTemplateProfileSchema | None:
    if profile is None:
        return None
    return DormantStepTemplateProfileSchema(
        tone=profile.tone,
        style=profile.style,
        length=profile.length,
        call_to_action=profile.call_to_action,
        greeting=profile.greeting,
        sign_off=profile.sign_off,
        listing_context=profile.listing_context,
        personalization_fields=list(profile.personalization_fields),
        custom_instructions=profile.custom_instructions,
        custom_sign_off_text=profile.custom_sign_off_text,
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
