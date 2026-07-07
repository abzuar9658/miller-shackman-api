from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.services.canonical_lead_inputs import (
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