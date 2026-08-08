from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.campaigns.paused_search_occurrences import RecurringOccurrenceOutcome
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTimingBasis,
    PausedSearchTrackMode,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    paused_search_interim_contact_is_configured,
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
    OCCURRENCE_LIMIT_REACHED = "occurrence_limit_reached"
    TOUCH_LIMIT_REACHED = "touch_limit_reached"
    DURATION_EXPIRED = "duration_expired"


@dataclass(frozen=True)
class PausedSearchNextActionPlan:
    next_action_at: datetime | None
    phase: PausedSearchTrackStepPhase | None
    step_id: PausedSearchTrackStepId | None
    reason_code: PausedSearchTimingReasonCode
    reason_detail: str | None = None


@dataclass(frozen=True)
class PausedSearchOccurrencePlan:
    next_action_at: datetime | None
    due_at: datetime | None
    phase: PausedSearchTrackStepPhase | None
    step_id: PausedSearchTrackStepId | None
    occurrence_number: int
    outcome: RecurringOccurrenceOutcome
    reason_code: PausedSearchTimingReasonCode
    reason_detail: str | None = None


def plan_next_paused_search_occurrence(
    *,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    step: PausedSearchTrackStep,
    steps: tuple[PausedSearchTrackStep, ...],
    workflow: LeadWorkflow,
    timezone: str,
    now: datetime,
    occurrence_number: int,
    previous_due_at: datetime | None,
    quiet_hours_enabled: bool = True,
    quiet_hours_start: time | None = time(10, 0),
    quiet_hours_end: time | None = time(17, 0),
) -> PausedSearchOccurrencePlan:
    if occurrence_number > step.max_occurrences:
        return PausedSearchOccurrencePlan(
            next_action_at=None,
            due_at=None,
            phase=step.phase,
            step_id=step.step_id,
            occurrence_number=occurrence_number,
            outcome=RecurringOccurrenceOutcome.TERMINALIZE,
            reason_code=PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED,
        )

    base_plan = plan_paused_search_next_action(
        profile=profile,
        track_version=track_version,
        steps=steps,
        workflow=workflow,
        timezone=timezone,
        now=now,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )
    if base_plan.next_action_at is None:
        return PausedSearchOccurrencePlan(
            next_action_at=None,
            due_at=None,
            phase=base_plan.phase,
            step_id=base_plan.step_id,
            occurrence_number=occurrence_number,
            outcome=_outcome_for_non_scheduled_reason(base_plan.reason_code),
            reason_code=base_plan.reason_code,
            reason_detail=base_plan.reason_detail,
        )

    if occurrence_number == 1:
        due_at = base_plan.next_action_at
    else:
        if step.interval_days is None or previous_due_at is None:
            return PausedSearchOccurrencePlan(
                next_action_at=None,
                due_at=None,
                phase=step.phase,
                step_id=step.step_id,
                occurrence_number=occurrence_number,
                outcome=RecurringOccurrenceOutcome.TERMINALIZE,
                reason_code=PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED,
                reason_detail="step is not configured for recurring occurrences",
            )
        due_at = _add_calendar_days(previous_due_at, step.interval_days, timezone)

    duration_end = paused_search_duration_end(
        workflow=workflow,
        track_version=track_version,
        timezone=timezone,
    )
    if due_at > duration_end:
        return PausedSearchOccurrencePlan(
            next_action_at=None,
            due_at=due_at,
            phase=step.phase,
            step_id=step.step_id,
            occurrence_number=occurrence_number,
            outcome=RecurringOccurrenceOutcome.EXPIRED,
            reason_code=PausedSearchTimingReasonCode.DURATION_EXPIRED,
        )

    return PausedSearchOccurrencePlan(
        next_action_at=_roll_forward_to_allowed_window(
            due_at,
            timezone,
            quiet_hours_enabled=quiet_hours_enabled,
            quiet_hours_start=quiet_hours_start,
            quiet_hours_end=quiet_hours_end,
        ),
        due_at=due_at,
        phase=step.phase,
        step_id=step.step_id,
        occurrence_number=occurrence_number,
        outcome=RecurringOccurrenceOutcome.SEND,
        reason_code=PausedSearchTimingReasonCode.SCHEDULED,
    )


