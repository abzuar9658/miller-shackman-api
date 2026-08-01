import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.lead_activity import LeadActivityItem
from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.canonical_lead_inputs import (
    approved_outbound_context_from_canonical_lead,
)
from app.application.services.llm.outbound_message_drafting import ApprovedOutboundLeadContext
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    coerce_string_tuple,
    normalize_llm_json_text,
)
from app.domain.conversations import CrmConversationEvent
from app.domain.leads import CanonicalLeadRecord
from app.domain.outbound_drafting import SUPPORTED_QUERY_EXTRACTION_FIELDS

OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION = "outbound_query_extraction:v1"
MIN_OUTBOUND_QUERY_EXTRACTION_CONFIDENCE = 0.7

_SUPPORTED_QUERY_FIELDS = frozenset(SUPPORTED_QUERY_EXTRACTION_FIELDS)
_SEARCH_TYPE_ALIASES: Mapping[str, Literal["rent", "sale"]] = {
    "rent": "rent",
    "rental": "rent",
    "lease": "rent",
    "leasing": "rent",
    "sale": "sale",
    "buy": "sale",
    "buyer": "sale",
    "buying": "sale",
    "purchase": "sale",
    "purchasing": "sale",
    "for_sale": "sale",
}


class OutboundQueryExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class OutboundQueryExtractionMethod(StrEnum):
    LLM = "llm"
    FALLBACK = "fallback"


class OutboundQueryExtractionReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    NO_CANDIDATE_QUERY = "no_candidate_query"
    NO_ENABLED_FIELDS = "no_enabled_fields"
    NO_FIELDS_EXTRACTED = "no_fields_extracted"


def _empty_preferences() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class OutboundQueryExtractionResult:
    status: OutboundQueryExtractionStatus
    preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    prompt_version: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    confidence: float | None = None
    reasons: tuple[OutboundQueryExtractionReasonCode, ...] = ()


@dataclass(frozen=True)
class OutboundQueryExtractionSelection:
    lead_context: ApprovedOutboundLeadContext
    method: OutboundQueryExtractionMethod
    confidence: float | None = None
    reasons: tuple[OutboundQueryExtractionReasonCode, ...] = ()


