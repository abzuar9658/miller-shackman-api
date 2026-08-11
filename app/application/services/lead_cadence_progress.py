from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.execution import CampaignCadenceStep
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStep
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import LeadWorkflow, WorkflowState, is_terminal_workflow_state


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


@dataclass(frozen=True)
class LeadCadenceProgressView:
    journey: LeadCadenceJourney
    flow_name: str
    steps: tuple[CadenceStepProgressView, ...]
    total_steps: int
    completed_steps: int
    current_step_order: int | None = None
    next_action_at: datetime | None = None


@dataclass(frozen=True)
class _StepFacts:
    attempt_count: int
    has_sent: bool
    has_pending: bool
    sent_at: datetime | None
    scheduled_for: datetime | None
    last_failure_reason: str | None


def build_dormant_cadence_progress(
    *,
    flow_name: str,
    cadence_steps: tuple[CampaignCadenceStep, ...],
    outbound_messages: tuple[OutboundMessage, ...],
    workflow: LeadWorkflow | None,
) -> LeadCadenceProgressView | None:
    if not cadence_steps:
        return None
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
) -> LeadCadenceProgressView | None:
    if not track_steps:
        return None
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
    return _build_progress(
        journey=LeadCadenceJourney.PAUSED_SEARCH,
        flow_name=flow_name,
        specs=specs,
        outbound_messages=outbound_messages,
        workflow=workflow,
        cursor_step_id=workflow.paused_search_track_step_id if workflow is not None else None,
    )


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
    return _StepFacts(
        attempt_count=len(attempts),
        has_sent=bool(sent),
        has_pending=bool(pending),
        sent_at=max(
            (message.sent_at for message in sent if message.sent_at is not None),
            default=None,
        ),
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
    if workflow is not None and is_terminal_workflow_state(workflow.state):
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
