from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.application.use_cases.apply_customer_timing_update import (
    apply_customer_timing_update,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads import (
    CustomerTimingCandidate,
    CustomerTimingEvidenceType,
    CustomerTimingStatus,
    PausedSearchReasonCode,
    PausedSearchSource,
)


class FakeCustomerTimingRepository:
    def __init__(self) -> None:
        self.saved: list[CustomerTimingCandidate] = []

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> tuple[CustomerTimingCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.saved
            if candidate.workspace_id == workspace_id and candidate.lead_id == lead_id
        )

    async def save(self, candidate: CustomerTimingCandidate) -> CustomerTimingCandidate:
        self.saved.append(candidate)
        return candidate


@pytest.mark.asyncio
async def test_ai_timing_is_candidate_until_operator_confirmation() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    repository = FakeCustomerTimingRepository()

    result = await apply_customer_timing_update(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        reason_code=PausedSearchReasonCode.TIMING_NOT_RIGHT,
        customer_date=now,
        source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
        evidence_type=CustomerTimingEvidenceType.AI_EXTRACTION,
        evidence="Customer said next summer",
        confidence=0.8,
        now=now,
        repository=repository,
    )

    assert result.candidate.status == CustomerTimingStatus.CANDIDATE
    assert result.candidate.confirmed_at is None


@pytest.mark.asyncio
async def test_operator_timing_is_confirmed_immediately() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    repository = FakeCustomerTimingRepository()

    result = await apply_customer_timing_update(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        reason_code=PausedSearchReasonCode.TIMING_NOT_RIGHT,
        customer_date=now,
        source=PausedSearchSource.OPERATOR,
        evidence_type=CustomerTimingEvidenceType.OPERATOR_INPUT,
        evidence="Operator confirmed date",
        confidence=None,
        now=now,
        repository=repository,
    )

    assert result.candidate.status == CustomerTimingStatus.CONFIRMED
    assert result.candidate.confirmed_at == now