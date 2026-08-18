from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.common.ids import (
    CampaignEnrollmentId,
    CampaignId,
    CampaignVersionId,
    LeadId,
    UserId,
    WorkspaceId,
)
from app.domain.workflows import WorkflowState


class CampaignEnrollmentSource(StrEnum):
    CRM_TAG = "crm_tag"
    DORMANT_SELECTOR = "dormant_selector"
    MANUAL_ADMIN = "manual_admin"
    MANUAL_AGENT = "manual_agent"


class CampaignEnrollmentStatus(StrEnum):
    CANDIDATE = "candidate"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    HANDOFF = "handoff"
    COMPLETED = "completed"
    SUPPRESSED = "suppressed"
    CLOSED = "closed"


@dataclass(frozen=True)
class CampaignEnrollment:
    campaign_enrollment_id: CampaignEnrollmentId
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    campaign_version_id: CampaignVersionId
    lead_id: LeadId
    source: CampaignEnrollmentSource
    status: CampaignEnrollmentStatus
    eligible_at: datetime | None
    enrolled_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    created_by_user_id: UserId | None
    reason_codes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            CampaignEnrollmentStatus.COMPLETED,
            CampaignEnrollmentStatus.SUPPRESSED,
            CampaignEnrollmentStatus.CLOSED,
        }


def enrollment_status_for_terminal_workflow_state(
    state: WorkflowState,
) -> CampaignEnrollmentStatus | None:
    """Map a terminal workflow state to the enrollment status that mirrors it.

    Returns None for non-terminal states so callers can no-op safely.
    """
    return {
        WorkflowState.COMPLETED: CampaignEnrollmentStatus.COMPLETED,
        WorkflowState.SUPPRESSED: CampaignEnrollmentStatus.SUPPRESSED,
        WorkflowState.CLOSED: CampaignEnrollmentStatus.CLOSED,
    }.get(state)


def build_enrollment_reason_codes(
    *,
    source: CampaignEnrollmentSource,
    additional_reasons: Sequence[str] | None = None,
) -> tuple[str, ...]:
    reasons = [source.value]
    if additional_reasons:
        reasons.extend(additional_reasons)
    return tuple(reasons)
