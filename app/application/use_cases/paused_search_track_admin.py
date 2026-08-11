from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from math import ceil
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
    DEFAULT_PAUSED_SEARCH_EMAIL_WRITING_PURPOSE,
    DEFAULT_PAUSED_SEARCH_SMS_WRITING_PURPOSE,
    PausedSearchChannelSequence,
    PausedSearchFallbackTimingPolicy,
    PausedSearchInterimContactPolicy,
    PausedSearchReplyPolicy,
    PausedSearchStepAction,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditAction,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackAdminView,
    PausedSearchTrackMode,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.paused_search_validation import (
    MAX_AI_TOUCHES_PER_TRACK,
    PausedSearchTrackValidationReport,
    validate_paused_search_track,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.common.ids import PausedSearchTrackId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.outbound_drafting import DormantStepTemplateProfile


class PausedSearchTrackAdminReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    TRACK_NOT_FOUND = "track_not_found"
    TRACK_NOT_RETIRED = "track_not_retired"
    LEADS_ASSIGNED = "leads_assigned"
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
    LEGACY_CONFIGURATION_NOT_ALLOWED = "legacy_configuration_not_allowed"


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


class PausedSearchTrackRestoreStatus(StrEnum):
    RESTORED = "restored"
    REJECTED = "rejected"


class PausedSearchTrackDeleteStatus(StrEnum):
    DELETED = "deleted"
    BLOCKED = "blocked_leads_assigned"
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
    template_profile: DormantStepTemplateProfile | None = None
    action: PausedSearchStepAction | None = None


@dataclass(frozen=True)
class PausedSearchTrackConfigInput:
    selection_guidance: str
    enabled: bool
    allowed_channels: tuple[ContactChannel, ...]
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    steps: tuple[PausedSearchTrackStepInput, ...]
    default_pause_duration_days: int = 60
    max_duration_days: int = 365
    terminal_behavior: PausedSearchTerminalBehavior = (
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    )
    track_mode: PausedSearchTrackMode = PausedSearchTrackMode.CUSTOM_BOUNDED
    interim_contact_policy: PausedSearchInterimContactPolicy = (
        PausedSearchInterimContactPolicy.NOT_ALLOWED
    )
    reply_policy: PausedSearchReplyPolicy = PausedSearchReplyPolicy.END
    channel_sequence: PausedSearchChannelSequence = PausedSearchChannelSequence.SEQUENTIAL
    max_cycles: int = 1
    max_ai_interactions: int = 5
    restart_delay_days: int = 30
    email_writing_purpose: str = DEFAULT_PAUSED_SEARCH_EMAIL_WRITING_PURPOSE
    sms_writing_purpose: str = DEFAULT_PAUSED_SEARCH_SMS_WRITING_PURPOSE
    compatibility: str = "guided"


MAX_PAUSED_SEARCH_DURATION_DAYS = 730


def _configured_occurrence_cap(step: PausedSearchTrackStepInput) -> int:
    if (
        step.phase is PausedSearchTrackStepPhase.MAINTENANCE
        and step.interval_days is not None
        and step.max_occurrences == 1
    ):
        return MAX_AI_TOUCHES_PER_TRACK
    return step.max_occurrences


def _effective_safety_limits(
    config: PausedSearchTrackConfigInput,
) -> tuple[int, int]:
    """Keep code-owned limits large enough for the configured cadence.

    The request still carries these fields for API compatibility, but a track
    must not silently cap its own configured steps below their occurrence
    count. Customer-date reactivation tracks also need the full platform
    duration so a future lead-selected date is not expired prematurely.
    """

    configured_touches = sum(_configured_occurrence_cap(step) for step in config.steps)
    max_total_touches = min(
        MAX_AI_TOUCHES_PER_TRACK,
        max(config.max_total_touches, configured_touches),
    )

    cadence_horizon_days = max(
        (
            ceil(step.delay_hours / 24)
            + max(0, _configured_occurrence_cap(step) - 1) * (step.interval_days or 0)
            for step in config.steps
        ),
        default=30,
    )
    has_customer_date_reactivation = any(
        step.phase is PausedSearchTrackStepPhase.REACTIVATION
        and step.timing_basis is PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE
        for step in config.steps
    )
    required_duration_days = (
        MAX_PAUSED_SEARCH_DURATION_DAYS if has_customer_date_reactivation else cadence_horizon_days
    )
    max_duration_days = min(
        MAX_PAUSED_SEARCH_DURATION_DAYS,
        max(config.max_duration_days, required_duration_days),
    )
    return max_total_touches, max_duration_days


def _is_legacy_configuration(config: PausedSearchTrackConfigInput) -> bool:
    return (
        config.compatibility == "legacy"
        or config.fallback_timing_policy
        is PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
        or config.reply_policy
        in {
            PausedSearchReplyPolicy.RESTART_AFTER_DELAY,
            PausedSearchReplyPolicy.REVIEW_OR_REMIND,
        }
        or config.channel_sequence is PausedSearchChannelSequence.SIMULTANEOUS
        or any(
            step.review_required
            or step.action in {PausedSearchStepAction.REVIEW, PausedSearchStepAction.REMINDER}
            for step in config.steps
        )
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


@dataclass(frozen=True)
class PausedSearchTrackRestoreResult:
    status: PausedSearchTrackRestoreStatus
    view: PausedSearchTrackAdminView | None = None
    reasons: tuple[PausedSearchTrackAdminReasonCode, ...] = ()


@dataclass(frozen=True)
class PausedSearchTrackDeleteResult:
    status: PausedSearchTrackDeleteStatus
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
    legacy_rejection = _reject_new_legacy_configuration(config)
    if legacy_rejection is not None:
        return legacy_rejection
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
    legacy_rejection = _reject_new_legacy_configuration(config)
    if legacy_rejection is not None:
        return legacy_rejection

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
    view = PausedSearchTrackAdminView(active_track, published_version, steps)
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
        if track.status != PausedSearchTrackStatus.RETIRED
        and (view := await _view_for_track(repository, track))
    ]
    return PausedSearchTrackListResult(status=PausedSearchTrackReadStatus.OK, views=tuple(views))


async def list_retired_paused_search_track_views(
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
        if track.status == PausedSearchTrackStatus.RETIRED
        and (view := await _view_for_track(repository, track))
    ]
    return PausedSearchTrackListResult(status=PausedSearchTrackReadStatus.OK, views=tuple(views))


async def delete_retired_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    now: datetime,
) -> PausedSearchTrackDeleteResult:
    if not _can_administer_tracks(actor):
        return PausedSearchTrackDeleteResult(
            status=PausedSearchTrackDeleteStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED,),
        )
    track = await repository.get_track_for_update(workspace_id, track_id)
    if track is None:
        return PausedSearchTrackDeleteResult(
            status=PausedSearchTrackDeleteStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND,),
        )
    if track.status is not PausedSearchTrackStatus.RETIRED:
        return PausedSearchTrackDeleteResult(
            status=PausedSearchTrackDeleteStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_RETIRED,),
        )
    assigned_leads = await repository.list_assigned_leads(
        workspace_id,
        track_id,
        lock=True,
    )
    view = await _view_for_track(repository, track)
    if view is None:
        return PausedSearchTrackDeleteResult(
            status=PausedSearchTrackDeleteStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND,),
        )
    view = replace(view, assigned_leads=assigned_leads)
    if assigned_leads:
        return PausedSearchTrackDeleteResult(
            status=PausedSearchTrackDeleteStatus.BLOCKED,
            view=view,
            reasons=(PausedSearchTrackAdminReasonCode.LEADS_ASSIGNED,),
        )
    await _append_audit(
        audit_log_repository,
        PausedSearchTrackAdminAuditAction.TRACK_DELETED,
        actor,
        view,
        now,
        additional_details={"deleted_track_id": str(track_id)},
    )
    await repository.delete_retired_track(workspace_id, track_id)
    return PausedSearchTrackDeleteResult(
        status=PausedSearchTrackDeleteStatus.DELETED,
        view=view,
    )


