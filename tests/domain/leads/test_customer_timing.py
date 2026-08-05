from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.leads import (
    CustomerTimingCandidate,
    CustomerTimingEvidenceType,
    CustomerTimingStatus,
    PausedSearchSource,
    confirm_customer_timing,
)


def test_confirming_ai_candidate_requires_a_date_and_records_operator() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    candidate = CustomerTimingCandidate(
        timing_id=uuid4(),
        workspace_id=uuid4(),
        lead_id=uuid4(),
        customer_date=now,
        source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
        evidence_type=CustomerTimingEvidenceType.AI_EXTRACTION,
        evidence="Customer said next summer",
        confidence=0.8,
        status=CustomerTimingStatus.CANDIDATE,
        created_at=now,
    )

    confirmed = confirm_customer_timing(candidate, actor_user_id=uuid4(), confirmed_at=now)

    assert confirmed.status == CustomerTimingStatus.CONFIRMED
    assert confirmed.confirmed_by_user_id is not None


def test_confirming_without_a_date_is_rejected() -> None:
    now = datetime(2026, 7, 1, tzinfo=UTC)
    candidate = CustomerTimingCandidate(
        timing_id=uuid4(),
        workspace_id=uuid4(),
        lead_id=uuid4(),
        customer_date=None,
        source=PausedSearchSource.OPERATOR,
        evidence_type=CustomerTimingEvidenceType.OPERATOR_INPUT,
        evidence="No date supplied",
        confidence=None,
        status=CustomerTimingStatus.CANDIDATE,
        created_at=now,
    )

    with pytest.raises(ValueError, match="customer date"):
        confirm_customer_timing(candidate, actor_user_id=uuid4(), confirmed_at=now)
