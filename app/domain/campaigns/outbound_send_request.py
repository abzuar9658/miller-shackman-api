from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class OutboundSendRequestStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    SENT = "sent"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class OutboundSendRequest:
    request_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    workflow_id: UUID
    temporal_workflow_id: str
    outbound_message_id: UUID
    reconciliation_id: UUID
    idempotency_key: str
    channel: ContactChannel
    provider_name: str
    provider_payload: dict[str, object]
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    status: OutboundSendRequestStatus = OutboundSendRequestStatus.PENDING
    attempt_count: int = 0
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    provider_message_id: str | None = None
    failure_kind: str | None = None
    failure_reason: str | None = None