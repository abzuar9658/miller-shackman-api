from datetime import datetime
from email.parser import HeaderParser
from email.utils import parseaddr
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class TwilioInboundMessagePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_sid: str | None = Field(default=None, alias="MessageSid")
    sms_sid: str | None = Field(default=None, alias="SmsSid")
    from_phone: str = Field(alias="From")
    to_phone: str = Field(alias="To")
    body: str = Field(alias="Body")
    account_sid: str | None = Field(default=None, alias="AccountSid")
    num_media: str | None = Field(default=None, alias="NumMedia")

    @model_validator(mode="after")
    def validate_provider_message_id(self) -> "TwilioInboundMessagePayload":
        if self.message_sid or self.sms_sid:
            return self
        raise ValueError("MessageSid or SmsSid is required")

    @property
    def provider_message_id(self) -> str:
        return self.message_sid or self.sms_sid or ""


class SendGridInboundParsePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    headers: str | None = None
    raw_email: str | None = Field(default=None, alias="email")
    to_email: str = Field(alias="to")
    from_email: str = Field(alias="from")
    subject: str | None = None
    text: str | None = None
    html: str | None = None
    attachments: str | None = None
    attachment_info: str | None = Field(default=None, alias="attachment-info")
    content_ids: str | None = Field(default=None, alias="content-ids")
    charsets: str | None = None
    envelope: str | None = None
    sender_ip: str | None = None
    spam_score: str | None = None

    @model_validator(mode="after")
    def validate_provider_message_id(self) -> "SendGridInboundParsePayload":
        if self.provider_message_id is not None:
            return self
        raise ValueError("headers or email must contain a Message-ID")

    @property
    def provider_message_id(self) -> str | None:
        return _message_id_from_headers(self.headers or self.raw_email)

    @property
    def body(self) -> str:
        return self.text or ""

    @property
    def from_email_address(self) -> str | None:
        return _normalized_email_address(self.from_email)

    @property
    def to_email_address(self) -> str | None:
        return _normalized_email_address(self.to_email)


def _message_id_from_headers(raw_headers: str | None) -> str | None:
    if raw_headers is None or not raw_headers.strip():
        return None
    headers = HeaderParser().parsestr(raw_headers, headersonly=True)
    message_id = headers.get("Message-ID")
    if message_id is None:
        return None
    normalized = " ".join(message_id.split())
    return normalized or None


def _normalized_email_address(raw_address: str) -> str | None:
    _, email_address = parseaddr(raw_address)
    normalized = email_address.strip().lower()
    return normalized or None


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
    signal_queued: bool = False
    review_tag_applied: bool = False
    review_notification_sent: bool = False
    review_notification_recipient: str | None = None
    review_notification_failure_reason: str | None = None
    continue_ai_status: str | None = None
    continue_ai_outbound_message_id: UUID | None = None
    continue_ai_provider_message_id: str | None = None
    continue_ai_pause_reason: str | None = None
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
    signal_queued: bool = False
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
    signal_queued: bool = False
    transition_skip_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)


class FollowUpBossWebhookResponse(BaseModel):
    status: str
    external_event_id: UUID | None = None
    event_type: str | None = None
    processed_count: int = 0
    ignored_count: int = 0
    duplicate_count: int = 0
    reasons: list[str] = Field(default_factory=list)
