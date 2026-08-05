import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode
from app.domain.outbound_drafting import DormantStepTemplateProfile


def generate_paused_search_track_key(display_name: str) -> str:
    key = display_name.strip().lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return key or "paused-search-track"


class PausedSearchTrackStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class PausedSearchTrackFamily(StrEnum):
    MAINTENANCE = "maintenance"
    REACTIVATION = "reactivation"
    AGENT_OWNED_REMINDER = "agent_owned_reminder"


class PausedSearchTrackStepPhase(StrEnum):
    MAINTENANCE = "maintenance"
    REACTIVATION = "reactivation"


class PausedSearchTimingBasis(StrEnum):
    CUSTOMER_REENGAGEMENT_DATE = "customer_reengagement_date"
    WORKFLOW_CREATED_AT = "workflow_created_at"
    PREVIOUS_OCCURRENCE = "previous_occurrence"


class PausedSearchFallbackTimingPolicy(StrEnum):
    HOLD_FOR_REVIEW = "hold_for_review"
    USE_REENGAGEMENT_NOT_BEFORE = "use_reengagement_not_before"
    USE_MAINTENANCE_INTERVAL = "use_maintenance_interval"
    USE_DEFAULT_PAUSE_DURATION = "use_default_pause_duration"


class PausedSearchTerminalBehavior(StrEnum):
    COMPLETE_KEEP_PAUSED = "complete_keep_paused"
    PAUSE_FOR_REVIEW = "pause_for_review"
    CLOSE_AUTOMATION = "close_automation"


class PausedSearchTrackAdminAuditAction(StrEnum):
    DRAFT_CREATED = "paused_search_track_draft_created"
    DRAFT_UPDATED = "paused_search_track_draft_updated"
    VERSION_PUBLISHED = "paused_search_track_version_published"
    TRACK_RETIRED = "paused_search_track_retired"
    TRACK_RESTORED = "paused_search_track_restored"
    TRACK_DELETED = "paused_search_track_deleted"


class PausedSearchTrackAssignmentSource(StrEnum):
    REASON_MAPPING = "reason_mapping"
    WORKFLOW_BACKFILL = "workflow_backfill"
    LEGACY_REASON_BACKFILL = "legacy_reason_backfill"
    ADMIN_MIGRATION = "admin_migration"
    ADMIN_REPAIR = "admin_repair"


def _empty_details() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class PausedSearchTrackAdminAuditLog:
    audit_log_id: UUID
    workspace_id: WorkspaceId
    track_id: PausedSearchTrackId | None
    action: PausedSearchTrackAdminAuditAction
    actor_user_id: UserId
    created_at: datetime
    track_version_id: PausedSearchTrackVersionId | None = None
    details: Mapping[str, object] = field(default_factory=_empty_details)


@dataclass(frozen=True)
class PausedSearchTrack:
    track_id: PausedSearchTrackId
    workspace_id: WorkspaceId
    track_key: str
    display_name: str
    status: PausedSearchTrackStatus
    active_version_id: PausedSearchTrackVersionId | None
    created_by_user_id: UserId
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PausedSearchTrackVersion:
    track_version_id: PausedSearchTrackVersionId
    workspace_id: WorkspaceId
    track_id: PausedSearchTrackId
    version_number: int
    status: CampaignVersionStatus
    track_family: PausedSearchTrackFamily
    enabled: bool
    allowed_channels: tuple[ContactChannel, ...]
    default_for_reason_codes: tuple[PausedSearchReasonCode, ...]
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    requires_review_before_publish: bool
    created_by_user_id: UserId
    created_at: datetime
    published_at: datetime | None = None
    default_pause_duration_days: int = 60
    max_duration_days: int = 365
    terminal_behavior: PausedSearchTerminalBehavior = (
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    )


@dataclass(frozen=True)
class PausedSearchTrackStep:
    step_id: UUID
    workspace_id: WorkspaceId
    track_version_id: PausedSearchTrackVersionId
    step_order: int
    phase: PausedSearchTrackStepPhase
    channel: ContactChannel
    delay_hours: int
    message_goal: str
    template_key: str
    max_attempts: int
    review_required: bool
    created_at: datetime
    timing_basis: PausedSearchTimingBasis = PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE
    fallback_channel: ContactChannel | None = None
    interval_days: int | None = None
    max_occurrences: int = 1
    template_version_id: UUID | None = None
    template_profile: DormantStepTemplateProfile | None = None


@dataclass(frozen=True)
class PausedSearchReasonMapping:
    mapping_id: UUID
    workspace_id: WorkspaceId
    reason_code: PausedSearchReasonCode
    track_id: PausedSearchTrackId
    track_version_id: PausedSearchTrackVersionId
    created_by_user_id: UserId
    created_at: datetime


@dataclass(frozen=True)
class PausedSearchTrackAssignment:
    assignment_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    track_id: PausedSearchTrackId | None
    track_version_id: PausedSearchTrackVersionId | None
    track_key_snapshot: str
    track_name_snapshot: str
    track_version_snapshot: int
    reason_code: PausedSearchReasonCode | None
    source: PausedSearchTrackAssignmentSource
    assigned_by_user_id: UserId | None
    assigned_at: datetime
    released_at: datetime | None = None
    released_by: UserId | None = None
    release_reason: str | None = None


@dataclass(frozen=True)
class PausedSearchTrackLeadAssignment:
    lead_id: UUID
    workflow_id: UUID | None
    track_version_id: PausedSearchTrackVersionId | None
    crm_lead_id: str
    primary_email: str | None
    lead_stage: str
    workflow_state: str | None


@dataclass(frozen=True)
class PausedSearchTrackAdminView:
    track: PausedSearchTrack
    version: PausedSearchTrackVersion
    steps: tuple[PausedSearchTrackStep, ...]
    reason_mappings: tuple[PausedSearchReasonMapping, ...] = ()
    assigned_leads: tuple[PausedSearchTrackLeadAssignment, ...] = ()
