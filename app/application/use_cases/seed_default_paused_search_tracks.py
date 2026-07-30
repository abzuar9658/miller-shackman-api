from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    PausedSearchTrackAdminAuditLogRepository,
    PausedSearchTrackAdminRepository,
)
from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackConfigInput,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackPublishStatus,
    PausedSearchTrackStepInput,
    create_draft_paused_search_track,
    publish_paused_search_track_version,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrackFamily,
    PausedSearchTrackStepPhase,
)
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import AuthenticatedActor
from app.domain.leads import PausedSearchReasonCode


class SeedDefaultPausedSearchTrackStatus(StrEnum):
    CREATED = "created"
    SKIPPED_REASON_ALREADY_MAPPED = "skipped_reason_already_mapped"
    SKIPPED_TRACK_KEY_EXISTS = "skipped_track_key_exists"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SeedDefaultPausedSearchTrackItemResult:
    reason_code: PausedSearchReasonCode
    track_key: str
    display_name: str
    status: SeedDefaultPausedSearchTrackStatus
    track_id: UUID | None = None
    track_version_id: UUID | None = None
    reasons: tuple[str, ...] = ()
    detail: str | None = None


@dataclass(frozen=True)
class SeedDefaultPausedSearchTracksResult:
    items: tuple[SeedDefaultPausedSearchTrackItemResult, ...]


@dataclass(frozen=True)
class _DefaultPausedSearchTrackTemplate:
    reason_code: PausedSearchReasonCode
    display_name: str
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    maintenance_message_goal: str
    reactivation_message_goal: str

    @property
    def track_key(self) -> str:
        return f"paused-search-{self.reason_code.value.replace('_', '-')}"


DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES = (
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
        display_name="Rented temporarily",
        maintenance_interval_days=120,
        reactivation_window_days=45,
        max_total_touches=3,
        maintenance_message_goal=(
            "Check in lightly while the lead finishes their current rental "
            "timeline."
        ),
        reactivation_message_goal=(
            "Reconnect as the lead's likely return window approaches."
        ),
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.TIMING_NOT_RIGHT,
        display_name="Timing not right",
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=3,
        maintenance_message_goal="Check whether the lead's timing has changed.",
        reactivation_message_goal=(
            "Offer a soft reactivation check-in as the expected timing "
            "window approaches."
        ),
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.WAITING_FOR_RATES,
        display_name="Waiting for rates",
        maintenance_interval_days=45,
        reactivation_window_days=21,
        max_total_touches=4,
        maintenance_message_goal=(
            "Send a low-pressure readiness check while the lead watches "
            "rates."
        ),
        reactivation_message_goal="Reconnect when the lead may be closer to acting again.",
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.WAITING_FOR_INVENTORY,
        display_name="Waiting for inventory",
        maintenance_interval_days=30,
        reactivation_window_days=14,
        max_total_touches=4,
        maintenance_message_goal=(
            "Check whether the lead still wants help staying aware of the "
            "market."
        ),
        reactivation_message_goal="Reconnect as the lead approaches a renewed search window.",
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.FINANCIAL_PREP,
        display_name="Financial prep",
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=3,
        maintenance_message_goal=(
            "Offer a supportive, non-advisory check-in while the lead "
            "prepares financially."
        ),
        reactivation_message_goal="Reconnect once the lead may be nearing readiness again.",
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.PERSONAL_LIFE_TIMING,
        display_name="Personal life timing",
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=3,
        maintenance_message_goal=(
            "Keep in touch respectfully while the lead handles personal "
            "timing constraints."
        ),
        reactivation_message_goal="Reconnect as the lead's stated timing window approaches.",
    ),
    _DefaultPausedSearchTrackTemplate(
        reason_code=PausedSearchReasonCode.OTHER_KNOWN_PAUSE,
        display_name="Other known pause",
        maintenance_interval_days=90,
        reactivation_window_days=30,
        max_total_touches=3,
        maintenance_message_goal=(
            "Use a gentle check-in for a known paused-search lead with "
            "custom context."
        ),
        reactivation_message_goal=(
            "Reconnect when the lead may be open to restarting the "
            "conversation."
        ),
    ),
)


