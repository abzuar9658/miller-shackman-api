from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId


class LeadStartStatus(StrEnum):
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    ALREADY_ACTIVE_ELSEWHERE = "already_active_elsewhere"
    TERMINAL_REQUIRES_MANUAL_ENROLLMENT = "terminal_requires_manual_enrollment"
    REENTRY_REASON_REQUIRED = "reentry_reason_required"
    FAILED = "failed"


@dataclass(frozen=True)
class LeadStartResult:
    lead_id: LeadId
    status: LeadStartStatus
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    error: str | None = None
