from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4, uuid5

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    PausedSearchTrackAdminAuditLogRepository,
    PausedSearchTrackAdminRepository,
    TemplateRepository,
)
from app.application.use_cases.preview_paused_search_track import (
    paused_search_preview_evidence,
    paused_search_preview_reference,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditAction,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackAdminView,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.paused_search_validation import (
    PausedSearchTrackValidationReport,
    validate_paused_search_track,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.common.ids import PausedSearchTrackId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.leads import PausedSearchReasonCode


class PausedSearchTrackAdminReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    TRACK_NOT_FOUND = "track_not_found"
    TRACK_KEY_TAKEN = "track_key_taken"
    VERSION_NOT_FOUND = "version_not_found"
    VERSION_NOT_DRAFT = "version_not_draft"
    VERSION_NOT_IN_TRACK = "version_not_in_track"
    INVALID_CONFIGURATION = "invalid_configuration"
    INVALID_TRACK_STATUS = "invalid_track_status"
    STALE_DRAFT_VERSION = "stale_draft_version"
    PREVIEW_REFERENCE_REQUIRED = "preview_reference_required"
    PREVIEW_REFERENCE_MISMATCH = "preview_reference_mismatch"
    WARNINGS_NOT_ACKNOWLEDGED = "warnings_not_acknowledged"


class PausedSearchTrackDraftStatus(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    REJECTED = "rejected"


class PausedSearchTrackPublishStatus(StrEnum):
    PUBLISHED = "published"
    REJECTED = "rejected"


class PausedSearchTrackReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class PausedSearchTrackRetireStatus(StrEnum):
    RETIRED = "retired"
    ALREADY_RETIRED = "already_retired"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PausedSearchTrackStepInput:
    phase: PausedSearchTrackStepPhase
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    review_required: bool = False
    interval_days: int | None = None
    max_occurrences: int = 1
    template_version_id: UUID | None = None
    timing_basis: PausedSearchTimingBasis = PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE
    fallback_channel: ContactChannel | None = None


@dataclass(frozen=True)
class PausedSearchTrackConfigInput:
    track_family: PausedSearchTrackFamily
    enabled: bool
    allowed_channels: tuple[ContactChannel, ...]
    default_for_reason_codes: tuple[PausedSearchReasonCode, ...]
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    requires_review_before_publish: bool
    steps: tuple[PausedSearchTrackStepInput, ...]
    default_pause_duration_days: int = 60
    max_duration_days: int = 365
    terminal_behavior: PausedSearchTerminalBehavior = (
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    )


@dataclass(frozen=True)
class PausedSearchTrackDraftResult:
    status: PausedSearchTrackDraftStatus
    view: PausedSearchTrackAdminView | None = None
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()
    validation: PausedSearchTrackValidationReport | None = None


@dataclass(frozen=True)
class PausedSearchTrackPublishResult:
    status: PausedSearchTrackPublishStatus
    view: PausedSearchTrackAdminView | None = None
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()
    validation: PausedSearchTrackValidationReport | None = None


@dataclass(frozen=True)
class PausedSearchTrackListResult:
    status: PausedSearchTrackReadStatus
    views: tuple[PausedSearchTrackAdminView, ...] = ()
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class PausedSearchTrackDetailResult:
    status: PausedSearchTrackReadStatus
    view: PausedSearchTrackAdminView | None = None
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class PausedSearchTrackRetireResult:
    status: PausedSearchTrackRetireStatus
    view: PausedSearchTrackAdminView | None = None
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()


async def build_unsaved_paused_search_track_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track: PausedSearchTrack,
    track_key: str,
    display_name: str,
    config: PausedSearchTrackConfigInput,
    repository: PausedSearchTrackAdminRepository,
    template_repository: TemplateRepository | None = None,
    now: datetime,
) -> tuple[
    PausedSearchTrackAdminView,
    PausedSearchTrackValidationReport,
    dict[UUID, TemplateVersion],
]:
    draft_version = await repository.get_latest_draft_version(workspace_id, track.track_id)
    existing_step_ids: dict[int, UUID] = {}
    if draft_version is None:
        draft_version = _build_version(
            workspace_id=workspace_id,
            track_id=track.track_id,
            track_version_id=uuid5(
                track.track_id,
                f"preview-version:{track_key.strip()}:{display_name.strip()}",
            ),
            version_number=(
                await repository.get_latest_version_number(workspace_id, track.track_id) + 1
            ),
            actor=actor,
            config=config,
            now=now,
        )
    else:
        draft_version = _replace_version_config(draft_version, config)
        existing_step_ids = {
            step.step_order: step.step_id
            for step in await repository.get_steps(workspace_id, draft_version.track_version_id)
        }
    updated_track = replace(
        track,
        track_key=track_key.strip(),
        display_name=display_name.strip(),
        updated_at=now,
    )
    steps = _build_steps(
        workspace_id=workspace_id,
        version_id=draft_version.track_version_id,
        config=config,
        now=now,
    )
    steps = tuple(
        replace(
            step,
            step_id=existing_step_ids.get(
                step.step_order,
                uuid5(draft_version.track_version_id, f"preview-step:{step.step_order}"),
            ),
        )
        for step in steps
    )
    steps, templates = await _resolve_template_bindings(
        workspace_id=workspace_id,
        steps=steps,
        template_repository=template_repository,
    )
    validation = validate_paused_search_track(
        track=updated_track,
        version=draft_version,
        steps=steps,
        for_publish=False,
        templates=templates,
    )
    return (
        PausedSearchTrackAdminView(updated_track, draft_version, steps),
        validation,
        templates or {},
    )


async def create_draft_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_key: str,
    display_name: str,
    config: PausedSearchTrackConfigInput,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    template_repository: TemplateRepository | None = None,
    now: datetime,
    event_bus: EventBus | None = None,
) -> PausedSearchTrackDraftResult:
    if not _can_administer_tracks(actor):
        return _draft_rejected(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED)
    if await repository.get_track_by_key(workspace_id, track_key.strip()) is not None:
        return _draft_rejected(PausedSearchTrackAdminReasonCode.TRACK_KEY_TAKEN)

    track_id = uuid4()
    version_id = uuid4()
    track = PausedSearchTrack(
        track_id=track_id,
        workspace_id=workspace_id,
        track_key=track_key.strip(),
        display_name=display_name.strip(),
        status=PausedSearchTrackStatus.DRAFT,
        active_version_id=None,
        created_by_user_id=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    version = _build_version(
        workspace_id=workspace_id,
        track_id=track_id,
        track_version_id=version_id,
        version_number=1,
        actor=actor,
        config=config,
        now=now,
    )
    steps = _build_steps(workspace_id=workspace_id, version_id=version_id, config=config, now=now)
    steps, templates = await _resolve_template_bindings(
        workspace_id=workspace_id,
        steps=steps,
        template_repository=template_repository,
    )
    validation = validate_paused_search_track(
        track=track,
        version=version,
        steps=steps,
        for_publish=False,
        templates=templates,
    )
    if not validation.publishable:
        return _draft_rejected(
            PausedSearchTrackAdminReasonCode.INVALID_CONFIGURATION,
            validation=validation,
        )

    saved_track = await repository.save_track(track)
    saved_version = await repository.save_version(version)
    saved_steps = await repository.replace_steps(workspace_id, version_id, steps)
    view = PausedSearchTrackAdminView(saved_track, saved_version, saved_steps)
    await _append_audit(
        audit_log_repository, PausedSearchTrackAdminAuditAction.DRAFT_CREATED, actor, view, now
    )
    await _publish_event(event_bus, DomainEventType.PAUSED_SEARCH_TRACK_DRAFT_CREATED, view, actor)
    return PausedSearchTrackDraftResult(
        status=PausedSearchTrackDraftStatus.CREATED,
        view=view,
        validation=validation,
    )


async def update_draft_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    track_key: str,
    display_name: str,
    config: PausedSearchTrackConfigInput,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    template_repository: TemplateRepository | None = None,
    now: datetime,
    event_bus: EventBus | None = None,
) -> PausedSearchTrackDraftResult:
    if not _can_administer_tracks(actor):
        return _draft_rejected(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED)

    track = await repository.get_track(workspace_id, track_id)
    if track is None:
        return _draft_rejected(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND)
    if track.status == PausedSearchTrackStatus.RETIRED:
        return _draft_rejected(PausedSearchTrackAdminReasonCode.INVALID_TRACK_STATUS)

    existing_track = await repository.get_track_by_key(workspace_id, track_key.strip())
    if existing_track is not None and existing_track.track_id != track_id:
        return _draft_rejected(PausedSearchTrackAdminReasonCode.TRACK_KEY_TAKEN)

    draft_version = await repository.get_latest_draft_version(workspace_id, track_id)
    if draft_version is None:
        draft_version = _build_version(
            workspace_id=workspace_id,
            track_id=track_id,
            track_version_id=uuid4(),
            version_number=await repository.get_latest_version_number(workspace_id, track_id) + 1,
            actor=actor,
            config=config,
            now=now,
        )
    else:
        draft_version = _replace_version_config(draft_version, config)

    updated_track = replace(
        track,
        track_key=track_key.strip(),
        display_name=display_name.strip(),
        status=(PausedSearchTrackStatus.DRAFT if track.active_version_id is None else track.status),
        updated_at=now,
    )
    steps = _build_steps(
        workspace_id=workspace_id,
        version_id=draft_version.track_version_id,
        config=config,
        now=now,
    )
    steps, templates = await _resolve_template_bindings(
        workspace_id=workspace_id,
        steps=steps,
        template_repository=template_repository,
    )
    validation = validate_paused_search_track(
        track=updated_track,
        version=draft_version,
        steps=steps,
        for_publish=False,
        templates=templates,
    )
    if not validation.publishable:
        return _draft_rejected(
            PausedSearchTrackAdminReasonCode.INVALID_CONFIGURATION,
            validation=validation,
        )
    saved_track = await repository.save_track(updated_track)
    saved_version = await repository.save_version(draft_version)
    saved_steps = await repository.replace_steps(
        workspace_id, draft_version.track_version_id, steps
    )
    view = PausedSearchTrackAdminView(saved_track, saved_version, saved_steps)
    await _append_audit(
        audit_log_repository, PausedSearchTrackAdminAuditAction.DRAFT_UPDATED, actor, view, now
    )
    await _publish_event(event_bus, DomainEventType.PAUSED_SEARCH_TRACK_DRAFT_UPDATED, view, actor)
    return PausedSearchTrackDraftResult(
        status=PausedSearchTrackDraftStatus.UPDATED,
        view=view,
        validation=validation,
    )


async def publish_paused_search_track_version(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    track_version_id: PausedSearchTrackVersionId,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    template_repository: TemplateRepository | None = None,
    now: datetime,
    event_bus: EventBus | None = None,
    expected_version_number: int | None = None,
    preview_reference: str | None = None,
    confirm_warnings: bool = False,
) -> PausedSearchTrackPublishResult:
    if not _can_administer_tracks(actor):
        return _publish_rejected(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED)
    track = await repository.get_track_for_update(workspace_id, track_id)
    if track is None:
        return _publish_rejected(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND)
    version = await repository.get_version(workspace_id, track_version_id)
    if version is None:
        return _publish_rejected(PausedSearchTrackAdminReasonCode.VERSION_NOT_FOUND)
    if version.track_id != track_id:
        return _publish_rejected(PausedSearchTrackAdminReasonCode.VERSION_NOT_IN_TRACK)
    if version.status != CampaignVersionStatus.DRAFT:
        return _publish_rejected(PausedSearchTrackAdminReasonCode.VERSION_NOT_DRAFT)
    contract_enforced = expected_version_number is not None or preview_reference is not None
    if expected_version_number is not None and version.version_number != expected_version_number:
        return _publish_rejected(PausedSearchTrackAdminReasonCode.STALE_DRAFT_VERSION)

    steps = await repository.get_steps(workspace_id, track_version_id)
    steps, templates = await _resolve_template_bindings(
        workspace_id=workspace_id,
        steps=steps,
        template_repository=template_repository,
    )
    validation = validate_paused_search_track(
        track=track,
        version=version,
        steps=steps,
        for_publish=True,
        templates=templates if template_repository is not None else {},
    )
    if not validation.publishable:
        return _publish_rejected(
            PausedSearchTrackAdminReasonCode.INVALID_CONFIGURATION,
            validation=validation,
        )

    publish_templates = templates or {}
    current_preview_reference = paused_search_preview_reference(
        track,
        version,
        steps,
        validation,
        publish_templates,
    )
    if contract_enforced and preview_reference is None:
        return _publish_rejected(
            PausedSearchTrackAdminReasonCode.PREVIEW_REFERENCE_REQUIRED,
            validation=validation,
        )
    if contract_enforced and preview_reference != current_preview_reference:
        return _publish_rejected(
            PausedSearchTrackAdminReasonCode.PREVIEW_REFERENCE_MISMATCH,
            validation=validation,
        )
    if contract_enforced and validation.warnings and not confirm_warnings:
        return _publish_rejected(
            PausedSearchTrackAdminReasonCode.WARNINGS_NOT_ACKNOWLEDGED,
            validation=validation,
        )

    if template_repository is not None and steps != await repository.get_steps(
        workspace_id,
        track_version_id,
    ):
        steps = await repository.replace_steps(workspace_id, track_version_id, steps)

    await repository.retire_published_versions(
        workspace_id, track_id, except_version_id=track_version_id
    )
    published_version = await repository.save_version(
        replace(version, status=CampaignVersionStatus.PUBLISHED, published_at=now),
    )
    active_track = await repository.save_track(
        replace(
            track,
            status=PausedSearchTrackStatus.ACTIVE,
            active_version_id=track_version_id,
            updated_at=now,
        ),
    )
    mappings = await repository.replace_reason_mappings(
        workspace_id=workspace_id,
        track_id=track_id,
        track_version_id=track_version_id,
        reason_codes=published_version.default_for_reason_codes,
        actor_user_id=actor.user_id,
        now=now,
    )
    view = PausedSearchTrackAdminView(active_track, published_version, steps, mappings)
    preview_evidence = paused_search_preview_evidence(
        track,
        version,
        steps,
        validation,
        publish_templates,
    )
    await _append_audit(
        audit_log_repository,
        PausedSearchTrackAdminAuditAction.VERSION_PUBLISHED,
        actor,
        view,
        now,
        additional_details={
            "publish_evidence": preview_evidence,
            "preview_reference": paused_search_preview_reference(
                track,
                version,
                steps,
                validation,
                publish_templates,
            ),
        },
    )
    await _publish_event(event_bus, DomainEventType.PAUSED_SEARCH_TRACK_PUBLISHED, view, actor)
    return PausedSearchTrackPublishResult(
        status=PausedSearchTrackPublishStatus.PUBLISHED,
        view=view,
        validation=validation,
    )


async def retire_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> PausedSearchTrackRetireResult:
    if not _can_administer_tracks(actor):
        return PausedSearchTrackRetireResult(
            status=PausedSearchTrackRetireStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED,),
        )
    track = await repository.get_track(workspace_id, track_id)
    if track is None:
        return PausedSearchTrackRetireResult(
            status=PausedSearchTrackRetireStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND,),
        )
    if track.status == PausedSearchTrackStatus.RETIRED:
        return PausedSearchTrackRetireResult(
            status=PausedSearchTrackRetireStatus.ALREADY_RETIRED,
            view=await _view_for_track(repository, track),
        )

    await repository.retire_published_versions(workspace_id, track_id, except_version_id=None)
    await repository.clear_reason_mappings_for_track(workspace_id, track_id)
    retired_track = await repository.save_track(
        replace(
            track, status=PausedSearchTrackStatus.RETIRED, active_version_id=None, updated_at=now
        ),
    )
    view = await _view_for_track(repository, retired_track)
    if view is not None:
        await _append_audit(
            audit_log_repository,
            PausedSearchTrackAdminAuditAction.TRACK_RETIRED,
            actor,
            view,
            now,
        )
        await _publish_event(event_bus, DomainEventType.PAUSED_SEARCH_TRACK_RETIRED, view, actor)
    return PausedSearchTrackRetireResult(status=PausedSearchTrackRetireStatus.RETIRED, view=view)


