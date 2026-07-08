from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.compliance.contactability import ContactChannel


class FollowUpBossInboundMessageRequest(BaseModel):
    workspace_id: UUID
    provider_event_id: str
    provider_message_id: str
    crm_lead_id: str
    channel: ContactChannel
    body: str
    received_at: datetime
    from_address_redacted: str | None = None
    to_address_redacted: str | None = None
    payload_redacted: dict[str, Any] = Field(default_factory=dict)


class InboundWebhookResponse(BaseModel):
    status: str
    external_event_id: UUID | None = None
    lead_id: UUID | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    handoff_id: UUID | None = None
    intent: str | None = None
    handoff_required: bool = False
    opt_out_detected: bool = False
    reasons: list[str] = Field(default_factory=list)
    classification_reasons: list[str] = Field(default_factory=list)