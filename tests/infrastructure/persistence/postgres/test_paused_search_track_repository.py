from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchReasonMapping,
    PausedSearchTrack,
    PausedSearchTrackAdminAuditAction,
    PausedSearchTrackAdminAuditLog,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.template_registry import TemplateChannel, TemplateStatus, TemplateVersion
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode
from app.infrastructure.persistence.postgres.models import UserModel, WorkspaceModel
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminAuditLogRepository,
    PostgresPausedSearchTrackAdminRepository,
    _track_statement,
)
from app.infrastructure.persistence.postgres.template_repository import PostgresTemplateRepository

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
TRACK_ID = UUID("22222222-2222-2222-2222-222222222222")
VERSION_ID = UUID("33333333-3333-3333-3333-333333333333")
STEP_ID = UUID("44444444-4444-4444-4444-444444444444")
TEMPLATE_ID = UUID("77777777-7777-7777-7777-777777777777")
USER_ID = UUID("55555555-5555-5555-5555-555555555555")
AUDIT_ID = UUID("66666666-6666-6666-6666-666666666666")


@pytest.mark.asyncio
async def test_paused_search_track_repository_saves_versions_steps_mappings_and_audit(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace_and_user(postgres_session)
    repository = PostgresPausedSearchTrackAdminRepository(postgres_session)
    audit_repository = PostgresPausedSearchTrackAdminAuditLogRepository(postgres_session)

    track = await repository.save_track(_track())
    version = await repository.save_version(_version())
    steps = await repository.replace_steps(WORKSPACE_ID, VERSION_ID, (_step(),))
    mappings = await repository.replace_reason_mappings(
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        track_version_id=VERSION_ID,
        reason_codes=(PausedSearchReasonCode.RENTED_TEMPORARILY,),
        actor_user_id=USER_ID,
        now=NOW,
    )
    audit_log = await audit_repository.append(_audit_log())

    assert track == _track()
    assert version == _version()
    assert steps == (_step(),)
    assert mappings == (_mapping(mappings[0].mapping_id),)
    assert audit_log.action == PausedSearchTrackAdminAuditAction.DRAFT_CREATED
    assert await repository.list_tracks(WORKSPACE_ID) == (track,)
    assert await repository.get_track_for_update(WORKSPACE_ID, TRACK_ID) == track
    assert await repository.get_track_by_key(WORKSPACE_ID, "rented-year") == track
    assert await repository.get_latest_draft_version(WORKSPACE_ID, TRACK_ID) == version
    assert await repository.get_latest_version(WORKSPACE_ID, TRACK_ID) == version
    assert await repository.get_latest_version_number(WORKSPACE_ID, TRACK_ID) == 1
    assert await repository.get_steps(WORKSPACE_ID, VERSION_ID) == (_step(),)
    assert (
        await repository.get_reason_mapping(
            WORKSPACE_ID,
            PausedSearchReasonCode.RENTED_TEMPORARILY,
        )
        == mappings[0]
    )

    await repository.retire_published_versions(WORKSPACE_ID, TRACK_ID, except_version_id=None)
    assert await repository.get_version(WORKSPACE_ID, VERSION_ID) == version


def test_paused_search_track_publish_read_is_workspace_scoped_and_locked() -> None:
    statement = str(_track_statement(WORKSPACE_ID, TRACK_ID, for_update=True))

    assert "paused_search_tracks.workspace_id" in statement
    assert "paused_search_tracks.track_id" in statement
    assert "FOR UPDATE" in statement


@pytest.mark.asyncio
async def test_paused_search_step_round_trips_workspace_template_binding(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace_and_user(postgres_session)
    template_repository = PostgresTemplateRepository(postgres_session)
    await template_repository.save(
        TemplateVersion(
            template_version_id=TEMPLATE_ID,
            workspace_id=WORKSPACE_ID,
            template_key="paused-search-maintenance-email-1",
            version=1,
            channel=TemplateChannel.EMAIL,
            purpose="paused_search",
            content="{{message_body}}",
            subject="Checking in",
            prompt_text="Write a check-in.",
            allowed_variables=("message_body",),
            permitted_use_tags=("no_prohibited_advice",),
            status=TemplateStatus.APPROVED,
            approved_at=NOW,
            created_at=NOW,
        )
    )
    repository = PostgresPausedSearchTrackAdminRepository(postgres_session)
    await repository.save_track(_track())
    await repository.save_version(_version())
    expected = replace(_step(), template_version_id=TEMPLATE_ID)

    saved = await repository.replace_steps(WORKSPACE_ID, VERSION_ID, (expected,))

    assert saved == (expected,)
    assert await repository.get_steps(WORKSPACE_ID, VERSION_ID) == (expected,)


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="rented-year",
        display_name="Rented for a year",
        status=PausedSearchTrackStatus.DRAFT,
        active_version_id=None,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.DRAFT,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=(PausedSearchReasonCode.RENTED_TEMPORARILY,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=90,
        reactivation_window_days=45,
        max_total_touches=2,
        requires_review_before_publish=False,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


def _step() -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=STEP_ID,
        workspace_id=WORKSPACE_ID,
        track_version_id=VERSION_ID,
        step_order=1,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        delay_hours=24 * 90,
        message_goal="Check whether the lead's plans have changed.",
        template_key="paused-search-maintenance-email-1",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
    )


def _mapping(mapping_id: UUID) -> PausedSearchReasonMapping:
    return PausedSearchReasonMapping(
        mapping_id=mapping_id,
        workspace_id=WORKSPACE_ID,
        reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
        track_id=TRACK_ID,
        track_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


def _audit_log() -> PausedSearchTrackAdminAuditLog:
    return PausedSearchTrackAdminAuditLog(
        audit_log_id=AUDIT_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        track_version_id=VERSION_ID,
        action=PausedSearchTrackAdminAuditAction.DRAFT_CREATED,
        actor_user_id=USER_ID,
        details={"track_key": "rented-year"},
        created_at=NOW,
    )


async def _create_workspace_and_user(postgres_session: AsyncSession) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    postgres_session.add(
        UserModel(
            user_id=USER_ID,
            email="admin@example.com",
            email_normalized="admin@example.com",
            full_name="Admin User",
            status="active",
            email_verified_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