async def restore_retired_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    track_id: PausedSearchTrackId,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> PausedSearchTrackRestoreResult:
    if not _can_administer_tracks(actor):
        return PausedSearchTrackRestoreResult(
            status=PausedSearchTrackRestoreStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.PERMISSION_DENIED,),
        )
    track = await repository.get_track_for_update(workspace_id, track_id)
    if track is None:
        return PausedSearchTrackRestoreResult(
            status=PausedSearchTrackRestoreStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_FOUND,),
        )
    if track.status is not PausedSearchTrackStatus.RETIRED:
        return PausedSearchTrackRestoreResult(
            status=PausedSearchTrackRestoreStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.TRACK_NOT_RETIRED,),
        )
    version = await repository.get_latest_version(workspace_id, track_id)
    if version is None:
        return PausedSearchTrackRestoreResult(
            status=PausedSearchTrackRestoreStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.VERSION_NOT_FOUND,),
        )

    next_version_number = (await repository.get_latest_version_number(workspace_id, track_id)) + 1
    restored_version = await repository.save_version(
        replace(
            version,
            track_version_id=uuid4(),
            version_number=next_version_number,
            status=CampaignVersionStatus.DRAFT,
            published_at=None,
            created_by_user_id=actor.user_id,
            created_at=now,
        ),
    )
    previous_steps = await repository.get_steps(workspace_id, version.track_version_id)
    restored_steps = tuple(
        replace(
            step,
            step_id=uuid4(),
            track_version_id=restored_version.track_version_id,
            created_at=now,
        )
        for step in previous_steps
    )
    await repository.replace_steps(
        workspace_id,
        restored_version.track_version_id,
        restored_steps,
    )
    restored_track = await repository.save_track(
        replace(
            track,
            status=PausedSearchTrackStatus.DRAFT,
            active_version_id=None,
            updated_at=now,
        ),
    )
    view = await _view_for_track(repository, restored_track)
    if view is None:
        return PausedSearchTrackRestoreResult(
            status=PausedSearchTrackRestoreStatus.REJECTED,
            reasons=(PausedSearchTrackAdminReasonCode.VERSION_NOT_FOUND,),
        )
    view = replace(view, version=restored_version)
    await _append_audit(
        audit_log_repository,
        PausedSearchTrackAdminAuditAction.TRACK_RESTORED,
        actor,
        view,
        now,
    )
    await _publish_event(
        event_bus,
        DomainEventType.PAUSED_SEARCH_TRACK_RESTORED,
        view,
        actor,
    )
    return PausedSearchTrackRestoreResult(
        status=PausedSearchTrackRestoreStatus.RESTORED,
        view=view,
    )


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


