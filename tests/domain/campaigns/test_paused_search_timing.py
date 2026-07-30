from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTimingReasonCode,
    PausedSearchTrackFamily,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    plan_paused_search_next_action,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import (
    LeadPausedSearchProfile,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState

WORKSPACE_ID = uuid4()
LEAD_ID = uuid4()
TRACK_VERSION_ID = uuid4()
TRACK_ID = uuid4()
USER_ID = uuid4()
STEP_ONE_ID = uuid4()
STEP_TWO_ID = uuid4()
STEP_REACTIVATION_ID = uuid4()
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
TIMEZONE = "America/Chicago"


def _track_version(
    *,
    enabled: bool = True,
    fallback_timing_policy: PausedSearchFallbackTimingPolicy = (
        PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
    ),
    maintenance_interval_days: int = 60,
    reactivation_window_days: int = 30,
) -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=enabled,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=(PausedSearchReasonCode.RENTED_TEMPORARILY,),
        fallback_timing_policy=fallback_timing_policy,
        maintenance_interval_days=maintenance_interval_days,
        reactivation_window_days=reactivation_window_days,
        max_total_touches=5,
        requires_review_before_publish=False,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _steps() -> tuple[PausedSearchTrackStep, ...]:
    return (
        PausedSearchTrackStep(
            step_id=STEP_ONE_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=1,
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.EMAIL,
            delay_hours=24 * 60,
            message_goal="First maintenance touch",
            template_key="paused-search-maintenance-1",
            max_attempts=1,
            review_required=False,
            created_at=NOW,
        ),
        PausedSearchTrackStep(
            step_id=STEP_TWO_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=2,
            phase=PausedSearchTrackStepPhase.MAINTENANCE,
            channel=ContactChannel.EMAIL,
            delay_hours=24 * 60,
            message_goal="Second maintenance touch",
            template_key="paused-search-maintenance-2",
            max_attempts=1,
            review_required=False,
            created_at=NOW,
        ),
        PausedSearchTrackStep(
            step_id=STEP_REACTIVATION_ID,
            workspace_id=WORKSPACE_ID,
            track_version_id=TRACK_VERSION_ID,
            step_order=1,
            phase=PausedSearchTrackStepPhase.REACTIVATION,
            channel=ContactChannel.EMAIL,
            delay_hours=0,
            message_goal="Reactivation touch",
            template_key="paused-search-reactivation-1",
            max_attempts=1,
            review_required=False,
            created_at=NOW,
        ),
    )


def _profile(
    *,
    reengagement_not_before: datetime | None = None,
) -> LeadPausedSearchProfile:
    return LeadPausedSearchProfile(
        paused_search_active=True,
        pause_reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
        reengagement_not_before=reengagement_not_before,
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
    )


def _workflow(
    *,
    state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    paused_search_track_step_id: UUID | None = None,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=uuid4(),
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=uuid4(),
        campaign_id=uuid4(),
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=TRACK_VERSION_ID,
        paused_search_track_step_id=paused_search_track_step_id,
    )


def test_workflow_not_sendable_returns_hold() -> None:
    workflow = _workflow(state=WorkflowState.PAUSED)
    plan = plan_paused_search_next_action(
        profile=_profile(),
        track_version=_track_version(),
        steps=_steps(),
        workflow=workflow,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.WORKFLOW_NOT_SENDABLE
    assert plan.next_action_at is None


def test_profile_not_active_returns_hold() -> None:
    profile = LeadPausedSearchProfile(paused_search_active=False)
    plan = plan_paused_search_next_action(
        profile=profile,
        track_version=_track_version(),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.PROFILE_NOT_ACTIVE


def test_disabled_track_returns_hold() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(),
        track_version=_track_version(enabled=False),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.TRACK_UNAVAILABLE


def test_hold_for_review_when_reengagement_unknown_and_policy_requires() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=None),
        track_version=_track_version(
            fallback_timing_policy=PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW
        ),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.HOLD_FOR_REVIEW


def test_maintenance_interval_fallback_when_reengagement_unknown() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=None),
        track_version=_track_version(
            fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
        ),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.SCHEDULED
    assert plan.phase == PausedSearchTrackStepPhase.MAINTENANCE
    assert plan.step_id == STEP_ONE_ID
    # NOW is 12:00 UTC = 7:00 CDT, so the next allowed window is 15:00 UTC.
    assert plan.next_action_at == (NOW + timedelta(hours=24 * 60)).replace(hour=15, minute=0)


def test_schedules_first_maintenance_step() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=NOW + timedelta(days=120)),
        track_version=_track_version(),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.SCHEDULED
    assert plan.phase == PausedSearchTrackStepPhase.MAINTENANCE
    assert plan.step_id == STEP_ONE_ID
    assert plan.next_action_at == (NOW + timedelta(hours=24 * 60)).replace(hour=15, minute=0)


def test_reactivation_phase_before_reengagement_window() -> None:
    reengagement = NOW + timedelta(days=30)
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=reengagement),
        track_version=_track_version(reactivation_window_days=30),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.phase == PausedSearchTrackStepPhase.REACTIVATION
    assert plan.step_id == STEP_REACTIVATION_ID


def test_schedules_targeted_step_when_in_phase() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=NOW + timedelta(days=120)),
        track_version=_track_version(),
        steps=_steps(),
        workflow=_workflow(paused_search_track_step_id=STEP_TWO_ID),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.step_id == STEP_TWO_ID


def test_switches_step_when_phase_changes() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=NOW + timedelta(days=30)),
        track_version=_track_version(reactivation_window_days=30),
        steps=_steps(),
        workflow=_workflow(paused_search_track_step_id=STEP_ONE_ID),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.phase == PausedSearchTrackStepPhase.REACTIVATION
    assert plan.step_id == STEP_REACTIVATION_ID


def test_rolls_forward_to_allowed_window() -> None:
    late_night = datetime(2026, 7, 1, 4, 0, 0, tzinfo=UTC)
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=None),
        track_version=_track_version(
            fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
        ),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=late_night,
    )
    # 4 AM UTC = 11 PM previous day CDT, which is outside 10-17 window.
    # Candidate is 60 days later, then rolled forward to 10 AM CDT = 15:00 UTC.
    assert plan.next_action_at == (late_night + timedelta(hours=24 * 60)).replace(
        hour=15, minute=0
    )


def test_reactivation_step_respects_window_start() -> None:
    reengagement = NOW + timedelta(days=30)
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=reengagement),
        track_version=_track_version(reactivation_window_days=30),
        steps=_steps(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    # reactivation_start is NOW, delay_hours is 0, but NOW is outside the
    # allowed window in CDT so it rolls forward to 15:00 UTC.
    assert plan.next_action_at == NOW.replace(hour=15, minute=0)


def test_no_step_in_phase_returns_hold() -> None:
    plan = plan_paused_search_next_action(
        profile=_profile(reengagement_not_before=NOW + timedelta(days=30)),
        track_version=_track_version(reactivation_window_days=30),
        steps=(),
        workflow=_workflow(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert plan.reason_code == PausedSearchTimingReasonCode.NO_STEP_IN_PHASE
