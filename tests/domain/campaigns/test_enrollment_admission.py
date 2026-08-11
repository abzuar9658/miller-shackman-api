from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.enrollment_admission import (
    EnrollmentAdmissionOutcome,
    evaluate_lead_enrollment_admission,
)
from app.domain.workflows import LeadWorkflow, WorkflowState

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_A = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_B = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000005")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000006")


def _workflow(state: WorkflowState, campaign_id: UUID = CAMPAIGN_A) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=campaign_id,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_admits_lead_without_any_workflow() -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_A,
        source=CampaignEnrollmentSource.DORMANT_SELECTOR,
        latest_workflow=None,
    )

    assert decision.admitted
    assert decision.outcome == EnrollmentAdmissionOutcome.ADMITTED


@pytest.mark.parametrize(
    "state",
    [
        WorkflowState.QUEUED,
        WorkflowState.ACTIVE_NURTURE,
        WorkflowState.WAITING_FOR_RESPONSE,
        WorkflowState.RESPONSE_PROCESSING,
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
    ],
)
def test_rejects_re_enrollment_into_same_campaign_while_non_terminal(
    state: WorkflowState,
) -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_A,
        source=CampaignEnrollmentSource.CRM_TAG,
        latest_workflow=_workflow(state),
    )

    assert not decision.admitted
    assert decision.outcome == EnrollmentAdmissionOutcome.ALREADY_ACTIVE_IN_CAMPAIGN


@pytest.mark.parametrize(
    "source",
    [
        CampaignEnrollmentSource.CRM_TAG,
        CampaignEnrollmentSource.DORMANT_SELECTOR,
        CampaignEnrollmentSource.MANUAL_ADMIN,
        CampaignEnrollmentSource.MANUAL_AGENT,
    ],
)
def test_rejects_enrollment_when_lead_is_active_in_another_campaign(
    source: CampaignEnrollmentSource,
) -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_B,
        source=source,
        latest_workflow=_workflow(WorkflowState.ACTIVE_NURTURE, campaign_id=CAMPAIGN_A),
    )

    assert not decision.admitted
    assert decision.outcome == EnrollmentAdmissionOutcome.ACTIVE_ELSEWHERE


@pytest.mark.parametrize(
    "state",
    [WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED],
)
@pytest.mark.parametrize(
    "source",
    [CampaignEnrollmentSource.CRM_TAG, CampaignEnrollmentSource.DORMANT_SELECTOR],
)
def test_rejects_automatic_re_entry_after_terminal_state(
    state: WorkflowState,
    source: CampaignEnrollmentSource,
) -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_B,
        source=source,
        latest_workflow=_workflow(state),
    )

    assert not decision.admitted
    assert decision.outcome == EnrollmentAdmissionOutcome.TERMINAL_REQUIRES_MANUAL_ENROLLMENT


@pytest.mark.parametrize(
    "state",
    [WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED],
)
def test_allows_admin_re_entry_after_terminal_state(state: WorkflowState) -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_B,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        latest_workflow=_workflow(state),
    )

    assert decision.admitted
    assert decision.requires_reentry_reason


@pytest.mark.parametrize(
    "state",
    [WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED],
)
def test_rejects_assigned_agent_re_entry_after_terminal_state(state: WorkflowState) -> None:
    decision = evaluate_lead_enrollment_admission(
        campaign_id=CAMPAIGN_B,
        source=CampaignEnrollmentSource.MANUAL_AGENT,
        latest_workflow=_workflow(state),
    )

    assert not decision.admitted
    assert decision.outcome == EnrollmentAdmissionOutcome.TERMINAL_REQUIRES_MANUAL_ENROLLMENT
