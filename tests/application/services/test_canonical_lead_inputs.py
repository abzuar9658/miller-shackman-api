from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.services.canonical_lead_inputs import (
    approved_outbound_context_from_canonical_lead,
    contactability_facts_from_canonical_lead,
    enrollment_facts_from_canonical_lead,
)
from app.domain.compliance.contactability import (
    ContactabilityDecision,
    ContactChannel,
    ContactPermissionStatus,
    SuppressionType,
)
from app.domain.compliance.enrollment import EnrollmentSource
from app.domain.leads import ActivityReliability, CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def _canonical_lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        last_meaningful_communication_at=NOW - timedelta(days=90),
        activity_reliability=ActivityReliability.RELIABLE,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.UNKNOWN,
        do_not_contact=False,
        suppression_types=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
    )


def test_builds_contactability_facts_from_canonical_lead_without_changing_rule_shape() -> None:
    facts = contactability_facts_from_canonical_lead(_canonical_lead())

    assert facts.do_not_contact is False
    assert facts.sms_consent_status == ContactPermissionStatus.CONFIRMED
    assert facts.email_permission_status == ContactPermissionStatus.UNKNOWN
    assert facts.suppressions == frozenset({SuppressionType.EMAIL_UNSUBSCRIBED})


def test_builds_enrollment_facts_from_canonical_lead_without_changing_rule_shape() -> None:
    contactability = ContactabilityDecision(allowed=True, channel=ContactChannel.SMS)

    facts = enrollment_facts_from_canonical_lead(
        _canonical_lead(),
        enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
        enabled_channels=frozenset({ContactChannel.SMS}),
        channel_contactability={ContactChannel.SMS: contactability},
    )

    assert facts.enrollment_sources == frozenset({EnrollmentSource.DORMANT_SELECTOR})
    assert facts.last_meaningful_communication_at == NOW - timedelta(days=90)
    assert facts.activity_data_complete is True
    assert facts.enabled_channels == frozenset({ContactChannel.SMS})
    assert facts.channel_contactability == {ContactChannel.SMS: contactability}


def test_builds_approved_outbound_context_from_canonical_lead_safe_facts() -> None:
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        has_accountable_owner=True,
        last_meaningful_communication_at=NOW - timedelta(days=90),
        latest_property_price_band="500k-750k",
        mapped_custom_fields={"preferred_location": "Austin"},
    )

    context = approved_outbound_context_from_canonical_lead(
        lead,
        now=NOW,
        allowed_mapped_custom_field_keys=("preferred_location",),
    )

    assert context.conversation_summary is not None
    assert "Lead source: website." in context.conversation_summary
    assert "No meaningful communication recorded for 90 days." in context.conversation_summary
    assert context.latest_lead_request == "Safe price-band signal: 500k-750k."
    assert context.extracted_preferences == {
        "price_band": "500k-750k",
        "preferred_location": "Austin",
    }


def test_explicit_outbound_context_values_override_canonical_defaults() -> None:
    context = approved_outbound_context_from_canonical_lead(
        _canonical_lead(),
        now=NOW,
        conversation_summary="Lead replied last month asking for a call.",
        latest_lead_request="Asked to speak with an agent.",
        extracted_preferences={"timeline": "within_3_months"},
    )

    assert context.conversation_summary == "Lead replied last month asking for a call."
    assert context.latest_lead_request == "Asked to speak with an agent."
    assert context.extracted_preferences == {"timeline": "within_3_months"}
