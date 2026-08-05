from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.lead_workflow_overrides import (
    _next_step_id_after_current,
    _workflow_allows_cursor_override,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTimingBasis,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import LeadWorkflow, WorkflowState

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000002")


def _step(step_id: UUID, order: int) -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=UUID("00000000-0000-0000-0000-000000000010"),
        track_version_id=UUID("00000000-0000-0000-0000-000000000011"),
        step_order=order,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        delay_hours=24,
        message_goal="Check in on timing.",
        template_key=f"paused-search-{order}",
        max_attempts=1,
        review_required=False,
        timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
        created_at=NOW,
    )


def _workflow(state: WorkflowState) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=UUID("00000000-0000-0000-0000-000000000012"),
        temporal_workflow_id="lead-nurture:override-test",
        workspace_id=UUID("00000000-0000-0000-0000-000000000010"),
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000013"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000014"),
        lead_id=UUID("00000000-0000-0000-0000-000000000015"),
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_override_cursor_moves_to_next_step_in_the_pinned_track_version() -> None:
    steps = (_step(STEP_ONE_ID, 1), _step(STEP_TWO_ID, 2))

    assert _next_step_id_after_current(STEP_ONE_ID, steps) == STEP_TWO_ID


def test_cursor_override_is_limited_to_live_workflow_states() -> None:
    assert _workflow_allows_cursor_override(_workflow(WorkflowState.PAUSED))
    assert _workflow_allows_cursor_override(_workflow(WorkflowState.ACTIVE_NURTURE))
    assert not _workflow_allows_cursor_override(_workflow(WorkflowState.HUMAN_OWNED))