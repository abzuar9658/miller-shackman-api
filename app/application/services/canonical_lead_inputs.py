import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundConversationItem,
    ApprovedOutboundLeadContext,
)
from app.domain.campaigns.start_queue import CampaignStartCandidate
from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
    LeadContactabilityFacts,
)
from app.domain.compliance.enrollment import CampaignEnrollmentFacts, EnrollmentSource
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import ActivityReliability, CanonicalLeadRecord, LeadType, PropertyEventType

MAX_CRM_CONTEXT_EVENTS = 5
MAX_CRM_EVENT_CONTENT_CHARS = 160
MAX_CRM_MEMORY_EVENTS = 12
MAX_CRM_LATEST_REQUEST_CHARS = 240
MAX_ACTIVITY_CONTEXT_ITEMS = 5
MAX_ACTIVITY_CONTEXT_CHARS = 160
MAX_ACTIVITY_MEMORY_ITEMS = 24
MAX_ACTIVITY_MEMORY_CHARS = 180
MAX_ACTIVITY_LATEST_REQUEST_CHARS = 240
MAX_RECENT_CONVERSATION_ITEMS = 8
MAX_RECENT_CONVERSATION_ITEM_CHARS = 240
MAX_RECENT_OUTBOUND_MESSAGES = 4
MAX_RECENT_OUTBOUND_MESSAGE_CHARS = 240
MAX_HISTORY_LOCATION_VALUES = 3
MAX_HISTORY_KEYWORD_VALUES = 5
LOCATION_PREFERENCE_KEYS = frozenset({"location", "preferred_location", "neighborhood"})
ADDRESS_PREFERENCE_KEYS = frozenset({"address", "preferred_address"})

ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.'’-]+(?:\s+[A-Za-z0-9.'’-]+){0,5}\s+"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|place|pl|court|ct|terrace|ter)\b"
    r"(?:,\s*[A-Za-z ]+)?",
    re.IGNORECASE,
)
LOCATION_TRIGGER_PATTERNS = (
    re.compile(
        r"\b(?:looking|searching|interested|focusing|prefer(?:ring)?|want|need|thinking|considering|move(?:ing)?|buy(?:ing)?|rent(?:ing)?)\b"
        r"[^.!?;]{0,40}\b(?:in|near|around)\s+"
        r"([A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4}(?:\s*(?:,|/|or|and)\s*"
        r"[A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4})*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:want|need|prefer(?:ring)?|thinking|considering)\s+"
        r"([A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4}(?:\s*(?:,|/|or|and)\s*"
        r"[A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4})*)"
        r"(?=\s+(?:with|under|over|budget|priced|and\s+need|and\s+want|still)\b|[.!?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:areas?|neighborhoods?)\s+(?:like|include|are|is)\s+"
        r"([A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4}(?:\s*(?:,|/|or|and)\s*"
        r"[A-Za-z][A-Za-z'’-]*(?:[ -][A-Za-z][A-Za-z'’-]*){0,4})*)",
        re.IGNORECASE,
    ),
)
BEDROOM_PATTERN = re.compile(
    r"\b(?:at\s+least\s+|minimum\s+|min\s+)?([0-9]+(?:\.[0-9]+)?)\s*(?:\+)?\s*"
    r"(?:bed|beds|bedroom|bedrooms|br)\b",
    re.IGNORECASE,
)
PRICE_RANGE_PATTERN = re.compile(
    r"\b(?:between|from)?\s*(\$?[0-9][0-9,]*(?:\.[0-9]+)?\s*[km]?)\s*(?:-|to|and)\s*"
    r"(\$?[0-9][0-9,]*(?:\.[0-9]+)?\s*[km]?)\b",
    re.IGNORECASE,
)
MAX_PRICE_PATTERN = re.compile(
    r"\b(?:under|below|up\s+to|less\s+than|no\s+more\s+than|max(?:imum)?(?:\s+budget)?\s*(?:is)?|budget\s*(?:is)?\s*under)\s*"
    r"(\$?[0-9][0-9,]*(?:\.[0-9]+)?\s*[km]?)\b",
    re.IGNORECASE,
)
MIN_PRICE_PATTERN = re.compile(
    r"\b(?:over|above|at\s+least|minimum\s+budget\s*(?:is)?|min(?:imum)?\s*(?:budget)?\s*(?:is)?|starting\s+at)\s*"
    r"(\$?[0-9][0-9,]*(?:\.[0-9]+)?\s*[km]?)\b",
    re.IGNORECASE,
)
APPROX_PRICE_PATTERN = re.compile(
    r"\b(?:around|about|roughly)\s*(\$?[0-9][0-9,]*(?:\.[0-9]+)?\s*[km]?)\b",
    re.IGNORECASE,
)
SEARCH_TYPE_RENT_PATTERN = re.compile(r"\b(?:rent|rental|lease|leasing)\b", re.IGNORECASE)
SEARCH_TYPE_SALE_PATTERN = re.compile(
    r"\b(?:buy|buying|purchase|purchasing|for\s+sale)\b",
    re.IGNORECASE,
)
HISTORY_KEYWORD_ALIASES = {
    "condo": ("condo", "condominium"),
    "co-op": ("co-op", "coop", "co op"),
    "townhouse": ("townhouse", "town home", "townhome"),
    "single family": ("single family", "single-family"),
    "multi family": ("multi family", "multi-family", "multifamily"),
    "doorman": ("doorman",),
    "elevator": ("elevator",),
    "parking": ("parking",),
    "balcony": ("balcony",),
    "outdoor space": ("outdoor space",),
    "laundry": ("laundry", "washer dryer", "washer/dryer"),
}
INVALID_LOCATION_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "area",
        "areas",
        "home",
        "homes",
        "house",
        "houses",
        "move",
        "moving",
        "neighborhood",
        "neighborhoods",
        "or",
        "something",
        "this",
        "to",
        "tour",
        "week",
        "weekend",
    }
)


