from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.use_cases.paused_search_operations import (
    PausedSearchOperationsStatus,
    PausedSearchReviewActionResult,
    apply_paused_search_review_action,
    edit_paused_search_message_review,
    get_paused_search_occurrence,
    get_paused_search_review,
    list_paused_search_occurrences,
    list_paused_search_reviews,
)
from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackAdminReasonCode,
    PausedSearchTrackConfigInput,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackPublishStatus,
    PausedSearchTrackReadStatus,
    PausedSearchTrackRetireStatus,
    PausedSearchTrackStepInput,
    build_unsaved_paused_search_track_view,
    create_draft_paused_search_track,
    get_paused_search_track_view,
    list_paused_search_track_views,
    publish_paused_search_track_version,
    retire_paused_search_track,
    update_draft_paused_search_track,
)
from app.application.use_cases.preview_paused_search_track import (
    PausedSearchTrackPreviewResult,
    preview_paused_search_track_version,
)
from app.application.use_cases.resolve_uncertain_paused_search_occurrence import (
    UncertainOccurrenceResolution,
    UncertainOccurrenceResolutionStatus,
    resolve_uncertain_paused_search_occurrence,
)
from app.domain.campaigns.capability_profiles import CAPABILITY_PROFILES
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.paused_search_occurrences import RecurringOccurrence
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewAction,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchReasonMapping,
    PausedSearchTerminalBehavior,
    PausedSearchTrack,
    PausedSearchTrackAdminView,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.paused_search_validation import (
    PausedSearchTrackValidationReport,
    PausedSearchValidationFinding,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.compliance.contactability import (
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
)
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.leads import CanonicalLeadRecord, LeadPausedSearchProfile
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.interfaces.api.dependencies.lead_paused_search import (
    LeadPausedSearchActionBundle,
    get_lead_paused_search_action_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.paused_search_tracks import (
    PausedSearchOperationsBundle,
    PausedSearchTrackReadBundle,
    PausedSearchTrackServiceBundle,
    get_paused_search_operations_bundle,
    get_paused_search_track_read_bundle,
    get_paused_search_track_service_bundle,
)
from app.interfaces.api.schemas.paused_search_tracks import (
    PausedSearchCapabilityProfileListResponse,
    PausedSearchCapabilityProfileResponse,
    PausedSearchLeadSummaryResponse,
    PausedSearchMessageReviewEditRequest,
    PausedSearchOccurrenceListResponse,
    PausedSearchOccurrenceResponse,
    PausedSearchPolicyReviewResolveRequest,
    PausedSearchReasonMappingResponse,
    PausedSearchReviewActionRequest,
    PausedSearchReviewActionResponse,
    PausedSearchReviewListResponse,
    PausedSearchReviewResponse,
    PausedSearchTemplateListResponse,
    PausedSearchTemplateResponse,
    PausedSearchTrackAdminResponse,
    PausedSearchTrackConfigRequest,
    PausedSearchTrackDetailResponse,
    PausedSearchTrackDraftPreviewRequest,
    PausedSearchTrackDraftRequest,
    PausedSearchTrackDraftValidateRequest,
    PausedSearchTrackDraftValidationResponse,
    PausedSearchTrackListResponse,
    PausedSearchTrackPreviewOccurrenceResponse,
    PausedSearchTrackPreviewResponse,
    PausedSearchTrackPublishRequest,
    PausedSearchTrackResponse,
    PausedSearchTrackStepResponse,
    PausedSearchTrackSummaryResponse,
    PausedSearchTrackValidationResponse,
    PausedSearchTrackVersionResponse,
    PausedSearchValidationFindingResponse,
    UncertainOccurrenceResolutionRequest,
    UncertainOccurrenceResolutionResponse,
)

router = APIRouter(tags=["paused-search-tracks"])


@router.post(
    "/{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}/resolve",
)
async def resolve_uncertain_occurrence_route(
    workspace_id: UUID,
    occurrence_id: UUID,
    payload: UncertainOccurrenceResolutionRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadPausedSearchActionBundle,
        Depends(get_lead_paused_search_action_bundle),
    ],
) -> UncertainOccurrenceResolutionResponse:
    if bundle.occurrence_repository is None or bundle.workflow_transition_repository is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    result = await resolve_uncertain_paused_search_occurrence(
        workspace_id=workspace_id,
        occurrence_id=occurrence_id,
        resolution=UncertainOccurrenceResolution(payload.resolution),
        reason=payload.reason,
        occurrence_repository=bundle.occurrence_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        now=datetime.now(UTC),
        actor_user_id=actor.user_id,
        actor=actor,
        lead_repository=bundle.lead_repository,
    )
    if result.status is UncertainOccurrenceResolutionStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status is UncertainOccurrenceResolutionStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="occurrence_not_found")
    if result.status is UncertainOccurrenceResolutionStatus.ALREADY_RESOLVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="occurrence_already_resolved",
        )
    await bundle.session.commit()
    return UncertainOccurrenceResolutionResponse(
        status=result.status.value,
        occurrence_id=result.occurrence.occurrence_id if result.occurrence else None,
        occurrence_status=result.occurrence.status.value if result.occurrence else None,
        workflow_state=result.workflow_state.value if result.workflow_state else None,
    )