async def list_paused_search_track_views(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    repository: PausedSearchTrackAdminRepository,
) -> PausedSearchTrackListResult:
    if not _can_view_tracks(actor):
        return PausedSearchTrackListResult(
            status=PausedSearchTrackReadStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED,),
        )
    views = [
        view
        for track in await repository.list_tracks(workspace_id)
        if (view := await _view_for_track(repository, track))
    ]
    return PausedSearchTrackListResult(status=PausedSearchTrackReadStatus.OK, views=tuple(views))


async def get_paused_search_track_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    repository: PausedSearchTrackAdminRepository,
) -> PausedSearchTrackDetailResult:
    if not _can_view_tracks(actor):
        return PausedSearchTrackDetailResult(
            status=PausedSearchTrackReadStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED,),
        )
    track = await repository.get_track(workspace_id, track_id)
    if track is None:
        return PausedSearchTrackDetailResult(status=PausedSearchTrackReadStatus.NOT_FOUND)
    view = await _view_for_track(repository, track)
    if view is None:
        return PausedSearchTrackDetailResult(status=PausedSearchTrackReadStatus.NOT_FOUND)
    return PausedSearchTrackDetailResult(status=PausedSearchTrackReadStatus.OK, view=view)


def _draft_rejected(
    reason: PausedSearchTrackAdminReasonCode,
    *,
    validation: PausedSearchTrackValidationReport | None = None,
) -> PausedSearchTrackDraftResult:
    return PausedSearchTrackDraftResult(
        status=PausedSearchTrackDraftStatus.REJECTED,
        reasons=(reason,),
        validation=validation,
    )


