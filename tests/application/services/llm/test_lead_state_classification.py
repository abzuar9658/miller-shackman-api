import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationReasonCode,
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    HandoffReasonCode,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadStateClassificationOutcome,
    PausedSearchReasonCode,
    PropertyEventType,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class _StubLLMClient(LLMClient):
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=10,
            usage_tokens=20,
        )


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-1",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
    )


def _event(
    content: str,
    *,
    direction: CrmConversationEventDirection = CrmConversationEventDirection.INBOUND,
    occurred_at: datetime = NOW,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=f"act-{content[:20]}",
        activity_type="Note",
        direction=direction,
        content=content,
        occurred_at=occurred_at,
        created_at=occurred_at,
        updated_at=occurred_at,
    )


def _classification_json(**kwargs: object) -> str:
    return json.dumps(kwargs)


async def test_classifies_paused_search_with_reason_and_timing() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            reengagement_not_before="2026-09-01",
            reengagement_window_label="after summer",
            confidence=0.88,
            evidence=["Lead said rates are too high"],
            summary="Lead is waiting for lower rates.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("I'm waiting for rates to drop"),),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH
    assert result.pause_reason_code == PausedSearchReasonCode.WAITING_FOR_RATES
    assert result.reengagement_not_before == datetime(2026, 9, 1, tzinfo=UTC)
    assert result.reengagement_window_label == "after summer"
    assert result.confidence == 0.88
    assert result.evidence == ("Lead said rates are too high",)
    assert result.summary == "Lead is waiting for lower rates."
    assert result.prompt_text == client.requests[0].prompt
    assert result.input_context["conversation_summary"] is None
    recent_messages = result.input_context["recent_messages"]
    assert isinstance(recent_messages, list)
    assert recent_messages[0]["content"] == "I'm waiting for rates to drop"
    assert result.raw_llm_response_text == client.text
    assert result.parsed_llm_response["outcome"] == "paused_search"


async def test_classifies_human_handoff_with_reason_code() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            pause_reason_code=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            confidence=0.93,
            evidence=["Lead asked for pricing advice on a listing"],
            summary="Lead needs an agent for pricing advice.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Can you advise me on pricing for this listing?"),),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF
    assert result.handoff_reason_code == HandoffReasonCode.SPECIFIC_PROPERTY_OR_ADVICE


async def test_rejects_human_handoff_without_reason_code() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            pause_reason_code=None,
            reengagement_not_before=None,
            reengagement_window_label=None,
            confidence=0.90,
            evidence=["Lead asked to speak with someone"],
            summary="Lead needs a person.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Can I speak with an agent?"),),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons


async def test_maps_unknown_outcome_to_review_hold() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="unknown",
            handoff_reason_code=None,
            pause_reason_code=None,
            confidence=0.91,
            evidence=["Conversation mixed timing and interest signals."],
            summary="No route is a clear safe winner.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(_event("Maybe next year, not sure yet."),),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.CLASSIFIED
    assert result.outcome == LeadStateClassificationOutcome.REVIEW_HOLD
    assert result.parsed_llm_response["outcome"] == "unknown"


async def test_rejects_low_confidence() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="waiting_for_rates",
            confidence=0.45,
            evidence=["Maybe waiting"],
            summary="Low confidence.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.LOW_CONFIDENCE in result.reasons
    assert result.raw_llm_response_text == client.text
    assert result.parsed_llm_response["confidence"] == 0.45


async def test_rejects_invalid_response() -> None:
    client = _StubLLMClient("this is not valid json")
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons
    assert result.prompt_text == client.requests[-1].prompt
    assert result.raw_llm_response_text == client.text
    assert result.validation_error is not None


async def test_rejects_unknown_outcome() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="unknown_outcome",
            confidence=0.95,
            evidence=["Something"],
            summary="Unknown.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons


async def test_rejects_unknown_pause_reason_code() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="paused_search",
            pause_reason_code="aliens_are_landin",
            confidence=0.95,
            evidence=["Lead said something"],
            summary="Unknown reason code.",
        )
    )
    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(),
        llm_client=client,
    )
    assert result.status == LeadStateClassificationStatus.REJECTED
    assert LeadStateClassificationReasonCode.INVALID_LLM_RESPONSE in result.reasons


