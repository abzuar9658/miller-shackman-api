from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionError,
    WorkflowTransitionReasonCode,
    transition_workflow,
)

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000005")
STEP_ID = UUID("00000000-0000-0000-0000-000000000006")
TRANSITION_ID = UUID("00000000-0000-0000-0000-000000000007")
EXTERNAL_EVENT_ID = UUID("00000000-0000-0000-0000-000000000008")


def test_inbound_handoff_transition_pauses_pending_action_and_records_audit() -> None:
    result = transition_workflow(
        workflow=_workflow(WorkflowState.WAITING_FOR_RESPONSE),
        to_state=WorkflowState.HUMAN_HANDOFF,
        reason_code=WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED,
        transition_id=TRANSITION_ID,
        now=NOW,
        external_event_id=EXTERNAL_EVENT_ID,
        metadata={"intent": "human_requested"},
        pause_reason="human_handoff_required",
    )

    assert result.workflow.state == WorkflowState.HUMAN_HANDOFF
    assert result.workflow.current_step_id is None
    assert result.workflow.next_action_at is None
    assert result.workflow.state_version == 4
    assert result.workflow.pause_reason == "human_handoff_required"
    assert result.transition.from_state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.transition.to_state == WorkflowState.HUMAN_HANDOFF
    assert result.transition.external_event_id == EXTERNAL_EVENT_ID
    assert result.transition.metadata == {"intent": "human_requested"}


def test_queued_workflow_can_enter_active_nurture_for_due_step() -> None:
    result = transition_workflow(
        workflow=_workflow(WorkflowState.QUEUED),
        to_state=WorkflowState.ACTIVE_NURTURE,
        reason_code=WorkflowTransitionReasonCode.CADENCE_STEP_STARTED,
        transition_id=TRANSITION_ID,
        now=NOW,
    )

    assert result.workflow.state == WorkflowState.ACTIVE_NURTURE
    assert result.workflow.current_step_id == STEP_ID
    assert result.workflow.next_action_at == NOW


def test_active_nurture_can_enter_waiting_for_response_after_send() -> None:
    result = transition_workflow(
        workflow=_workflow(WorkflowState.ACTIVE_NURTURE),
        to_state=WorkflowState.WAITING_FOR_RESPONSE,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
        transition_id=TRANSITION_ID,
        now=NOW,
    )

    assert result.workflow.state == WorkflowState.WAITING_FOR_RESPONSE
    assert result.transition.from_state == WorkflowState.ACTIVE_NURTURE
    assert result.transition.to_state == WorkflowState.WAITING_FOR_RESPONSE


def test_terminal_workflow_cannot_transition_from_inbound_reply() -> None:
    with pytest.raises(WorkflowTransitionError):
        transition_workflow(
            workflow=_workflow(WorkflowState.COMPLETED),
            to_state=WorkflowState.PAUSED,
            reason_code=WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED,
            transition_id=TRANSITION_ID,
            now=NOW,
        )


def test_human_owned_workflow_requires_explicit_authorized_resume() -> None:
    with pytest.raises(WorkflowTransitionError):
        transition_workflow(
            workflow=_workflow(WorkflowState.HUMAN_OWNED),
            to_state=WorkflowState.PAUSED,
            reason_code=WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED,
            transition_id=TRANSITION_ID,
            now=NOW,
        )


def _workflow(state: WorkflowState) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        current_step_id=STEP_ID,
        next_action_at=NOW,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW,
        updated_at=NOW,
    )
