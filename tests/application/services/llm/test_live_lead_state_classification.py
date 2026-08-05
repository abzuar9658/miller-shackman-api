from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.providers import build_llm_client

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000040")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000041")


@pytest.mark.live_llm
async def test_live_lead_classifier_returns_a_valid_structured_result() -> None:
    result = await classify_lead_from_conversation(
        lead=CanonicalLeadRecord(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="live-classification-lead",
            facts_derived_at=NOW,
            source_payload_version="test:live-v1",
        ),
        now=NOW,
        crm_conversation_events=(),
        llm_client=build_llm_client(),
    )

    assert result.status in {
        LeadStateClassificationStatus.CLASSIFIED,
        LeadStateClassificationStatus.REJECTED,
    }