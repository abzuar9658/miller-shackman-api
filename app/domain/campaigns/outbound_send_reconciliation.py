from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.common.ids import LeadId, WorkspaceId


class OutboundSendReconciliationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class OutboundSendReconciliation:
    reconciliation_id: UUID
    workspace_id: WorkspaceId
    lead_id: LeadId
    workflow_id: UUID
    temporal_workflow_id: str
    outbound_message_id: UUID
    idempotency_key: str
    status: OutboundSendReconciliationStatus
    provider_name: str
    provider_message_id: str | None
    provider_delivery_status: ProviderDeliveryStatus | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    failure_reason: str | None = None