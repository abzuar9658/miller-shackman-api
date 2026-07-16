import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    coerce_string_tuple,
    normalize_llm_json_text,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord

OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION = "outbound_message_draft:v2"
MIN_DRAFT_CONFIDENCE = 0.7
MAX_SMS_BODY_LENGTH = 320
MAX_EMAIL_BODY_LENGTH = 4000
PROHIBITED_MESSAGE_TERMS = (
    "guarantee",
    "legal advice",
    "tax advice",
    "investment advice",
    "mortgage approval",
    "pre-approved",
)


class OutboundMessageDraftStatus(StrEnum):
    DRAFTED = "drafted"
    REJECTED = "rejected"


class OutboundMessageDraftReasonCode(StrEnum):
    INVALID_LLM_RESPONSE = "invalid_llm_response"
    LOW_CONFIDENCE = "low_confidence"
    SAFETY_FLAGS_PRESENT = "safety_flags_present"
    MISSING_EMAIL_SUBJECT = "missing_email_subject"
    BODY_TOO_LONG = "body_too_long"
    PROHIBITED_CONTENT = "prohibited_content"


def _empty_preferences() -> Mapping[str, str]:
    return {}


def _empty_conversation_items() -> tuple["ApprovedOutboundConversationItem", ...]:
    return ()


def _empty_recent_outbounds() -> tuple[str, ...]:
    return ()


def _empty_listing_matches() -> tuple["ApprovedOutboundListingMatch", ...]:
    return ()


@dataclass(frozen=True)
class ApprovedOutboundConversationItem:
    occurred_at: str
    title: str
    content: str
    direction: str | None = None
    channel: str | None = None
    actor_name: str | None = None


@dataclass(frozen=True)
class ApprovedOutboundListingMatch:
    title: str | None = None
    address_text: str | None = None
    neighborhood: str | None = None
    price_text: str | None = None
    beds_text: str | None = None
    baths_text: str | None = None
    property_type: str | None = None
    source_url: str | None = None
    scraped_at: str | None = None


@dataclass(frozen=True)
class ApprovedOutboundListingContext:
    source_name: str
    search_summary: str
    result_count: int
    matches: tuple[ApprovedOutboundListingMatch, ...] = field(
        default_factory=_empty_listing_matches
    )


@dataclass(frozen=True)
class ApprovedOutboundLeadContext:
    conversation_summary: str | None = None
    conversation_memory_summary: str | None = None
    latest_lead_request: str | None = None
    extracted_preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    recent_conversation_items: tuple[ApprovedOutboundConversationItem, ...] = field(
        default_factory=_empty_conversation_items
    )
    recent_outbound_messages: tuple[str, ...] = field(default_factory=_empty_recent_outbounds)
    listing_context: ApprovedOutboundListingContext | None = None


@dataclass(frozen=True)
class OutboundMessageDraftResult:
    status: OutboundMessageDraftStatus
    prompt_version: str
    model: str | None = None
    latency_ms: int | None = None
    usage_tokens: int | None = None
    body: str | None = None
    subject: str | None = None
    raw_llm_response_text: str | None = None
    validation_error: str | None = None
    confidence: float | None = None
    personalization_notes: tuple[str, ...] = ()
    safety_flags: tuple[str, ...] = ()
    reasons: tuple[OutboundMessageDraftReasonCode, ...] = ()


class _LLMOutboundMessageDraft(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_EMAIL_BODY_LENGTH)
    subject: str | None = Field(default=None, max_length=120)
    confidence: float = Field(ge=0.0, le=1.0)
    personalization_notes: tuple[str, ...] = ()
    safety_flags: tuple[str, ...] = ()

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: object) -> object:
        return coerce_llm_confidence(value)

    @field_validator("personalization_notes", "safety_flags", mode="before")
    @classmethod
    def _coerce_string_collections(cls, value: object) -> object:
        return coerce_string_tuple(value)


async def draft_outbound_message(
    *,
    lead: CanonicalLeadRecord,
    channel: ContactChannel,
    campaign_goal: str,
    brokerage_name: str,
    assigned_agent_name: str | None,
    lead_context: ApprovedOutboundLeadContext,
    llm_client: LLMClient,
    model: str | None = None,
    min_confidence: float = MIN_DRAFT_CONFIDENCE,
) -> OutboundMessageDraftResult:
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=_build_prompt(
                lead=lead,
                channel=channel,
                campaign_goal=campaign_goal,
                brokerage_name=brokerage_name,
                assigned_agent_name=assigned_agent_name,
                lead_context=lead_context,
            ),
            prompt_version=OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION,
            model=model,
            temperature=0.4,
            max_tokens=700,
        ),
    )

    try:
        draft = _LLMOutboundMessageDraft.model_validate_json(
            normalize_llm_json_text(llm_result.text)
        )
    except ValidationError as exc:
        return OutboundMessageDraftResult(
            status=OutboundMessageDraftStatus.REJECTED,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            latency_ms=llm_result.latency_ms,
            usage_tokens=llm_result.usage_tokens,
            raw_llm_response_text=llm_result.text,
            validation_error=str(exc),
            reasons=(OutboundMessageDraftReasonCode.INVALID_LLM_RESPONSE,),
        )

    reasons = _validation_reasons(draft, channel=channel, min_confidence=min_confidence)
    status = OutboundMessageDraftStatus.DRAFTED
    if reasons:
        status = OutboundMessageDraftStatus.REJECTED

    return OutboundMessageDraftResult(
        status=status,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        body=draft.body,
        subject=draft.subject,
        confidence=draft.confidence,
        personalization_notes=draft.personalization_notes,
        safety_flags=draft.safety_flags,
        reasons=tuple(reasons),
    )