@router.get(
    "/{workspace_id}/paused-search-tracks/occurrences",
    response_model=PausedSearchOccurrenceListResponse,
)
async def list_paused_search_occurrences_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
    lead_id: Annotated[UUID | None, Query()] = None,
    occurrence_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PausedSearchOccurrenceListResponse:
    result = await list_paused_search_occurrences(
        actor=actor,
        workspace_id=workspace_id,
        occurrence_repository=bundle.occurrence_repository,
        lead_repository=bundle.lead_repository,
        lead_id=lead_id,
        status=occurrence_status,
        limit=limit,
    )
    _raise_operations_read_error(result.status, result.reasons)
    return PausedSearchOccurrenceListResponse(
        status=result.status.value,
        occurrences=[
            _occurrence_response(view.occurrence, view.lead) for view in result.occurrences
        ],
        reasons=[reason.value for reason in result.reasons],
    )


@router.get(
    "/{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}",
    response_model=PausedSearchOccurrenceResponse,
)
async def get_paused_search_occurrence_route(
    workspace_id: UUID,
    occurrence_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchOccurrenceResponse:
    result = await get_paused_search_occurrence(
        actor=actor,
        workspace_id=workspace_id,
        occurrence_id=occurrence_id,
        occurrence_repository=bundle.occurrence_repository,
        lead_repository=bundle.lead_repository,
    )
    _raise_operations_read_error(result.status, result.reasons)
    assert result.occurrence is not None
    return _occurrence_response(result.occurrence.occurrence, result.occurrence.lead)


@router.get(
    "/{workspace_id}/paused-search-tracks/reviews",
    response_model=PausedSearchReviewListResponse,
)
async def list_paused_search_reviews_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
    lead_id: Annotated[UUID | None, Query()] = None,
    review_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> PausedSearchReviewListResponse:
    result = await list_paused_search_reviews(
        actor=actor,
        workspace_id=workspace_id,
        review_repository=bundle.review_repository,
        lead_repository=bundle.lead_repository,
        lead_id=lead_id,
        status=review_status,
        limit=limit,
        message_repository=bundle.message_repository,
    )
    _raise_operations_read_error(result.status, result.reasons)
    return PausedSearchReviewListResponse(
        status=result.status.value,
        reviews=[
            _review_response(view.review, view.lead, view.message) for view in result.reviews
        ],
        reasons=[reason.value for reason in result.reasons],
    )


@router.get(
    "/{workspace_id}/paused-search-tracks/reviews/{review_id}",
    response_model=PausedSearchReviewResponse,
)
async def get_paused_search_review_route(
    workspace_id: UUID,
    review_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchReviewResponse:
    result = await get_paused_search_review(
        actor=actor,
        workspace_id=workspace_id,
        review_id=review_id,
        review_repository=bundle.review_repository,
        lead_repository=bundle.lead_repository,
        message_repository=bundle.message_repository,
    )
    _raise_operations_read_error(result.status, result.reasons)
    assert result.review is not None
    return _review_response(result.review.review, result.review.lead, result.review.message)


@router.post(
    "/{workspace_id}/paused-search-tracks/reviews/{review_id}/approve",
    response_model=PausedSearchReviewActionResponse,
)
async def approve_paused_search_review_route(
    workspace_id: UUID,
    review_id: UUID,
    payload: PausedSearchReviewActionRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchReviewActionResponse:
    return await _apply_review_action_route(
        workspace_id=workspace_id,
        review_id=review_id,
        actor=actor,
        bundle=bundle,
        action=PausedSearchReviewAction.APPROVE,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
    )


@router.post(
    "/{workspace_id}/paused-search-tracks/reviews/{review_id}/reject",
    response_model=PausedSearchReviewActionResponse,
)
async def reject_paused_search_review_route(
    workspace_id: UUID,
    review_id: UUID,
    payload: PausedSearchReviewActionRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchReviewActionResponse:
    return await _apply_review_action_route(
        workspace_id=workspace_id,
        review_id=review_id,
        actor=actor,
        bundle=bundle,
        action=PausedSearchReviewAction.REJECT,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
    )


@router.put(
    "/{workspace_id}/paused-search-tracks/reviews/{review_id}",
    response_model=PausedSearchReviewActionResponse,
)
async def edit_paused_search_review_route(
    workspace_id: UUID,
    review_id: UUID,
    payload: PausedSearchMessageReviewEditRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchReviewActionResponse:
    result = await edit_paused_search_message_review(
        actor=actor,
        workspace_id=workspace_id,
        review_id=review_id,
        body=payload.body,
        subject=payload.subject,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
        review_repository=bundle.review_repository,
        message_repository=bundle.message_repository,
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        now=datetime.now(UTC),
    )
    return await _review_action_response(
        result=result,
        workspace_id=workspace_id,
        bundle=bundle,
    )


@router.post(
    "/{workspace_id}/paused-search-tracks/reviews/{review_id}/resolve",
    response_model=PausedSearchReviewActionResponse,
)
async def resolve_paused_search_review_route(
    workspace_id: UUID,
    review_id: UUID,
    payload: PausedSearchPolicyReviewResolveRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchOperationsBundle,
        Depends(get_paused_search_operations_bundle),
    ],
) -> PausedSearchReviewActionResponse:
    return await _apply_review_action_route(
        workspace_id=workspace_id,
        review_id=review_id,
        actor=actor,
        bundle=bundle,
        action=PausedSearchReviewAction.RESOLVE,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
        resolution_action=payload.resolution_action,
        target_track_version_id=payload.target_track_version_id,
        terminal_behavior=payload.terminal_behavior,
    )


@router.get("/{workspace_id}/paused-search-tracks")
async def list_paused_search_tracks(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[PausedSearchTrackReadBundle, Depends(get_paused_search_track_read_bundle)],
) -> PausedSearchTrackListResponse:
    result = await list_paused_search_track_views(
        actor=actor,
        workspace_id=workspace_id,
        repository=bundle.track_repository,
    )
    if result.status == PausedSearchTrackReadStatus.REJECTED:
        _raise_rejection(result.reasons)
    return PausedSearchTrackListResponse(
        status=result.status.value,
        tracks=[_summary_response(view) for view in result.views],
    )


@router.get("/{workspace_id}/paused-search-tracks/templates")
async def list_paused_search_templates(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTemplateListResponse:
    _require_track_viewer(actor)
    if bundle.template_repository is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    templates = await bundle.template_repository.list_approved(workspace_id)
    return PausedSearchTemplateListResponse(
        templates=[_template_response(template) for template in templates]
    )


@router.get("/{workspace_id}/paused-search-tracks/profiles")
async def list_paused_search_profiles(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
) -> PausedSearchCapabilityProfileListResponse:
    _require_track_viewer(actor)
    del workspace_id
    return PausedSearchCapabilityProfileListResponse(
        profiles=[
            PausedSearchCapabilityProfileResponse(
                profile_key=profile.profile_key,
                profile_version=profile.profile_version,
                reason_code=profile.reason_code.value,
                min_recurring_interval_days=profile.min_recurring_interval_days,
                max_recurring_interval_days=profile.max_recurring_interval_days,
                max_total_touches=profile.max_total_touches,
                max_duration_days=profile.max_duration_days,
                required_safety_tags=list(profile.required_safety_tags),
                restriction=profile.restriction,
            )
            for profile in CAPABILITY_PROFILES.values()
        ]
    )


@router.get("/{workspace_id}/paused-search-tracks/{track_id}")
async def get_paused_search_track(
    workspace_id: UUID,
    track_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[PausedSearchTrackReadBundle, Depends(get_paused_search_track_read_bundle)],
) -> PausedSearchTrackDetailResponse:
    result = await get_paused_search_track_view(
        actor=actor,
        workspace_id=workspace_id,
        track_id=track_id,
        repository=bundle.track_repository,
    )
    if result.status == PausedSearchTrackReadStatus.REJECTED:
        _raise_rejection(result.reasons)
    if result.status == PausedSearchTrackReadStatus.NOT_FOUND or result.view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["track_not_found"])
    return _detail_response(result.status.value, result.view)


@router.post("/{workspace_id}/paused-search-tracks/{track_id}/draft/validate")
async def validate_paused_search_track_draft(
    workspace_id: UUID,
    track_id: UUID,
    payload: PausedSearchTrackDraftValidateRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackDraftValidationResponse:
    _require_track_admin(actor)
    track = await bundle.track_repository.get_track(workspace_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["track_not_found"])
    view, validation, _ = await build_unsaved_paused_search_track_view(
        actor=actor,
        workspace_id=workspace_id,
        track=track,
        track_key=payload.track_key,
        display_name=payload.display_name,
        config=_config_input(payload),
        repository=bundle.track_repository,
        template_repository=bundle.template_repository,
        now=datetime.now(UTC),
    )
    return PausedSearchTrackDraftValidationResponse(
        status="valid" if validation.publishable else "blocked",
        track_version_id=view.version.track_version_id,
        validation=_validation_response(validation),
    )


@router.post("/{workspace_id}/paused-search-tracks/{track_id}/draft/preview")
async def preview_paused_search_track_draft(
    workspace_id: UUID,
    track_id: UUID,
    payload: PausedSearchTrackDraftPreviewRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackPreviewResponse:
    _require_track_admin(actor)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=["invalid_timezone"],
        ) from exc
    track = await bundle.track_repository.get_track(workspace_id, track_id)
    if track is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["track_not_found"])
    view, _, templates = await build_unsaved_paused_search_track_view(
        actor=actor,
        workspace_id=workspace_id,
        track=track,
        track_key=payload.track_key,
        display_name=payload.display_name,
        config=_config_input(payload),
        repository=bundle.track_repository,
        template_repository=bundle.template_repository,
        now=payload.as_of,
    )
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        pause_reason_code=(
            view.version.default_for_reason_codes[0]
            if view.version.default_for_reason_codes
            else None
        ),
        reengagement_not_before=payload.reengagement_not_before,
    )
    workflow = LeadWorkflow(
        workflow_id=uuid5(track_id, "preview-workflow"),
        temporal_workflow_id=f"preview-{track_id}",
        workspace_id=workspace_id,
        campaign_enrollment_id=uuid5(track_id, "preview-enrollment"),
        campaign_id=uuid5(track_id, "preview-campaign"),
        lead_id=uuid5(track_id, "preview-lead"),
        state=WorkflowState.PAUSED,
        last_transition_at=payload.as_of,
        state_version=0,
        created_at=payload.as_of,
        updated_at=payload.as_of,
        paused_search_track_version_id=view.version.track_version_id,
    )
    contact_policy: WorkspaceContactPolicy = default_workspace_contact_policy(workspace_id)
    if bundle.workspace_contact_policy_repository is not None:
        contact_policy = (
            await bundle.workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
            or contact_policy
        )
    result = await preview_paused_search_track_version(
        actor=actor,
        track=view.track,
        version=view.version,
        steps=view.steps,
        profile=profile,
        workflow=workflow,
        timezone=payload.timezone,
        now=payload.as_of,
        templates=templates,
        quiet_hours_enabled=contact_policy.quiet_hours_enabled,
        quiet_hours_start=contact_policy.quiet_hours_start,
        quiet_hours_end=contact_policy.quiet_hours_end,
    )
    return _preview_response(result, view.version.track_version_id)


@router.post("/{workspace_id}/paused-search-tracks", status_code=status.HTTP_201_CREATED)
async def create_paused_search_track(
    workspace_id: UUID,
    payload: PausedSearchTrackDraftRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackAdminResponse:
    result = await create_draft_paused_search_track(
        actor=actor,
        workspace_id=workspace_id,
        track_key=payload.track_key,
        display_name=payload.display_name,
        config=_config_input(payload),
        repository=bundle.track_repository,
        audit_log_repository=bundle.audit_log_repository,
        template_repository=bundle.template_repository,
        now=datetime.now(UTC),
        event_bus=bundle.event_bus,
    )
    if result.status == PausedSearchTrackDraftStatus.REJECTED:
        _raise_rejection(result.reasons)
    assert result.view is not None
    await bundle.session.commit()
    return _admin_response(result.status.value, result.view)


@router.put("/{workspace_id}/paused-search-tracks/{track_id}/draft")
async def update_paused_search_track(
    workspace_id: UUID,
    track_id: UUID,
    payload: PausedSearchTrackDraftRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackAdminResponse:
    result = await update_draft_paused_search_track(
        actor=actor,
        workspace_id=workspace_id,
        track_id=track_id,
        track_key=payload.track_key,
        display_name=payload.display_name,
        config=_config_input(payload),
        repository=bundle.track_repository,
        audit_log_repository=bundle.audit_log_repository,
        template_repository=bundle.template_repository,
        now=datetime.now(UTC),
        event_bus=bundle.event_bus,
    )
    if result.status == PausedSearchTrackDraftStatus.REJECTED:
        _raise_rejection(result.reasons)
    assert result.view is not None
    await bundle.session.commit()
    return _admin_response(result.status.value, result.view)


@router.post("/{workspace_id}/paused-search-tracks/{track_id}/versions/{track_version_id}/publish")
async def publish_paused_search_track(
    workspace_id: UUID,
    track_id: UUID,
    track_version_id: UUID,
    payload: PausedSearchTrackPublishRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackAdminResponse:
    result = await publish_paused_search_track_version(
        actor=actor,
        workspace_id=workspace_id,
        track_id=track_id,
        track_version_id=track_version_id,
        repository=bundle.track_repository,
        audit_log_repository=bundle.audit_log_repository,
        template_repository=bundle.template_repository,
        now=datetime.now(UTC),
        event_bus=bundle.event_bus,
        expected_version_number=payload.draft_version_number,
        preview_reference=payload.preview_reference,
        confirm_warnings=payload.confirm_warnings,
    )
    if result.status == PausedSearchTrackPublishStatus.REJECTED:
        _raise_rejection(result.reasons)
    assert result.view is not None
    await bundle.session.commit()
    return _admin_response(result.status.value, result.view)


@router.post("/{workspace_id}/paused-search-tracks/{track_id}/retire")
async def retire_paused_search_track_route(
    workspace_id: UUID,
    track_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        PausedSearchTrackServiceBundle,
        Depends(get_paused_search_track_service_bundle),
    ],
) -> PausedSearchTrackAdminResponse:
    result = await retire_paused_search_track(
        actor=actor,
        workspace_id=workspace_id,
        track_id=track_id,
        repository=bundle.track_repository,
        audit_log_repository=bundle.audit_log_repository,
        now=datetime.now(UTC),
        event_bus=bundle.event_bus,
    )
    if result.status == PausedSearchTrackRetireStatus.REJECTED:
        _raise_rejection(result.reasons)
    assert result.view is not None
    await bundle.session.commit()
    return _admin_response(result.status.value, result.view)


async def _apply_review_action_route(
    *,
    workspace_id: UUID,
    review_id: UUID,
    actor: AuthenticatedActor,
    bundle: PausedSearchOperationsBundle,
    action: PausedSearchReviewAction,
    reason: str,
    idempotency_key: str,
    resolution_action: str | None = None,
    target_track_version_id: UUID | None = None,
    terminal_behavior: str | None = None,
) -> PausedSearchReviewActionResponse:
    result = await apply_paused_search_review_action(
        actor=actor,
        workspace_id=workspace_id,
        review_id=review_id,
        action=action,
        reason=reason,
        review_repository=bundle.review_repository,
        occurrence_repository=bundle.occurrence_repository,
        lead_repository=bundle.lead_repository,
        action_lead_repository=bundle.action_lead_repository,
        action_workflow_repository=bundle.action_workflow_repository,
        workflow_repository=bundle.workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        external_event_repository=bundle.external_event_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        lead_workflow_override_audit_repository=bundle.lead_workflow_override_audit_repository,
        workspace_repository=bundle.workspace_repository,
        paused_search_occurrence_repository=bundle.occurrence_transition_repository,
        commit=bundle.session.commit,
        message_repository=bundle.message_repository,
        idempotency_key=idempotency_key,
        resolution_action=resolution_action,
        target_track_version_id=target_track_version_id,
        terminal_behavior=(
            PausedSearchTerminalBehavior(terminal_behavior)
            if terminal_behavior is not None
            else None
        ),
        now=datetime.now(UTC),
    )
    return await _review_action_response(
        result=result,
        workspace_id=workspace_id,
        bundle=bundle,
    )


async def _review_action_response(
    *,
    result: PausedSearchReviewActionResult,
    workspace_id: UUID,
    bundle: PausedSearchOperationsBundle,
) -> PausedSearchReviewActionResponse:
    if result.status is PausedSearchOperationsStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=list(result.reasons))
    if result.status is PausedSearchOperationsStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=list(result.reasons))
    if result.status is PausedSearchOperationsStatus.INVALID:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=list(result.reasons))
    if result.status is PausedSearchOperationsStatus.OK:
        await bundle.session.commit()
    review_response = None
    if result.review is not None:
        lead = await bundle.lead_repository.get_by_id(workspace_id, result.review.lead_id)
        if lead is not None:
            review_response = _review_response(result.review, lead, result.message)
    occurrence_response = None
    if result.occurrence is not None:
        lead = await bundle.lead_repository.get_by_id(workspace_id, result.occurrence.lead_id)
        if lead is not None:
            occurrence_response = _occurrence_response(result.occurrence, lead)
    return PausedSearchReviewActionResponse(
        status=result.status.value,
        review=review_response,
        occurrence=occurrence_response,
        reasons=[reason.value for reason in result.reasons],
    )


def _raise_operations_read_error(
    result_status: PausedSearchOperationsStatus,
    reasons: tuple[object, ...],
) -> None:
    if result_status is PausedSearchOperationsStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[str(reason) for reason in reasons],
        )
    if result_status is PausedSearchOperationsStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[str(reason) for reason in reasons],
        )


