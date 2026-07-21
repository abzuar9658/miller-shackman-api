import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest, LLMResult
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    normalize_llm_json_text,
)
from app.domain.leads import CanonicalLeadRecord

INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION = "inbound_reply_classification:v2"
STRICT_RETRY_PROMPT_VERSION = f"{INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION}:strict_retry"
MIN_REPLY_CLASSIFICATION_CONFIDENCE = 0.65


class InboundReplyIntent(StrEnum):
    HIGH_INTEREST = "high_interest"
    HUMAN_REQUESTED = "human_requested"
    SELLER_INTEREST = "seller_interest"
    OPT_OUT = "opt_out"
    NOT_INTERESTED = "not_interested"
    GENERAL_REPLY = "general_reply"
    UNCLEAR = "unclear"


_INTENT_ALIASES: Mapping[str, str] = {
    "asks_for_human": InboundReplyIntent.HUMAN_REQUESTED,
    "buying_interest": InboundReplyIntent.HIGH_INTEREST,
    "selling_interest": InboundReplyIntent.SELLER_INTEREST,
    "asks_property_or_advice": InboundReplyIntent.HUMAN_REQUESTED,
    "mixed_intent": InboundReplyIntent.UNCLEAR,
}


def _normalize_classification_json_text(raw_text: str) -> str:
    normalized = normalize_llm_json_text(raw_text)
    try:
        data = json.loads(normalized)
    except Exception:
        return normalized
    if isinstance(data, dict) and isinstance(data.get("intent"), str):
        alias = _INTENT_ALIASES.get(data["intent"])
        if alias is not None:
            data["intent"] = alias
    return json.dumps(data)


class ReplyClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    REJECTED = "rejected"


class ReplyClassificationReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_SUMMARY = "missing_summary"


def _empty_preferences() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class InboundReplyRuleEvidence:
    asks_for_human: bool = False
    shows_buying_interest: bool = False
    shows_selling_interest: bool = False
    asks_property_or_advice: bool = False


@dataclass(frozen=True)
class ReplyClassificationResult:
    status: ReplyClassificationStatus
    prompt_version: str
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    intent: InboundReplyIntent | None = None
    confidence: float | None = None
    evidence: InboundReplyRuleEvidence = field(default_factory=InboundReplyRuleEvidence)
    opt_out_detected: bool = False
    summary_text: str | None = None
    preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    reasons: tuple[ReplyClassificationReasonCode, ...] = ()


class _LLMReplyClassification(BaseModel):
    intent: InboundReplyIntent
    confidence: float = Field(ge=0.0, le=1.0)
    asks_for_human: bool
    shows_buying_interest: bool
    shows_selling_interest: bool
    asks_property_or_advice: bool
    opt_out_detected: bool = False
    summary_text: str = Field(min_length=1, max_length=600)
    preferences: dict[str, str] = Field(default_factory=dict)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)


async def classify_inbound_reply(
    *,
    lead: CanonicalLeadRecord,
    inbound_text: str,
    llm_client: LLMClient,
    model: str | None = None,
    min_confidence: float = MIN_REPLY_CLASSIFICATION_CONFIDENCE,
) -> ReplyClassificationResult:
    llm_result = await _complete_classification_request(
        llm_client=llm_client,
        prompt=_build_prompt(lead=lead, inbound_text=inbound_text),
        prompt_version=INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
        model=model,
    )

    try:
        classification = _parse_classification_result(llm_result.text)
    except ValidationError:
        retry_result = await _complete_classification_request(
            llm_client=llm_client,
            prompt=_build_strict_retry_prompt(lead=lead, inbound_text=inbound_text),
            prompt_version=STRICT_RETRY_PROMPT_VERSION,
            model=model,
        )
        try:
            classification = _parse_classification_result(retry_result.text)
        except ValidationError:
            return _build_rejected_result(
                llm_result=retry_result,
                latency_ms=llm_result.latency_ms + retry_result.latency_ms,
                usage_tokens=_aggregate_usage_tokens(
                    llm_result.usage_tokens,
                    retry_result.usage_tokens,
                ),
            )
        llm_result = _combine_retry_metadata(initial_result=llm_result, retry_result=retry_result)

    reasons = _validation_reasons(classification, min_confidence=min_confidence)
    status = (
        ReplyClassificationStatus.CLASSIFIED if not reasons else ReplyClassificationStatus.REJECTED
    )
    return ReplyClassificationResult(
        status=status,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        intent=classification.intent if not reasons else None,
        confidence=classification.confidence,
        evidence=(
            InboundReplyRuleEvidence(
                asks_for_human=classification.asks_for_human,
                shows_buying_interest=classification.shows_buying_interest,
                shows_selling_interest=classification.shows_selling_interest,
                asks_property_or_advice=classification.asks_property_or_advice,
            )
            if not reasons
            else InboundReplyRuleEvidence()
        ),
        opt_out_detected=classification.opt_out_detected if not reasons else False,
        summary_text=classification.summary_text if not reasons else None,
        preferences=classification.preferences if not reasons else {},
        reasons=tuple(reasons),
    )


async def _complete_classification_request(
    *,
    llm_client: LLMClient,
    prompt: str,
    prompt_version: str,
    model: str | None,
) -> LLMResult:
    return await llm_client.complete(
        LLMCompletionRequest(
            prompt=prompt,
            prompt_version=prompt_version,
            model=model,
            temperature=0.1,
            max_tokens=500,
        )
    )