async def seed_default_paused_search_tracks(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    repository: PausedSearchTrackAdminRepository,
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository,
    now: datetime,
    event_bus: EventBus | None = None,
) -> SeedDefaultPausedSearchTracksResult:
    items: list[SeedDefaultPausedSearchTrackItemResult] = []

    for template in DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES:
        existing_mapping = await repository.get_reason_mapping(
            workspace_id,
            template.reason_code,
        )
        if existing_mapping is not None:
            items.append(
                SeedDefaultPausedSearchTrackItemResult(
                    reason_code=template.reason_code,
                    track_key=template.track_key,
                    display_name=template.display_name,
                    status=SeedDefaultPausedSearchTrackStatus.SKIPPED_REASON_ALREADY_MAPPED,
                    track_id=existing_mapping.track_id,
                    track_version_id=existing_mapping.track_version_id,
                    detail="reason already mapped in this workspace",
                )
            )
            continue

        existing_track = await repository.get_track_by_key(workspace_id, template.track_key)
        if existing_track is not None:
            items.append(
                SeedDefaultPausedSearchTrackItemResult(
                    reason_code=template.reason_code,
                    track_key=template.track_key,
                    display_name=template.display_name,
                    status=SeedDefaultPausedSearchTrackStatus.SKIPPED_TRACK_KEY_EXISTS,
                    track_id=existing_track.track_id,
                    detail="track key already exists; left unchanged",
                )
            )
            continue

        draft = await create_draft_paused_search_track(
            actor=actor,
            workspace_id=workspace_id,
            track_key=template.track_key,
            display_name=template.display_name,
            config=_config_for_template(template),
            repository=repository,
            audit_log_repository=audit_log_repository,
            now=now,
            event_bus=event_bus,
        )
        if draft.status != PausedSearchTrackDraftStatus.CREATED or draft.view is None:
            items.append(
                SeedDefaultPausedSearchTrackItemResult(
                    reason_code=template.reason_code,
                    track_key=template.track_key,
                    display_name=template.display_name,
                    status=SeedDefaultPausedSearchTrackStatus.REJECTED,
                    reasons=tuple(reason.value for reason in draft.reasons),
                    detail="draft creation rejected",
                )
            )
            continue

        publish = await publish_paused_search_track_version(
            actor=actor,
            workspace_id=workspace_id,
            track_id=draft.view.track.track_id,
            track_version_id=draft.view.version.track_version_id,
            repository=repository,
            audit_log_repository=audit_log_repository,
            now=now,
            event_bus=event_bus,
        )
        if publish.status != PausedSearchTrackPublishStatus.PUBLISHED or publish.view is None:
            items.append(
                SeedDefaultPausedSearchTrackItemResult(
                    reason_code=template.reason_code,
                    track_key=template.track_key,
                    display_name=template.display_name,
                    status=SeedDefaultPausedSearchTrackStatus.REJECTED,
                    track_id=draft.view.track.track_id,
                    track_version_id=draft.view.version.track_version_id,
                    reasons=tuple(reason.value for reason in publish.reasons),
                    detail="publish rejected",
                )
            )
            continue

        items.append(
            SeedDefaultPausedSearchTrackItemResult(
                reason_code=template.reason_code,
                track_key=template.track_key,
                display_name=template.display_name,
                status=SeedDefaultPausedSearchTrackStatus.CREATED,
                track_id=publish.view.track.track_id,
                track_version_id=publish.view.version.track_version_id,
            )
        )

    return SeedDefaultPausedSearchTracksResult(items=tuple(items))


def _config_for_template(
    template: _DefaultPausedSearchTrackTemplate,
) -> PausedSearchTrackConfigInput:
    base_key = template.track_key
    return PausedSearchTrackConfigInput(
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=(template.reason_code,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=template.maintenance_interval_days,
        reactivation_window_days=template.reactivation_window_days,
        max_total_touches=template.max_total_touches,
        requires_review_before_publish=False,
        steps=(
            PausedSearchTrackStepInput(
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                channel=ContactChannel.EMAIL,
                delay_hours=24 * template.maintenance_interval_days,
                message_goal=template.maintenance_message_goal,
                template_key=f"{base_key}-maintenance-email-1",
                max_attempts=1,
            ),
            PausedSearchTrackStepInput(
                phase=PausedSearchTrackStepPhase.REACTIVATION,
                channel=ContactChannel.EMAIL,
                delay_hours=0,
                message_goal=template.reactivation_message_goal,
                template_key=f"{base_key}-reactivation-email-1",
                max_attempts=1,
            ),
        ),
    )