from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
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
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
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
        primary_email="lead@example.com",
        primary_phone="+15551234567",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        last_meaningful_communication_at=NOW - timedelta(days=90),
        activity_reliability=ActivityReliability.RELIABLE,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.UNKNOWN,
        suppression_types=frozenset({SuppressionType.EMAIL_UNSUBSCRIBED}),
    )


def _crm_event(
    *,
    crm_activity_id: str,
    content: str,
    direction: CrmConversationEventDirection,
) -> CrmConversationEvent:
    lead = _canonical_lead()
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=lead.workspace_id,
        lead_id=lead.lead_id,
        crm_provider=lead.crm_provider.value,
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction=direction,
        occurred_at=NOW,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


def _activity_item(
    *,
    title: str,
    preview: str,
    kind: LeadActivityKind,
    occurred_at: datetime,
    content: str | None = None,
    direction: str | None = None,
    channel: str | None = None,
    actor_name: str | None = None,
) -> LeadActivityItem:
    lead = _canonical_lead()
    return LeadActivityItem(
        activity_id=uuid4(),
        lead_id=lead.lead_id,
        kind=kind,
        occurred_at=occurred_at,
        title=title,
        preview=preview,
        content=content,
        direction=direction,
        channel=channel,
        actor_name=actor_name,
    )


def test_builds_contactability_facts_from_canonical_lead_without_changing_rule_shape() -> None:
    facts = contactability_facts_from_canonical_lead(_canonical_lead())

    assert facts.do_not_contact is False
    assert facts.has_sms_destination is True
    assert facts.has_email_destination is True
    assert facts.sms_consent_status == ContactPermissionStatus.CONFIRMED
    assert facts.email_permission_status == ContactPermissionStatus.UNKNOWN
    assert facts.suppressions == frozenset({SuppressionType.EMAIL_UNSUBSCRIBED})


def test_contactability_facts_derive_do_not_contact_true_without_any_destination() -> None:
    lead = CanonicalLeadRecord(
        workspace_id=uuid4(),
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
    )

    facts = contactability_facts_from_canonical_lead(lead)

    assert facts.do_not_contact is True
    assert facts.has_sms_destination is False
    assert facts.has_email_destination is False


def test_contactability_facts_preserve_explicit_do_not_contact_true() -> None:
    facts = contactability_facts_from_canonical_lead(
        replace(_canonical_lead(), do_not_contact=True)
    )

    assert facts.do_not_contact is True


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
        crm_conversation_events=(
            _crm_event(
                crm_activity_id="act-1",
                content="I want to tour this weekend.",
                direction=CrmConversationEventDirection.INBOUND,
            ),
        ),
    )

    assert context.conversation_summary == "Lead replied last month asking for a call."
    assert context.conversation_memory_summary == "Lead replied last month asking for a call."
    assert context.latest_lead_request == "Asked to speak with an agent."
    assert context.extracted_preferences == {"timeline": "within_3_months"}


def test_activity_history_builds_bounded_memory_recent_transcript_and_outbound_history() -> None:
    lead = _canonical_lead()
    activity_items = (
        _activity_item(
            title="Outbound message",
            preview="Checking in about your home search.",
            content=(
                "Checking in about your home search in Riverdale and whether a 2 bed still works."
            ),
            kind=LeadActivityKind.OUTBOUND_MESSAGE,
            occurred_at=NOW,
            direction="outbound",
            channel="email",
            actor_name="ai_assistant",
        ),
        _activity_item(
            title="Inbound message",
            preview="We still want Riverdale and need 2 beds under 600k.",
            content="We still want Riverdale and need at least 2 beds under 600k.",
            kind=LeadActivityKind.INBOUND_MESSAGE,
            occurred_at=NOW - timedelta(hours=1),
            direction="inbound",
            channel="sms",
            actor_name="lead",
        ),
        _activity_item(
            title="CRM note",
            preview="Agent note: co-op is okay.",
            content="Agent note: co-op is okay and the lead wants to move before school starts.",
            kind=LeadActivityKind.CRM_CONVERSATION_EVENT,
            occurred_at=NOW - timedelta(hours=2),
            direction="internal",
            actor_name="Alex Agent",
        ),
    )

    context = approved_outbound_context_from_canonical_lead(
        lead,
        now=NOW,
        activity_items=activity_items,
    )

    assert context.conversation_summary is not None
    assert context.conversation_memory_summary is not None
    assert "Riverdale" in context.conversation_memory_summary
    assert "co-op is okay" in context.conversation_memory_summary
    assert context.latest_lead_request == (
        "We still want Riverdale and need at least 2 beds under 600k."
    )
    assert len(context.recent_conversation_items) == 3
    assert context.recent_conversation_items[0].title == "CRM note"
    assert context.recent_conversation_items[-1].title == "Outbound message"
    assert context.recent_outbound_messages == (
        "Checking in about your home search in Riverdale and whether a 2 bed still works.",
    )


