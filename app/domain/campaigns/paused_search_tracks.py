from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import (
    PausedSearchTrackId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import PausedSearchReasonCode


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


class PausedSearchFallbackTimingPolicy(StrEnum):
    HOLD_FOR_REVIEW = "hold_for_review"
    USE_REENGAGEMENT_NOT_BEFORE = "use_reengagement_not_before"
    USE_MAINTENANCE_INTERVAL = "use_maintenance_interval"


class PausedSearchTrackAdminAuditAction(StrEnum):
    DRAFT_CREATED = "paused_search_track_draft_created"
    DRAFT_UPDATED = "paused_search_track_draft_updated"
    VERSION_PUBLISHED = "paused_search_track_version_published"
    TRACK_RETIRED = "paused_search_track_retired"


def _empty_details() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class PausedSearchTrackAdminAuditLog:
    audit_log_id: UUID
    workspace_id: WorkspaceId
    track_id: PausedSearchTrackId
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
class PausedSearchTrackAdminView:
    track: PausedSearchTrack
    version: PausedSearchTrackVersion
    steps: tuple[PausedSearchTrackStep, ...]
    reason_mappings: tuple[PausedSearchReasonMapping, ...] = ()