def _lead_summary_response(lead: object) -> PausedSearchLeadSummaryResponse:
    canonical_lead = cast("CanonicalLeadRecord", lead)
    return PausedSearchLeadSummaryResponse(
        lead_id=canonical_lead.lead_id,
        display_name=(
            canonical_lead.mapped_custom_fields.get("display_name")
            or canonical_lead.crm_lead_id
        ),
        assigned_agent_user_id=canonical_lead.effective_owner_user_id,
    )


def _occurrence_response(occurrence: object, lead: object) -> PausedSearchOccurrenceResponse:
    item = cast("RecurringOccurrence", occurrence)
    return PausedSearchOccurrenceResponse(
        occurrence_id=item.occurrence_id,
        lead_id=item.lead_id,
        workflow_id=item.workflow_id,
        track_version_id=item.track_version_id,
        step_id=item.step_id,
        phase=item.phase.value,
        occurrence_number=item.occurrence_number,
        scheduled_for=item.scheduled_for,
        due_at=item.due_at,
        status=item.status.value,
        logical_touch_count=item.logical_touch_count,
        provider_message_id=item.provider_message_id,
        provider_delivery_status=(
            item.provider_delivery_status.value
            if item.provider_delivery_status is not None
            else None
        ),
        closed_at=item.closed_at,
        failure_reason=item.failure_reason,
        lead=_lead_summary_response(lead),
    )


