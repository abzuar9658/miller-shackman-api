from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.execution import CampaignCadenceStep
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_timing import (
    PausedSearchTimingReasonCode,
    paused_search_planning_reference,
    paused_search_step_occurrence_cap,
    plan_next_paused_search_occurrence,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import LeadPausedSearchProfile
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    is_sendable_workflow_state,
    is_terminal_workflow_state,
)


class LeadCadenceJourney(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


class CadenceStepProgressStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    CURRENT = "current"
    UPCOMING = "upcoming"


@dataclass(frozen=True)
class CadenceStepOccurrenceView:
    occurrence_number: int
    sent_at: datetime | None = None
    projected_for: datetime | None = None


@dataclass(frozen=True)
class CadenceStepProgressView:
    step_id: UUID
    step_order: int
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    status: CadenceStepProgressStatus
    attempt_count: int
    sent_at: datetime | None = None
    scheduled_for: datetime | None = None
    last_failure_reason: str | None = None
    phase: str | None = None
    interval_days: int | None = None
    max_occurrences: int = 1
    occurrences: tuple[CadenceStepOccurrenceView, ...] = ()


@dataclass(frozen=True)
class LeadCadenceProgressView:
    journey: LeadCadenceJourney
    flow_name: str
    steps: tuple[CadenceStepProgressView, ...]
    total_steps: int
    completed_steps: int
    current_step_order: int | None = None
    next_action_at: datetime | None = None
    workflow_state: WorkflowState | None = None
    is_sendable: bool = True


@dataclass(frozen=True)
class _StepFacts:
    attempt_count: int
    has_sent: bool
    has_pending: bool
    sent_at: datetime | None
    sent_ats: tuple[datetime, ...]
    scheduled_for: datetime | None
    last_failure_reason: str | None


def _messages_for_workflow_run(
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow | None,
) -> tuple[OutboundMessage, ...]:
    """Keep only messages belonging to the given workflow run.

    Progress must never adopt sends from a previous enrollment of the same
    campaign (close-and-create re-enrollments reuse campaign and step ids).
    Messages written before workflow attribution existed have no workflow_id;
    those are attributed by creation time relative to the run's start.
    """
    if workflow is None:
        return outbound_messages
    return tuple(
        message
        for message in outbound_messages
        if (
            message.workflow_id == workflow.workflow_id
            if message.workflow_id is not None
            else message.created_at >= workflow.created_at
        )
    )


def build_dormant_cadence_progress(
    *,
    flow_name: str,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow | None,
) -> LeadCadenceProgressView | None:
    if not cadence_steps:
        return None
    outbound_messages = _messages_for_workflow_run(outbound_messages, workflow)
    ordered = tuple(sorted(cadence_steps, key=lambda step: step.step_order))
    specs = tuple(
        (
            step.cadence_step_id,
            step.step_order,
            step.channel,
            step.delay_hours,
            step.message_goal,
            None,
        )
        for step in ordered
    )
    return _build_progress(
        journey=LeadCadenceJourney.DORMANT,
        flow_name=flow_name,
        specs=specs,
        outbound_messages=outbound_messages,
        workflow=workflow,
        cursor_step_id=workflow.current_step_id if workflow is not None else None,
    )


def build_paused_search_cadence_progress(
    *,
    flow_name: str,
    track_steps: tuple[PausedSearchTrackStep, ...],
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow | None,
    profile: LeadPausedSearchProfile | None = None,
    track_version: PausedSearchTrackVersion | None = None,
    timezone: str | None = None,
    now: datetime | None = None,
    quiet_hours_enabled: bool = True,
    quiet_hours_start: time | None = time(10, 0),
    quiet_hours_end: time | None = time(17, 0),
) -> LeadCadenceProgressView | None:
    if not track_steps:
        return None
    outbound_messages = _messages_for_workflow_run(outbound_messages, workflow)
    ordered = tuple(sorted(track_steps, key=lambda step: (step.phase.value, step.step_order)))
    specs = tuple(
        (
            step.step_id,
            step.step_order,
            step.channel,
            step.delay_hours,
            step.message_goal,
            step.phase.value,
        )
        for step in ordered
    )
    progress = _build_progress(
        journey=LeadCadenceJourney.PAUSED_SEARCH,
        flow_name=flow_name,
        specs=specs,
        outbound_messages=outbound_messages,
        workflow=workflow,
        cursor_step_id=workflow.paused_search_track_step_id if workflow is not None else None,
    )
    steps_by_id = {step.step_id: step for step in ordered}
    enriched = tuple(
        replace(
            view,
            interval_days=steps_by_id[view.step_id].interval_days,
            max_occurrences=steps_by_id[view.step_id].max_occurrences,
        )
        for view in progress.steps
    )
    progress = replace(progress, steps=enriched)
    if (
        workflow is None
        or profile is None
        or track_version is None
        or timezone is None
        or now is None
    ):
        return progress
    return _apply_paused_search_projection(
        progress=progress,
        ordered_steps=ordered,
        outbound_messages=outbound_messages,
        workflow=workflow,
        profile=profile,
        track_version=track_version,
        timezone=timezone,
        now=now,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )


def _apply_paused_search_projection(
    *,
    progress: LeadCadenceProgressView,
    ordered_steps: tuple[PausedSearchTrackStep, ...],
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow,
    profile: LeadPausedSearchProfile,
    track_version: PausedSearchTrackVersion,
    timezone: str,
    now: datetime,
    quiet_hours_enabled: bool,
    quiet_hours_start: time | None,
    quiet_hours_end: time | None,
) -> LeadCadenceProgressView:
    """Project send times for every remaining occurrence of every step.

    The projection replays the scheduler's own planning rules
    (``plan_next_paused_search_occurrence``) with a simulated clock that
    advances to each projected send, so admins see the same dates the
    dispatcher will produce as the track unfolds.
    """

    if not is_sendable_workflow_state(workflow.state):
        return progress
    occurrences_by_step: dict[UUID, tuple[CadenceStepOccurrenceView, ...]] = {}
    sim_now = now
    scheduled_touches = workflow.logical_touch_count
    cursor_index = next(
        (
            index
            for index, step in enumerate(ordered_steps)
            if step.step_id == workflow.paused_search_track_step_id
        ),
        None,
    )
    for step_index, step in enumerate(ordered_steps):
        facts = _step_facts(str(step.step_id), outbound_messages)
        occurrence_views = [
            CadenceStepOccurrenceView(occurrence_number=index + 1, sent_at=sent_at)
            for index, sent_at in enumerate(facts.sent_ats)
        ]
        # A never-sent step behind the cursor was skipped (e.g. enrollment
        # landed directly in a later phase) and will never send.
        if cursor_index is not None and step_index < cursor_index and not facts.sent_ats:
            continue
        previous_due_at: datetime | None = facts.sent_ats[-1] if facts.sent_ats else None
        occurrence_cap = paused_search_step_occurrence_cap(step, track_version)
        targeted_workflow = replace(workflow, paused_search_track_step_id=step.step_id)
        for occurrence_number in range(len(facts.sent_ats) + 1, occurrence_cap + 1):
            if scheduled_touches >= track_version.max_total_touches:
                break
            planning_now = paused_search_planning_reference(
                step=step,
                profile=profile,
                track_version=track_version,
                now=sim_now,
            )
            plan = plan_next_paused_search_occurrence(
                profile=profile,
                track_version=track_version,
                step=step,
                steps=ordered_steps,
                workflow=targeted_workflow,
                timezone=timezone,
                now=planning_now,
                occurrence_number=occurrence_number,
                previous_due_at=previous_due_at,
                quiet_hours_enabled=quiet_hours_enabled,
                quiet_hours_start=quiet_hours_start,
                quiet_hours_end=quiet_hours_end,
            )
            if (
                plan.reason_code is not PausedSearchTimingReasonCode.SCHEDULED
                or plan.next_action_at is None
            ):
                break
            projected_for = plan.next_action_at
            # The dispatcher's own schedule is authoritative for the very
            # next occurrence of the current step.
            if (
                step.step_id == workflow.paused_search_track_step_id
                and occurrence_number == len(facts.sent_ats) + 1
            ):
                authoritative = facts.scheduled_for or workflow.next_action_at
                if authoritative is not None:
                    projected_for = authoritative
            occurrence_views.append(
                CadenceStepOccurrenceView(
                    occurrence_number=occurrence_number,
                    projected_for=projected_for,
                )
            )
            scheduled_touches += 1
            previous_due_at = plan.due_at
            sim_now = max(sim_now, projected_for)
        if occurrence_views:
            occurrences_by_step[step.step_id] = tuple(occurrence_views)
    enriched_steps: list[CadenceStepProgressView] = []
    for view in progress.steps:
        occurrence_views_for_step = occurrences_by_step.get(view.step_id, ())
        first_projected = next(
            (
                occurrence.projected_for
                for occurrence in occurrence_views_for_step
                if occurrence.projected_for is not None
            ),
            None,
        )
        enriched_steps.append(
            replace(
                view,
                occurrences=occurrence_views_for_step,
                scheduled_for=(
                    view.scheduled_for if view.scheduled_for is not None else first_projected
                ),
            )
        )
    return replace(progress, steps=tuple(enriched_steps))


def _build_progress(
    *,
    journey: LeadCadenceJourney,
    flow_name: str,
    specs: tuple[tuple[UUID, int, ContactChannel, int, str, str | None], ...],
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow | None,
    cursor_step_id: UUID | None,
) -> LeadCadenceProgressView:
    facts_by_step = {
        step_id: _step_facts(str(step_id), outbound_messages) for step_id, *_ in specs
    }
    current_step_id = _derive_current_step_id(
        specs=specs,
        facts_by_step=facts_by_step,
        workflow=workflow,
        cursor_step_id=cursor_step_id,
    )
    steps: list[CadenceStepProgressView] = []
    completed = 0
    current_order: int | None = None
    for step_id, step_order, channel, delay_hours, message_goal, phase in specs:
        facts = facts_by_step[step_id]
        status = _step_status(facts, is_current=step_id == current_step_id)
        if status == CadenceStepProgressStatus.COMPLETED:
            completed += 1
        if status in (CadenceStepProgressStatus.CURRENT, CadenceStepProgressStatus.IN_PROGRESS):
            current_order = step_order
        steps.append(
            CadenceStepProgressView(
                step_id=step_id,
                step_order=step_order,
                channel=channel,
                delay_hours=delay_hours,
                message_goal=message_goal,
                status=status,
                attempt_count=facts.attempt_count,
                sent_at=facts.sent_at,
                scheduled_for=facts.scheduled_for
                if facts.scheduled_for is not None
                else (
                    workflow.next_action_at
                    if workflow is not None and step_id == current_step_id
                    else None
                ),
                last_failure_reason=facts.last_failure_reason,
                phase=phase,
            )
        )
    return LeadCadenceProgressView(
        journey=journey,
        flow_name=flow_name,
        steps=tuple(steps),
        total_steps=len(steps),
        completed_steps=completed,
        current_step_order=current_order,
        next_action_at=workflow.next_action_at if workflow is not None else None,
        workflow_state=workflow.state if workflow is not None else None,
        is_sendable=(
            is_sendable_workflow_state(workflow.state) if workflow is not None else True
        ),
    )


def _step_facts(
    cadence_step_id: str,
    outbound_messages: tuple[OutboundMessage, ...],
) -> _StepFacts:
    attempts = tuple(
        message for message in outbound_messages if message.cadence_step_id == cadence_step_id
    )
    sent = tuple(
        message
        for message in attempts
        if message.status in (OutboundMessageStatus.SENT, OutboundMessageStatus.UNCERTAIN)
    )
    pending = tuple(
        message for message in attempts if message.status == OutboundMessageStatus.PENDING
    )
    failed = tuple(
        message for message in attempts if message.status == OutboundMessageStatus.FAILED
    )
    latest_failure = max(failed, key=lambda message: message.updated_at, default=None)
    sent_ats = tuple(
        sorted(message.sent_at for message in sent if message.sent_at is not None)
    )
    return _StepFacts(
        attempt_count=len(attempts),
        has_sent=bool(sent),
        has_pending=bool(pending),
        sent_at=sent_ats[-1] if sent_ats else None,
        sent_ats=sent_ats,
        scheduled_for=max(
            (message.scheduled_for for message in pending if message.scheduled_for is not None),
            default=None,
        ),
        last_failure_reason=latest_failure.failure_reason if latest_failure is not None else None,
    )


def _derive_current_step_id(
    *,
    specs: tuple[tuple[UUID, int, ContactChannel, int, str, str | None], ...],
    facts_by_step: dict[UUID, _StepFacts],
    workflow: LeadWorkflow | None,
    cursor_step_id: UUID | None,
) -> UUID | None:
    if workflow is not None and not is_sendable_workflow_state(workflow.state):
        return None
    known_ids = {step_id for step_id, *_ in specs}
    if cursor_step_id is not None and cursor_step_id in known_ids:
        return cursor_step_id
    # No authoritative cursor: infer the first step with a pending attempt, then
    # the first step never sent successfully.
    for step_id, *_ in specs:
        if facts_by_step[step_id].has_pending:
            return step_id
    for step_id, *_ in specs:
        if not facts_by_step[step_id].has_sent:
            return step_id
    return None


def _step_status(facts: _StepFacts, *, is_current: bool) -> CadenceStepProgressStatus:
    if facts.has_sent:
        return CadenceStepProgressStatus.COMPLETED
    if facts.has_pending:
        return CadenceStepProgressStatus.IN_PROGRESS
    if is_current:
        return (
            CadenceStepProgressStatus.FAILED
            if facts.attempt_count > 0
            else CadenceStepProgressStatus.CURRENT
        )
    if facts.attempt_count > 0:
        return CadenceStepProgressStatus.FAILED
    return CadenceStepProgressStatus.UPCOMING


_STATE_PHRASES: dict[WorkflowState, str] = {
    WorkflowState.ELIGIBLE: "Eligible for nurture",
    WorkflowState.QUEUED: "Queued to start nurture",
    WorkflowState.ACTIVE_NURTURE: "Actively nurturing",
    WorkflowState.WAITING_FOR_RESPONSE: "Waiting for the lead to respond",
    WorkflowState.RESPONSE_PROCESSING: "Processing the lead's reply",
    WorkflowState.PAUSED: "AI outreach is paused",
    WorkflowState.HUMAN_HANDOFF: "Handed off to a human agent",
    WorkflowState.HUMAN_OWNED: "Owned by a human agent",
    WorkflowState.COMPLETED: "Nurture completed",
    WorkflowState.SUPPRESSED: "Suppressed — no automated outreach",
    WorkflowState.CLOSED: "Closed",
}


def build_lead_status_narrative(
    *,
    workflow: LeadWorkflow | None,
    progress_views: tuple[LeadCadenceProgressView, ...],
    now: datetime,
) -> str:
    if workflow is None:
        return "No nurture workflow yet — the lead has not been enrolled in any campaign."

    parts: list[str] = [_STATE_PHRASES.get(workflow.state, workflow.state.value)]

    active_progress = next(
        (view for view in progress_views if view.current_step_order is not None),
        progress_views[0] if progress_views else None,
    )
    if active_progress is not None:
        if active_progress.current_step_order is not None:
            parts.append(
                f"step {active_progress.current_step_order} of "
                f"{active_progress.total_steps} in {active_progress.flow_name}"
            )
        elif active_progress.completed_steps > 0:
            parts.append(
                f"{active_progress.completed_steps} of {active_progress.total_steps} "
                f"steps completed in {active_progress.flow_name}"
            )

    if workflow.state == WorkflowState.PAUSED and workflow.pause_reason:
        parts.append(f"reason: {workflow.pause_reason}")
    elif workflow.next_action_at is not None and not is_terminal_workflow_state(workflow.state):
        when = workflow.next_action_at.strftime("%b %-d, %Y %H:%M UTC")
        if workflow.next_action_at <= now:
            parts.append(f"next action was due {when} and is awaiting the dispatcher")
        else:
            parts.append(f"next action scheduled for {when}")

    return " — ".join(parts)