class _LLMOutboundQueryExtraction(BaseModel):
    search_type: Literal["rent", "sale"] | None = None
    address: str | None = Field(default=None, max_length=240)
    location: str | None = Field(default=None, max_length=240)
    keywords: str | None = Field(default=None, max_length=240)
    beds: str | None = Field(default=None, max_length=24)
    min_price: str | None = Field(default=None, max_length=24)
    max_price: str | None = Field(default=None, max_length=24)
    price_band: str | None = Field(default=None, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: tuple[str, ...] = ()

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @field_validator("reasons", mode="before")
    @classmethod
    def _coerce_reasons(cls, value: object) -> object:
        return coerce_string_tuple(value)

    @field_validator("search_type", mode="before")
    @classmethod
    def _normalize_search_type(cls, value: object) -> object:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            return None
        alias = _SEARCH_TYPE_ALIASES.get(normalized.lower().replace(" ", "_"))
        return alias

    @field_validator("address", "location", "keywords", "price_band", mode="before")
    @classmethod
    def _normalize_text_field(cls, value: object) -> object:
        return _normalize_optional_text(value)

    @field_validator("beds", mode="before")
    @classmethod
    def _normalize_beds(cls, value: object) -> object:
        return _normalize_decimal_string(value)

    @field_validator("min_price", "max_price", mode="before")
    @classmethod
    def _normalize_amount_field(cls, value: object) -> object:
        return _normalize_amount_string(value)


async def build_outbound_context_with_query_extraction(
    *,
    lead: CanonicalLeadRecord,
    now: datetime,
    llm_client: LLMClient,
    conversation_summary: str | None = None,
    latest_lead_request: str | None = None,
    extracted_preferences: Mapping[str, str] | None = None,
    enabled_query_extraction_fields: tuple[str, ...] | None = None,
    allowed_mapped_custom_field_keys: tuple[str, ...] = (),
    activity_items: tuple[LeadActivityItem, ...] = (),
    crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
    model: str | None = None,
    min_confidence: float = MIN_OUTBOUND_QUERY_EXTRACTION_CONFIDENCE,
) -> OutboundQueryExtractionSelection:
    fallback_context = approved_outbound_context_from_canonical_lead(
        lead,
        now=now,
        conversation_summary=conversation_summary,
        latest_lead_request=latest_lead_request,
        extracted_preferences=extracted_preferences,
        enabled_query_extraction_fields=enabled_query_extraction_fields,
        allowed_mapped_custom_field_keys=allowed_mapped_custom_field_keys,
        activity_items=activity_items,
        crm_conversation_events=crm_conversation_events,
    )
    extraction = await extract_outbound_query_preferences(
        lead=lead,
        query_text=fallback_context.latest_lead_request,
        llm_client=llm_client,
        enabled_fields=enabled_query_extraction_fields,
        model=model,
        min_confidence=min_confidence,
    )
    if extraction.status != OutboundQueryExtractionStatus.EXTRACTED:
        return OutboundQueryExtractionSelection(
            lead_context=fallback_context,
            method=OutboundQueryExtractionMethod.FALLBACK,
            confidence=extraction.confidence,
            reasons=extraction.reasons,
        )

    merged_preferences = dict(extracted_preferences or {})
    merged_preferences.update(dict(extraction.preferences))
    llm_context = approved_outbound_context_from_canonical_lead(
        lead,
        now=now,
        conversation_summary=conversation_summary,
        latest_lead_request=latest_lead_request,
        extracted_preferences=merged_preferences,
        enabled_query_extraction_fields=enabled_query_extraction_fields,
        allowed_mapped_custom_field_keys=allowed_mapped_custom_field_keys,
        activity_items=activity_items,
        crm_conversation_events=crm_conversation_events,
    )
    return OutboundQueryExtractionSelection(
        lead_context=llm_context,
        method=OutboundQueryExtractionMethod.LLM,
        confidence=extraction.confidence,
    )


async def extract_outbound_query_preferences(
    *,
    lead: CanonicalLeadRecord,
    query_text: str | None,
    llm_client: LLMClient,
    enabled_fields: tuple[str, ...] | None,
    model: str | None = None,
    min_confidence: float = MIN_OUTBOUND_QUERY_EXTRACTION_CONFIDENCE,
) -> OutboundQueryExtractionResult:
    resolved_query = _normalized_query_text(query_text)
    if resolved_query is None:
        return OutboundQueryExtractionResult(
            status=OutboundQueryExtractionStatus.SKIPPED,
            reasons=(OutboundQueryExtractionReasonCode.NO_CANDIDATE_QUERY,),
        )

    allowed_fields = _resolved_enabled_fields(enabled_fields)
    if not allowed_fields:
        return OutboundQueryExtractionResult(
            status=OutboundQueryExtractionStatus.SKIPPED,
            reasons=(OutboundQueryExtractionReasonCode.NO_ENABLED_FIELDS,),
        )

    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=_build_prompt(
                lead=lead,
                query_text=resolved_query,
                enabled_fields=allowed_fields,
            ),
            prompt_version=OUTBOUND_QUERY_EXTRACTION_PROMPT_VERSION,
            model=model,
            temperature=0.1,
            max_tokens=450,
        )
    )
    try:
        extraction = _LLMOutboundQueryExtraction.model_validate_json(
            normalize_llm_json_text(llm_result.text)
        )
    except ValidationError:
        return OutboundQueryExtractionResult(
            status=OutboundQueryExtractionStatus.REJECTED,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            latency_ms=llm_result.latency_ms,
            usage_tokens=llm_result.usage_tokens,
            reasons=(OutboundQueryExtractionReasonCode.INVALID_LLM_RESPONSE,),
        )

    preferences = _filtered_preferences(extraction, allowed_fields=allowed_fields)
    reasons: list[OutboundQueryExtractionReasonCode] = []
    if extraction.confidence < min_confidence:
        reasons.append(OutboundQueryExtractionReasonCode.LOW_CONFIDENCE)
    if not preferences:
        reasons.append(OutboundQueryExtractionReasonCode.NO_FIELDS_EXTRACTED)
    status = (
        OutboundQueryExtractionStatus.EXTRACTED
        if not reasons
        else OutboundQueryExtractionStatus.REJECTED
    )
    return OutboundQueryExtractionResult(
        status=status,
        preferences=preferences,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        confidence=extraction.confidence,
        reasons=tuple(reasons),
    )


