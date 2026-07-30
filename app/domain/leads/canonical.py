from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactPermissionStatus, SuppressionType
from app.domain.lead_assignment import AssignmentResolutionStatus, EffectiveOwnerSource


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


class PausedSearchReasonCode(StrEnum):
    RENTED_TEMPORARILY = "rented_temporarily"
    TIMING_NOT_RIGHT = "timing_not_right"
    WAITING_FOR_RATES = "waiting_for_rates"
    WAITING_FOR_INVENTORY = "waiting_for_inventory"
    FINANCIAL_PREP = "financial_prep"
    PERSONAL_LIFE_TIMING = "personal_life_timing"
    OTHER_KNOWN_PAUSE = "other_known_pause"


class PausedSearchSource(StrEnum):
    OPERATOR = "operator"
    REVIEW_PROPOSAL = "review_proposal"
    CRM_SIGNAL = "crm_signal"
    AI_CONVERSATION_CLASSIFICATION = "ai_conversation_classification"
    DETERMINISTIC_FUTURE_TIMING = "deterministic_future_timing"


class LeadStateClassificationOutcome(StrEnum):
    PAUSED_SEARCH = "paused_search"
    DORMANT = "dormant"
    HUMAN_HANDOFF = "human_handoff"
    REVIEW_HOLD = "review_hold"
    BLOCKED = "blocked"


class LeadClassificationAppliedStatus(StrEnum):
    APPLIED = "applied"
    REVIEW = "review"
    BLOCKED = "blocked"


class PausedSearchAction(StrEnum):
    SET = "set"
    UPDATED = "updated"
    CLEARED = "cleared"


def _empty_tags() -> tuple[str, ...]:
    return ()


def _empty_mapping() -> Mapping[str, str]:
    return {}


def _empty_suppressions() -> frozenset[SuppressionType]:
    return frozenset()


@dataclass(frozen=True)
class LeadPausedSearchProfile:
    paused_search_active: bool
    pause_reason_code: PausedSearchReasonCode | None = None
    pause_reason_note: str | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    paused_search_source: PausedSearchSource | None = None
    paused_search_recorded_at: datetime | None = None
    paused_search_recorded_by_user_id: UUID | None = None
    paused_search_last_confirmed_at: datetime | None = None


@dataclass(frozen=True)
class LeadClassificationArtifact:
    artifact_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    source: str
    outcome: LeadStateClassificationOutcome
    pause_reason_code: PausedSearchReasonCode | None
    reengagement_not_before: datetime | None
    reengagement_window_label: str | None
    confidence: float
    evidence: tuple[str, ...]
    summary: str | None
    model: str
    prompt_version: str
    latency_ms: int
    usage_tokens: int | None
    applied_status: LeadClassificationAppliedStatus
    applied_at: datetime | None
    created_at: datetime
    prompt_text: str | None = None
    input_context: Mapping[str, object] = field(default_factory=dict)
    raw_llm_response_text: str | None = None
    parsed_llm_response: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LeadPausedSearchHistoryEntry:
    history_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    action: PausedSearchAction
    previous_profile: LeadPausedSearchProfile | None
    current_profile: LeadPausedSearchProfile | None
    actor_user_id: UUID | None
    created_at: datetime


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
    assigned_agent_user_id: UUID | None = None
    effective_owner_user_id: UUID | None = None
    effective_owner_source: EffectiveOwnerSource | None = None
    assignment_resolution_status: AssignmentResolutionStatus = AssignmentResolutionStatus.UNRESOLVED
    assignment_last_resolved_at: datetime | None = None
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
    paused_search_active: bool = False
    pause_reason_code: PausedSearchReasonCode | None = None
    pause_reason_note: str | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    paused_search_source: PausedSearchSource | None = None
    paused_search_recorded_at: datetime | None = None
    paused_search_recorded_by_user_id: UUID | None = None
    paused_search_last_confirmed_at: datetime | None = None


def lead_paused_search_profile(
    lead: CanonicalLeadRecord,
) -> LeadPausedSearchProfile | None:
    if not lead.paused_search_active:
        return None
    return LeadPausedSearchProfile(
        paused_search_active=lead.paused_search_active,
        pause_reason_code=lead.pause_reason_code,
        pause_reason_note=lead.pause_reason_note,
        reengagement_not_before=lead.reengagement_not_before,
        reengagement_window_label=lead.reengagement_window_label,
        paused_search_source=lead.paused_search_source,
        paused_search_recorded_at=lead.paused_search_recorded_at,
        paused_search_recorded_by_user_id=lead.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=lead.paused_search_last_confirmed_at,
    )