def plan_paused_search_next_action(
    *,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    workflow: LeadWorkflow,
    timezone: str,
    now: datetime,
    quiet_hours_enabled: bool = True,
    quiet_hours_start: time | None = time(10, 0),
    quiet_hours_end: time | None = time(17, 0),
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

    if workflow.logical_touch_count >= track_version.max_total_touches:
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED,
            reason_detail="track logical-touch limit has been reached",
        )

    phase = _determine_phase(
        profile=profile,
        track_version=track_version,
        workflow=workflow,
        timezone=timezone,
        reference_time=now,
    )
    if phase is None:
        reason_detail = (
            "Maintenance outreach is not permitted for this track."
            if _maintenance_outreach_blocked(track_version)
            else "no actionable phase for current profile and track timing"
        )
        return PausedSearchNextActionPlan(
            next_action_at=None,
            phase=None,
            step_id=None,
            reason_code=PausedSearchTimingReasonCode.HOLD_FOR_REVIEW,
            reason_detail=reason_detail,
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
            workflow=workflow,
            timezone=timezone,
            step=step,
        )
        candidate = base_time + timedelta(hours=step.delay_hours)
        if candidate < now:
            candidate = now

        new_phase = _determine_phase(
            profile=profile,
            track_version=track_version,
            workflow=workflow,
            timezone=timezone,
            reference_time=candidate,
        )
        if new_phase == phase:
            break
        phase = new_phase
        targeted_step_id = None

    next_action_at = _roll_forward_to_allowed_window(
        candidate,
        timezone,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )
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
    workflow: LeadWorkflow,
    timezone: str,
    reference_time: datetime,
) -> PausedSearchTrackStepPhase | None:
    reactivation_date = profile.reengagement_not_before or _fallback_reactivation_date(
        profile=profile,
        track_version=track_version,
        workflow=workflow,
        timezone=timezone,
    )
    if reactivation_date is not None:
        reactivation_start = reactivation_date - timedelta(
            days=track_version.reactivation_window_days
        )
        if reference_time >= reactivation_start:
            return PausedSearchTrackStepPhase.REACTIVATION
        if _maintenance_outreach_blocked(track_version):
            return None
        return PausedSearchTrackStepPhase.MAINTENANCE
    if (
        track_version.fallback_timing_policy
        is PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL
    ):
        if _maintenance_outreach_blocked(track_version):
            return None
        return PausedSearchTrackStepPhase.MAINTENANCE

    return None


def _maintenance_outreach_blocked(track_version: PausedSearchTrackVersion) -> bool:
    return (
        track_version.track_mode is PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT
        and not paused_search_interim_contact_is_configured(track_version.interim_contact_policy)
    )


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
    workflow: LeadWorkflow,
    timezone: str,
    step: PausedSearchTrackStep,
    now: datetime,
) -> datetime:
    if step.timing_basis is PausedSearchTimingBasis.WORKFLOW_CREATED_AT:
        return max(workflow.created_at, now)
    if step.timing_basis is PausedSearchTimingBasis.PREVIOUS_OCCURRENCE:
        return now
    reactivation_date = profile.reengagement_not_before or _fallback_reactivation_date(
        profile=profile,
        track_version=track_version,
        workflow=workflow,
        timezone=timezone,
    )
    if phase == PausedSearchTrackStepPhase.REACTIVATION and reactivation_date is not None:
        reactivation_start = reactivation_date - timedelta(
            days=track_version.reactivation_window_days
        )
        if now < reactivation_start:
            return reactivation_start
    return now


def _fallback_reactivation_date(
    *,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    workflow: LeadWorkflow,
    timezone: str,
) -> datetime | None:
    if profile.reengagement_not_before is not None:
        return profile.reengagement_not_before
    if (
        track_version.fallback_timing_policy
        is not PausedSearchFallbackTimingPolicy.USE_DEFAULT_PAUSE_DURATION
    ):
        return None
    return _add_calendar_days(
        workflow.created_at,
        track_version.default_pause_duration_days,
        timezone,
    )


def _roll_forward_to_allowed_window(
    candidate: datetime,
    timezone: str,
    *,
    quiet_hours_enabled: bool,
    quiet_hours_start: time | None,
    quiet_hours_end: time | None,
) -> datetime:
    if not quiet_hours_enabled or quiet_hours_start is None or quiet_hours_end is None:
        return candidate
    if quiet_hours_start >= quiet_hours_end:
        raise ValueError("quiet-hours start must be before quiet-hours end")

    local = _to_timezone(candidate, timezone)
    local_time = local.time().replace(tzinfo=None)
    if quiet_hours_start <= local_time < quiet_hours_end:
        return candidate

    start_of_window = local.replace(
        hour=quiet_hours_start.hour,
        minute=quiet_hours_start.minute,
        second=quiet_hours_start.second,
        microsecond=quiet_hours_start.microsecond,
    )
    if local_time < quiet_hours_start:
        return _from_timezone(start_of_window, timezone)
    return _from_timezone(start_of_window + timedelta(days=1), timezone)


def _outcome_for_non_scheduled_reason(
    reason_code: PausedSearchTimingReasonCode,
) -> RecurringOccurrenceOutcome:
    if reason_code in {
        PausedSearchTimingReasonCode.WORKFLOW_NOT_SENDABLE,
        PausedSearchTimingReasonCode.PROFILE_NOT_ACTIVE,
    }:
        return RecurringOccurrenceOutcome.CANCEL
    if reason_code in {
        PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED,
        PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED,
    }:
        return RecurringOccurrenceOutcome.TERMINALIZE
    if reason_code == PausedSearchTimingReasonCode.DURATION_EXPIRED:
        return RecurringOccurrenceOutcome.EXPIRED
    if reason_code == PausedSearchTimingReasonCode.HOLD_FOR_REVIEW:
        return RecurringOccurrenceOutcome.REVIEW
    return RecurringOccurrenceOutcome.HOLD


def _add_calendar_days(value: datetime, days: int, timezone: str) -> datetime:
    return _from_timezone(_to_timezone(value, timezone) + timedelta(days=days), timezone)


def paused_search_duration_end(
    *,
    workflow: LeadWorkflow,
    track_version: PausedSearchTrackVersion,
    timezone: str,
) -> datetime:
    return _add_calendar_days(
        workflow.created_at,
        track_version.max_duration_days,
        timezone,
    )


def _to_timezone(value: datetime, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(tz)
    return value.astimezone(tz)


def _from_timezone(value: datetime, timezone: str) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC)
