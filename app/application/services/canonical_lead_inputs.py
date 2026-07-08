from collections.abc import Mapping
from datetime import datetime

from app.application.services.llm.outbound_message_drafting import ApprovedOutboundLeadContext
from app.domain.campaigns.start_queue import CampaignStartCandidate
from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
    LeadContactabilityFacts,
)
from app.domain.compliance.enrollment import CampaignEnrollmentFacts, EnrollmentSource
from app.domain.leads import ActivityReliability, CanonicalLeadRecord, LeadType, PropertyEventType


def contactability_facts_from_canonical_lead(
    lead: CanonicalLeadRecord,
) -> LeadContactabilityFacts:
    return LeadContactabilityFacts(
        do_not_contact=lead.do_not_contact,
        sms_consent_status=lead.sms_permission_status,
        email_permission_status=lead.email_permission_status,
        suppressions=lead.suppression_types,
    )


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
        or _conversation_summary_from_canonical_lead(lead, now),
        latest_lead_request=_normalized_text(latest_lead_request)
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
