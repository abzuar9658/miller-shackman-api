from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class OutboundProviderFailureStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class OutboundProviderFailure:
    failure_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    outbound_message_id: UUID
    workflow_id: UUID | None
    channel: ContactChannel
    provider_name: str
    failure_kind: str
    failure_reason: str
    attempt_count: int
    status: OutboundProviderFailureStatus
    first_failed_at: datetime
    last_failed_at: datetime
    created_at: datetime
    resolved_at: datetime | None = None