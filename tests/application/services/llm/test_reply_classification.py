import json
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_classification import (
    INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
    STRICT_RETRY_PROMPT_VERSION,
    InboundReplyIntent,
    InboundReplyRuleEvidence,
    ReplyClassificationReasonCode,
    ReplyClassificationStatus,
    _build_prompt,
    classify_inbound_reply,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


class FakeLLMClient:
    def __init__(self, text: str | list[str]) -> None:
        self.texts = [text] if isinstance(text, str) else text
        self._response_index = 0
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        response_index = min(self._response_index, len(self.texts) - 1)
        self._response_index += 1
        return LLMResult(
            text=self.texts[response_index],
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=19,
            usage_tokens=51,
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


def _classification_json(
    *,
    intent: str = "human_requested",
    confidence: float | str = 0.91,
    asks_for_human: bool | None = None,
    shows_buying_interest: bool | None = None,
    shows_selling_interest: bool | None = None,
    asks_property_or_advice: bool = False,
    opt_out_detected: bool = False,
    summary_text: str = "Lead asked to speak with an agent.",
    preferences: dict[str, str] | None = None,
) -> str:
    if asks_for_human is None:
        asks_for_human = intent == "human_requested"
    if shows_buying_interest is None:
        shows_buying_interest = intent == "high_interest"
    if shows_selling_interest is None:
        shows_selling_interest = intent == "seller_interest"
    return json.dumps(
        {
            "intent": intent,
            "confidence": confidence,
            "asks_for_human": asks_for_human,
            "shows_buying_interest": shows_buying_interest,
            "shows_selling_interest": shows_selling_interest,
            "asks_property_or_advice": asks_property_or_advice,
            "opt_out_detected": opt_out_detected,
            "summary_text": summary_text,
            "preferences": preferences or {"timeline": "soon"},
        },
    )


async def test_classifies_human_request_and_builds_versioned_prompt() -> None:
    llm = FakeLLMClient(_classification_json())

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.evidence == InboundReplyRuleEvidence(asks_for_human=True)
    assert result.summary_text == "Lead asked to speak with an agent."
    assert llm.requests[0].prompt_version == INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION
    assert "Can someone call me today?" in llm.requests[0].prompt


async def test_rejects_invalid_json_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Stop texting me.",
        llm_client=FakeLLMClient("not-json"),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,)


async def test_accepts_markdown_fenced_json_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=FakeLLMClient(f"```json\n{_classification_json()}\n```"),
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.evidence.asks_for_human is True


async def test_accepts_confidence_alias_string() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=FakeLLMClient(
            _classification_json(confidence="high")
        ),
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.confidence == 0.9


async def test_rejects_low_confidence_response() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Maybe later.",
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                confidence=0.2,
                summary_text="Lead replied but intent is unclear.",
            ),
        ),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.LOW_CONFIDENCE,)


async def test_extracts_property_or_advice_evidence_without_direct_handoff_flag() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text=(
            "Can you tell me if this condo is still available and what the payments would be?"
        ),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                asks_property_or_advice=True,
                summary_text="Lead asked about a specific property and financing.",
            )
        ),
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.evidence.asks_property_or_advice is True


async def test_rejects_legacy_handoff_schema_without_structured_evidence_fields() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "intent": "human_requested",
                    "confidence": 0.91,
                    "handoff_required": True,
                    "handoff_reason": "human_requested",
                    "opt_out_detected": False,
                    "summary_text": "Lead asked to speak with an agent.",
                    "preferences": {"timeline": "soon"},
                }
            )
        ),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,)



async def test_maps_asks_for_human_intent_alias_to_human_requested() -> None:
    llm = FakeLLMClient(
        _classification_json(
            intent="asks_for_human",
            asks_for_human=True,
            summary_text="Lead asked for a phone call.",
        )
    )

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.intent == InboundReplyIntent.HUMAN_REQUESTED
    assert result.evidence == InboundReplyRuleEvidence(asks_for_human=True)


async def test_maps_buying_interest_intent_alias_to_high_interest() -> None:
    llm = FakeLLMClient(
        _classification_json(
            intent="buying_interest",
            shows_buying_interest=True,
            summary_text="Lead wants to buy.",
        )
    )

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="I'm ready to buy a home.",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.intent == InboundReplyIntent.HIGH_INTEREST
    assert result.evidence == InboundReplyRuleEvidence(shows_buying_interest=True)


async def test_maps_mixed_intent_alias_to_unclear() -> None:
    llm = FakeLLMClient(
        _classification_json(
            intent="mixed_intent",
            summary_text="Lead is contradictory.",
        )
    )

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Stop messaging me... actually wait, send me info first",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.intent == InboundReplyIntent.UNCLEAR


async def test_rejects_unknown_invalid_intent_even_after_alias_mapping() -> None:
    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Hello",
        llm_client=FakeLLMClient(
            json.dumps(
                {
                    "intent": "totally_unknown_label",
                    "confidence": 0.91,
                    "asks_for_human": False,
                    "shows_buying_interest": False,
                    "shows_selling_interest": False,
                    "asks_property_or_advice": False,
                    "opt_out_detected": False,
                    "summary_text": "Lead is unknown.",
                    "preferences": {},
                }
            )
        ),
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.reasons == (ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,)


async def test_retries_with_strict_prompt_after_invalid_first_pass() -> None:
    llm = FakeLLMClient(["not-json", _classification_json()])

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.CLASSIFIED
    assert result.intent == InboundReplyIntent.HUMAN_REQUESTED
    assert result.prompt_version == STRICT_RETRY_PROMPT_VERSION
    assert result.latency_ms == 38
    assert result.usage_tokens == 102
    assert [request.prompt_version for request in llm.requests] == [
        INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
        STRICT_RETRY_PROMPT_VERSION,
    ]


async def test_rejects_after_both_attempts_fail_validation() -> None:
    llm = FakeLLMClient(["not-json", "still-not-json"])

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Can someone call me today?",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.prompt_version == STRICT_RETRY_PROMPT_VERSION
    assert result.latency_ms == 38
    assert result.usage_tokens == 102
    assert result.reasons == (ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,)
    assert [request.prompt_version for request in llm.requests] == [
        INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
        STRICT_RETRY_PROMPT_VERSION,
    ]


async def test_does_not_retry_low_confidence_valid_response() -> None:
    llm = FakeLLMClient(
        _classification_json(
            intent="general_reply",
            confidence=0.2,
            summary_text="Lead replied but intent is unclear.",
        )
    )

    result = await classify_inbound_reply(
        lead=_lead(),
        inbound_text="Maybe later.",
        llm_client=llm,
    )

    assert result.status == ReplyClassificationStatus.REJECTED
    assert result.prompt_version == INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION
    assert result.reasons == (ReplyClassificationReasonCode.LOW_CONFIDENCE,)
    assert len(llm.requests) == 1


def test_prompt_lists_allowed_intent_values_and_boolean_field_rules() -> None:
    lead = _lead()

    prompt = _build_prompt(lead=lead, inbound_text="Can someone call me today?")

    assert "Allowed intent values are" in prompt
    assert "high_interest" in prompt
    assert "human_requested" in prompt
    assert "asks_for_human" in prompt
    assert "boolean evidence flags, not intent values" in prompt
