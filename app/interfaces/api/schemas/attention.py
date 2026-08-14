from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AttentionAcknowledgementRequest(BaseModel):
    item_version: str = Field(min_length=1, max_length=500)


class AttentionAcknowledgementResponse(BaseModel):
    item_id: str
    item_version: str
    acknowledged_at: datetime
    acknowledged_by_user_id: UUID
    acknowledged_by_name: str | None = None


class AttentionAcknowledgementListResponse(BaseModel):
    status: str
    acknowledgements: list[AttentionAcknowledgementResponse]


class AttentionAcknowledgementResultResponse(BaseModel):
    status: str
    acknowledgement: AttentionAcknowledgementResponse | None = None


class ClearAttentionAcknowledgementResponse(BaseModel):
    status: str
    item_id: str


class OutboundSendExceptionResponse(BaseModel):
    request_id: UUID
    workspace_id: UUID
    lead_id: UUID
    workflow_id: UUID
    outbound_message_id: UUID
    reconciliation_id: UUID
    status: str
    channel: str
    provider_name: str
    attempt_count: int
    available_at: datetime
    created_at: datetime
    updated_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    failure_kind: str | None = None
    failure_reason: str | None = None
    reconciliation_status: str | None = None
    reconciliation_failure_reason: str | None = None
    provider_failure_status: str | None = None
    provider_failure_id: UUID | None = None
    first_failed_at: datetime | None = None
    last_failed_at: datetime | None = None


class OutboundSendExceptionListResponse(BaseModel):
    status: str
    exceptions: list[OutboundSendExceptionResponse]


class OutboundSendExceptionDetailResponse(BaseModel):
    status: str
    exception: OutboundSendExceptionResponse
