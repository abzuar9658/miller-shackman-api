from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import PausedSearchTrackStepId
from app.domain.leads import LeadPausedSearchProfile
from app.domain.workflows import LeadWorkflow, WorkflowState


class PausedSearchTimingReasonCode(StrEnum):
    WORKFLOW_NOT_SENDABLE = "workflow_not_sendable"
    PROFILE_NOT_ACTIVE = "profile_not_active"
    TRACK_UNAVAILABLE = "track_unavailable"
    HOLD_FOR_REVIEW = "hold_for_review"
    NO_STEP_IN_PHASE = "no_step_in_phase"
    SCHEDULED = "scheduled"


@dataclass(frozen=True)
class PausedSearchNextActionPlan:
    next_action_at: datetime | None
    phase: PausedSearchTrackStepPhase | None
    step_id: PausedSearchTrackStepId | None
    reason_code: PausedSearchTimingReasonCode
    reason_detail: str | None = None


def plan_paused_search_next_action(
    *,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    workflow: LeadWorkflow,
    timezone: str,
    now: datetime,
) -> PausedSearchNextActionPlan:
    if workflow.state in _NON_SENDABLE_STATES:
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.WORKFLOW_NOT_SENDABLE,
            reason_detail=f"workflow state {workflow.state.value} is not sendable",
        )

    if not profile.paused_search_active:
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.PROFILE_NOT_ACTIVE,
        )

    if not track_version.enabled:
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.TRACK_UNAVAILABLE,
            reason_detail="track version is disabled",
        )

    phase = _determine_phase(
        profile=profile,
        track_version=track_version,
        reference_time=now,
    )
    if phase is None:
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.HOLD_FOR_REVIEW,
            reason_detail="no actionable phase for current profile and track timing",
        )

    targeted_step_id: UUID | None = workflow.paused_search_track_step_id
    while True:
        assert phase is not None
        step = _resolve_step_for_phase(steps, phase, targeted_step_id)
        if step is None:
            return PausedSearchNextActionPlan(
                next_action_at=None,
                phase=phase,
                step_id=None,
                reason_code=PausedSearchTimingReasonCode.NO_STEP_IN_PHASE,
                reason_detail=f"no remaining step in {phase.value} phase",
            )

        base_time = _base_time_for_phase(
            phase=phase,
            profile=profile,
            track_version=track_version,
            now=now,
        )
        candidate = base_time + timedelta(hours=step.delay_hours)
        if candidate < now:
            candidate = now

        new_phase = _determine_phase(
            profile=profile,
            track_version=track_version,
            reference_time=candidate,
        )
        if new_phase == phase:
            break
        phase = new_phase
        targeted_step_id = None

    next_action_at = _roll_forward_to_allowed_window(candidate, timezone)
    return PausedSearchNextActionPlan(
        next_action_at=next_action_at,
        phase=phase,
        step_id=step.step_id,
        reason_code=PausedSearchTimingReasonCode.SCHEDULED,
    )


_NON_SENDABLE_STATES = frozenset(
    {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
        WorkflowState.COMPLETED,
        WorkflowState.SUPPRESSED,
        WorkflowState.CLOSED,
    }
)


def _determine_phase(
    *,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    reference_time: datetime,
) -> PausedSearchTrackStepPhase | None:
    if profile.reengagement_not_before is not None:
        reactivation_start = profile.reengagement_not_before - timedelta(
            days=track_version.reactivation_window_days
        )
        if reference_time >= reactivation_start:
            return PausedSearchTrackStepPhase.REACTIVATION
        return PausedSearchTrackStepPhase.MAINTENANCE

    if (
        track_version.fallback_timing_policy
        == PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
    ):
        return PausedSearchTrackStepPhase.MAINTENANCE

    return None


def _resolve_step_for_phase(
    steps: tuple[PausedSearchTrackStep, ...],
    phase: PausedSearchTrackStepPhase,
    targeted_step_id: UUID | None,
) -> PausedSearchTrackStep | None:
    phase_steps = tuple(
        sorted(
            (step for step in steps if step.phase == phase),
            key=lambda step: step.step_order,
        )
    )
    if not phase_steps:
        return None

    if targeted_step_id is not None:
        for step in phase_steps:
            if step.step_id == targeted_step_id:
                return step

    return phase_steps[0]


def _base_time_for_phase(
    *,
    phase: PausedSearchTrackStepPhase,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    now: datetime,
) -> datetime:
    if (
        phase == PausedSearchTrackStepPhase.REACTIVATION
        and profile.reengagement_not_before is not None
    ):
        reactivation_start = profile.reengagement_not_before - timedelta(
            days=track_version.reactivation_window_days
        )
        if now < reactivation_start:
            return reactivation_start
    return now


def _roll_forward_to_allowed_window(candidate: datetime, timezone: str) -> datetime:
    allowed_start_hour = 10
    allowed_end_hour = 17
    local = _to_timezone(candidate, timezone)
    if allowed_start_hour <= local.hour < allowed_end_hour:
        return candidate

    start_of_window = local.replace(hour=allowed_start_hour, minute=0, second=0, microsecond=0)
    if local.hour < allowed_start_hour:
        return _from_timezone(start_of_window, timezone)
    return _from_timezone(start_of_window + timedelta(days=1), timezone)


def _to_timezone(value: datetime, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(tz)
    return value.astimezone(tz)


def _from_timezone(value: datetime, timezone: str) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC)
