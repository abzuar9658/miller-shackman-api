from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
from app.domain.campaigns import PausedSearchTrackCatalogEntry
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.infrastructure.providers import build_llm_client

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000020")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000021")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000022")


@pytest.mark.live_llm
async def test_live_classifier_uses_catalog_keys_and_returns_a_safe_route() -> None:
    lead = CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="live-paused-search-lead",
        facts_derived_at=NOW,
        source_payload_version="test:live-v1",
    )
    event = CrmConversationEvent(
        crm_conversation_event_id=UUID("00000000-0000-0000-0000-000000000023"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider="follow_up_boss",
        crm_activity_id="live-paused-search-event",
        activity_type="Text message",
        direction=CrmConversationEventDirection.INBOUND,
        content="We still want to buy, but please check back after rates improve.",
        occurred_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    catalog = (
        PausedSearchTrackCatalogEntry(
            track_key="waiting-for-rates",
            display_name="Waiting for rates",
            selection_guidance="Use only when the lead explicitly waits for rates.",
            track_id=UUID("00000000-0000-0000-0000-000000000024"),
            track_version_id=TRACK_VERSION_ID,
        ),
    )

    result = await classify_lead_from_conversation(
        lead=lead,
        now=NOW,
        crm_conversation_events=(event,),
        llm_client=build_llm_client(),
        paused_search_catalog=catalog,
    )

    assert result.status in {
        LeadStateClassificationStatus.CLASSIFIED,
        LeadStateClassificationStatus.REJECTED,
    }
    if result.track_version_id is not None:
        assert result.track_version_id == TRACK_VERSION_ID