def _reject_new_legacy_configuration(
    config: PausedSearchTrackConfigInput,
) -> PausedSearchTrackDraftResult | None:
    """Prevent new drafts from opting into deprecated compatibility behavior.

    Persisted versions are still read and executed unchanged. New guided drafts
    must express recurrence through explicit step policy instead of the legacy
    maintenance interval or boolean review switch.
    """

    if _is_legacy_configuration(config):
        return _draft_rejected(PausedSearchTrackAdminReasonCode.LEGACY_CONFIGURATION_NOT_ALLOWED)
    return None


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
    max_total_touches, max_duration_days = _effective_safety_limits(config)
    return PausedSearchTrackVersion(
        track_version_id=track_version_id,
        workspace_id=workspace_id,
        track_id=track_id,
        version_number=version_number,
        status=CampaignVersionStatus.DRAFT,
        selection_guidance=config.selection_guidance.strip(),
        enabled=config.enabled,
        allowed_channels=tuple(config.allowed_channels),
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=max_total_touches,
        default_pause_duration_days=config.default_pause_duration_days,
        max_duration_days=max_duration_days,
        terminal_behavior=config.terminal_behavior,
        track_mode=config.track_mode,
        interim_contact_policy=config.interim_contact_policy,
        reply_policy=config.reply_policy,
        channel_sequence=config.channel_sequence,
        max_cycles=config.max_cycles,
        max_ai_interactions=config.max_ai_interactions,
        restart_delay_days=config.restart_delay_days,
        email_writing_purpose=config.email_writing_purpose.strip(),
        sms_writing_purpose=config.sms_writing_purpose.strip(),
        created_by_user_id=actor.user_id,
        created_at=now,
    )


def _replace_version_config(
    version: PausedSearchTrackVersion,
    config: PausedSearchTrackConfigInput,
) -> PausedSearchTrackVersion:
    max_total_touches, max_duration_days = _effective_safety_limits(config)
    return replace(
        version,
        selection_guidance=config.selection_guidance.strip(),
        enabled=config.enabled,
        allowed_channels=tuple(config.allowed_channels),
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=max_total_touches,
        default_pause_duration_days=config.default_pause_duration_days,
        max_duration_days=max_duration_days,
        terminal_behavior=config.terminal_behavior,
        track_mode=config.track_mode,
        interim_contact_policy=config.interim_contact_policy,
        reply_policy=config.reply_policy,
        channel_sequence=config.channel_sequence,
        max_cycles=config.max_cycles,
        max_ai_interactions=config.max_ai_interactions,
        restart_delay_days=config.restart_delay_days,
        email_writing_purpose=config.email_writing_purpose.strip(),
        sms_writing_purpose=config.sms_writing_purpose.strip(),
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
            template_profile=step.template_profile,
            action=step.action,
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
        if step.template_profile is not None:
            bound_steps.append(replace(step, template_version_id=None))
            continue
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
    # Admin editing must read back the current draft. A published track keeps
    # its active version pinned while edits are stored in a newer draft version.
    version = await repository.get_latest_draft_version(track.workspace_id, track.track_id)
    if version is None and track.active_version_id is not None:
        version = await repository.get_version(track.workspace_id, track.active_version_id)
    if version is None:
        version = await repository.get_latest_version(track.workspace_id, track.track_id)
    if version is None:
        return None
    steps = await repository.get_steps(track.workspace_id, version.track_version_id)
    assigned_leads = await repository.list_assigned_leads(track.workspace_id, track.track_id)
    return PausedSearchTrackAdminView(track, version, steps, assigned_leads)


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
        "selection_guidance": view.version.selection_guidance,
        "enabled": view.version.enabled,
        "allowed_channels": [channel.value for channel in view.version.allowed_channels],
        "step_count": len(view.steps),
    }
