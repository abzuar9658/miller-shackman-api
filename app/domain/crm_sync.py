from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId


class CRMSyncJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CRMSyncType(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class ExternalEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    IGNORED = "ignored"


@dataclass(frozen=True)
class CRMSyncJob:
    sync_job_id: UUID
    workspace_id: WorkspaceId
    crm_provider: str
    sync_type: CRMSyncType
    status: CRMSyncJobStatus
    started_at: datetime | None
    finished_at: datetime | None
    cursor_started_at: datetime | None
    cursor_finished_at: datetime | None
    total_seen: int
    total_upserted: int
    total_failed: int
    failure_reason: str | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ExternalEvent:
    external_event_id: UUID
    workspace_id: WorkspaceId
    provider: str
    event_type: str
    provider_event_id: str
    crm_lead_id: str | None
    lead_id: LeadId | None
    received_at: datetime
    processed_at: datetime | None
    status: ExternalEventStatus
    payload_redacted: dict[str, Any]
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