async def test_includes_freshness_context_for_stale_property_interest_without_reply() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            handoff_reason_code=None,
            pause_reason_code=None,
            confidence=0.91,
            evidence=["Inquiry is stale"],
            summary="Historical property inquiry with no later reply.",
        )
    )
    property_inquiry_at = NOW - timedelta(days=95)
    lead = replace(
        _lead(),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_event_at=property_inquiry_at,
        latest_property_context_present=True,
        last_meaningful_communication_at=property_inquiry_at,
    )

    result = await classify_lead_from_conversation(
        lead=lead,
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 343 East 74th Street.",
                occurred_at=property_inquiry_at,
            ),
        ),
        llm_client=client,
        dormant_threshold_days=60,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["dormant_threshold_days"] == 60
    assert freshness_context["latest_observed_message_at"] == property_inquiry_at.isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 95
    assert (
        freshness_context["latest_observed_message_older_than_dormant_threshold"] is True
    )
    assert freshness_context["days_since_latest_property_event"] == 95
    assert freshness_context["has_observed_inbound_reply_after_latest_property_event"] is False
    assert freshness_context["property_interest_is_stale_by_threshold"] is True
    assert freshness_context["stale_property_interest_without_observed_reply"] is True
    assert "Do not choose human_handoff from a stale property inquiry alone." in result.prompt_text
    assert (
        "If a property inquiry is older than the configured dormant threshold"
        in result.prompt_text
    )
    assert (
        "If the newest observed message in the available context window is older"
        in result.prompt_text
    )
    assert (
        "do not assign low confidence just because the historical message text sounds urgent"
        in result.prompt_text
    )


async def test_uses_latest_observed_message_freshness_when_property_fields_are_missing() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="dormant",
            handoff_reason_code=None,
            pause_reason_code=None,
            confidence=0.9,
            evidence=["No fresh engagement after old tour request"],
            summary="Old conversation window should be treated as dormant.",
        )
    )
    outbound_at = NOW - timedelta(days=74)
    internal_at = NOW - timedelta(days=60)

    result = await classify_lead_from_conversation(
        lead=_lead(),
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 425 W 24th St and want a tour.",
                direction=CrmConversationEventDirection.OUTBOUND,
                occurred_at=outbound_at,
            ),
            _event(
                "AI has been disabled until ai_on is added.",
                direction=CrmConversationEventDirection.INTERNAL,
                occurred_at=internal_at,
            ),
        ),
        llm_client=client,
        dormant_threshold_days=10,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["latest_observed_message_at"] == internal_at.isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 60
    assert (
        freshness_context["latest_observed_message_older_than_dormant_threshold"] is True
    )
    assert freshness_context["latest_observed_inbound_message_at"] is None
    assert freshness_context["days_since_last_meaningful_communication"] is None
    assert freshness_context["property_interest_is_stale_by_threshold"] is None
    assert freshness_context["stale_property_interest_without_observed_reply"] is None
    assert "prefer dormant over human_handoff" in result.prompt_text
    assert "confidence should usually be high" in result.prompt_text


async def test_marks_recent_property_interest_with_reply_as_not_stale() -> None:
    client = _StubLLMClient(
        _classification_json(
            outcome="human_handoff",
            handoff_reason_code="specific_property_or_advice",
            pause_reason_code=None,
            confidence=0.95,
            evidence=["Lead asked for help on a specific property"],
            summary="Fresh property help request needs an agent.",
        )
    )
    property_inquiry_at = NOW - timedelta(days=4)
    lead = replace(
        _lead(),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_event_at=property_inquiry_at,
        latest_property_context_present=True,
        last_meaningful_communication_at=NOW - timedelta(days=1),
    )

    result = await classify_lead_from_conversation(
        lead=lead,
        now=NOW,
        crm_conversation_events=(
            _event(
                "I am interested in 343 East 74th Street.",
                occurred_at=property_inquiry_at,
            ),
            _event(
                "Can someone help me with this property today?",
                occurred_at=NOW - timedelta(days=1),
            ),
        ),
        llm_client=client,
        dormant_threshold_days=60,
    )

    freshness_context = result.input_context["freshness_context"]
    assert isinstance(freshness_context, dict)
    assert result.prompt_text is not None
    assert freshness_context["latest_observed_message_at"] == (NOW - timedelta(days=1)).isoformat()
    assert freshness_context["days_since_latest_observed_message"] == 1
    assert (
        freshness_context["latest_observed_message_older_than_dormant_threshold"] is False
    )
    assert freshness_context["property_interest_is_stale_by_threshold"] is False
    assert freshness_context["has_observed_inbound_reply_after_latest_property_event"] is True
    assert freshness_context["stale_property_interest_without_observed_reply"] is False
