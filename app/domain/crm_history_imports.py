from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

CrmHistoryScalar = str | int | float | bool | None


class CrmHistoryImportJobStatus(StrEnum):
    PENDING = "pending"
    RECEIVING = "receiving"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrmHistoryImportEventStatus(StrEnum):
    RECEIVED = "received"
    PROMOTED = "promoted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class CrmHistoryImportDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


def _empty_details() -> Mapping[str, CrmHistoryScalar]:
    return {}


@dataclass(frozen=True)
class CrmHistoryImportJob:
    import_job_id: UUID
    workspace_id: UUID
    lead_id: UUID
    crm_lead_id: str
    requested_by_user_id: UUID
    status: CrmHistoryImportJobStatus
    upload_token_hash: str
    token_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    received_count: int = 0
    promoted_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    failure_count: int = 0
    upload_completed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class CrmHistoryImportEventPayload:
    fingerprint: str
    activity_type: str
    occurred_at: datetime
    external_activity_id: str | None = None
    direction: CrmHistoryImportDirection | None = None
    content: str | None = None
    actor_agent_id: str | None = None
    actor_name: str | None = None
    details: Mapping[str, CrmHistoryScalar] = field(default_factory=_empty_details)


@dataclass(frozen=True)
class StagedCrmHistoryImportEvent:
    import_event_id: UUID
    workspace_id: UUID
    import_job_id: UUID
    lead_id: UUID
    fingerprint: str
    activity_type: str
    occurred_at: datetime
    status: CrmHistoryImportEventStatus
    created_at: datetime
    external_activity_id: str | None = None
    direction: CrmHistoryImportDirection | None = None
    content: str | None = None
    actor_agent_id: str | None = None
    actor_name: str | None = None
    details: Mapping[str, CrmHistoryScalar] = field(default_factory=_empty_details)
    promoted_at: datetime | None = None
    failure_reason: str | None = None