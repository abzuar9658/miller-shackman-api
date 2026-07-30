import json
import re
from collections.abc import Iterable, Mapping
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
from app.domain.outbound_drafting import (
    SUPPORTED_TEMPLATE_PLACEHOLDERS,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
    render_outbound_subject_template,
    render_outbound_template,
)

OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION_PREFIX = "outbound_message_draft:v10"
MIN_DRAFT_CONFIDENCE = 0.7
MAX_SMS_BODY_LENGTH = 320
MAX_EMAIL_BODY_LENGTH = 4000
DEFAULT_LISTING_SEARCH_BASIS = "the lead's stated preferences"
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


def _empty_string_tuple() -> tuple[str, ...]:
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
    source: str | None = None


@dataclass(frozen=True)
class ApprovedListingRelevanceBrief:
    search_basis: str
    match_count: int
    matching_areas: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    matching_property_types: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    budget_alignment_note: str | None = None
    safe_talking_point: str | None = None
    safe_cta: str = "Ask whether they want their assigned agent to send a few current options."
    listing_context_source: str | None = None


@dataclass(frozen=True)
class ApprovedListingMessageGuidance:
    must_acknowledge_current_matches: bool
    mentionable_areas: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    mentionable_property_types: tuple[str, ...] = field(default_factory=_empty_string_tuple)
    safe_talking_point: str | None = None
    safe_cta: str = "Ask whether they want their assigned agent to send a few current options."
    draft_directive: str | None = None


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
    journey_kind: OutboundJourneyKind | None = None,
    llm_client: LLMClient,
    drafting_config: WorkspaceOutboundDraftingConfig | None = None,
    model: str | None = None,
    min_confidence: float = MIN_DRAFT_CONFIDENCE,
) -> OutboundMessageDraftResult:
    resolved_config = drafting_config or default_workspace_outbound_drafting_config(
        lead.workspace_id,
    )
    resolved_agent_name = _resolved_assigned_agent_name(assigned_agent_name)
    resolved_lead_first_name = _resolved_lead_first_name(lead)
    prompt_version = _prompt_version_for_config(resolved_config)
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=_build_prompt(
                lead=lead,
                channel=channel,
                campaign_goal=campaign_goal,
                brokerage_name=brokerage_name,
                assigned_agent_name=resolved_agent_name,
                lead_context=lead_context,
                journey_kind=journey_kind,
                drafting_config=resolved_config,
            ),
            prompt_version=prompt_version,
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
    rendered_body = render_outbound_template(
        _channel_template_for_config(resolved_config, channel=channel),
        {
            "agent_name": resolved_agent_name or "",
            "brokerage_name": brokerage_name,
            "lead_first_name": resolved_lead_first_name,
            "message_body": _normalized_message_body_fragment(draft.body),
        },
    )
    rendered_subject = draft.subject
    if channel == ContactChannel.EMAIL:
        rendered_subject = render_outbound_subject_template(
            resolved_config.email_subject_template,
            {
                "agent_name": resolved_agent_name or "",
                "brokerage_name": brokerage_name,
                "message_subject": _normalized_message_subject_fragment(draft.subject),
            },
        )
    rendered_reasons = _rendered_message_validation_reasons(
        body=rendered_body,
        subject=rendered_subject,
        channel=channel,
    )
    if rendered_reasons:
        reasons.extend(rendered_reasons)
        status = OutboundMessageDraftStatus.REJECTED

    return OutboundMessageDraftResult(
        status=status,
        prompt_version=llm_result.prompt_version,
        model=llm_result.model,
        latency_ms=llm_result.latency_ms,
        usage_tokens=llm_result.usage_tokens,
        body=rendered_body,
        subject=rendered_subject,
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
    if channel == ContactChannel.EMAIL and not _normalized_message_subject_fragment(draft.subject):
        reasons.append(OutboundMessageDraftReasonCode.MISSING_EMAIL_SUBJECT)

    return reasons


def _rendered_message_validation_reasons(
    *,
    body: str,
    subject: str | None,
    channel: ContactChannel,
) -> list[OutboundMessageDraftReasonCode]:
    reasons: list[OutboundMessageDraftReasonCode] = []
    if channel == ContactChannel.SMS and len(body) > MAX_SMS_BODY_LENGTH:
        reasons.append(OutboundMessageDraftReasonCode.BODY_TOO_LONG)
    if channel == ContactChannel.EMAIL and not _normalized_message_subject_fragment(subject):
        reasons.append(OutboundMessageDraftReasonCode.MISSING_EMAIL_SUBJECT)
    if _contains_prohibited_content(body):
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
    journey_kind: OutboundJourneyKind | None,
    drafting_config: WorkspaceOutboundDraftingConfig,
) -> str:
    channel_template = _channel_template_for_config(drafting_config, channel=channel)
    channel_prompt_text = _channel_prompt_text_for_config(
        drafting_config,
        channel=channel,
    )
    payload = {
        "task": "draft_outbound_real_estate_lead_follow_up",
        "channel": channel.value,
        "journey_kind": journey_kind.value if journey_kind is not None else None,
        "campaign_goal": campaign_goal,
        "brokerage_name": brokerage_name,
        "assigned_agent_name": assigned_agent_name,
        "admin_drafting_config": {
            "config_revision": drafting_config.revision,
            "channel_prompt_text": channel_prompt_text,
            "channel_template": channel_template,
            "email_subject_template": drafting_config.email_subject_template,
            "supported_template_placeholders": list(SUPPORTED_TEMPLATE_PLACEHOLDERS),
            "message_body_placeholder": "{{message_body}}",
            "message_subject_placeholder": "{{message_subject}}",
            "enabled_extraction_fields": list(drafting_config.enabled_extraction_fields),
        },
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
        f"{drafting_config.prompt_text}\n"
        "Follow the admin-configured prompt_text as the top-level role and behavior brief "
        "for all channels.\n"
        "The admin-configured prompt_text and channel_prompt_text are instruction-only. "
        "The admin-configured channel template is final layout-only. Do not copy either "
        "instruction text or template "
        "scaffolding into your output.\n"
        "Follow the admin-configured channel_prompt_text as the tone/style brief for this "
        "channel.\n"
        "Your job is to generate ONLY the natural-language message content that should be "
        "inserted into or appended to the final template as the message body. The "
        "application will deterministically render the final message afterward.\n"
        "If the channel template contains {{message_body}}, your generated body will replace "
        "that placeholder. Otherwise, the application will append your generated body after "
        "the template.\n"
        "If the channel template already contains a greeting, sign-off, hardcoded name, or "
        "other fixed text, do not repeat that text in your generated body unless the context "
        "truly requires it.\n"
        "For email, the application may also apply an admin-configured subject template after "
        "you respond. Provide a concise, natural subject that works well when inserted into "
        "that subject template.\n"
        "Follow the admin-configured prompt text and channel template as closely as possible, "
        "unless they conflict with the safety rules below.\n"
        "Do not invent listings, prices, offers, agent actions, appointments, or "
        "past conversations.\n"
        "Use the approved conversation memory summary and recent conversation items to "
        "continue the thread naturally. Avoid repeating the same greeting, ask, or "
        "call-to-action if recent outbound messages already covered it, unless the lead's "
        "context clearly changed.\n"
        f"{_journey_instructions(journey_kind)}"
        "If approved listing context is present, the payload will include both "
        "listing_relevance_brief and listing_message_guidance. You MUST follow "
        "listing_message_guidance.draft_directive and explicitly acknowledge current "
        "matches in general terms using listing_message_guidance.safe_talking_point as "
        "your factual basis. Keep that acknowledgement to one concise sentence in SMS "
        "or at most two short sentences in email, and include "
        "listing_message_guidance.safe_cta or an equivalent offer to have the assigned "
        "agent share a few current options. You may mention matching areas, property "
        "types, or budget alignment only in general terms. Do not mention exact "
        "addresses, exact listing prices, or claim any listing is guaranteed to still be "
        "available.\n"
        "If approved listing context is NOT present (i.e., approved_listing_context is null), "
        "you MUST NOT imply that listings, properties, or options are currently available. "
        "In that case, acknowledge the lead's request and offer to have the assigned agent "
        "look into current options and follow up. Do not use phrases like 'great options "
        "available right now,' 'we have matches,' or 'there are options.'\n"
        "Do not provide legal, tax, financing, investment, or market prediction "
        "advice.\n"
        "If the lead request requires a human agent, set a safety flag instead of answering it.\n"
        "For SMS, keep the generated body short enough that the final rendered SMS remains "
        "under 320 characters.\n"
        "For email, include a concise subject.\n"
        "Return only JSON with keys: body, subject, confidence, personalization_notes, "
        "safety_flags.\n"
        f"Approved context: {json.dumps(payload, sort_keys=True)}"
    )


