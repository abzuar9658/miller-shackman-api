from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.compliance.contactability import ContactChannel, ContactSuppressionKind


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


class FollowUpBossCRMHumanActivityRequest(BaseModel):
    workspace_id: UUID
    provider_event_id: str
    crm_lead_id: str
    occurred_at: datetime
    event_type: str
    activity_type: str | None = None
    crm_activity_id: str | None = None
    actor_agent_id: str | None = None
    changed_field: str | None = None
    previous_value_redacted: str | None = None
    new_value_redacted: str | None = None
    payload_redacted: dict[str, Any] = Field(default_factory=dict)


class FollowUpBossContactSuppressionRequest(BaseModel):
    workspace_id: UUID
    source_provider: str
    provider_event_id: str
    crm_lead_id: str
    suppression_kind: ContactSuppressionKind
    occurred_at: datetime
    provider_message_id: str | None = None
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


class CRMHumanActivityWebhookResponse(BaseModel):
    status: str
    external_event_id: UUID | None = None
    lead_id: UUID | None = None
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    activity_kind: str | None = None
    pause_reason: str | None = None
    pause_requested: bool = False
    signal_sent: bool = False
    signal_failure_reason: str | None = None
    transition_skip_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ContactSuppressionWebhookResponse(BaseModel):
    status: str
    external_event_id: UUID | None = None
    lead_id: UUID | None = None
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    suppression_kind: str | None = None
    workflow_state: str | None = None
    suppression_applied: bool = False
    signal_sent: bool = False
    signal_failure_reason: str | None = None
    transition_skip_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)
