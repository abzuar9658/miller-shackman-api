import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.application.ports.llm import LLMClient, LLMCompletionRequest
from app.application.services.llm.structured_json import (
    coerce_llm_confidence,
    coerce_string_tuple,
    normalize_llm_json_text,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord
from app.domain.llm import LLMProviderKind, LLMTaskKind
from app.domain.outbound_drafting import (
    OutboundJourneyChange,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
    render_outbound_subject_template,
    render_outbound_template,
)

logger = structlog.get_logger(__name__)

OUTBOUND_MESSAGE_DRAFT_PROMPT_VERSION_PREFIX = "outbound_message_draft:v16"
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
    journey_change: OutboundJourneyChange | None = None,
    message_purpose: str | None = None,
    llm_client: LLMClient,
    drafting_config: WorkspaceOutboundDraftingConfig | None = None,
    model: str | None = None,
    provider: LLMProviderKind | None = None,
    min_confidence: float = MIN_DRAFT_CONFIDENCE,
) -> OutboundMessageDraftResult:
    resolved_config = drafting_config or default_workspace_outbound_drafting_config(
        lead.workspace_id,
    )
    resolved_agent_name = _resolved_assigned_agent_name(assigned_agent_name)
    resolved_lead_first_name = _resolved_lead_first_name(lead)
    prompt_version = _prompt_version_for_config(resolved_config)
    prompt = _build_prompt(
        lead=lead,
        channel=channel,
        campaign_goal=campaign_goal,
        brokerage_name=brokerage_name,
        assigned_agent_name=resolved_agent_name,
        lead_context=lead_context,
        journey_kind=journey_kind,
        journey_change=journey_change,
        message_purpose=message_purpose,
        drafting_config=resolved_config,
    )
    logger.info(
        "outbound_message_draft_prompt",
        workspace_id=str(lead.workspace_id),
        lead_id=str(lead.lead_id),
        channel=channel.value,
        prompt_version=prompt_version,
        model=model,
        prompt=prompt,
    )
    llm_result = await llm_client.complete(
        LLMCompletionRequest(
            prompt=prompt,
            prompt_version=prompt_version,
            model=model,
            provider=provider,
            task=LLMTaskKind.DRAFTING,
            temperature=0.4,
            max_tokens=700,
        ),
    )

    try:
        draft = _LLMOutboundMessageDraft.model_validate_json(
            normalize_llm_json_text(llm_result.text)
        )
    except ValidationError as exc:
        logger.warning(
            "outbound_message_draft_invalid_llm_response",
            workspace_id=str(lead.workspace_id),
            lead_id=str(lead.lead_id),
            channel=channel.value,
            prompt_version=llm_result.prompt_version,
            model=llm_result.model,
            validation_error=str(exc),
            raw_llm_response_text=llm_result.text,
        )
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
    journey_change: OutboundJourneyChange | None,
    message_purpose: str | None,
    drafting_config: WorkspaceOutboundDraftingConfig,
) -> str:
    channel_template = _channel_template_for_config(drafting_config, channel=channel)
    channel_prompt_text = _channel_prompt_text_for_config(
        drafting_config,
        channel=channel,
    )
    sections = [
        f"{drafting_config.prompt_text}",
        "",
        "# Writing Instructions",
        channel_prompt_text,
        "",
        "These admin-configured writing instructions are the primary behavior brief for "
        "this draft. Follow them closely unless they conflict with the safety rules below.",
        "",
        "# Your Task",
        f"Channel: {channel.value}",
        f"Journey: {journey_kind.value if journey_kind else 'general'}",
        f"Campaign goal: {campaign_goal}",
    ]

    if message_purpose:
        sections.extend([
            "",
            "## Writing Objective",
            message_purpose,
            "",
            "This purpose guides wording only; it never overrides application safety, "
            "consent, suppression, handoff, or send rules.",
        ])

    journey_change_note = _journey_change_note(
        journey_kind=journey_kind,
        journey_change=journey_change,
    )
    if journey_change_note:
        sections.extend([
            "",
            "## Journey Change",
            journey_change_note,
        ])

    # Add lead context
    sections.extend([
        "",
        "# Lead Context",
        f"Lead type: {lead.lead_type.value}",
    ])

    if lead.lead_source:
        sections.append(f"Lead source: {lead.lead_source}")
    if lead.lead_stage:
        sections.append(f"Lead stage: {lead.lead_stage}")

    if lead_context.latest_lead_request:
        sections.append(f"Latest request: {lead_context.latest_lead_request}")

    if lead_context.conversation_memory_summary:
        sections.append(f"Conversation summary: {lead_context.conversation_memory_summary}")

    if lead_context.conversation_summary and (
        lead_context.conversation_summary != lead_context.conversation_memory_summary
    ):
        sections.append(f"Recent activity: {lead_context.conversation_summary}")

    if lead_context.extracted_preferences:
        sections.append("")
        sections.append("## Extracted Preferences")
        for key, value in sorted(lead_context.extracted_preferences.items()):
            sections.append(f"- {key}: {value}")

    if lead_context.recent_conversation_items:
        sections.append("")
        sections.append("## Recent Conversation")
        for item in lead_context.recent_conversation_items:
            direction_marker = "→" if item.direction == "outbound" else "←"
            sections.append(f"{direction_marker} {item.occurred_at} ({item.title}): {item.content}")

    if lead_context.recent_outbound_messages:
        sections.append("")
        sections.append("## Recent Outbound Messages")
        for msg in lead_context.recent_outbound_messages:
            sections.append(f"- {msg}")

    # Add listing context if present
    listing_context = lead_context.listing_context
    if listing_context is not None:
        relevance_brief = build_listing_relevance_brief(listing_context)
        message_guidance = build_listing_message_guidance(listing_context)
        sections.extend([
            "",
            "# Approved Listing Context",
            f"Source: {listing_context.source_name}",
            f"Match count: {listing_context.result_count}",
            "",
            "## Listing Relevance",
        ])
        if relevance_brief.safe_talking_point:
            sections.append(f"Safe talking point: {relevance_brief.safe_talking_point}")
        if relevance_brief.matching_areas:
            sections.append(f"Matching areas: {', '.join(relevance_brief.matching_areas)}")
        if relevance_brief.matching_property_types:
            sections.append(
                f"Property types: {', '.join(relevance_brief.matching_property_types)}"
            )
        if relevance_brief.budget_alignment_note:
            sections.append(f"Budget alignment: {relevance_brief.budget_alignment_note}")

        sections.append("")
        sections.append("## Listing Message Guidance")
        if message_guidance.draft_directive:
            sections.append(message_guidance.draft_directive)
        sections.extend([
            "",
            "You MUST follow the draft directive above and explicitly acknowledge current "
            "matches in general terms using the safe talking point as your factual basis.",
            "Keep that acknowledgement to one concise sentence in SMS or at most two short "
            "sentences in email.",
            "You may mention matching areas, property types, or budget alignment only in "
            "general terms.",
            "Do not mention exact addresses, exact listing prices, or claim any listing is "
            "guaranteed to still be available.",
        ])
    else:
        sections.extend([
            "",
            "# No Listing Context Available",
            "You MUST NOT imply that listings, properties, or options are currently available.",
            "In that case, acknowledge the lead's request and offer to have the assigned "
            "agent look into current options and follow up.",
            "Do not use phrases like 'great options available right now,' 'we have matches,' "
            "or 'there are options.'",
        ])

    # Add safety rules
    journey_instructions = _journey_instructions(journey_kind)
    sections.extend([
        "",
        "# Safety Rules",
        "- Do not invent listings, prices, offers, agent actions, appointments, or past "
        "conversations.",
        "- Use the approved conversation memory summary and recent conversation items to "
        "continue the thread naturally.",
        "- Avoid repeating the same greeting, ask, or call-to-action if recent outbound "
        "messages already covered it, unless the lead's context clearly changed.",
    ])

    if journey_instructions:
        sections.append(f"- {journey_instructions.strip()}")

    sections.extend([
        "- Do not provide legal, tax, financing, investment, or market prediction advice.",
        "- If the lead request requires a human agent, set a safety flag instead of "
        "answering it.",
        "- Follow the admin-configured prompt text and channel template as closely as "
        "possible, unless they conflict with these safety rules.",
    ])

    # Add template context
    sections.extend([
        "",
        "# Template Context",
        f"Channel template: {channel_template}",
    ])

    if channel == ContactChannel.EMAIL:
        sections.append(f"Email subject template: {drafting_config.email_subject_template}")

    sections.append(f"Brokerage: {brokerage_name}")

    if assigned_agent_name:
        sections.append(f"Assigned agent: {assigned_agent_name}")

    sections.extend([
        "",
        "The channel template is final layout-only; the application renders it "
        "deterministically after you respond. Do not copy template scaffolding, greetings, "
        "sign-offs, or hardcoded names into your output unless the context truly requires it.",
        "",
        "# Output Requirements",
        "Your job is to generate ONLY the natural-language message content that should be "
        "inserted into or appended to the final template as the message body.",
        "",
        f"For {channel.value}, keep the generated body short enough that the final rendered "
        f"{channel.value.upper()} remains under "
        f"{MAX_SMS_BODY_LENGTH if channel == ContactChannel.SMS else MAX_EMAIL_BODY_LENGTH} "
        "characters.",
        "",
        "If the channel template contains {{message_body}}, your generated body will replace "
        "that placeholder.",
        "Otherwise, the application will append your generated body after the template.",
        "",
        "For email, the application may also apply the admin-configured subject template "
        "after you respond. Provide a concise, natural subject that works well when inserted "
        "into that subject template.",
        "",
        "Return only JSON with keys: body (string), subject (string), confidence (a "
        "number between 0.0 and 1.0), personalization_notes (an array of strings), "
        "safety_flags (an array of strings; use an empty array [] when there are none).",
    ])

    return "\n".join(sections)