def _review_response(
    review: object,
    lead: object,
    message: OutboundMessage | None = None,
) -> PausedSearchReviewResponse:
    item = cast("PausedSearchReview", review)
    return PausedSearchReviewResponse(
        review_id=item.review_id,
        lead_id=item.lead_id,
        workflow_id=item.workflow_id,
        occurrence_id=item.occurrence_id,
        kind=item.kind.value,
        status=item.status.value,
        reason=item.reason,
        requested_at=item.requested_at,
        review_expiry_at=item.review_expiry_at,
        reviewer_user_id=item.reviewer_user_id,
        acted_at=item.acted_at,
        action_reason=item.action_reason,
        outbound_message_id=item.outbound_message_id,
        outbound_message_version=item.outbound_message_version,
        message_channel=message.channel.value if message is not None else None,
        message_subject=message.subject if message is not None else None,
        message_body=message.body if message is not None else None,
        lead=_lead_summary_response(lead),
    )


def _config_input(payload: PausedSearchTrackConfigRequest) -> PausedSearchTrackConfigInput:
    return PausedSearchTrackConfigInput(
        track_family=payload.track_family,
        enabled=payload.enabled,
        allowed_channels=tuple(payload.allowed_channels),
        default_for_reason_codes=tuple(payload.default_for_reason_codes),
        fallback_timing_policy=payload.fallback_timing_policy,
        maintenance_interval_days=payload.maintenance_interval_days,
        reactivation_window_days=payload.reactivation_window_days,
        max_total_touches=payload.max_total_touches,
        requires_review_before_publish=payload.requires_review_before_publish,
        default_pause_duration_days=payload.default_pause_duration_days,
        max_duration_days=payload.max_duration_days,
        terminal_behavior=payload.terminal_behavior,
        steps=tuple(
            PausedSearchTrackStepInput(
                phase=step.phase,
                channel=step.channel,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                template_key=step.template_key,
                max_attempts=step.max_attempts,
                review_required=step.review_required,
                interval_days=step.interval_days,
                max_occurrences=step.max_occurrences,
                template_version_id=step.template_version_id,
                timing_basis=step.timing_basis,
                fallback_channel=step.fallback_channel,
            )
            for step in payload.steps
        ),
    )


