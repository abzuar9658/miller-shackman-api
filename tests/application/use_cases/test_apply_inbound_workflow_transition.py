from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.application.use_cases.apply_inbound_workflow_transition import (
    InboundWorkflowTransitionStatus,
    apply_inbound_workflow_transition,
)
from app.application.use_cases.evaluate_inbound_action import (
    InboundAction,
    InboundActionReasonCode,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reminders import (
    PausedSearchAgentReminder,
    PausedSearchReminderStatus,
)
from app.domain.campaigns.paused_search_reply_policy import PausedSearchReplyDecision
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStepPhase
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakePausedSearchAgentReminderRepository,
    FakePausedSearchOccurrenceRepository,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)


class FakeWorkflowRepository:
    def __init__(self, workflow: LeadWorkflow) -> None:
        self.workflow = workflow

    async def get_latest_for_lead_for_update(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> LeadWorkflow | None:
        return self.workflow

    async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
        self.workflow = workflow
        return workflow

    async def list_active_paused_search_for_lead_for_update(
        self,
        workspace_id: UUID,
        lead_id: UUID,
    ) -> tuple[LeadWorkflow, ...]:
        return ()

    async def list_recent_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 5,
    ) -> tuple[LeadWorkflow, ...]:
        return (self.workflow,)[:limit]

    async def list_paused_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[LeadWorkflow, ...]:
        return ()


class FakeTransitionRepository:
    def __init__(self) -> None:
        self.transitions: list[object] = []

    async def append(self, transition: object) -> object:
        self.transitions.append(transition)
        return transition

    async def list_for_workflow(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        limit: int = 100,
    ) -> tuple[Any, ...]:
        return ()


@pytest.mark.asyncio
async def test_inbound_pause_cancels_pending_agent_reminders() -> None:
    workflow = LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-workflow-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000004"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000005"),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    reminder_repository = FakePausedSearchAgentReminderRepository()
    reminder_repository.reminders["reminder-1"] = PausedSearchAgentReminder(
        reminder_id=UUID("00000000-0000-0000-0000-000000000006"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        occurrence_id=UUID("00000000-0000-0000-0000-000000000007"),
        assigned_user_id=None,
        due_at=NOW,
        status=PausedSearchReminderStatus.PENDING,
        title="Follow up",
        body="Check in",
        idempotency_key="reminder-1",
        created_at=NOW,
    )

    result = await apply_inbound_workflow_transition(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        action=InboundAction.PAUSE_FOR_REVIEW,
        decision_reason=InboundActionReasonCode.UNCLEAR_INTENT,
        lead_workflow_repository=FakeWorkflowRepository(workflow),
        workflow_transition_repository=FakeTransitionRepository(),
        paused_search_reminder_repository=reminder_repository,
        now=NOW,
    )

    assert result.status is InboundWorkflowTransitionStatus.UPDATED
    assert result.workflow is not None
    assert result.workflow.state is WorkflowState.PAUSED
    assert reminder_repository.reminders["reminder-1"].status is (
        PausedSearchReminderStatus.CANCELLED
    )
    assert reminder_repository.reminders["reminder-1"].cancelled_at == NOW


def _workflow_with_touch_count(state: WorkflowState = WorkflowState.ACTIVE_NURTURE) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-workflow-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000004"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000005"),
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=4,
        created_at=NOW,
        updated_at=NOW,
        logical_touch_count=3,
    )


def _pending_occurrence() -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=UUID("00000000-0000-0000-0000-000000000007"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        track_version_id=UUID("00000000-0000-0000-0000-000000000008"),
        step_id=UUID("00000000-0000-0000-0000-000000000009"),
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        occurrence_number=2,
        scheduled_for=NOW,
        due_at=NOW,
        status=RecurringOccurrenceStatus.PLANNED,
        idempotency_key="occurrence-2",
        created_at=NOW,
        logical_touch_count=2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "action", "expected_state"),
    [
        (
            PausedSearchReplyDecision.END,
            InboundAction.COMPLETE_AUTOMATION,
            WorkflowState.COMPLETED,
        ),
        (
            PausedSearchReplyDecision.RESTART,
            InboundAction.CONTINUE_AI,
            WorkflowState.ACTIVE_NURTURE,
        ),
    ],
)
async def test_end_and_restart_preserve_counters_and_cancel_pending_work(
    decision: PausedSearchReplyDecision,
    action: InboundAction,
    expected_state: WorkflowState,
) -> None:
    workflow_repository = FakeWorkflowRepository(
        _workflow_with_touch_count(
            state=(
                WorkflowState.WAITING_FOR_RESPONSE
                if decision is PausedSearchReplyDecision.RESTART
                else WorkflowState.ACTIVE_NURTURE
            )
        )
    )
    transition_repository = FakeTransitionRepository()
    occurrence_repository = FakePausedSearchOccurrenceRepository(_pending_occurrence())
    reminder_repository = FakePausedSearchAgentReminderRepository()
    reminder_repository.reminders["reminder-1"] = PausedSearchAgentReminder(
        reminder_id=UUID("00000000-0000-0000-0000-000000000010"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        occurrence_id=UUID("00000000-0000-0000-0000-000000000007"),
        assigned_user_id=None,
        due_at=NOW,
        status=PausedSearchReminderStatus.PENDING,
        title="Follow up",
        body="Check in",
        idempotency_key="reminder-1",
        created_at=NOW,
    )

    result = await apply_inbound_workflow_transition(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        action=action,
        decision_reason=InboundActionReasonCode.PAUSED_SEARCH_REPLY_REVIEW,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=transition_repository,
        paused_search_occurrence_repository=occurrence_repository,
        paused_search_reminder_repository=reminder_repository,
        paused_search_reply_decision=decision,
        now=NOW,
    )

    assert result.status is InboundWorkflowTransitionStatus.UPDATED
    assert result.workflow is not None
    assert result.workflow.state is expected_state
    assert result.workflow.logical_touch_count == 3
    assert occurrence_repository.occurrence is not None
    assert occurrence_repository.occurrence.status is RecurringOccurrenceStatus.CANCELLED
    assert reminder_repository.reminders["reminder-1"].status is (
        PausedSearchReminderStatus.CANCELLED
    )