def contactability_facts_from_canonical_lead(
    lead: CanonicalLeadRecord,
) -> LeadContactabilityFacts:
    has_sms_destination = lead.has_sms_capable_phone and lead.primary_phone is not None
    has_email_destination = lead.has_email and lead.primary_email is not None
    has_any_contact_destination = has_email_destination or (
        lead.has_phone and lead.primary_phone is not None
    )

    return LeadContactabilityFacts(
        do_not_contact=_contactability_do_not_contact(
            lead=lead,
            has_any_contact_destination=has_any_contact_destination,
        ),
        has_sms_destination=has_sms_destination,
        has_email_destination=has_email_destination,
        sms_consent_status=lead.sms_permission_status,
        email_permission_status=lead.email_permission_status,
        suppressions=lead.suppression_types,
    )


def _contactability_do_not_contact(
    *,
    lead: CanonicalLeadRecord,
    has_any_contact_destination: bool,
) -> bool:
    if lead.do_not_contact is not None:
        return lead.do_not_contact
    return not has_any_contact_destination


def enrollment_facts_from_canonical_lead(
    lead: CanonicalLeadRecord,
    *,
    enrollment_sources: frozenset[EnrollmentSource],
    enabled_channels: frozenset[ContactChannel],
    channel_contactability: Mapping[ContactChannel, ContactabilityDecision],
    enrollment_tag_observed_at: datetime | None = None,
) -> CampaignEnrollmentFacts:
    return CampaignEnrollmentFacts(
        enrollment_sources=enrollment_sources,
        enrollment_tag_observed_at=enrollment_tag_observed_at,
        last_meaningful_communication_at=lead.last_meaningful_communication_at,
        activity_data_complete=lead.activity_reliability == ActivityReliability.RELIABLE,
        enabled_channels=enabled_channels,
        channel_contactability=channel_contactability,
    )