def _raise_rejection(reasons: tuple[PausedSearchTrackAdminReasonCode, ...]) -> None:
    if PausedSearchTrackAdminReasonCode.PERMISSION_DENIED in reasons:
        code = status.HTTP_403_FORBIDDEN
    elif (
        PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND in reasons
        or PausedSearchTrackAdminReasonCode.VERSION_NOT_FOUND in reasons
    ):
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=[reason.value for reason in reasons])


def _admin_response(
    status_value: str,
    view: PausedSearchTrackAdminView,
) -> PausedSearchTrackAdminResponse:
    return PausedSearchTrackAdminResponse(
        status=status_value,
        track=_track_response(view.track),
        version=_version_response(view.version),
        steps=[_step_response(step) for step in view.steps],
        reason_mappings=[_mapping_response(mapping) for mapping in view.reason_mappings],
        reasons=[],
    )


def _summary_response(view: PausedSearchTrackAdminView) -> PausedSearchTrackSummaryResponse:
    return PausedSearchTrackSummaryResponse(
        track=_track_response(view.track),
        version=_version_response(view.version),
        step_count=len(view.steps),
        reason_mappings=[_mapping_response(mapping) for mapping in view.reason_mappings],
    )


def _detail_response(
    status_value: str,
    view: PausedSearchTrackAdminView,
) -> PausedSearchTrackDetailResponse:
    return PausedSearchTrackDetailResponse(
        status=status_value,
        track=_track_response(view.track),
        version=_version_response(view.version),
        steps=[_step_response(step) for step in view.steps],
        reason_mappings=[_mapping_response(mapping) for mapping in view.reason_mappings],
    )