def test_history_preferences_are_extracted_from_activity_items() -> None:
    context = approved_outbound_context_from_canonical_lead(
        _canonical_lead(),
        now=NOW,
        activity_items=(
            _activity_item(
                title="Inbound message",
                preview="We still want Riverdale or Spuyten Duyvil.",
                content=(
                    "We still want Riverdale or Spuyten Duyvil and need at least 2 bedrooms "
                    "under 600k. A co-op is okay."
                ),
                kind=LeadActivityKind.INBOUND_MESSAGE,
                occurred_at=NOW,
                direction="inbound",
                channel="sms",
                actor_name="lead",
            ),
        ),
    )

    assert context.extracted_preferences["location"] == "Riverdale, Spuyten Duyvil"
    assert context.extracted_preferences["beds"] == "2"
    assert context.extracted_preferences["max_price"] == "600000"
    assert context.extracted_preferences["keywords"] == "co-op"


def test_history_location_extraction_stops_before_budget_phrase() -> None:
    context = approved_outbound_context_from_canonical_lead(
        _canonical_lead(),
        now=NOW,
        activity_items=(
            _activity_item(
                title="Inbound message",
                preview="Looking for 2 bedroom apartments in Queens under $2k/month.",
                content="Looking for 2 bedroom apartments in Queens under $2k/month.",
                kind=LeadActivityKind.INBOUND_MESSAGE,
                occurred_at=NOW,
                direction="inbound",
                channel="sms",
                actor_name="lead",
            ),
        ),
    )

    assert context.extracted_preferences["location"] == "Queens"
    assert context.extracted_preferences["max_price"] == "2000"


def test_history_preferences_fall_back_to_crm_events_when_activity_items_missing() -> None:
    context = approved_outbound_context_from_canonical_lead(
        _canonical_lead(),
        now=NOW,
        crm_conversation_events=(
            _crm_event(
                crm_activity_id="act-1",
                content=(
                    "We want to rent near 225 East 134th Street and need 1 bedroom with "
                    "doorman."
                ),
                direction=CrmConversationEventDirection.INBOUND,
            ),
        ),
    )

    assert context.extracted_preferences["address"] == "225 East 134th Street"
    assert context.extracted_preferences["search_type"] == "rent"
    assert context.extracted_preferences["beds"] == "1"
    assert context.extracted_preferences["keywords"] == "doorman"


def test_crm_conversation_history_precedes_synthetic_summary_and_request() -> None:
    lead = _canonical_lead()

    context = approved_outbound_context_from_canonical_lead(
        lead,
        now=NOW,
        crm_conversation_events=(
            _crm_event(
                crm_activity_id="act-1",
                content="Sent a check-in email last week.",
                direction=CrmConversationEventDirection.OUTBOUND,
            ),
            _crm_event(
                crm_activity_id="act-2",
                content="We are hoping to move before school starts.",
                direction=CrmConversationEventDirection.INBOUND,
            ),
        ),
    )

    assert context.conversation_summary is not None
    assert "Recent CRM conversation history:" in context.conversation_summary
    assert "Sent a check-in email last week." in context.conversation_summary
    assert "We are hoping to move before school starts." in context.conversation_summary
    assert context.latest_lead_request == "We are hoping to move before school starts."


def test_crm_conversation_summary_is_bounded_to_most_recent_five_events() -> None:
    lead = _canonical_lead()
    events = tuple(
        _crm_event(
            crm_activity_id=f"act-{index}",
            content=f"Conversation detail {index}",
            direction=CrmConversationEventDirection.OUTBOUND,
        )
        for index in range(5, -1, -1)
    )

    context = approved_outbound_context_from_canonical_lead(
        lead,
        now=NOW,
        crm_conversation_events=events,
    )

    assert context.conversation_summary is not None
    assert "Conversation detail 0" not in context.conversation_summary
    for index in range(1, 6):
        assert f"Conversation detail {index}" in context.conversation_summary