def approved_outbound_context_from_canonical_lead(
    lead: CanonicalLeadRecord,
    *,
    now: datetime,
    conversation_summary: str | None = None,
    latest_lead_request: str | None = None,
    extracted_preferences: Mapping[str, str] | None = None,
    allowed_mapped_custom_field_keys: tuple[str, ...] = (),
    activity_items: tuple[LeadActivityItem, ...] = (),
    crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
) -> ApprovedOutboundLeadContext:
    preferences = _safe_preference_snapshot(
        lead,
        allowed_mapped_custom_field_keys=allowed_mapped_custom_field_keys,
    )
    history_preferences = _history_preference_snapshot(
        activity_items=activity_items,
        crm_conversation_events=crm_conversation_events,
    )
    _clear_superseded_preferences(preferences, history_preferences)
    preferences.update(history_preferences)
    if extracted_preferences:
        explicit_preferences = {
            key: value
            for key, value in extracted_preferences.items()
            if key.strip() and value.strip()
        }
        _clear_superseded_preferences(preferences, explicit_preferences)
        preferences.update(explicit_preferences)

    conversation_summary_text = (
        _normalized_text(conversation_summary)
        or _conversation_summary_from_activity_items(activity_items)
        or _conversation_summary_from_crm_events(crm_conversation_events)
        or _conversation_summary_from_canonical_lead(lead, now)
    )

    return ApprovedOutboundLeadContext(
        conversation_summary=conversation_summary_text,
        conversation_memory_summary=_normalized_text(conversation_summary)
        or _conversation_memory_summary_from_activity_items(activity_items)
        or _conversation_memory_summary_from_crm_events(crm_conversation_events)
        or conversation_summary_text,
        latest_lead_request=_normalized_text(latest_lead_request)
        or _latest_lead_request_from_activity_items(activity_items)
        or _latest_lead_request_from_crm_events(crm_conversation_events)
        or _latest_lead_request_from_canonical_lead(lead),
        extracted_preferences=preferences,
        recent_conversation_items=_recent_conversation_items_from_activity_items(activity_items)
        or _recent_conversation_items_from_crm_events(crm_conversation_events),
        recent_outbound_messages=_recent_outbound_messages_from_activity_items(activity_items)
        or _recent_outbound_messages_from_crm_events(crm_conversation_events),
    )


def start_candidate_from_canonical_lead(
    lead: CanonicalLeadRecord,
    *,
    enrollment_decision: object,
    now: datetime,
) -> CampaignStartCandidate:
    from app.domain.compliance.enrollment import CampaignEnrollmentDecision

    if not isinstance(enrollment_decision, CampaignEnrollmentDecision):
        raise TypeError("enrollment_decision must be CampaignEnrollmentDecision")

    return CampaignStartCandidate(
        lead_id=lead.lead_id,
        enrollment_decision=enrollment_decision,
        has_assigned_agent=lead.has_accountable_owner,
        days_since_last_meaningful_communication=_days_since(
            lead.last_meaningful_communication_at,
            now,
        ),
    )