def _publish_rejected(
    reason: PausedSearchTrackAdminReasonCode,
    *,
    validation: PausedSearchTrackValidationReport | None = None,
) -> PausedSearchTrackPublishResult:
    return PausedSearchTrackPublishResult(
        status=PausedSearchTrackPublishStatus.REJECTED,
        reasons=(reason,),
        validation=validation,
    )


def _can_administer_tracks(actor: AuthenticatedActor) -> bool:
    return evaluate_permission(actor, PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN).allowed


def _can_view_tracks(actor: AuthenticatedActor) -> bool:
    return evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed


def _build_version(
    *,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    track_version_id: PausedSearchTrackVersionId,
    version_number: int,
    actor: AuthenticatedActor,
    config: PausedSearchTrackConfigInput,
    now: datetime,
) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=track_version_id,
        workspace_id=workspace_id,
        track_id=track_id,
        version_number=version_number,
        status=CampaignVersionStatus.DRAFT,
        track_family=config.track_family,
        enabled=config.enabled,
        allowed_channels=tuple(config.allowed_channels),
        default_for_reason_codes=tuple(config.default_for_reason_codes),
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=config.max_total_touches,
        requires_review_before_publish=config.requires_review_before_publish,
        default_pause_duration_days=config.default_pause_duration_days,
        max_duration_days=config.max_duration_days,
        terminal_behavior=config.terminal_behavior,
        created_by_user_id=actor.user_id,
        created_at=now,
    )


