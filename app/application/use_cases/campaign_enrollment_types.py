from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId


class LeadStartStatus(StrEnum):
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    FAILED = "failed"


@dataclass(frozen=True)
class LeadStartResult:
    lead_id: LeadId
    status: LeadStartStatus
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    error: str | None = None
