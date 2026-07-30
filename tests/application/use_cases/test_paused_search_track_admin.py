from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.use_cases.paused_search_track_admin import (
    PausedSearchTrackConfigInput,
    PausedSearchTrackDraftStatus,
    PausedSearchTrackPublishStatus,
    PausedSearchTrackStepInput,
    create_draft_paused_search_track,
    publish_paused_search_track_version,
    retire_paused_search_track,
    update_draft_paused_search_track,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import PausedSearchTrackId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.events import DomainEvent, DomainEventType
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import PausedSearchReasonCode

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
PREVIOUS_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000005")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000006")


def test_create_draft_paused_search_track_persists_audit_and_event() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    audit_repo = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(),
            repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackDraftStatus.CREATED
    assert result.view is not None
    assert result.view.track.status == PausedSearchTrackStatus.DRAFT
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert result.view.steps[0].phase == PausedSearchTrackStepPhase.MAINTENANCE
    assert audit_repo.logs[-1].action.value == "paused_search_track_draft_created"
    assert event_bus.events[-1].event_type == DomainEventType.PAUSED_SEARCH_TRACK_DRAFT_CREATED


def test_create_draft_rejects_assigned_agent_and_duplicate_reason_mapping() -> None:
    permission_result = _run(
        create_draft_paused_search_track(
            actor=_actor(role=WorkspaceMembershipRole.ASSIGNED_AGENT),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(),
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )
    mapping_result = _run(
        create_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_key="rented-year",
            display_name="Rented for a year",
            config=_config(
                default_for_reason_codes=(
                    PausedSearchReasonCode.RENTED_TEMPORARILY,
                    PausedSearchReasonCode.RENTED_TEMPORARILY,
                )
            ),
            repository=FakePausedSearchTrackAdminRepository(),
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert permission_result.status == PausedSearchTrackDraftStatus.REJECTED
    assert permission_result.reasons[0].value == "permission_denied"
    assert mapping_result.status == PausedSearchTrackDraftStatus.REJECTED
    assert mapping_result.reasons[0].value == "invalid_configuration"


def test_publish_track_version_creates_reason_mappings_and_retires_previous_version() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        track_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
    )
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.DRAFT, version_number=2)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    audit_repo = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()

    result = _run(
        publish_paused_search_track_version(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            track_version_id=VERSION_ID,
            repository=repo,
            audit_log_repository=audit_repo,
            event_bus=event_bus,
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackPublishStatus.PUBLISHED
    assert result.view is not None
    assert result.view.track.active_version_id == VERSION_ID
    assert repo.versions[PREVIOUS_VERSION_ID].status == CampaignVersionStatus.RETIRED
    assert repo.versions[PREVIOUS_VERSION_ID].track_version_id == PREVIOUS_VERSION_ID
    assert repo.mappings[PausedSearchReasonCode.RENTED_TEMPORARILY].track_version_id == VERSION_ID
    assert event_bus.events[-1].event_type == DomainEventType.PAUSED_SEARCH_TRACK_PUBLISHED


def test_update_published_track_creates_new_draft_without_mutating_active_version() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[PREVIOUS_VERSION_ID] = _version(
        track_version_id=PREVIOUS_VERSION_ID,
        status=CampaignVersionStatus.PUBLISHED,
    )
    repo.steps[PREVIOUS_VERSION_ID] = _step_tuple(PREVIOUS_VERSION_ID)

    result = _run(
        update_draft_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            track_key="rented-year",
            display_name="Rented for a year updated",
            config=_config(max_total_touches=3),
            repository=repo,
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status == PausedSearchTrackDraftStatus.UPDATED
    assert result.view is not None
    assert result.view.version.version_number == 2
    assert result.view.version.status == CampaignVersionStatus.DRAFT
    assert repo.versions[PREVIOUS_VERSION_ID].status == CampaignVersionStatus.PUBLISHED
    assert repo.tracks[TRACK_ID].active_version_id == PREVIOUS_VERSION_ID


def test_retire_track_clears_mappings_but_keeps_pinned_version_readable() -> None:
    repo = FakePausedSearchTrackAdminRepository()
    repo.tracks[TRACK_ID] = _track(status=PausedSearchTrackStatus.ACTIVE)
    repo.versions[VERSION_ID] = _version(status=CampaignVersionStatus.PUBLISHED)
    repo.steps[VERSION_ID] = _step_tuple(VERSION_ID)
    repo.mappings[PausedSearchReasonCode.RENTED_TEMPORARILY] = _mapping(VERSION_ID)

    result = _run(
        retire_paused_search_track(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            track_id=TRACK_ID,
            repository=repo,
            audit_log_repository=FakePausedSearchTrackAuditLogRepository(),
            now=NOW,
        )
    )

    assert result.status.value == "retired"
    assert repo.tracks[TRACK_ID].status == PausedSearchTrackStatus.RETIRED
    assert repo.mappings == {}
    assert repo.versions[VERSION_ID].status == CampaignVersionStatus.RETIRED
    assert repo.versions[VERSION_ID].track_version_id == VERSION_ID


class FakePausedSearchTrackAdminRepository:
    def __init__(self) -> None:
        self.tracks: dict[PausedSearchTrackId, PausedSearchTrack] = {}
        self.versions: dict[PausedSearchTrackVersionId, PausedSearchTrackVersion] = {}
        self.steps: dict[PausedSearchTrackVersionId, tuple[PausedSearchTrackStep, ...]] = {}
        self.mappings: dict[PausedSearchReasonCode, PausedSearchReasonMapping] = {}

    async def list_tracks(self, workspace_id: WorkspaceId) -> tuple[PausedSearchTrack, ...]:
        return tuple(track for track in self.tracks.values() if track.workspace_id == workspace_id)

    async def get_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrack | None:
        track = self.tracks.get(track_id)
        return track if track is not None and track.workspace_id == workspace_id else None

    async def get_track_by_key(
        self,
        workspace_id: WorkspaceId,
        track_key: str,
    ) -> PausedSearchTrack | None:
        return next(
            (
                track
                for track in self.tracks.values()
                if track.workspace_id == workspace_id and track.track_key == track_key
            ),
            None,
        )

    async def save_track(self, track: PausedSearchTrack) -> PausedSearchTrack:
        self.tracks[track.track_id] = track
        return track

    async def get_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> PausedSearchTrackVersion | None:
        version = self.versions.get(track_version_id)
        return version if version is not None and version.workspace_id == workspace_id else None

    async def get_latest_draft_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        return max(
            (
                version
                for version in self.versions.values()
                if version.workspace_id == workspace_id
                and version.track_id == track_id
                and version.status == CampaignVersionStatus.DRAFT
            ),
            key=lambda version: version.version_number,
            default=None,
        )

    async def get_latest_version(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> PausedSearchTrackVersion | None:
        return max(
            (
                version
                for version in self.versions.values()
                if version.workspace_id == workspace_id and version.track_id == track_id
            ),
            key=lambda version: version.version_number,
            default=None,
        )

    async def get_latest_version_number(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> int:
        return max(
            (
                version.version_number
                for version in self.versions.values()
                if version.workspace_id == workspace_id and version.track_id == track_id
            ),
            default=0,
        )

    async def save_version(
        self,
        version: PausedSearchTrackVersion,
    ) -> PausedSearchTrackVersion:
        self.versions[version.track_version_id] = version
        return version

    async def get_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchTrackStep, ...]:
        return tuple(
            step
            for step in self.steps.get(track_version_id, ())
            if step.workspace_id == workspace_id
        )

    async def replace_steps(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
        steps: tuple[PausedSearchTrackStep, ...],
    ) -> tuple[PausedSearchTrackStep, ...]:
        saved = tuple(step for step in steps if step.workspace_id == workspace_id)
        self.steps[track_version_id] = saved
        return saved

    async def retire_published_versions(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        except_version_id: PausedSearchTrackVersionId | None,
    ) -> None:
        for version_id, version in tuple(self.versions.items()):
            if (
                version.workspace_id == workspace_id
                and version.track_id == track_id
                and version.track_version_id != except_version_id
                and version.status == CampaignVersionStatus.PUBLISHED
            ):
                self.versions[version_id] = replace(version, status=CampaignVersionStatus.RETIRED)

    async def replace_reason_mappings(
        self,
        *,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
        track_version_id: PausedSearchTrackVersionId,
        reason_codes: tuple[PausedSearchReasonCode, ...],
        actor_user_id: UUID,
        now: datetime,
    ) -> tuple[PausedSearchReasonMapping, ...]:
        self.mappings = {
            reason_code: mapping
            for reason_code, mapping in self.mappings.items()
            if mapping.track_id != track_id and reason_code not in reason_codes
        }
        for reason_code in reason_codes:
            self.mappings[reason_code] = PausedSearchReasonMapping(
                mapping_id=UUID(int=len(self.mappings) + 1),
                workspace_id=workspace_id,
                reason_code=reason_code,
                track_id=track_id,
                track_version_id=track_version_id,
                created_by_user_id=actor_user_id,
                created_at=now,
            )
        return tuple(self.mappings[reason_code] for reason_code in reason_codes)

    async def clear_reason_mappings_for_track(
        self,
        workspace_id: WorkspaceId,
        track_id: PausedSearchTrackId,
    ) -> None:
        self.mappings = {
            reason_code: mapping
            for reason_code, mapping in self.mappings.items()
            if mapping.workspace_id != workspace_id or mapping.track_id != track_id
        }

    async def list_reason_mappings_for_version(
        self,
        workspace_id: WorkspaceId,
        track_version_id: PausedSearchTrackVersionId,
    ) -> tuple[PausedSearchReasonMapping, ...]:
        return tuple(
            mapping
            for mapping in self.mappings.values()
            if mapping.workspace_id == workspace_id and mapping.track_version_id == track_version_id
        )

    async def get_reason_mapping(
        self,
        workspace_id: WorkspaceId,
        reason_code: PausedSearchReasonCode,
    ) -> PausedSearchReasonMapping | None:
        mapping = self.mappings.get(reason_code)
        return mapping if mapping is not None and mapping.workspace_id == workspace_id else None


class FakePausedSearchTrackAuditLogRepository:
    def __init__(self) -> None:
        self.logs: list[PausedSearchTrackAdminAuditLog] = []

    async def append(
        self,
        audit_log: PausedSearchTrackAdminAuditLog,
    ) -> PausedSearchTrackAdminAuditLog:
        self.logs.append(audit_log)
        return audit_log


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _config(
    *,
    max_total_touches: int = 2,
    default_for_reason_codes: tuple[PausedSearchReasonCode, ...] = (
        PausedSearchReasonCode.RENTED_TEMPORARILY,
    ),
) -> PausedSearchTrackConfigInput:
    return PausedSearchTrackConfigInput(
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=default_for_reason_codes,
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=90,
        reactivation_window_days=45,
        max_total_touches=max_total_touches,
        requires_review_before_publish=False,
        steps=(
            PausedSearchTrackStepInput(
                phase=PausedSearchTrackStepPhase.MAINTENANCE,
                channel=ContactChannel.EMAIL,
                delay_hours=24 * 90,
                message_goal="Check whether the lead's plans have changed.",
                template_key="paused-search-maintenance-email-1",
                max_attempts=1,
            ),
        ),
    )


def _track(*, status: PausedSearchTrackStatus) -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="rented-year",
        display_name="Rented for a year",
        status=status,
        active_version_id=PREVIOUS_VERSION_ID,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version(
    *,
    track_version_id: UUID = VERSION_ID,
    status: CampaignVersionStatus,
    version_number: int = 1,
) -> PausedSearchTrackVersion:
    config = _config()
    return PausedSearchTrackVersion(
        track_version_id=track_version_id,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=version_number,
        status=status,
        track_family=config.track_family,
        enabled=config.enabled,
        allowed_channels=config.allowed_channels,
        default_for_reason_codes=config.default_for_reason_codes,
        fallback_timing_policy=config.fallback_timing_policy,
        maintenance_interval_days=config.maintenance_interval_days,
        reactivation_window_days=config.reactivation_window_days,
        max_total_touches=config.max_total_touches,
        requires_review_before_publish=config.requires_review_before_publish,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
        published_at=NOW if status == CampaignVersionStatus.PUBLISHED else None,
    )


def _step_tuple(track_version_id: UUID) -> tuple[PausedSearchTrackStep, ...]:
    config = _config()
    return (
        PausedSearchTrackStep(
            step_id=UUID("00000000-0000-0000-0000-000000000007"),
            workspace_id=WORKSPACE_ID,
            track_version_id=track_version_id,
            step_order=1,
            phase=config.steps[0].phase,
            channel=config.steps[0].channel,
            delay_hours=config.steps[0].delay_hours,
            message_goal=config.steps[0].message_goal,
            template_key=config.steps[0].template_key,
            max_attempts=config.steps[0].max_attempts,
            review_required=config.steps[0].review_required,
            created_at=NOW,
        ),
    )


def _mapping(track_version_id: UUID) -> PausedSearchReasonMapping:
    return PausedSearchReasonMapping(
        mapping_id=UUID("00000000-0000-0000-0000-000000000008"),
        workspace_id=WORKSPACE_ID,
        reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
        track_id=TRACK_ID,
        track_version_id=track_version_id,
        created_by_user_id=ACTOR_ID,
        created_at=NOW,
    )


def _actor(
    *,
    role: WorkspaceMembershipRole = WorkspaceMembershipRole.BROKERAGE_ADMIN,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
