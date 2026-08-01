from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorkflowStateCountsResponse(BaseModel):
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


class EnrollmentStatusCountsResponse(BaseModel):
    candidate: int = 0
    queued: int = 0
    active: int = 0
    paused: int = 0
    handoff: int = 0
    completed: int = 0
    suppressed: int = 0
    closed: int = 0


class MessageStatusCountsResponse(BaseModel):
    pending: int = 0
    sent: int = 0
    failed: int = 0
    uncertain: int = 0
    cancelled: int = 0
    delivered: int = 0
    delivery_issues: int = 0


class HandoffStatusCountsResponse(BaseModel):
    created: int = 0
    notified: int = 0
    acknowledged: int = 0
    resolved: int = 0
    cancelled: int = 0


class PausedSearchOccurrenceHealthResponse(BaseModel):
    due: int = 0
    held: int = 0
    review_pending: int = 0
    expired: int = 0
    failed: int = 0
    uncertain: int = 0
    terminal: int = 0
    fallback: int = 0


class WorkspaceOperationsSummaryResponse(BaseModel):
    workspace_id: UUID
    active_campaigns: int
    paused_campaigns: int
    last_successful_sync_at: datetime | None = None
    workflow_counts: WorkflowStateCountsResponse
    message_counts: MessageStatusCountsResponse
    handoff_counts: HandoffStatusCountsResponse
    paused_search_occurrence_health: PausedSearchOccurrenceHealthResponse
    pending_external_events: int
    failed_external_events: int
    pending_outbox_events: int
    failed_outbox_events: int


class CampaignOperationsSummaryResponse(BaseModel):
    workspace_id: UUID
    campaign_id: UUID
    campaign_name: str
    campaign_status: str
    active_version_id: UUID | None = None
    latest_audit_at: datetime | None = None
    enrollment_counts: EnrollmentStatusCountsResponse
    workflow_counts: WorkflowStateCountsResponse
    message_counts: MessageStatusCountsResponse
    handoff_counts: HandoffStatusCountsResponse


class CampaignAuditLogEntryResponse(BaseModel):
    audit_log_id: UUID
    workspace_id: UUID
    campaign_id: UUID
    campaign_version_id: UUID | None = None
    action: str
    actor_user_id: UUID
    details: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class WorkspaceOperationsReportResponse(BaseModel):
    status: str
    report: WorkspaceOperationsSummaryResponse


class CampaignOperationsReportResponse(BaseModel):
    status: str
    report: CampaignOperationsSummaryResponse


class CampaignAuditLogListResponse(BaseModel):
    status: str
    entries: list[CampaignAuditLogEntryResponse] = Field(default_factory=list)
