from collections.abc import Coroutine
from datetime import UTC, datetime
from uuid import UUID

from app.application.services.paused_search_drafting_templates import (
    get_paused_search_drafting_template,
)
from app.application.use_cases.seed_default_paused_search_tracks import (
    DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES,
    SeedDefaultPausedSearchTrackStatus,
    _config_for_template,
    seed_default_paused_search_tracks,
)
from app.domain.campaigns import CampaignVersionStatus, capability_profile_for_reason
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import PausedSearchReasonCode
from tests.application.use_cases.test_paused_search_track_admin import (
    FakeEventBus,
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAuditLogRepository,
    FakeTemplateRepository,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000121")
USER_ID = UUID("00000000-0000-0000-0000-000000000122")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000123")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def test_seed_default_paused_search_tracks_creates_and_publishes_all_defaults() -> None:
    repository = FakePausedSearchTrackAdminRepository()
    audit_repository = FakePausedSearchTrackAuditLogRepository()
    event_bus = FakeEventBus()
    template_repository = FakeTemplateRepository()

    result = _run(
        seed_default_paused_search_tracks(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            repository=repository,
            audit_log_repository=audit_repository,
            event_bus=event_bus,
            template_repository=template_repository,
            now=NOW,
        )
    )

    assert len(result.items) == len(DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES)
    assert {item.status for item in result.items} == {
        SeedDefaultPausedSearchTrackStatus.CREATED,
    }
    assert len(repository.tracks) == len(DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES)
    assert len(repository.mappings) == len(DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES)
    assert all(
        version.status == CampaignVersionStatus.PUBLISHED
        for version in repository.versions.values()
    )
    assert len(audit_repository.logs) == len(DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES) * 2
    assert len(event_bus.events) == len(DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES) * 2


def test_seed_default_paused_search_tracks_skips_existing_mapping_and_track_key_conflict() -> None:
    repository = FakePausedSearchTrackAdminRepository()
    audit_repository = FakePausedSearchTrackAuditLogRepository()
    template_repository = FakeTemplateRepository()

    first = _run(
        seed_default_paused_search_tracks(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            repository=repository,
            audit_log_repository=audit_repository,
            template_repository=template_repository,
            now=NOW,
        )
    )
    assert first.items[0].status == SeedDefaultPausedSearchTrackStatus.CREATED

    rented_result = next(
        item
        for item in first.items
        if item.reason_code == PausedSearchReasonCode.RENTED_TEMPORARILY
    )
    timing_track = next(
        track
        for track in repository.tracks.values()
        if track.track_key == "paused-search-timing-not-right"
    )
    repository.mappings.pop(PausedSearchReasonCode.TIMING_NOT_RIGHT)

    second = _run(
        seed_default_paused_search_tracks(
            actor=_actor(),
            workspace_id=WORKSPACE_ID,
            repository=repository,
            audit_log_repository=audit_repository,
            template_repository=template_repository,
            now=NOW,
        )
    )

    rented_item = next(
        item
        for item in second.items
        if item.reason_code == PausedSearchReasonCode.RENTED_TEMPORARILY
    )
    timing_item = next(
        item for item in second.items if item.reason_code == PausedSearchReasonCode.TIMING_NOT_RIGHT
    )
    assert rented_item.status == SeedDefaultPausedSearchTrackStatus.SKIPPED_REASON_ALREADY_MAPPED
    assert rented_item.track_id == rented_result.track_id
    assert timing_item.status == SeedDefaultPausedSearchTrackStatus.SKIPPED_TRACK_KEY_EXISTS
    assert timing_item.track_id == timing_track.track_id


def test_seeded_default_tracks_only_reference_known_paused_search_templates() -> None:
    for track_template in DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES:
        config = _config_for_template(track_template)
        for step in config.steps:
            assert get_paused_search_drafting_template(step.template_key) is not None


def test_seeded_default_tracks_preserve_each_reason_limits_and_step_timing() -> None:
    for track_template in DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES:
        config = _config_for_template(track_template)
        capability_profile = capability_profile_for_reason(track_template.reason_code)

        assert capability_profile is not None
        assert config.maintenance_interval_days == track_template.maintenance_interval_days
        assert config.reactivation_window_days == track_template.reactivation_window_days
        assert config.max_total_touches == track_template.max_total_touches
        assert config.max_duration_days == capability_profile.max_duration_days
        assert config.steps[0].delay_hours == 24 * track_template.maintenance_interval_days
        assert config.steps[0].template_key.endswith("-maintenance-email-1")
        assert config.steps[1].delay_hours == 0
        assert config.steps[1].template_key.endswith("-reactivation-email-1")


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[object, object, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
