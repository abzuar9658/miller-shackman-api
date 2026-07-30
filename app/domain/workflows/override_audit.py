from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, UserId, WorkspaceId


class LeadWorkflowOverrideAction(StrEnum):
    TIMING_CHANGED = "paused_search_timing_changed"
    TRACK_VERSION_MIGRATED = "paused_search_track_version_migrated"
    NEXT_TOUCH_SKIPPED = "paused_search_next_touch_skipped"


def _empty_details() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class LeadWorkflowOverrideAuditLog:
    audit_log_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    workflow_id: UUID
    actor_user_id: UserId
    action: LeadWorkflowOverrideAction
    reason: str
    created_at: datetime
    details: Mapping[str, object] = field(default_factory=_empty_details)