def _track_response(track: PausedSearchTrack) -> PausedSearchTrackResponse:
    return PausedSearchTrackResponse(**track.__dict__)


def _version_response(version: PausedSearchTrackVersion) -> PausedSearchTrackVersionResponse:
    data = dict(version.__dict__)
    data["allowed_channels"] = list(version.allowed_channels)
    data["default_for_reason_codes"] = list(version.default_for_reason_codes)
    return PausedSearchTrackVersionResponse(**data)


def _step_response(step: PausedSearchTrackStep) -> PausedSearchTrackStepResponse:
    return PausedSearchTrackStepResponse(**step.__dict__)


def _mapping_response(mapping: PausedSearchReasonMapping) -> PausedSearchReasonMappingResponse:
    return PausedSearchReasonMappingResponse(**mapping.__dict__)


def _require_track_admin(actor: AuthenticatedActor) -> None:
    if not evaluate_permission(actor, PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN).allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[PausedSearchTrackAdminReasonCode.PERMISSION_DENIED.value],
        )


def _require_track_viewer(actor: AuthenticatedActor) -> None:
    if not evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[PausedSearchTrackAdminReasonCode.PERMISSION_DENIED.value],
        )


def _template_response(template: TemplateVersion) -> PausedSearchTemplateResponse:
    return PausedSearchTemplateResponse(
        template_version_id=template.template_version_id,
        template_key=template.template_key,
        version=template.version,
        channel=template.channel.value,
        purpose=template.purpose,
        content=template.content,
        subject=template.subject,
        allowed_variables=list(template.allowed_variables),
        permitted_use_tags=list(template.permitted_use_tags),
        status=template.status.value,
    )


