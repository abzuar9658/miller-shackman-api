from collections.abc import Mapping
from datetime import datetime

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.services.llm.outbound_message_drafting import ApprovedOutboundLeadContext
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
MAX_CRM_LATEST_REQUEST_CHARS = 240
MAX_ACTIVITY_CONTEXT_ITEMS = 5
MAX_ACTIVITY_CONTEXT_CHARS = 160
MAX_ACTIVITY_LATEST_REQUEST_CHARS = 240


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
    if extracted_preferences:
        preferences.update(
            {
                key: value
                for key, value in extracted_preferences.items()
                if key.strip() and value.strip()
            },
        )

    return ApprovedOutboundLeadContext(
        conversation_summary=_normalized_text(conversation_summary)
        or _conversation_summary_from_activity_items(activity_items)
        or _conversation_summary_from_crm_events(crm_conversation_events)
        or _conversation_summary_from_canonical_lead(lead, now),
        latest_lead_request=_normalized_text(latest_lead_request)
        or _latest_lead_request_from_activity_items(activity_items)
        or _latest_lead_request_from_crm_events(crm_conversation_events)
        or _latest_lead_request_from_canonical_lead(lead),
        extracted_preferences=preferences,
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
        preview = _normalized_text(item.preview)
        if preview is None:
            continue
        parts.append(
            f"{item.title}: {_truncate_text(preview, MAX_ACTIVITY_CONTEXT_CHARS)}",
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
        preview = _normalized_text(item.preview)
        if preview is not None:
            return _truncate_text(preview, MAX_ACTIVITY_LATEST_REQUEST_CHARS)
    return None


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
