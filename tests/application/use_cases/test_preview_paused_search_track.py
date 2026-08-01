from collections.abc import Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.application.use_cases.preview_paused_search_track import (
    PausedSearchTrackPreviewStatus,
    preview_paused_search_track_version,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackFamily,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    PausedSearchValidationCode,
    plan_next_paused_search_occurrence,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import LeadPausedSearchProfile, PausedSearchReasonCode
from app.domain.workflows import LeadWorkflow, WorkflowState

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
TRACK_ID = UUID("20000000-0000-0000-0000-000000000002")
VERSION_ID = UUID("20000000-0000-0000-0000-000000000003")
STEP_ID = UUID("20000000-0000-0000-0000-000000000004")
USER_ID = UUID("20000000-0000-0000-0000-000000000005")
LEAD_ID = UUID("20000000-0000-0000-0000-000000000006")


def test_preview_is_deterministic_and_matches_runtime_occurrence_planner() -> None:
    step = _step()
    workflow = _workflow()
    first = _run(
        preview_paused_search_track_version(
            actor=_actor(),
            track=_track(),
            version=_version(),
            steps=(step,),
            profile=_profile(),
            workflow=workflow,
            timezone="UTC",
            now=NOW,
        )
    )
    second = _run(
        preview_paused_search_track_version(
            actor=_actor(),
            track=_track(),
            version=_version(),
            steps=(step,),
            profile=_profile(),
            workflow=workflow,
            timezone="UTC",
            now=NOW,
        )
    )
    runtime_plan = plan_next_paused_search_occurrence(
        profile=_profile(),
        track_version=_version(),
        step=step,
        steps=(step,),
        workflow=workflow,
        timezone="UTC",
        now=NOW,
        occurrence_number=1,
        previous_due_at=None,
    )

    assert first.status is PausedSearchTrackPreviewStatus.READY
    assert first == second
    assert first.preview_reference is not None
    assert len(first.preview_reference) == 64
    assert first.occurrences[0].plan == runtime_plan
    assert first.maximum_logical_touches == 2
    assert first.local_expires_at == first.expires_at


def test_preview_blocks_invalid_unsaved_configuration_without_persistence() -> None:
    result = _run(
        preview_paused_search_track_version(
            actor=_actor(),
            track=_track(),
            version=replace(_version(), enabled=False),
            steps=(_step(),),
            profile=_profile(),
            workflow=_workflow(),
            timezone="UTC",
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackPreviewStatus.BLOCKED
    assert result.occurrences == ()
    assert [finding.code for finding in result.validation.errors] == [
        PausedSearchValidationCode.VERSION_DISABLED
    ]


def test_preview_does_not_project_sends_beyond_runtime_touch_cap() -> None:
    result = _run(
        preview_paused_search_track_version(
            actor=_actor(),
            track=_track(),
            version=replace(_version(), max_total_touches=1),
            steps=(_step(),),
            profile=_profile(),
            workflow=_workflow(),
            timezone="UTC",
            now=NOW,
        )
    )

    assert result.status is PausedSearchTrackPreviewStatus.READY
    assert len(result.occurrences) == 1
    assert result.maximum_logical_touches == 1
    assert result.validation.warnings[0].code is PausedSearchValidationCode.EXPECTED_TOUCHES_CAPPED


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
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=30,
        reactivation_window_days=30,
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
        delay_hours=24,
        message_goal="Check whether plans changed.",
        template_key="paused-search-maintenance-email-1",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
        interval_days=30,
        max_occurrences=2,
    )


def _profile() -> LeadPausedSearchProfile:
    return LeadPausedSearchProfile(
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=UUID("20000000-0000-0000-0000-000000000007"),
        temporal_workflow_id="preview-workflow",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("20000000-0000-0000-0000-000000000008"),
        campaign_id=UUID("20000000-0000-0000-0000-000000000009"),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=VERSION_ID,
        paused_search_track_step_id=STEP_ID,
    )


def _actor() -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=USER_ID,
        user_status=UserStatus.ACTIVE,
        active_role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("20000000-0000-0000-0000-000000000010"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