def _replace_version_config(
    version: PausedSearchTrackVersion,
    config: PausedSearchTrackConfigInput,
) -> PausedSearchTrackVersion:
    return replace(
        version,
        track_family=config.track_family,
        enabled=config.enabled,
        allowed_channels=tuple(config.allowed_channels),
        default_for_reason_codes=tuple(config.default_for_reason_codes),
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=config.max_total_touches,
        requires_review_before_publish=config.requires_review_before_publish,
        default_pause_duration_days=config.default_pause_duration_days,
        max_duration_days=config.max_duration_days,
        terminal_behavior=config.terminal_behavior,
    )


def _build_steps(
    *,
    workspace_id: WorkspaceId,
    version_id: PausedSearchTrackVersionId,
    config: PausedSearchTrackConfigInput,
    now: datetime,
) -> tuple[PausedSearchTrackStep, ...]:
    return tuple(
        PausedSearchTrackStep(
            step_id=uuid4(),
            workspace_id=workspace_id,
            track_version_id=version_id,
            step_order=index + 1,
            phase=step.phase,
            channel=step.channel,
            delay_hours=step.delay_hours,
            message_goal=step.message_goal.strip(),
            template_key=step.template_key.strip(),
            max_attempts=step.max_attempts,
            review_required=step.review_required,
            interval_days=step.interval_days,
            max_occurrences=step.max_occurrences,
            template_version_id=step.template_version_id,
            timing_basis=step.timing_basis,
            fallback_channel=step.fallback_channel,
            created_at=now,
        )
        for index, step in enumerate(config.steps)
    )


