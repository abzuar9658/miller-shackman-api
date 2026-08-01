from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.campaigns.admin import CampaignAdminAuditAction
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import WorkspaceId


@dataclass(frozen=True)
class WorkflowStateCounts:
    eligible: int = 0
    queued: int = 0
    active_nurture: int = 0
    waiting_for_response: int = 0
    response_processing: int = 0
    paused: int = 0
    human_handoff: int = 0
    human_owned: int = 0
    completed: int = 0
    suppressed: int = 0
    closed: int = 0


@dataclass(frozen=True)
class EnrollmentStatusCounts:
    candidate: int = 0
    queued: int = 0
    active: int = 0
    paused: int = 0
    handoff: int = 0
    completed: int = 0
    suppressed: int = 0
    closed: int = 0


@dataclass(frozen=True)
class MessageStatusCounts:
    pending: int = 0
    sent: int = 0
    failed: int = 0
    uncertain: int = 0
    cancelled: int = 0
    delivered: int = 0
    delivery_issues: int = 0


@dataclass(frozen=True)
class HandoffStatusCounts:
    created: int = 0
    notified: int = 0
    acknowledged: int = 0
    resolved: int = 0
    cancelled: int = 0


@dataclass(frozen=True)
class PausedSearchOccurrenceHealth:
    due: int = 0
    held: int = 0
    review_pending: int = 0
    expired: int = 0
    failed: int = 0
    uncertain: int = 0
    terminal: int = 0
    fallback: int = 0


@dataclass(frozen=True)
class CampaignAuditLogEntry:
    audit_log_id: UUID
    workspace_id: WorkspaceId
    campaign_id: UUID
    campaign_version_id: UUID | None
    action: CampaignAdminAuditAction
    actor_user_id: UUID
    details: dict[str, object]
    created_at: datetime


@dataclass(frozen=True)
class WorkspaceOperationsSummary:
    workspace_id: WorkspaceId
    active_campaigns: int
    paused_campaigns: int
    last_successful_sync_at: datetime | None
    workflow_counts: WorkflowStateCounts
    message_counts: MessageStatusCounts
    handoff_counts: HandoffStatusCounts
    pending_external_events: int
    failed_external_events: int
    pending_outbox_events: int
    failed_outbox_events: int
    paused_search_occurrence_health: PausedSearchOccurrenceHealth = PausedSearchOccurrenceHealth()


@dataclass(frozen=True)
class CampaignOperationsSummary:
    workspace_id: WorkspaceId
    campaign_id: UUID
    campaign_name: str
    campaign_status: CampaignStatus
    active_version_id: UUID | None
    latest_audit_at: datetime | None
    enrollment_counts: EnrollmentStatusCounts
    workflow_counts: WorkflowStateCounts
    message_counts: MessageStatusCounts
    handoff_counts: HandoffStatusCounts
