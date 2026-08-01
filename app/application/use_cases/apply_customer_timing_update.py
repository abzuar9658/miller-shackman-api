from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.repositories import CustomerTimingRepository
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads import (
    CustomerTimingCandidate,
    CustomerTimingEvidenceType,
    CustomerTimingStatus,
    PausedSearchReasonCode,
    PausedSearchSource,
)


@dataclass(frozen=True)
class CustomerTimingUpdateResult:
    candidate: CustomerTimingCandidate
    created: bool


async def apply_customer_timing_update(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason_code: PausedSearchReasonCode | None,
    customer_date: datetime | None,
    source: PausedSearchSource,
    evidence_type: CustomerTimingEvidenceType,
    evidence: str,
    confidence: float | None,
    now: datetime,
    repository: CustomerTimingRepository,
    timing_id: UUID | None = None,
) -> CustomerTimingUpdateResult:
    if not evidence.strip():
        raise ValueError("customer timing evidence is required")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("customer timing confidence must be between 0 and 1")

    candidate = CustomerTimingCandidate(
        timing_id=timing_id or uuid4(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason_code=reason_code,
        customer_date=customer_date,
        source=source,
        evidence_type=evidence_type,
        evidence=evidence.strip(),
        confidence=confidence,
        status=(
            CustomerTimingStatus.CANDIDATE
            if source == PausedSearchSource.AI_CONVERSATION_CLASSIFICATION
            else CustomerTimingStatus.CONFIRMED
        ),
        created_at=now,
        confirmed_at=now if source != PausedSearchSource.AI_CONVERSATION_CLASSIFICATION else None,
    )
    saved = await repository.save(candidate)
    return CustomerTimingUpdateResult(candidate=saved, created=True)