async def _resolve_template_bindings(
    *,
    workspace_id: WorkspaceId,
    steps: tuple[PausedSearchTrackStep, ...],
    template_repository: TemplateRepository | None,
) -> tuple[tuple[PausedSearchTrackStep, ...], dict[UUID, TemplateVersion] | None]:
    if template_repository is None:
        return steps, None
    resolved: dict[UUID, TemplateVersion] = {}
    bound_steps: list[PausedSearchTrackStep] = []
    for step in steps:
        template = (
            await template_repository.get_by_id(workspace_id, step.template_version_id)
            if step.template_version_id is not None
            else await template_repository.get_latest_approved_by_key(
                workspace_id,
                step.template_key,
            )
        )
        if template is not None:
            resolved[template.template_version_id] = template
            step = replace(step, template_version_id=template.template_version_id)
        bound_steps.append(step)
    return tuple(bound_steps), resolved


async def _view_for_track(
    repository: PausedSearchTrackAdminRepository,
    track: PausedSearchTrack,
) -> PausedSearchTrackAdminView | None:
    version = None
    if track.active_version_id is not None:
        version = await repository.get_version(track.workspace_id, track.active_version_id)
    if version is None:
        version = await repository.get_latest_version(track.workspace_id, track.track_id)
    if version is None:
        return None
    steps = await repository.get_steps(track.workspace_id, version.track_version_id)
    mappings = await repository.list_reason_mappings_for_version(
        track.workspace_id,
        version.track_version_id,
    )
    return PausedSearchTrackAdminView(track, version, steps, mappings)


