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
from app.domain.outbound_drafting import DormantStepTemplateProfile


def generate_paused_search_track_key(display_name: str) -> str:
    key = display_name.strip().lower().replace("&", " and ")
    key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    return key or "paused-search-track"


class PausedSearchTrackStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class PausedSearchTrackCompatibility(StrEnum):
    """Whether a track version uses fields retained only for legacy reads."""

    GUIDED = "guided"
    LEGACY = "legacy"


class PausedSearchTrackStepPhase(StrEnum):
    MAINTENANCE = "maintenance"
    REACTIVATION = "reactivation"


class PausedSearchTrackMode(StrEnum):
    WAIT_UNTIL_REQUESTED_DATE = "wait_until_requested_date"
    PERMISSION_BASED_INTERIM_CONTACT = "permission_based_interim_contact"
    AGENT_MANAGED = "agent_managed"
    SCHEDULED_REACTIVATION = "scheduled_reactivation"
    CUSTOM_BOUNDED = "custom_bounded"


class PausedSearchInterimContactPolicy(StrEnum):
    NOT_ALLOWED = "not_allowed"
    REQUIRES_EXPLICIT_LEAD_PERMISSION = "requires_explicit_lead_permission"
    ALLOWED_BY_PUBLISHED_TRACK = "allowed_by_published_track"


def paused_search_interim_contact_is_configured(
    policy: PausedSearchInterimContactPolicy,
) -> bool:
    """Return whether a track policy permits configured maintenance contact."""

    return policy is not PausedSearchInterimContactPolicy.NOT_ALLOWED


class PausedSearchStepAction(StrEnum):
    SEND = "send"
    REVIEW = "review"
    REMINDER = "reminder"
    SKIP = "skip"


class PausedSearchReplyPolicy(StrEnum):
    CONTINUE = "continue"
    RESTART_AFTER_DELAY = "restart_after_delay"
    REANCHOR_TO_NEW_TIMING = "reanchor_to_new_timing"
    REVIEW_OR_REMIND = "review_or_remind"
    END = "end"


class PausedSearchChannelSequence(StrEnum):
    SEQUENTIAL = "sequential"
    SIMULTANEOUS = "simultaneous"


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
    CLASSIFICATION = "classification"
    OPERATOR = "operator"


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
    selection_guidance: str
    enabled: bool
    allowed_channels: tuple[ContactChannel, ...]
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    created_by_user_id: UserId
    created_at: datetime
    published_at: datetime | None = None
    default_pause_duration_days: int = 60
    max_duration_days: int = 365
    terminal_behavior: PausedSearchTerminalBehavior = (
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    )
    track_mode: PausedSearchTrackMode = PausedSearchTrackMode.CUSTOM_BOUNDED
    interim_contact_policy: PausedSearchInterimContactPolicy = (
        PausedSearchInterimContactPolicy.NOT_ALLOWED
    )
    reply_policy: PausedSearchReplyPolicy = PausedSearchReplyPolicy.END
    channel_sequence: PausedSearchChannelSequence = PausedSearchChannelSequence.SEQUENTIAL
    max_cycles: int = 1
    max_ai_interactions: int = 5
    restart_delay_days: int = 30

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
    action: PausedSearchStepAction | None = None


def effective_paused_search_step_action(step: PausedSearchTrackStep) -> PausedSearchStepAction:
    """Return the canonical action while reading legacy step records safely."""

    if step.action is not None:
        return step.action
    return PausedSearchStepAction.REVIEW if step.review_required else PausedSearchStepAction.SEND


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
    assigned_leads: tuple[PausedSearchTrackLeadAssignment, ...] = ()

    @property
    def compatibility(self) -> PausedSearchTrackCompatibility:
        if any(step.action is None and step.review_required for step in self.steps):
            return PausedSearchTrackCompatibility.LEGACY
        return PausedSearchTrackCompatibility.GUIDED


@dataclass(frozen=True)
class PausedSearchTrackCatalogEntry:
    track_key: str
    display_name: str
    selection_guidance: str
    track_id: PausedSearchTrackId
    track_version_id: PausedSearchTrackVersionId