def _validation_response(
    validation: PausedSearchTrackValidationReport,
) -> PausedSearchTrackValidationResponse:
    def finding_response(
        finding: PausedSearchValidationFinding,
    ) -> PausedSearchValidationFindingResponse:
        return PausedSearchValidationFindingResponse(
            code=finding.code.value,
            severity=finding.severity.value,
            field=finding.field,
            detail=finding.detail,
        )

    return PausedSearchTrackValidationResponse(
        publishable=validation.publishable,
        errors=[finding_response(item) for item in validation.errors],
        warnings=[finding_response(item) for item in validation.warnings],
    )


def _preview_response(
    result: PausedSearchTrackPreviewResult,
    track_version_id: UUID,
) -> PausedSearchTrackPreviewResponse:
    return PausedSearchTrackPreviewResponse(
        status=result.status.value,
        track_version_id=track_version_id,
        preview_reference=result.preview_reference,
        validation=_validation_response(result.validation),
        occurrences=[
            PausedSearchTrackPreviewOccurrenceResponse(
                next_action_at=item.plan.next_action_at,
                due_at=item.plan.due_at,
                local_next_action_at=item.local_next_action_at,
                phase=item.plan.phase.value if item.plan.phase is not None else None,
                step_id=item.plan.step_id,
                occurrence_number=item.plan.occurrence_number,
                outcome=item.plan.outcome.value,
                reason_code=item.plan.reason_code.value,
                reason_detail=item.plan.reason_detail,
                channel=item.channel,
                review_required=item.review_required,
            )
            for item in result.occurrences
        ],
        maximum_logical_touches=result.maximum_logical_touches,
        expires_at=result.expires_at,
        local_expires_at=result.local_expires_at,
    )