async def _append_audit(
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    action: PausedSearchTrackAdminAuditAction,
    actor: AuthenticatedActor,
    view: PausedSearchTrackAdminView,
    now: datetime,
    additional_details: dict[str, object] | None = None,
) -> None:
    await audit_log_repository.append(
        PausedSearchTrackAdminAuditLog(
            audit_log_id=uuid4(),
            workspace_id=view.track.workspace_id,
            track_id=view.track.track_id,
            track_version_id=view.version.track_version_id,
            action=action,
            actor_user_id=actor.user_id,
            details={**_details_for_view(view), **(additional_details or {})},
            created_at=now,
        ),
    )


async def _publish_event(
    event_bus: EventBus | None,
    event_type: DomainEventType,
    view: PausedSearchTrackAdminView,
    actor: AuthenticatedActor,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=view.track.workspace_id,
            aggregate_type=AggregateType.PAUSED_SEARCH_TRACK,
            aggregate_id=view.track.track_id,
            event_type=event_type,
            payload={
                **_details_for_view(view),
                "track_id": str(view.track.track_id),
                "track_version_id": str(view.version.track_version_id),
                "actor_user_id": str(actor.user_id),
            },
        ),
    )


def _details_for_view(view: PausedSearchTrackAdminView) -> dict[str, object]:
    return {
        "track_key": view.track.track_key,
        "display_name": view.track.display_name,
        "track_status": view.track.status.value,
        "version_number": view.version.version_number,
        "version_status": view.version.status.value,
        "track_family": view.version.track_family.value,
        "enabled": view.version.enabled,
        "allowed_channels": [channel.value for channel in view.version.allowed_channels],
        "default_for_reason_codes": [
            reason_code.value for reason_code in view.version.default_for_reason_codes
        ],
        "step_count": len(view.steps),
    }