def _journey_instructions(journey_kind: OutboundJourneyKind | None) -> str:
    if journey_kind == OutboundJourneyKind.DORMANT:
        return (
            "For dormant outreach, treat the lead as quiet for an unknown reason. Keep the "
            "message low-pressure and administrative. Do not imply you already know why they "
            "stopped responding unless that reason appears in the approved context. Use the "
            "approved context to ask whether they are still interested, whether timing or "
            "preferences changed, or whether they want their assigned agent to reconnect.\n"
        )
    if journey_kind == OutboundJourneyKind.PAUSED_SEARCH:
        return (
            "For paused-search outreach, treat the lead as someone whose home search or "
            "move timing was intentionally paused. Keep the message administrative, "
            "low-pressure, and timing-aware. Do not imply urgency, available listings, "
            "pricing advice, or market predictions. Ask whether their timing or "
            "preferences have changed, or whether they want their assigned agent to "
            "reconnect.\n"
        )
    return ""


def _resolved_assigned_agent_name(assigned_agent_name: str | None) -> str | None:
    if assigned_agent_name is None:
        return None
    normalized = assigned_agent_name.strip()
    return normalized or None


def _resolved_lead_first_name(lead: CanonicalLeadRecord) -> str:
    raw_name = str(lead.mapped_custom_fields.get("display_name") or "").strip()
    if not raw_name or "@" in raw_name:
        return "there"
    first_name = raw_name.split()[0].strip(",.!? ")
    return first_name or "there"