def _parse_classification_result(raw_text: str) -> _LLMReplyClassification:
    return _LLMReplyClassification.model_validate_json(
        _normalize_classification_json_text(raw_text)
    )


def _build_rejected_result(
    *,
    llm_result: LLMResult,
    latency_ms: int | None = None,
    usage_tokens: int | None = None,
) -> ReplyClassificationResult:
    return ReplyClassificationResult(
        status=ReplyClassificationStatus.REJECTED,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms if latency_ms is None else latency_ms,
        usage_tokens=llm_result.usage_tokens if usage_tokens is None else usage_tokens,
        reasons=(ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,),
    )


def _combine_retry_metadata(*, initial_result: LLMResult, retry_result: LLMResult) -> LLMResult:
    return LLMResult(
        text=retry_result.text,
        model=retry_result.model,
        prompt_version=retry_result.prompt_version,
        latency_ms=initial_result.latency_ms + retry_result.latency_ms,
        usage_tokens=_aggregate_usage_tokens(
            initial_result.usage_tokens,
            retry_result.usage_tokens,
        ),
    )


def _aggregate_usage_tokens(*usage_tokens: int | None) -> int | None:
    known_usage = [value for value in usage_tokens if value is not None]
    return sum(known_usage) if known_usage else None


def _validation_reasons(
    classification: _LLMReplyClassification,
    *,
    min_confidence: float,
) -> list[ReplyClassificationReasonCode]:
    reasons: list[ReplyClassificationReasonCode] = []
    if classification.confidence < min_confidence:
        reasons.append(ReplyClassificationReasonCode.LOW_CONFIDENCE)
    if not classification.summary_text.strip():
        reasons.append(ReplyClassificationReasonCode.MISSING_SUMMARY)
    return reasons


def _approved_context_payload(*, lead: CanonicalLeadRecord, inbound_text: str) -> dict[str, object]:
    return {
        "task": "classify_inbound_real_estate_lead_reply",
        "lead": {
            "lead_type": lead.lead_type.value,
            "lead_stage": lead.lead_stage,
            "lead_source": lead.lead_source,
            "latest_property_event_type": lead.latest_property_event_type.value
            if lead.latest_property_event_type
            else None,
            "latest_property_price_band": lead.latest_property_price_band,
        },
        "inbound_text": inbound_text,
    }


def _base_prompt_instructions() -> str:
    return (
        "You classify inbound replies for a real estate lead nurture assistant. "
        "Return exactly one valid JSON object and nothing else. "
        "Do not include markdown fences, prose, comments, or trailing text.\n"
        "Allowed intent values are: high_interest, human_requested, seller_interest, "
        "opt_out, not_interested, general_reply, unclear.\n"
        "Choose intent using these rules, in priority order:\n"
        "1. opt_out — if the lead wants to stop receiving messages.\n"
        "2. high_interest — if the lead shows meaningful buyer intent "
        "(e.g. wants listings, make an offer, schedule a showing).\n"
        "3. seller_interest — if the lead asks about selling their home.\n"
        "4. human_requested — if the lead asks for a person, call, showing, or manual follow-up, "
        "or asks for advice about pricing, financing, market, legal, tax, or investment.\n"
        "5. not_interested — if the lead clearly declines.\n"
        "6. general_reply — for a neutral response that does not fit above.\n"
        "7. unclear — if the intent is genuinely ambiguous or contradictory.\n"
        "The fields asks_for_human, shows_buying_interest, shows_selling_interest, and "
        "asks_property_or_advice are boolean evidence flags, not intent values. "
        "Set them to true when the matching condition applies.\n"
        "Return only JSON with keys: intent, confidence, asks_for_human, "
        "shows_buying_interest, shows_selling_interest, asks_property_or_advice, "
        "opt_out_detected, summary_text, preferences.\n"
        "confidence must be a number from 0 to 1.\n"
        "summary_text must be a concise explanation under 600 characters.\n"
        "preferences must be an object with string values (empty if none)."
    )


def _build_prompt(*, lead: CanonicalLeadRecord, inbound_text: str) -> str:
    payload = _approved_context_payload(lead=lead, inbound_text=inbound_text)
    return f"{_base_prompt_instructions()}\nApproved context: {json.dumps(payload, sort_keys=True)}"


def _build_strict_retry_prompt(*, lead: CanonicalLeadRecord, inbound_text: str) -> str:
    payload = _approved_context_payload(lead=lead, inbound_text=inbound_text)
    example = {
        "intent": "human_requested",
        "confidence": 0.93,
        "asks_for_human": True,
        "shows_buying_interest": False,
        "shows_selling_interest": False,
        "asks_property_or_advice": False,
        "opt_out_detected": False,
        "summary_text": "Lead asked for a phone call today.",
        "preferences": {"timeline": "today"},
    }
    return (
        f"{_base_prompt_instructions()}\n"
        "Use these intent enum values only: high_interest, human_requested, seller_interest, "
        "opt_out, not_interested, general_reply, unclear.\n"
        "Required JSON schema:\n"
        "- intent: string enum\n"
        "- confidence: number between 0 and 1\n"
        "- asks_for_human: boolean\n"
        "- shows_buying_interest: boolean\n"
        "- shows_selling_interest: boolean\n"
        "- asks_property_or_advice: boolean\n"
        "- opt_out_detected: boolean\n"
        "- summary_text: non-empty string under 600 chars\n"
        "- preferences: object with string values\n"
        "If unsure, still return every required key with your best structured judgment.\n"
        f"Example valid response: {json.dumps(example, sort_keys=True)}\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )
