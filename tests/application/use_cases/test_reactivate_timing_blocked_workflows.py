import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.application.use_cases.reactivate_timing_blocked_workflows import (
    ReactivateTimingBlockedWorkflowStatus,
    reactivate_timing_blocked_workflow,
    reactivate_timing_blocked_workflows_for_workspace,
)
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)

WORKSPACE_ID = WorkspaceId("00000000-0000-0000-0000-000000000001")
LEAD_ID = LeadId("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = CampaignId("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
TRANSITION_ID = UUID("00000000-0000-0000-0000-000000000005")
REACTIVATION_TRANSITION_ID = UUID("00000000-0000-0000-0000-000000000007")
CAMPAIGN_ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")
NOW = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


def _paused_workflow(
    *,
    pause_reason: str = "cadence_step_blocked",
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_enrollment_id=CAMPAIGN_ENROLLMENT_ID,
        temporal_workflow_id="temporal-123",
        state=WorkflowState.PAUSED,
        state_version=2,
        created_at=NOW - timedelta(hours=2),
        updated_at=NOW - timedelta(hours=1),
        last_transition_at=NOW - timedelta(minutes=30),
        current_step_id=uuid4(),
        next_action_at=None,
        pause_reason=pause_reason,
    )


def _outside_hours_block_transition() -> WorkflowTransition:
    return WorkflowTransition(
        transition_id=TRANSITION_ID,
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        from_state=WorkflowState.ACTIVE_NURTURE,
        to_state=WorkflowState.PAUSED,
        reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
        created_at=NOW - timedelta(minutes=30),
        metadata={
            "pre_send_reasons": ["outside_allowed_hours"],
            "explanation": "Outside allowed hours",
        },
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_reactivates_paused_workflow_blocked_only_by_outside_hours() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _paused_workflow()

    transition_repo = FakeWorkflowTransitionRepository()
    transition_repo.transitions[TRANSITION_ID] = _outside_hours_block_transition()

    signal_repo = FakeTemporalSignalOutboxRepository()

    result = _run(
        reactivate_timing_blocked_workflow(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_workflow_repository=workflow_repo,
            workflow_transition_repository=transition_repo,
            temporal_signal_outbox_repository=signal_repo,
            now=NOW,
            id_generator=lambda: REACTIVATION_TRANSITION_ID,
        )
    )

    assert result.status == ReactivateTimingBlockedWorkflowStatus.REACTIVATED
    assert result.workflow_id == WORKFLOW_ID
    assert result.signal_queued is True

    workflow = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.ACTIVE_NURTURE
    assert workflow.pause_reason is None

    transitions = transition_repo.transitions
    assert len(transitions) == 2
    resumed = next(
        transition
        for transition in transitions.values()
        if transition.transition_id != TRANSITION_ID
    )
    assert resumed.reason_code == WorkflowTransitionReasonCode.CONTACT_POLICY_UPDATED
    assert resumed.to_state == WorkflowState.ACTIVE_NURTURE
    assert resumed.metadata["explanation"] == "Quiet hours disabled \u2014 workflow auto-resumed"

    signals = tuple(signal_repo.entries.values())
    assert len(signals) == 1
    assert signals[0].signal_name == TemporalSignalName.RESUME_REQUESTED


def test_does_not_reactivate_when_block_includes_other_reasons() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _paused_workflow()

    transition_repo = FakeWorkflowTransitionRepository()
    transition_repo.transitions[TRANSITION_ID] = replace(
        _outside_hours_block_transition(),
        metadata={
            "pre_send_reasons": ["outside_allowed_hours", "frequency_limit_reached"],
            "explanation": "Outside allowed hours and frequency limit reached",
        },
    )

    signal_repo = FakeTemporalSignalOutboxRepository()

    result = _run(
        reactivate_timing_blocked_workflow(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_workflow_repository=workflow_repo,
            workflow_transition_repository=transition_repo,
            temporal_signal_outbox_repository=signal_repo,
            now=NOW,
        )
    )

    assert result.status == ReactivateTimingBlockedWorkflowStatus.NOT_TIMING_BLOCKED
    assert len(signal_repo.entries) == 0


def test_does_not_reactivate_when_workflow_is_not_paused() -> None:
    workflow = replace(_paused_workflow(), state=WorkflowState.HUMAN_HANDOFF)
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = workflow

    transition_repo = FakeWorkflowTransitionRepository()
    transition_repo.transitions[TRANSITION_ID] = _outside_hours_block_transition()
    signal_repo = FakeTemporalSignalOutboxRepository()

    result = _run(
        reactivate_timing_blocked_workflow(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            lead_workflow_repository=workflow_repo,
            workflow_transition_repository=transition_repo,
            temporal_signal_outbox_repository=signal_repo,
            now=NOW,
        )
    )

    assert result.status == ReactivateTimingBlockedWorkflowStatus.NOT_TIMING_BLOCKED
    assert len(signal_repo.entries) == 0


def test_workspace_reactivation_only_runs_when_quiet_hours_disabled() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _paused_workflow()
    transition_repo = FakeWorkflowTransitionRepository()
    transition_repo.transitions[TRANSITION_ID] = _outside_hours_block_transition()
    signal_repo = FakeTemporalSignalOutboxRepository()

    results = _run(
        reactivate_timing_blocked_workflows_for_workspace(
            workspace_id=WORKSPACE_ID,
            quiet_hours_previously_enabled=True,
            quiet_hours_now_enabled=False,
            lead_workflow_repository=workflow_repo,
            workflow_transition_repository=transition_repo,
            temporal_signal_outbox_repository=signal_repo,
            now=NOW,
        )
    )

    assert len(results) == 1
    assert results[0].status == ReactivateTimingBlockedWorkflowStatus.REACTIVATED


def test_workspace_reactivation_skips_when_quiet_hours_still_enabled() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)] = _paused_workflow()
    transition_repo = FakeWorkflowTransitionRepository()
    transition_repo.transitions[TRANSITION_ID] = _outside_hours_block_transition()
    signal_repo = FakeTemporalSignalOutboxRepository()

    results = _run(
        reactivate_timing_blocked_workflows_for_workspace(
            workspace_id=WORKSPACE_ID,
            quiet_hours_previously_enabled=True,
            quiet_hours_now_enabled=True,
            lead_workflow_repository=workflow_repo,
            workflow_transition_repository=transition_repo,
            temporal_signal_outbox_repository=signal_repo,
            now=NOW,
        )
    )

    assert len(results) == 0
    assert len(signal_repo.entries) == 0
