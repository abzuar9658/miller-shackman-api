from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads.canonical import PausedSearchReasonCode, PausedSearchSource


class CustomerTimingStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class CustomerTimingEvidenceType(StrEnum):
    CRM_FIELD = "crm_field"
    CRM_NOTE = "crm_note"
    INBOUND_MESSAGE = "inbound_message"
    OPERATOR_INPUT = "operator_input"
    AI_EXTRACTION = "ai_extraction"


@dataclass(frozen=True)
class CustomerTimingCandidate:
    timing_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    reason_code: PausedSearchReasonCode | None
    customer_date: datetime | None
    source: PausedSearchSource
    evidence_type: CustomerTimingEvidenceType
    evidence: str
    confidence: float | None
    status: CustomerTimingStatus
    created_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by_user_id: UUID | None = None
    superseded_at: datetime | None = None


def confirm_customer_timing(
    candidate: CustomerTimingCandidate,
    *,
    actor_user_id: UUID,
    confirmed_at: datetime,
) -> CustomerTimingCandidate:
    if candidate.status not in {
        CustomerTimingStatus.CANDIDATE,
        CustomerTimingStatus.AMBIGUOUS,
    }:
        raise ValueError("only candidate or ambiguous timing can be confirmed")
    if candidate.customer_date is None:
        raise ValueError("confirmed customer timing requires a customer date")
    return replace(
        candidate,
        status=CustomerTimingStatus.CONFIRMED,
        confirmed_at=confirmed_at,
        confirmed_by_user_id=actor_user_id,
    )
