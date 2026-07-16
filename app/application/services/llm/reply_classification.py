import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    normalize_llm_json_text,
)
from app.domain.conversations import HandoffReasonCode
from app.domain.leads import CanonicalLeadRecord

INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION = "inbound_reply_classification:v1"
MIN_REPLY_CLASSIFICATION_CONFIDENCE = 0.65


class InboundReplyIntent(StrEnum):
    HIGH_INTEREST = "high_interest"
    HUMAN_REQUESTED = "human_requested"
    SELLER_INTEREST = "seller_interest"
    OPT_OUT = "opt_out"
    NOT_INTERESTED = "not_interested"
    GENERAL_REPLY = "general_reply"
    UNCLEAR = "unclear"


class ReplyClassificationStatus(StrEnum):
    CLASSIFIED = "classified"
    REJECTED = "rejected"


class ReplyClassificationReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_SUMMARY = "missing_summary"
    HANDOFF_REASON_MISSING = "handoff_reason_missing"


def _empty_preferences() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class ReplyClassificationResult:
    status: ReplyClassificationStatus
    prompt_version: str
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    intent: InboundReplyIntent | None = None
    confidence: float | None = None
    handoff_required: bool = False
    handoff_reason: HandoffReasonCode | None = None
    opt_out_detected: bool = False
    summary_text: str | None = None
    preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    reasons: tuple[ReplyClassificationReasonCode, ...] = ()


class _LLMReplyClassification(BaseModel):
    intent: InboundReplyIntent
    confidence: float = Field(ge=0.0, le=1.0)
    handoff_required: bool
    handoff_reason: HandoffReasonCode | None = None
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
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=_build_prompt(lead=lead, inbound_text=inbound_text),
            prompt_version=INBOUND_REPLY_CLASSIFICATION_PROMPT_VERSION,
            model=model,
            temperature=0.1,
            max_tokens=500,
        ),
    )

    try:
        classification = _LLMReplyClassification.model_validate_json(
            normalize_llm_json_text(llm_result.text)
        )
    except ValidationError:
        return ReplyClassificationResult(
            status=ReplyClassificationStatus.REJECTED,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            latency_ms=llm_result.latency_ms,
            usage_tokens=llm_result.usage_tokens,
            reasons=(ReplyClassificationReasonCode.INVALID_LLM_RESPONSE,),
        )

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
        handoff_required=classification.handoff_required if not reasons else False,
        handoff_reason=classification.handoff_reason if not reasons else None,
        opt_out_detected=classification.opt_out_detected if not reasons else False,
        summary_text=classification.summary_text if not reasons else None,
        preferences=classification.preferences if not reasons else {},
        reasons=tuple(reasons),
    )


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
    if classification.handoff_required and classification.handoff_reason is None:
        reasons.append(ReplyClassificationReasonCode.HANDOFF_REASON_MISSING)
    return reasons


def _build_prompt(*, lead: CanonicalLeadRecord, inbound_text: str) -> str:
    payload = {
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
    return (
        "You classify inbound replies for a real estate lead nurture assistant.\n"
        "Business rules, not the model, decide whether outreach can continue.\n"
        "If the lead shows meaningful buying or selling interest, asks for a person, "
        "asks about a specific property, pricing, financing, legal, tax, or investment "
        "advice, require handoff.\n"
        "If the lead opts out, set opt_out_detected true.\n"
        "Return only JSON with keys: intent, confidence, handoff_required, handoff_reason, "
        "opt_out_detected, summary_text, preferences.\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )
