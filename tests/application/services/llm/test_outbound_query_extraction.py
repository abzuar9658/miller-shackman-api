import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.outbound_query_extraction import (
    OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION,
    OutboundQueryExtractionMethod,
    OutboundQueryExtractionReasonCode,
    OutboundQueryExtractionStatus,
    build_outbound_context_with_query_extraction,
    extract_outbound_query_preferences,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model=request.model or "openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=17,
            usage_tokens=41,
        )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
    )


async def test_query_extraction_rent_vs_sale() -> None:
    llm = FakeLLMClient(
        json.dumps(
            {
                "search_type": "rent",
                "location": ["Astoria"],
                "max_price": "2400",
                "beds": 2,
                "confidence": 0.92,
                "reasons": ["Monthly budget language indicates a rental search."],
            }
        )
    )

    result = await extract_outbound_query_preferences(
        lead=_lead(),
        query_text="Need a 2 bedroom in Astoria around $2,400 per month.",
        llm_client=llm,
        enabled_fields=("search_type", "location", "max_price", "beds"),
    )

    assert result.status == OutboundQueryExtractionStatus.EXTRACTED
    assert result.preferences == {
        "search_type": "rent",
        "location": "Astoria",
        "max_price": "2400",
        "beds": "2",
    }
    assert result.confidence == 0.92
    assert llm.requests[0].prompt_version == OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION
    assert "Need a 2 bedroom in Astoria around $2,400 per month." in llm.requests[0].prompt


async def test_extraction_fallback_when_llm_invalid() -> None:
    selection = await build_outbound_context_with_query_extraction(
        lead=_lead(),
        now=NOW,
        llm_client=FakeLLMClient("not-json"),
        enabled_query_extraction_fields=("location", "max_price", "search_type"),
        activity_items=(
            LeadActivityItem(
                activity_id=uuid4(),
                lead_id=uuid4(),
                kind=LeadActivityKind.INBOUND_MESSAGE,
                occurred_at=NOW,
                title="Lead replied",
                preview="Looking for a rental in Queens under $2k/month.",
                content="Looking for a rental in Queens under $2k/month.",
                channel="sms",
                direction="inbound",
                actor_name="lead",
            ),
        ),
    )

    assert selection.method == OutboundQueryExtractionMethod.FALLBACK
    assert selection.reasons == (OutboundQueryExtractionReasonCode.INVALID_LLM_RESPONSE,)
    assert selection.lead_context.extracted_preferences["search_type"] == "rent"
    assert selection.lead_context.extracted_preferences["location"] == "Queens"
    assert selection.lead_context.extracted_preferences["max_price"] == "2000"