def _days_since(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return (now - value).days


def _conversation_summary_from_canonical_lead(
    lead: CanonicalLeadRecord,
    now: datetime,
) -> str | None:
    parts: list[str] = []

    if lead.lead_type != LeadType.UNKNOWN:
        parts.append(f"Lead type: {lead.lead_type.value.replace('_', ' ')}.")
    if lead.lead_source != "unknown":
        parts.append(f"Lead source: {lead.lead_source}.")
    if lead.lead_stage != "unknown":
        parts.append(f"Current CRM stage: {lead.lead_stage}.")

    dormant_days = _days_since(lead.last_meaningful_communication_at, now)
    if dormant_days is not None:
        parts.append(f"No meaningful communication recorded for {dormant_days} days.")

    if lead.has_accountable_owner:
        parts.append("Lead has an assigned agent.")

    summary = " ".join(parts)
    return summary or None


def _conversation_summary_from_activity_items(
    activity_items: tuple[LeadActivityItem, ...],
) -> str | None:
    parts: list[str] = []

    for item in reversed(activity_items[:MAX_ACTIVITY_CONTEXT_ITEMS]):
        content = _activity_text(item)
        if content is None:
            continue
        parts.append(
            f"{item.title}: {_truncate_text(content, MAX_ACTIVITY_CONTEXT_CHARS)}",
        )

    if not parts:
        return None
    return f"Recent meaningful activity: {'; '.join(parts)}"


def _conversation_summary_from_crm_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> str | None:
    parts: list[str] = []

    for event in reversed(crm_conversation_events[:MAX_CRM_CONTEXT_EVENTS]):
        content = _normalized_text(event.content)
        if content is None:
            continue
        parts.append(
            f"{_crm_event_label(event)}: {_truncate_text(content, MAX_CRM_EVENT_CONTENT_CHARS)}",
        )

    if not parts:
        return None
    return f"Recent CRM conversation history: {'; '.join(parts)}"


def _conversation_memory_summary_from_activity_items(
    activity_items: tuple[LeadActivityItem, ...],
) -> str | None:
    memory_items = activity_items[:MAX_ACTIVITY_MEMORY_ITEMS]
    if not memory_items:
        return None

    inbound_count = sum(1 for item in memory_items if _is_inbound(item))
    outbound_count = sum(1 for item in memory_items if _is_outbound(item))
    note_count = sum(
        1
        for item in memory_items
        if item.kind == LeadActivityKind.CRM_CONVERSATION_EVENT and item.direction == "internal"
    )
    handoff_count = sum(1 for item in memory_items if item.kind == LeadActivityKind.HANDOFF)
    details: list[str] = []

    for item in reversed(memory_items):
        content = _activity_text(item)
        if content is None:
            continue
        details.append(
            f"{item.title}: {_truncate_text(content, MAX_ACTIVITY_MEMORY_CHARS)}"
        )

    if not details:
        return None
    counts = []
    if inbound_count:
        counts.append(f"{inbound_count} inbound")
    if outbound_count:
        counts.append(f"{outbound_count} outbound")
    if note_count:
        counts.append(f"{note_count} crm notes")
    if handoff_count:
        counts.append(f"{handoff_count} handoffs")
    count_text = f" ({', '.join(counts)})" if counts else ""
    return f"Conversation memory{count_text}: {'; '.join(details)}"


def _conversation_memory_summary_from_crm_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> str | None:
    events = crm_conversation_events[:MAX_CRM_MEMORY_EVENTS]
    if not events:
        return None

    parts: list[str] = []
    for event in reversed(events):
        content = _normalized_text(event.content)
        if content is None:
            continue
        parts.append(
            f"{_crm_event_label(event)}: {_truncate_text(content, MAX_ACTIVITY_MEMORY_CHARS)}"
        )
    if not parts:
        return None
    return f"Conversation memory from CRM history: {'; '.join(parts)}"


def _latest_lead_request_from_canonical_lead(lead: CanonicalLeadRecord) -> str | None:
    parts: list[str] = []

    if lead.latest_property_event_type == PropertyEventType.PROPERTY_INQUIRY:
        parts.append("Recent safe property context: the lead inquired about a property.")
    elif lead.latest_property_event_type == PropertyEventType.VIEWED_PROPERTY:
        parts.append("Recent safe property context: the lead viewed a property.")

    if lead.latest_property_price_band:
        parts.append(f"Safe price-band signal: {lead.latest_property_price_band}.")

    request = " ".join(parts)
    return request or None


def _latest_lead_request_from_crm_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> str | None:
    for event in crm_conversation_events:
        if event.direction != CrmConversationEventDirection.INBOUND:
            continue
        content = _normalized_text(event.content)
        if content is not None:
            return _truncate_text(content, MAX_CRM_LATEST_REQUEST_CHARS)
    return None


def _latest_lead_request_from_activity_items(
    activity_items: tuple[LeadActivityItem, ...],
) -> str | None:
    for item in activity_items:
        if item.kind != LeadActivityKind.INBOUND_MESSAGE and item.direction != "inbound":
            continue
        content = _activity_text(item)
        if content is not None:
            return _truncate_text(content, MAX_ACTIVITY_LATEST_REQUEST_CHARS)
    return None


def _recent_conversation_items_from_activity_items(
    activity_items: tuple[LeadActivityItem, ...],
) -> tuple[ApprovedOutboundConversationItem, ...]:
    items: list[ApprovedOutboundConversationItem] = []
    for item in reversed(activity_items[:MAX_RECENT_CONVERSATION_ITEMS]):
        content = _activity_text(item)
        if content is None:
            continue
        items.append(
            ApprovedOutboundConversationItem(
                occurred_at=item.occurred_at.isoformat(),
                title=item.title,
                content=_truncate_text(content, MAX_RECENT_CONVERSATION_ITEM_CHARS),
                direction=item.direction,
                channel=item.channel,
                actor_name=item.actor_name,
            )
        )
    return tuple(items)


def _recent_conversation_items_from_crm_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> tuple[ApprovedOutboundConversationItem, ...]:
    items: list[ApprovedOutboundConversationItem] = []
    for event in reversed(crm_conversation_events[:MAX_RECENT_CONVERSATION_ITEMS]):
        content = _normalized_text(event.content)
        if content is None:
            continue
        items.append(
            ApprovedOutboundConversationItem(
                occurred_at=event.occurred_at.isoformat(),
                title=_crm_event_label(event),
                content=_truncate_text(content, MAX_RECENT_CONVERSATION_ITEM_CHARS),
                direction=event.direction.value if event.direction is not None else None,
                actor_name=event.actor_name,
            )
        )
    return tuple(items)


def _recent_outbound_messages_from_activity_items(
    activity_items: tuple[LeadActivityItem, ...],
) -> tuple[str, ...]:
    messages: list[str] = []
    for item in activity_items:
        if not _is_outbound(item):
            continue
        content = _activity_text(item)
        if content is None:
            continue
        messages.append(_truncate_text(content, MAX_RECENT_OUTBOUND_MESSAGE_CHARS))
        if len(messages) >= MAX_RECENT_OUTBOUND_MESSAGES:
            break
    return tuple(messages)


def _recent_outbound_messages_from_crm_events(
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> tuple[str, ...]:
    messages: list[str] = []
    for event in crm_conversation_events:
        if event.direction != CrmConversationEventDirection.OUTBOUND:
            continue
        content = _normalized_text(event.content)
        if content is None:
            continue
        messages.append(_truncate_text(content, MAX_RECENT_OUTBOUND_MESSAGE_CHARS))
        if len(messages) >= MAX_RECENT_OUTBOUND_MESSAGES:
            break
    return tuple(messages)


def _safe_preference_snapshot(
    lead: CanonicalLeadRecord,
    *,
    allowed_mapped_custom_field_keys: tuple[str, ...],
) -> dict[str, str]:
    preferences: dict[str, str] = {}

    if lead.latest_property_price_band:
        preferences["price_band"] = lead.latest_property_price_band

    for key in allowed_mapped_custom_field_keys:
        value = lead.mapped_custom_fields.get(key)
        if value is None:
            continue
        normalized = value.strip()
        if normalized:
            preferences[key] = normalized

    return preferences


def _history_preference_snapshot(
    *,
    activity_items: tuple[LeadActivityItem, ...],
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> dict[str, str]:
    evidence = _history_evidence(
        activity_items=activity_items,
        crm_conversation_events=crm_conversation_events,
    )
    if not evidence:
        return {}

    preferences: dict[str, str] = {}
    address = _first_history_address(evidence)
    if address is not None:
        preferences["address"] = address

    locations = _history_locations(evidence)
    if locations:
        preferences["location"] = ", ".join(locations)

    keywords = _history_keywords(evidence)
    if keywords:
        preferences["keywords"] = ", ".join(keywords)

    search_type = _first_history_search_type(evidence)
    if search_type is not None:
        preferences["search_type"] = search_type

    beds = _first_history_bedrooms(evidence)
    if beds is not None:
        preferences["beds"] = _decimal_to_string(beds)

    min_price, max_price, price_band = _first_history_price_preferences(evidence)
    if min_price is not None:
        preferences["min_price"] = str(min_price)
    if max_price is not None:
        preferences["max_price"] = str(max_price)
    if price_band is not None and min_price is None and max_price is None:
        preferences["price_band"] = price_band

    return preferences


def _clear_superseded_preferences(
    preferences: dict[str, str],
    overrides: Mapping[str, str],
) -> None:
    if any(key in overrides for key in LOCATION_PREFERENCE_KEYS):
        for key in LOCATION_PREFERENCE_KEYS:
            preferences.pop(key, None)
    if any(key in overrides for key in ADDRESS_PREFERENCE_KEYS):
        for key in ADDRESS_PREFERENCE_KEYS:
            preferences.pop(key, None)


def _history_evidence(
    *,
    activity_items: tuple[LeadActivityItem, ...],
    crm_conversation_events: tuple[CrmConversationEvent, ...],
) -> tuple[str, ...]:
    texts: list[str] = []
    if activity_items:
        for item in activity_items:
            text = _activity_text(item)
            if text is not None:
                texts.append(text)
        return tuple(texts)

    for event in crm_conversation_events:
        text = _normalized_text(event.content)
        if text is not None:
            texts.append(text)
    return tuple(texts)


def _first_history_address(evidence: tuple[str, ...]) -> str | None:
    for text in evidence:
        match = ADDRESS_PATTERN.search(text)
        if match is not None:
            return match.group(0).strip()
    return None


def _history_locations(evidence: tuple[str, ...]) -> tuple[str, ...]:
    locations: list[str] = []
    for text in evidence:
        for pattern in LOCATION_TRIGGER_PATTERNS:
            for match in pattern.finditer(text):
                for location in _split_location_candidates(match.group(1)):
                    if location not in locations:
                        locations.append(location)
                    if len(locations) >= MAX_HISTORY_LOCATION_VALUES:
                        return tuple(locations)
    return tuple(locations)


def _split_location_candidates(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for part in re.split(r"\s*(?:,|/|\bor\b|\band\b)\s*", raw, flags=re.IGNORECASE):
        normalized = _normalize_location_candidate(part)
        if normalized is None or normalized in values:
            continue
        values.append(normalized)
    return tuple(values)


def _normalize_location_candidate(raw: str) -> str | None:
    candidate = raw.strip(" .,:;-")
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered in INVALID_LOCATION_TOKENS:
        return None
    if any(character.isdigit() for character in candidate):
        return None
    words = [word for word in re.split(r"\s+", candidate) if word]
    if not words or len(words) > 5:
        return None
    if any(word.lower() in INVALID_LOCATION_TOKENS for word in words):
        return None
    return " ".join(word.capitalize() for word in words)


def _history_keywords(evidence: tuple[str, ...]) -> tuple[str, ...]:
    keywords: list[str] = []
    for text in evidence:
        lowered = text.lower()
        for normalized, aliases in HISTORY_KEYWORD_ALIASES.items():
            if normalized in keywords:
                continue
            if any(alias in lowered for alias in aliases):
                keywords.append(normalized)
            if len(keywords) >= MAX_HISTORY_KEYWORD_VALUES:
                return tuple(keywords)
    return tuple(keywords)


def _first_history_search_type(evidence: tuple[str, ...]) -> str | None:
    for text in evidence:
        if SEARCH_TYPE_RENT_PATTERN.search(text):
            return "rent"
        if SEARCH_TYPE_SALE_PATTERN.search(text):
            return "sale"
    return None


def _first_history_bedrooms(evidence: tuple[str, ...]) -> Decimal | None:
    for text in evidence:
        match = BEDROOM_PATTERN.search(text)
        if match is None:
            continue
        value = _parse_decimal_token(match.group(1))
        if value is not None:
            return value
    return None


def _first_history_price_preferences(
    evidence: tuple[str, ...],
) -> tuple[int | None, int | None, str | None]:
    for text in evidence:
        if match := PRICE_RANGE_PATTERN.search(text):
            low = _parse_amount_token(match.group(1))
            high = _parse_amount_token(match.group(2))
            if low is not None and high is not None:
                return min(low, high), max(low, high), None
        if match := MAX_PRICE_PATTERN.search(text):
            maximum = _parse_amount_token(match.group(1))
            if maximum is not None:
                return None, maximum, None
        if match := MIN_PRICE_PATTERN.search(text):
            minimum = _parse_amount_token(match.group(1))
            if minimum is not None:
                return minimum, None, None
        if match := APPROX_PRICE_PATTERN.search(text):
            amount = _parse_amount_token(match.group(1))
            if amount is not None:
                return None, None, _price_band_for_amount(amount)
    return None, None, None


def _parse_amount_token(raw: str) -> int | None:
    match = re.fullmatch(r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([km]?)", raw.strip(), re.IGNORECASE)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    scale = match.group(2).lower()
    if scale == "k":
        value *= 1000
    elif scale == "m":
        value *= 1000000
    return int(value)


def _parse_decimal_token(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    return value


def _price_band_for_amount(amount: int) -> str:
    if amount < 500_000:
        return "under_500k"
    if amount < 1_000_000:
        return "500k_to_1m"
    if amount < 2_000_000:
        return "1m_to_2m"
    return "2m_plus"


def _decimal_to_string(value: Decimal) -> str:
    integral = value.to_integral_value()
    if value == integral:
        return str(int(integral))
    return format(value.normalize(), "f")


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 1].rstrip()}…"


def _crm_event_label(event: CrmConversationEvent) -> str:
    if event.direction == CrmConversationEventDirection.INBOUND:
        return "Lead replied"
    if event.direction == CrmConversationEventDirection.OUTBOUND:
        return "Recent outbound"
    if event.direction == CrmConversationEventDirection.INTERNAL:
        return "CRM note"

    activity_type = event.activity_type.strip()
    if activity_type:
        return f"CRM {activity_type.lower()}"
    return "CRM activity"


def _activity_text(item: LeadActivityItem) -> str | None:
    return _normalized_text(item.content) or _normalized_text(item.preview)


def _is_inbound(item: LeadActivityItem) -> bool:
    return item.kind == LeadActivityKind.INBOUND_MESSAGE or item.direction == "inbound"


def _is_outbound(item: LeadActivityItem) -> bool:
    return item.kind == LeadActivityKind.OUTBOUND_MESSAGE or item.direction == "outbound"
