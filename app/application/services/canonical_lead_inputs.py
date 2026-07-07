from collections.abc import Mapping
from datetime import datetime

from app.domain.campaigns.start_queue import CampaignStartCandidate
from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
    LeadContactabilityFacts,
)
from app.domain.compliance.enrollment import CampaignEnrollmentFacts, EnrollmentSource
from app.domain.leads import ActivityReliability, CanonicalLeadRecord


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
