from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workspace_automation import WorkspaceAutomationStatus


class CRMSyncJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CRMSyncType(StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"


class CRMSyncLeadSort(StrEnum):
    UPDATED = "updated"
    CREATED = "created"


class ExternalEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    IGNORED = "ignored"


DEFAULT_WORKSPACE_CRM_SYNC_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class WorkspaceCRMSyncConfig:
    workspace_id: WorkspaceId
    crm_sync_enabled: bool = True
    crm_sync_interval_seconds: int = DEFAULT_WORKSPACE_CRM_SYNC_INTERVAL_SECONDS


def default_workspace_crm_sync_config(
    workspace_id: WorkspaceId,
    *,
    default_interval_seconds: int = DEFAULT_WORKSPACE_CRM_SYNC_INTERVAL_SECONDS,
) -> WorkspaceCRMSyncConfig:
    return WorkspaceCRMSyncConfig(
        workspace_id=workspace_id,
        crm_sync_enabled=True,
        crm_sync_interval_seconds=default_interval_seconds,
    )


@dataclass(frozen=True)
class WorkspaceCRMSyncScheduleTarget:
    workspace_id: WorkspaceId
    crm_sync_enabled: bool
    crm_sync_interval_seconds: int
    automation_status: WorkspaceAutomationStatus = WorkspaceAutomationStatus.ACTIVE


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
