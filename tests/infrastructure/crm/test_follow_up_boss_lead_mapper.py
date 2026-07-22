from datetime import UTC, datetime
from uuid import uuid4

from app.domain.leads import (
    ActivityReliability,
    LeadClassificationReason,
    LeadType,
    PropertyEventType,
)
from app.infrastructure.crm.follow_up_boss.lead_mapper import (
    map_follow_up_boss_person_to_canonical_lead,
)

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)


def test_maps_buyer_payload_to_canonical_lead_facts() -> None:
    workspace_id = uuid4()
    lead_id = uuid4()
    payload = {
        "id": 123,
        "assignedUserId": 42,
        "assignedTo": "Agent Name",
        "type": "Buyer",
        "source": "Zillow",
        "stage": "Lead",
        "createdVia": "Email Parsing",
        "tags": ["nurture", "buyer", "nurture"],
        "customFields": {"budget": "750000", "unmapped": "ignored"},
        "emails": [{"value": "lead@example.com"}],
        "phones": [{"value": "+15551234567", "isLandline": False}],
        "created": "2024-01-01T00:00:00Z",
        "updated": "2024-01-02T00:00:00Z",
        "lastCommunication": "2024-02-01T00:00:00Z",
        "lastActivity": "2024-02-02T00:00:00Z",
        "contacted": 3,
    }

    lead = map_follow_up_boss_person_to_canonical_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        payload=payload,
        now=NOW,
        mapped_custom_field_keys={"budget"},
    )

    assert lead.workspace_id == workspace_id
    assert lead.lead_id == lead_id
    assert lead.crm_lead_id == "123"
    assert lead.assigned_agent_crm_id == "42"
    assert lead.has_accountable_owner is True
    assert lead.lead_type == LeadType.BUYER
    assert lead.classification_reason == LeadClassificationReason.CRM_TYPE_BUYER
    assert lead.lead_source == "Zillow"
    assert lead.lead_stage == "Lead"
    assert lead.created_via == "Email Parsing"
    assert lead.tags == ("buyer", "nurture")
    assert lead.mapped_custom_fields == {
        "budget": "750000",
        "assigned_agent_name": "Agent Name",
    }
    assert lead.primary_email == "lead@example.com"
    assert lead.primary_phone == "+15551234567"
    assert lead.has_email is True
    assert lead.has_sms_capable_phone is True
    assert lead.email_count == 1
    assert lead.phone_count == 1
    assert lead.contacted_count == 3
    assert lead.activity_reliability == ActivityReliability.RELIABLE


def test_missing_type_and_partial_activity_fail_safe() -> None:
    lead = map_follow_up_boss_person_to_canonical_lead(
        workspace_id=uuid4(),
        payload={
            "id": 123,
            "source": "",
            "stage": None,
            "createdVia": None,
            "phones": [{"value": "+15551234567", "isLandline": True}],
            "lastActivity": "2024-02-02T00:00:00Z",
        },
        now=NOW,
    )

    assert lead.lead_type == LeadType.UNKNOWN
    assert lead.classification_reason == LeadClassificationReason.CRM_TYPE_MISSING
    assert lead.lead_source == "unknown"
    assert lead.lead_stage == "unknown"
    assert lead.created_via == "unknown"
    assert lead.has_email is False
    assert lead.has_phone is True
    assert lead.primary_email is None
    assert lead.primary_phone == "+15551234567"
    assert lead.has_sms_capable_phone is False
    assert lead.last_meaningful_communication_at is None
    assert lead.activity_reliability == ActivityReliability.PARTIAL


def test_primary_phone_prefers_sms_capable_number_when_multiple_numbers_exist() -> None:
    lead = map_follow_up_boss_person_to_canonical_lead(
        workspace_id=uuid4(),
        payload={
            "id": 123,
            "type": "Buyer",
            "phones": [
                {"value": "+15550000001", "isLandline": True},
                {"value": "+15550000002", "isLandline": False},
            ],
        },
        now=NOW,
    )

    assert lead.primary_phone == "+15550000002"
    assert lead.has_sms_capable_phone is True


def test_property_event_keeps_safe_context_without_exact_price_or_address() -> None:
    lead = map_follow_up_boss_person_to_canonical_lead(
        workspace_id=uuid4(),
        payload={"id": 123, "type": "Buyer"},
        events=[
            {
                "type": "Property Inquiry",
                "created": "2024-04-01T00:00:00Z",
                "property": {
                    "price": 750000,
                    "street": "123 Main Street",
                    "url": "https://example.invalid/listing",
                },
            }
        ],
        now=NOW,
    )

    assert lead.latest_property_context_present is True
    assert lead.latest_property_event_type == PropertyEventType.PROPERTY_INQUIRY
    assert lead.latest_property_price_band == "500k_to_1m"
    assert "750000" not in str(lead)
    assert "123 Main" not in str(lead)
