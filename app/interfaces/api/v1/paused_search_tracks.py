from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackAdminReasonCode,
    PausedSearchTrackConfigInput,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackPublishStatus,
    PausedSearchTrackReadStatus,
    PausedSearchTrackRetireStatus,
    PausedSearchTrackStepInput,
    create_draft_paused_search_track,
    get_paused_search_track_view,
    list_paused_search_track_views,
    publish_paused_search_track_version,
    retire_paused_search_track,
    update_draft_paused_search_track,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackAdminView,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.paused_search_tracks import (
    PausedSearchTrackReadBundle,
    PausedSearchTrackServiceBundle,
    get_paused_search_track_read_bundle,
    get_paused_search_track_service_bundle,
)
from app.interfaces.api.schemas.paused_search_tracks import (
    PausedSearchReasonMappingResponse,
    PausedSearchTrackAdminResponse,
    PausedSearchTrackConfigRequest,
    PausedSearchTrackDetailResponse,
    PausedSearchTrackDraftRequest,
    PausedSearchTrackListResponse,
    PausedSearchTrackResponse,
    PausedSearchTrackStepResponse,
    PausedSearchTrackSummaryResponse,
    PausedSearchTrackVersionResponse,
)

router = APIRouter(tags=["paused-search-tracks"])


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
        now=datetime.now(UTC),
        event_bus=bundle.event_bus,
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
        steps=tuple(
            PausedSearchTrackStepInput(
                phase=step.phase,
                channel=step.channel,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                template_key=step.template_key,
                max_attempts=step.max_attempts,
                review_required=step.review_required,
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