def _validation_reasons(
    draft: _LLMOutboundMessageDraft,
    *,
    channel: ContactChannel,
    min_confidence: float,
) -> list[OutboundMessageDraftReasonCode]:
    reasons: list[OutboundMessageDraftReasonCode] = []

    if draft.confidence < min_confidence:
        reasons.append(OutboundMessageDraftReasonCode.LOW_CONFIDENCE)
    if draft.safety_flags:
        reasons.append(OutboundMessageDraftReasonCode.SAFETY_FLAGS_PRESENT)
    if channel == ContactChannel.EMAIL and not draft.subject:
        reasons.append(OutboundMessageDraftReasonCode.MISSING_EMAIL_SUBJECT)
    if channel == ContactChannel.SMS and len(draft.body) > MAX_SMS_BODY_LENGTH:
        reasons.append(OutboundMessageDraftReasonCode.BODY_TOO_LONG)
    if _contains_prohibited_content(draft.body):
        reasons.append(OutboundMessageDraftReasonCode.PROHIBITED_CONTENT)

    return reasons


def _contains_prohibited_content(body: str) -> bool:
    normalized = body.lower()
    return any(term in normalized for term in PROHIBITED_MESSAGE_TERMS)


def _build_prompt(
    *,
    lead: CanonicalLeadRecord,
    channel: ContactChannel,
    campaign_goal: str,
    brokerage_name: str,
    assigned_agent_name: str | None,
    lead_context: ApprovedOutboundLeadContext,
) -> str:
    payload = {
        "task": "draft_outbound_real_estate_lead_follow_up",
        "channel": channel.value,
        "campaign_goal": campaign_goal,
        "brokerage_name": brokerage_name,
        "assigned_agent_name": assigned_agent_name,
        "known_lead_facts": {
            "lead_type": lead.lead_type.value,
            "lead_source": lead.lead_source,
            "lead_stage": lead.lead_stage,
            "latest_property_event_type": lead.latest_property_event_type.value
            if lead.latest_property_event_type
            else None,
            "latest_property_price_band": lead.latest_property_price_band,
            "latest_property_context_present": lead.latest_property_context_present,
        },
        "approved_lead_context": {
            "conversation_summary": lead_context.conversation_summary,
            "conversation_memory_summary": lead_context.conversation_memory_summary,
            "latest_lead_request": lead_context.latest_lead_request,
            "extracted_preferences": dict(lead_context.extracted_preferences),
            "recent_conversation_items": [
                {
                    "occurred_at": item.occurred_at,
                    "title": item.title,
                    "content": item.content,
                    "direction": item.direction,
                    "channel": item.channel,
                    "actor_name": item.actor_name,
                }
                for item in lead_context.recent_conversation_items
            ],
            "recent_outbound_messages": list(lead_context.recent_outbound_messages),
        },
        "approved_listing_context": _listing_context_payload(lead_context.listing_context),
    }
    return (
        "You are an administrative follow-up assistant for a real estate brokerage.\n"
        "Draft one compliant outbound message using only the approved JSON context below.\n"
        "Do not invent listings, prices, offers, agent actions, appointments, or "
        "past conversations.\n"
        "Use the approved conversation memory summary and recent conversation items to "
        "continue the thread naturally. Avoid repeating the same greeting, ask, or "
        "call-to-action if recent outbound messages already covered it, unless the lead's "
        "context clearly changed.\n"
        "If approved listing context is present, you may reference at most two matching "
        "listings using only the provided fields. Do not claim any listing is guaranteed "
        "to still be available, and do not add facts beyond the approved listing context.\n"
        "Do not provide legal, tax, financing, investment, or market prediction "
        "advice.\n"
        "If the lead request requires a human agent, set a safety flag instead of answering it.\n"
        "For SMS, keep the body short, conversational, and under 320 characters.\n"
        "For email, include a concise subject.\n"
        "Return only JSON with keys: body, subject, confidence, personalization_notes, "
        "safety_flags.\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _listing_context_payload(
    listing_context: ApprovedOutboundListingContext | None,
) -> dict[str, object] | None:
    if listing_context is None:
        return None
    return {
        "source_name": listing_context.source_name,
        "search_summary": listing_context.search_summary,
        "result_count": listing_context.result_count,
        "matches": [
            {
                "title": match.title,
                "address_text": match.address_text,
                "neighborhood": match.neighborhood,
                "price_text": match.price_text,
                "beds_text": match.beds_text,
                "baths_text": match.baths_text,
                "property_type": match.property_type,
                "source_url": match.source_url,
                "scraped_at": match.scraped_at,
            }
            for match in listing_context.matches
        ],
    }
