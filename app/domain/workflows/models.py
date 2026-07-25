from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import CampaignId, LeadId, UserId, WorkspaceId


class WorkflowState(StrEnum):
    ELIGIBLE = "eligible"
    QUEUED = "queued"
    ACTIVE_NURTURE = "active_nurture"
    WAITING_FOR_RESPONSE = "waiting_for_response"
    RESPONSE_PROCESSING = "response_processing"
    PAUSED = "paused"
    HUMAN_HANDOFF = "human_handoff"
    HUMAN_OWNED = "human_owned"
    COMPLETED = "completed"
    SUPPRESSED = "suppressed"
    CLOSED = "closed"


class WorkflowTransitionReasonCode(StrEnum):
    CAMPAIGN_ENROLLMENT_STARTED = "campaign_enrollment_started"
    CADENCE_STEP_STARTED = "cadence_step_started"
    INBOUND_REPLY_RECEIVED = "inbound_reply_received"
    INBOUND_REVIEW_REQUIRED = "inbound_review_required"
    CRM_HUMAN_ACTIVITY_DETECTED = "crm_human_activity_detected"
    CRM_OWNERSHIP_CHANGED = "crm_ownership_changed"
    CONTACT_SUPPRESSION_DETECTED = "contact_suppression_detected"
    LEAD_NOT_INTERESTED = "lead_not_interested"
    REPLY_CLASSIFICATION_REJECTED = "reply_classification_rejected"
    HUMAN_HANDOFF_REQUIRED = "human_handoff_required"
    OPT_OUT_DETECTED = "opt_out_detected"
    OUTBOUND_MESSAGE_SENT = "outbound_message_sent"
    OUTBOUND_MESSAGE_BLOCKED = "outbound_message_blocked"
    OUTBOUND_MESSAGE_FAILED = "outbound_message_failed"
    MANUAL_PAUSE = "manual_pause"
    MANUAL_RESUME = "manual_resume"
    CONTACT_POLICY_UPDATED = "contact_policy_updated"


class WorkflowTransitionError(ValueError):
    pass


def _empty_metadata() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class LeadWorkflow:
    workflow_id: UUID
    temporal_workflow_id: str
    workspace_id: WorkspaceId
    campaign_enrollment_id: UUID
    campaign_id: CampaignId
    lead_id: LeadId
    state: WorkflowState
    last_transition_at: datetime
    state_version: int
    created_at: datetime
    updated_at: datetime
    current_step_id: UUID | None = None
    next_action_at: datetime | None = None
    pause_reason: str | None = None
    resume_reason: str | None = None


@dataclass(frozen=True)
class WorkflowTransition:
    transition_id: UUID
    workspace_id: WorkspaceId
    workflow_id: UUID
    lead_id: LeadId
    campaign_id: CampaignId
    to_state: WorkflowState
    reason_code: WorkflowTransitionReasonCode
    created_at: datetime
    from_state: WorkflowState | None = None
    actor_user_id: UserId | None = None
    external_event_id: UUID | None = None
    metadata: Mapping[str, object] = field(default_factory=_empty_metadata)


@dataclass(frozen=True)
class WorkflowTransitionResult:
    workflow: LeadWorkflow
    transition: WorkflowTransition


def transition_workflow(
    *,
    workflow: LeadWorkflow,
    to_state: WorkflowState,
    reason_code: WorkflowTransitionReasonCode,
    transition_id: UUID,
    now: datetime,
    actor_user_id: UserId | None = None,
    external_event_id: UUID | None = None,
    metadata: Mapping[str, object] | None = None,
    pause_reason: str | None = None,
    resume_reason: str | None = None,
) -> WorkflowTransitionResult:
    _validate_transition(workflow.state, to_state)
    updated = replace(
        workflow,
        state=to_state,
        current_step_id=_next_current_step_id(workflow, to_state),
        next_action_at=_next_action_at(workflow, to_state),
        last_transition_at=now,
        pause_reason=pause_reason
        if to_state in {WorkflowState.PAUSED, WorkflowState.HUMAN_HANDOFF, WorkflowState.SUPPRESSED}
        else None,
        resume_reason=resume_reason,
        state_version=workflow.state_version + 1,
        updated_at=now,
    )
    transition = WorkflowTransition(
        transition_id=transition_id,
        workspace_id=workflow.workspace_id,
        workflow_id=workflow.workflow_id,
        lead_id=workflow.lead_id,
        campaign_id=workflow.campaign_id,
        from_state=workflow.state,
        to_state=to_state,
        reason_code=reason_code,
        actor_user_id=actor_user_id,
        external_event_id=external_event_id,
        metadata=metadata or {},
        created_at=now,
    )
    return WorkflowTransitionResult(workflow=updated, transition=transition)


def _validate_transition(from_state: WorkflowState, to_state: WorkflowState) -> None:
    if from_state in _terminal_states():
        raise WorkflowTransitionError(
            f"Cannot transition workflow from terminal state {from_state.value}."
        )
    if from_state == WorkflowState.HUMAN_OWNED and to_state != WorkflowState.ACTIVE_NURTURE:
        raise WorkflowTransitionError("Human-owned workflows require explicit authorized resume.")
    if to_state in {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.SUPPRESSED,
        WorkflowState.COMPLETED,
        WorkflowState.CLOSED,
    }:
        return
    if from_state == WorkflowState.QUEUED and to_state == WorkflowState.ACTIVE_NURTURE:
        return
    if from_state == WorkflowState.PAUSED and to_state == WorkflowState.ACTIVE_NURTURE:
        return
    if (
        from_state in {WorkflowState.HUMAN_HANDOFF, WorkflowState.HUMAN_OWNED}
        and to_state == WorkflowState.ACTIVE_NURTURE
    ):
        return
    if (
        from_state == WorkflowState.WAITING_FOR_RESPONSE
        and to_state == WorkflowState.ACTIVE_NURTURE
    ):
        return
    if (
        from_state == WorkflowState.WAITING_FOR_RESPONSE
        and to_state == WorkflowState.RESPONSE_PROCESSING
    ):
        return
    if (
        from_state == WorkflowState.RESPONSE_PROCESSING
        and to_state == WorkflowState.WAITING_FOR_RESPONSE
    ):
        return
    if (
        from_state == WorkflowState.RESPONSE_PROCESSING
        and to_state in {WorkflowState.PAUSED, WorkflowState.HUMAN_HANDOFF}
    ):
        return
    if (
        from_state == WorkflowState.ACTIVE_NURTURE
        and to_state == WorkflowState.WAITING_FOR_RESPONSE
    ):
        return
    raise WorkflowTransitionError(
        f"Transition from {from_state.value} to {to_state.value} is not allowed in V1.",
    )


def _terminal_states() -> frozenset[WorkflowState]:
    return frozenset({WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED})


def _non_sendable_states() -> frozenset[WorkflowState]:
    return frozenset(
        {
            WorkflowState.PAUSED,
            WorkflowState.HUMAN_HANDOFF,
            WorkflowState.HUMAN_OWNED,
            WorkflowState.COMPLETED,
            WorkflowState.SUPPRESSED,
            WorkflowState.CLOSED,
        }
    )


def _next_current_step_id(workflow: LeadWorkflow, to_state: WorkflowState) -> UUID | None:
    if to_state in _terminal_states() | {WorkflowState.HUMAN_HANDOFF, WorkflowState.HUMAN_OWNED}:
        return None
    return workflow.current_step_id


def _next_action_at(workflow: LeadWorkflow, to_state: WorkflowState) -> datetime | None:
    if to_state in _non_sendable_states():
        return None
    return workflow.next_action_at
