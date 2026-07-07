from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactPermissionStatus, SuppressionType


class CRMProvider(StrEnum):
    FOLLOW_UP_BOSS = "follow_up_boss"


class LeadType(StrEnum):
    BUYER = "buyer"
    SELLER = "seller"
    BUYER_SELLER = "buyer_seller"
    UNKNOWN = "unknown"


class LeadClassificationReason(StrEnum):
    CRM_TYPE_BUYER = "crm_type_buyer"
    CRM_TYPE_SELLER = "crm_type_seller"
    CRM_TYPE_BUYER_SELLER = "crm_type_buyer_seller"
    CRM_TYPE_MISSING = "crm_type_missing"
    CRM_TYPE_UNSUPPORTED = "crm_type_unsupported"


class ActivityReliability(StrEnum):
    RELIABLE = "reliable"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class PropertyEventType(StrEnum):
    PROPERTY_INQUIRY = "property_inquiry"
    VIEWED_PROPERTY = "viewed_property"


def _empty_tags() -> tuple[str, ...]:
    return ()


def _empty_mapping() -> Mapping[str, str]:
    return {}


def _empty_suppressions() -> frozenset[SuppressionType]:
    return frozenset()


@dataclass(frozen=True)
class CanonicalLeadRecord:
    workspace_id: WorkspaceId
    lead_id: LeadId
    crm_provider: CRMProvider
    crm_lead_id: str
    facts_derived_at: datetime
    source_payload_version: str
    source_updated_at: datetime | None = None
    assigned_agent_crm_id: str | None = None
    assigned_agent_name_present: bool = False
    has_accountable_owner: bool = False
    ownership_last_changed_at: datetime | None = None
    lead_type: LeadType = LeadType.UNKNOWN
    classification_reason: LeadClassificationReason = LeadClassificationReason.CRM_TYPE_MISSING
    crm_type_raw: str | None = None
    lead_source: str = "unknown"
    lead_stage: str = "unknown"
    created_via: str = "unknown"
    tags: tuple[str, ...] = field(default_factory=_empty_tags)
    mapped_custom_fields: Mapping[str, str] = field(default_factory=_empty_mapping)
    primary_email: str | None = None
    primary_phone: str | None = None
    has_email: bool = False
    has_phone: bool = False
    has_sms_capable_phone: bool = False
    email_count: int = 0
    phone_count: int = 0
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.UNKNOWN
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.UNKNOWN
    sms_opted_out: bool = False
    email_unsubscribed: bool = False
    do_not_contact: bool | None = None
    suppression_types: frozenset[SuppressionType] = field(default_factory=_empty_suppressions)
    permission_evidence: Mapping[str, str] = field(default_factory=_empty_mapping)
    crm_created_at: datetime | None = None
    crm_updated_at: datetime | None = None
    last_activity_at: datetime | None = None
    last_meaningful_communication_at: datetime | None = None
    last_agent_activity_at: datetime | None = None
    contacted_count: int | None = None
    activity_reliability: ActivityReliability = ActivityReliability.UNKNOWN
    latest_property_event_type: PropertyEventType | None = None
    latest_property_event_at: datetime | None = None
    latest_property_price_band: str | None = None
    latest_property_context_present: bool = False
