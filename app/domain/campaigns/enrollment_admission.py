from dataclasses import dataclass
from enum import StrEnum

from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.common.ids import CampaignId
from app.domain.workflows import LeadWorkflow, is_terminal_workflow_state

_TERMINAL_REENTRY_SOURCES = frozenset({CampaignEnrollmentSource.MANUAL_ADMIN})


class EnrollmentAdmissionOutcome(StrEnum):
    ADMITTED = "admitted"
    ALREADY_ACTIVE_IN_CAMPAIGN = "already_active_in_campaign"
    ACTIVE_ELSEWHERE = "active_elsewhere"
    TERMINAL_REQUIRES_MANUAL_ENROLLMENT = "terminal_requires_manual_enrollment"
    PAUSED_SEARCH_TRACK_ASSIGNED = "paused_search_track_assigned"


@dataclass(frozen=True)
class EnrollmentAdmissionDecision:
    outcome: EnrollmentAdmissionOutcome
    reason: str | None = None
    requires_reentry_reason: bool = False

    @property
    def admitted(self) -> bool:
        return self.outcome == EnrollmentAdmissionOutcome.ADMITTED


def evaluate_lead_enrollment_admission(
    *,
    campaign_id: CampaignId,
    source: CampaignEnrollmentSource,
    latest_workflow: LeadWorkflow | None,
    enrolling_paused_search: bool = False,
    has_active_paused_search_assignment: bool = False,
) -> EnrollmentAdmissionDecision:
    """Decide whether a lead may start a new campaign workflow.

    A lead may hold at most one non-terminal workflow at a time, regardless of
    campaign or journey kind. Once a workflow reaches a terminal state, automatic
    sources may never re-enter the lead; only an explicit manual enrollment may.
    A lead holding an active paused-search track assignment may only start a
    paused-search journey; dormant enrollment requires clearing that assignment
    first so a lead can never sit on two tracks at once.
    """
    if not enrolling_paused_search and has_active_paused_search_assignment:
        return EnrollmentAdmissionDecision(
            outcome=EnrollmentAdmissionOutcome.PAUSED_SEARCH_TRACK_ASSIGNED,
            reason=(
                "Lead has an active paused-search track assignment; clear the "
                "paused-search profile before enrolling in a dormant journey."
            ),
        )

    if latest_workflow is None:
        return EnrollmentAdmissionDecision(outcome=EnrollmentAdmissionOutcome.ADMITTED)

    if not is_terminal_workflow_state(latest_workflow.state):
        if latest_workflow.campaign_id == campaign_id:
            return EnrollmentAdmissionDecision(
                outcome=EnrollmentAdmissionOutcome.ALREADY_ACTIVE_IN_CAMPAIGN,
                reason=(
                    f"Lead already has a {latest_workflow.state.value} workflow in this campaign."
                ),
            )
        return EnrollmentAdmissionDecision(
            outcome=EnrollmentAdmissionOutcome.ACTIVE_ELSEWHERE,
            reason=(
                f"Lead already has a {latest_workflow.state.value} workflow in campaign "
                f"{latest_workflow.campaign_id}."
            ),
        )

    if source in _TERMINAL_REENTRY_SOURCES:
        return EnrollmentAdmissionDecision(
            outcome=EnrollmentAdmissionOutcome.ADMITTED,
            requires_reentry_reason=True,
        )

    return EnrollmentAdmissionDecision(
        outcome=EnrollmentAdmissionOutcome.TERMINAL_REQUIRES_MANUAL_ENROLLMENT,
        reason=(
            f"Lead's most recent workflow is {latest_workflow.state.value}; re-entry requires "
            "explicit admin enrollment."
        ),
    )