def _normalized_message_body_fragment(body: str) -> str:
    return body.replace("\r\n", "\n").strip()


def _normalized_message_subject_fragment(subject: str | None) -> str:
    if subject is None:
        return ""
    return subject.strip()


def _channel_template_for_config(
    drafting_config: WorkspaceOutboundDraftingConfig,
    *,
    channel: ContactChannel,
) -> str:
    return (
        drafting_config.sms_template
        if channel == ContactChannel.SMS
        else drafting_config.email_template
    )


def _channel_prompt_text_for_config(
    drafting_config: WorkspaceOutboundDraftingConfig,
    *,
    channel: ContactChannel,
) -> str:
    return (
        drafting_config.sms_prompt_text
        if channel == ContactChannel.SMS
        else drafting_config.email_prompt_text
    )


def outbound_message_draft_prompt_version_for_revision(revision: int) -> str:
    return f"{OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION_PREFIX}:r{revision}"


def _prompt_version_for_config(config: WorkspaceOutboundDraftingConfig) -> str:
    return outbound_message_draft_prompt_version_for_revision(config.revision)


def _listing_context_payload(
    listing_context: ApprovedOutboundListingContext | None,
) -> dict[str, object] | None:
    if listing_context is None:
        return None
    relevance_brief = build_listing_relevance_brief(listing_context)
    message_guidance = build_listing_message_guidance(listing_context)
    return {
        "source_name": listing_context.source_name,
        "result_count": listing_context.result_count,
        "listing_relevance_brief": _listing_relevance_brief_payload(relevance_brief),
        "listing_message_guidance": _listing_message_guidance_payload(message_guidance),
    }


def build_listing_relevance_brief(
    listing_context: ApprovedOutboundListingContext,
) -> ApprovedListingRelevanceBrief:
    search_basis = _listing_search_basis(listing_context.search_summary)
    budget_alignment_note = _budget_alignment_note(listing_context.search_summary)
    matching_areas = _top_unique_values(
        match.neighborhood for match in listing_context.matches if match.neighborhood
    )
    matching_property_types = _top_unique_values(
        _normalize_property_type(match.property_type)
        for match in listing_context.matches
        if match.property_type
    )
    match_noun = "match" if listing_context.result_count == 1 else "matches"
    match_verb = "lines up" if listing_context.result_count == 1 else "line up"
    return ApprovedListingRelevanceBrief(
        search_basis=search_basis,
        match_count=listing_context.result_count,
        matching_areas=matching_areas,
        matching_property_types=matching_property_types,
        budget_alignment_note=budget_alignment_note,
        safe_talking_point=_safe_listing_talking_point(
            source_name=listing_context.source_name,
            result_count=listing_context.result_count,
            match_noun=match_noun,
            match_verb=match_verb,
            search_basis=search_basis,
            budget_alignment_note=budget_alignment_note,
        ),
        listing_context_source=listing_context.source,
    )


