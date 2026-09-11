from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SuppressionType,
)
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


class PausedSearchTrackSelectionStatus(StrEnum):
    SELECTED = "selected"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


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
    paused_search_track_key: str | None = None
    paused_search_track_version_id: PausedSearchTrackVersionId | None = None
    pause_reason_note: str | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    paused_search_source: PausedSearchSource | None = None
    paused_search_recorded_at: datetime | None = None
    paused_search_recorded_by_user_id: UUID | None = None
    paused_search_last_confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.paused_search_active and (
            not self.paused_search_track_key or self.paused_search_track_version_id is None
        ):
            raise ValueError("active paused-search profiles require a concrete track assignment")


@dataclass(frozen=True)
class LeadClassificationArtifact:
    artifact_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    source: str
    outcome: LeadStateClassificationOutcome
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
    selected_track_key: str | None = None
    track_selection_status: PausedSearchTrackSelectionStatus | None = None
    track_version_id: UUID | None = None
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
    paused_search_track_key: str | None = None
    paused_search_track_version_id: PausedSearchTrackVersionId | None = None
    pause_reason_note: str | None = None
    reengagement_not_before: datetime | None = None
    reengagement_window_label: str | None = None
    paused_search_source: PausedSearchSource | None = None
    paused_search_recorded_at: datetime | None = None
    paused_search_recorded_by_user_id: UUID | None = None
    paused_search_last_confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.paused_search_active and (
            not self.paused_search_track_key or self.paused_search_track_version_id is None
        ):
            raise ValueError("active paused-search leads require a concrete track assignment")


def preserve_durable_lead_state(
    fresh: CanonicalLeadRecord,
    existing: CanonicalLeadRecord | None,
) -> CanonicalLeadRecord:
    """Protect restrictions and newest activity on every whole-record write.

    Persistence repeats this merge against the locked row, not a pre-fetch snapshot.
    Deliberate paused-profile edits remain possible through ordinary app writes.
    """
    if existing is None:
        return fresh
    evidence = dict(fresh.permission_evidence)
    retained: set[ContactSuppressionKind] = set()
    for suppression, active, crm_marker in (
        (
            ContactSuppressionKind.SMS_OPT_OUT,
            existing.sms_opted_out or SuppressionType.SMS_OPT_OUT in existing.suppression_types,
            "sms_opted_out_source",
        ),
        (
            ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            existing.email_unsubscribed
            or SuppressionType.EMAIL_UNSUBSCRIBED in existing.suppression_types,
            "email_unsubscribed_source",
        ),
        (
            ContactSuppressionKind.DO_NOT_CONTACT, existing.do_not_contact is True,
            "do_not_contact_source",
        ),
    ):
        source_keys = tuple(
            f"{suppression.value}_{suffix}"
            for suffix in ("source_provider", "source_event_id", "occurred_at")
        )
        has_platform_evidence = any(key in existing.permission_evidence for key in source_keys)
        crm_only = (
            existing.permission_evidence.get(crm_marker) == "follow_up_boss.customFields"
            and not has_platform_evidence
        )
        # Missing/partial provenance is not permission to clear an existing block.
        if not active or crm_only:
            continue
        retained.add(suppression)
        if has_platform_evidence:
            for key in source_keys:
                evidence.pop(key, None)
                if key in existing.permission_evidence:
                    evidence[key] = existing.permission_evidence[key]
        # A new snapshot must not relabel an ambiguous legacy block as CRM-only.
        if not has_platform_evidence:
            evidence.pop(crm_marker, None)
        if crm_marker in existing.permission_evidence:
            evidence[crm_marker] = existing.permission_evidence[crm_marker]
    return replace(
        fresh,
        sms_opted_out=fresh.sms_opted_out or ContactSuppressionKind.SMS_OPT_OUT in retained,
        email_unsubscribed=(
            fresh.email_unsubscribed or ContactSuppressionKind.EMAIL_UNSUBSCRIBED in retained
        ),
        do_not_contact=(
            True if ContactSuppressionKind.DO_NOT_CONTACT in retained else fresh.do_not_contact
        ),
        suppression_types=fresh.suppression_types
        | {kind for kind in SuppressionType if ContactSuppressionKind(kind.value) in retained},
        permission_evidence=evidence,
        last_agent_activity_at=max(
            (
                timestamp for timestamp in
                (existing.last_agent_activity_at, fresh.last_agent_activity_at)
                if timestamp is not None
            ),
            default=None,
        ),
    )


def preserve_app_owned_lead_state(
    fresh: CanonicalLeadRecord,
    existing: CanonicalLeadRecord | None,
) -> CanonicalLeadRecord:
    """CRM has no paused-search profile, so it cannot replace that app-owned state."""
    if existing is None:
        return fresh
    return replace(
        preserve_durable_lead_state(fresh, existing),
        paused_search_active=existing.paused_search_active,
        paused_search_track_key=existing.paused_search_track_key,
        paused_search_track_version_id=existing.paused_search_track_version_id,
        pause_reason_note=existing.pause_reason_note,
        reengagement_not_before=existing.reengagement_not_before,
        reengagement_window_label=existing.reengagement_window_label,
        paused_search_source=existing.paused_search_source,
        paused_search_recorded_at=existing.paused_search_recorded_at,
        paused_search_recorded_by_user_id=existing.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=existing.paused_search_last_confirmed_at,
    )


def lead_paused_search_profile(
    lead: CanonicalLeadRecord,
) -> LeadPausedSearchProfile | None:
    if not lead.paused_search_active:
        return None
    return LeadPausedSearchProfile(
        paused_search_active=lead.paused_search_active,
        paused_search_track_key=lead.paused_search_track_key,
        paused_search_track_version_id=lead.paused_search_track_version_id,
        pause_reason_note=lead.pause_reason_note,
        reengagement_not_before=lead.reengagement_not_before,
        reengagement_window_label=lead.reengagement_window_label,
        paused_search_source=lead.paused_search_source,
        paused_search_recorded_at=lead.paused_search_recorded_at,
        paused_search_recorded_by_user_id=lead.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=lead.paused_search_last_confirmed_at,
    )