def _build_prompt(
    *,
    lead: CanonicalLeadRecord,
    query_text: str,
    enabled_fields: tuple[str, ...],
) -> str:
    payload = {
        "task": "extract_outbound_real_estate_query_preferences",
        "lead": {
            "lead_type": lead.lead_type.value,
            "lead_source": lead.lead_source,
            "lead_stage": lead.lead_stage,
            "latest_property_price_band": lead.latest_property_price_band,
        },
        "enabled_fields": list(enabled_fields),
        "query_text": query_text,
    }
    return (
        "Extract structured real-estate search preferences from the lead's latest query.\n"
        "Only return fields that are clearly supported by the query text.\n"
        "If a field is unclear or absent, return null for that field.\n"
        "search_type must be one of rent, sale, or null.\n"
        "Infer rent vs sale only when the query clearly supports it. "
        "Monthly rent language can imply rent.\n"
        "location should contain only the lead's target areas. "
        "Use a comma-separated string when there are multiple areas.\n"
        "address should only be used for a concrete property or street address.\n"
        "keywords should capture durable listing-search traits like condo, "
        "co-op, townhouse, doorman, pet friendly, or similar.\n"
        "beds should be the minimum bedrooms as a number.\n"
        "min_price and max_price should be whole-dollar numeric amounts when possible.\n"
        "price_band should only be used when the query implies a budget band "
        "but not a clear min/max number.\n"
        "Do not invent neighborhoods, addresses, budgets, or listing details.\n"
        "Return only JSON with keys: search_type, address, location, "
        "keywords, beds, min_price, max_price, price_band, confidence, "
        "reasons.\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _resolved_enabled_fields(enabled_fields: tuple[str, ...] | None) -> tuple[str, ...]:
    if enabled_fields is None:
        return SUPPORTED_QUERY_EXTRACTION_FIELDS
    normalized: list[str] = []
    for field_name in enabled_fields:
        value = field_name.strip().lower()
        if value in _SUPPORTED_QUERY_FIELDS and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _filtered_preferences(
    extraction: _LLMOutboundQueryExtraction,
    *,
    allowed_fields: tuple[str, ...],
) -> dict[str, str]:
    raw = {
        "search_type": extraction.search_type,
        "address": extraction.address,
        "location": extraction.location,
        "keywords": extraction.keywords,
        "beds": extraction.beds,
        "min_price": extraction.min_price,
        "max_price": extraction.max_price,
        "price_band": extraction.price_band,
    }
    allowed = set(allowed_fields)
    return {
        key: value
        for key, value in raw.items()
        if key in allowed and value is not None and value.strip()
    }


def _normalized_query_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [part for part in (_normalize_optional_text(item) for item in value) if part]
        return ", ".join(dict.fromkeys(parts)) or None
    normalized = str(value).strip()
    return normalized or None


def _normalize_decimal_string(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    digits = re.sub(r"[^0-9.]", "", normalized)
    if not digits:
        return None
    try:
        decimal_value = Decimal(digits)
    except InvalidOperation:
        return None
    return _format_decimal(decimal_value)


def _normalize_amount_string(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    match = re.fullmatch(
        r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([km]?)",
        normalized,
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        decimal_value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    multiplier = {"": 1, "k": 1000, "m": 1000000}[match.group(2).lower()]
    return str(int(decimal_value * multiplier))


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return text[:-2] if text.endswith(".0") else text.rstrip("0").rstrip(".")