def build_listing_message_guidance(
    listing_context: ApprovedOutboundListingContext,
) -> ApprovedListingMessageGuidance:
    relevance_brief = build_listing_relevance_brief(listing_context)
    return ApprovedListingMessageGuidance(
        must_acknowledge_current_matches=relevance_brief.match_count > 0,
        mentionable_areas=relevance_brief.matching_areas,
        mentionable_property_types=relevance_brief.matching_property_types,
        safe_talking_point=relevance_brief.safe_talking_point,
        safe_cta=relevance_brief.safe_cta,
        draft_directive=_listing_draft_directive(relevance_brief),
    )


def build_listing_relevance_brief_payload(
    listing_context: ApprovedOutboundListingContext | None,
) -> dict[str, object] | None:
    if listing_context is None:
        return None
    return _listing_relevance_brief_payload(build_listing_relevance_brief(listing_context))


def _listing_search_basis(search_summary: str) -> str:
    value = search_summary.strip()
    for prefix in ("sale in ", "rent in ", "sale near ", "rent near "):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    else:
        for prefix in ("sale ", "rent "):
            if value.startswith(prefix):
                value = value[len(prefix) :]
                break
    value = re.sub(r"\s+up to \$[0-9,]+", "", value).strip(" ,")
    return value or DEFAULT_LISTING_SEARCH_BASIS


def _budget_alignment_note(search_summary: str) -> str | None:
    if re.search(r"\bup to \$[0-9,]+", search_summary):
        return "the lead's stated budget"
    return None


def _safe_listing_talking_point(
    *,
    source_name: str,
    result_count: int,
    match_noun: str,
    match_verb: str,
    search_basis: str,
    budget_alignment_note: str | None,
) -> str:
    alignment_basis = search_basis
    if budget_alignment_note:
        alignment_basis = f"{alignment_basis} and {budget_alignment_note}"
    return f"{result_count} current {source_name} {match_noun} {match_verb} with {alignment_basis}."


def _listing_relevance_brief_payload(
    relevance_brief: ApprovedListingRelevanceBrief,
) -> dict[str, object]:
    return {
        "search_basis": relevance_brief.search_basis,
        "match_count": relevance_brief.match_count,
        "matching_areas": list(relevance_brief.matching_areas),
        "matching_property_types": list(relevance_brief.matching_property_types),
        "budget_alignment_note": relevance_brief.budget_alignment_note,
        "safe_talking_point": relevance_brief.safe_talking_point,
        "safe_cta": relevance_brief.safe_cta,
        "draft_directive": _listing_draft_directive(relevance_brief),
        "listing_context_source": relevance_brief.listing_context_source,
    }


def _listing_message_guidance_payload(
    message_guidance: ApprovedListingMessageGuidance,
) -> dict[str, object]:
    return {
        "must_acknowledge_current_matches": message_guidance.must_acknowledge_current_matches,
        "mentionable_areas": list(message_guidance.mentionable_areas),
        "mentionable_property_types": list(message_guidance.mentionable_property_types),
        "safe_talking_point": message_guidance.safe_talking_point,
        "safe_cta": message_guidance.safe_cta,
        "draft_directive": message_guidance.draft_directive,
    }


def _listing_draft_directive(relevance_brief: ApprovedListingRelevanceBrief) -> str:
    parts = [
        f"Use this factual basis once in general terms: '{relevance_brief.safe_talking_point}'."
    ]
    if relevance_brief.matching_areas:
        areas = ", ".join(relevance_brief.matching_areas)
        parts.append(f"If helpful, you may mention general areas like {areas}.")
    if relevance_brief.matching_property_types:
        property_types = ", ".join(relevance_brief.matching_property_types)
        parts.append(
            f"If helpful, you may mention general property types like {property_types}."
        )
    parts.append(
        "Keep any listing reference general and never mention exact addresses or exact prices."
    )
    parts.append(relevance_brief.safe_cta)
    return " ".join(parts)


def _top_unique_values(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    for raw in values:
        normalized = str(raw).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
        if len(deduped) == 2:
            break
    return tuple(deduped)


def _normalize_property_type(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.replace("_", " ").replace("-", " ").strip()
    if not normalized:
        return ""
    return normalized.lower()