def _journey_change_note(
    *,
    journey_kind: OutboundJourneyKind | None,
    journey_change: OutboundJourneyChange | None,
) -> str | None:
    if journey_change is None or journey_kind is None:
        return None
    previous = journey_change.previous_journey_kind
    if previous == journey_kind and not journey_change.track_changed:
        return None
    previous_label = _journey_label(previous)
    current_label = _journey_label(journey_kind)
    if previous == journey_kind and journey_change.track_changed:
        transition_text = (
            f"This lead was previously on a different {previous_label} track and has now "
            f"moved to a new {current_label} track."
        )
    else:
        transition_text = (
            f"This lead was previously on a {previous_label} journey and has now moved "
            f"to a {current_label} journey."
        )
    return (
        f"{transition_text} Earlier outbound messages in the history above were written "
        "for that previous journey and its reason for outreach no longer applies. Do not "
        "reuse, paraphrase, or reference the framing, assumptions, or stated reasons from "
        "those earlier messages (for example a lease renewal, a paused timeline, or any "
        "other prior-track premise) unless the lead themselves confirmed it in an inbound "
        "reply. Write this message purely from the current journey's perspective."
    )


def _journey_label(journey_kind: OutboundJourneyKind) -> str:
    return journey_kind.value.replace("_", "-")


