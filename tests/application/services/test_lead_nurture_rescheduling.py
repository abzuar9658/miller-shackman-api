from datetime import UTC, datetime
from uuid import UUID

from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("20000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("20000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("20000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("20000000-0000-0000-0000-000000000005")
USER_ID = UUID("20000000-0000-0000-0000-000000000006")


async def test_enqueue_lead_nurture_reschedule_signal_is_idempotent() -> None:
    workflow_repository = FakeLeadWorkflowRepository()
    outbox_repository = FakeTemporalSignalOutboxRepository()
    await workflow_repository.save(_workflow())

    first = await enqueue_lead_nurture_reschedule_signal(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="paused_search_profile_updated",
        occurred_at=NOW,
        lead_workflow_repository=workflow_repository,
        temporal_signal_outbox_repository=outbox_repository,
        actor_user_id=USER_ID,
    )
    second = await enqueue_lead_nurture_reschedule_signal(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        reason="paused_search_profile_updated",
        occurred_at=NOW,
        lead_workflow_repository=workflow_repository,
        temporal_signal_outbox_repository=outbox_repository,
        actor_user_id=USER_ID,
    )

    assert first is True
    assert second is True
    assert len(outbox_repository.entries) == 1
    entry = next(iter(outbox_repository.entries.values()))
    assert entry.signal_name == TemporalSignalName.RESCHEDULE_REQUESTED
    assert entry.payload["reason"] == "paused_search_profile_updated"


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test-reschedule",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.PAUSED,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