def _journey_instructions(journey_kind: OutboundJourneyKind | None) -> str:
    if journey_kind == OutboundJourneyKind.DORMANT:
        return (
            "For dormant outreach, treat the lead as quiet for an unknown reason. Keep the "
            "message low-pressure and casual, like a person checking in — not a company "
            "following up. Do not imply you already know why they stopped responding unless "
            "that reason appears in the approved context. Use the approved context to ask "
            "whether they are still interested, whether timing or preferences changed, or "
            "whether they want their assigned agent to reconnect.\n"
        )
    if journey_kind == OutboundJourneyKind.PAUSED_SEARCH:
        return (
            "For paused-search outreach, treat the lead as someone whose home search or "
            "move timing was intentionally paused. Keep the message casual, low-pressure, "
            "and timing-aware — a person checking in, not a company following up. Do not "
            "imply urgency, available listings, pricing advice, or market predictions. Ask "
            "whether their timing or preferences have changed, or whether they want their "
            "assigned agent to reconnect.\n"
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


def _listing_draft_directive(relevance_brief: ApprovedListingRelevanceBrief) -> str:
    parts = [
        f"Use this factual basis once in general terms: '{relevance_brief.safe_talking_point}'."
    ]
    if relevance_brief.matching_areas:
        areas = ", ".join(relevance_brief.matching_areas)
        parts.append(f"If helpful, you may mention general areas like {areas}.")
    if relevance_brief.matching_property_types:
        property_types = ", ".join(relevance_brief.matching_property_types)
        parts.append(f"If helpful, you may mention general property types like {property_types}.")
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
