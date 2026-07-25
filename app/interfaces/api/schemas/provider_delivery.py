from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TwilioMessageStatusCallbackPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_sid: str | None = Field(default=None, alias="MessageSid")
    sms_sid: str | None = Field(default=None, alias="SmsSid")
    message_status: str = Field(alias="MessageStatus")
    error_code: str | None = Field(default=None, alias="ErrorCode")
    error_message: str | None = Field(default=None, alias="ErrorMessage")

    @model_validator(mode="after")
    def validate_provider_message_id(self) -> "TwilioMessageStatusCallbackPayload":
        if self.message_sid or self.sms_sid:
            return self
        raise ValueError("MessageSid or SmsSid is required")

    @property
    def provider_message_id(self) -> str:
        return self.message_sid or self.sms_sid or ""


class SendGridEventWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str
    timestamp: int
    sg_event_id: str | None = None
    sg_message_id: str | None = None
    smtp_id: str | None = Field(default=None, alias="smtp-id")
    reason: str | None = None
    response: str | None = None
    status: str | None = None


class MailgunEventWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event: str
    timestamp: float
    id: str | None = None
    recipient: str | None = None
    severity: str | None = None
    message: dict[str, Any] = Field(default_factory=dict)
    delivery_status: dict[str, Any] | None = Field(default=None, alias="delivery-status")
    signature: dict[str, Any] | None = None

    @property
    def provider_message_id(self) -> str | None:
        headers = self.message.get("headers") if isinstance(self.message, dict) else {}
        if not isinstance(headers, dict):
            return None
        raw_message_id = headers.get("message-id")
        if raw_message_id is None:
            return None
        return str(raw_message_id).strip().lstrip("<").rstrip(">")

    @property
    def provider_event_id(self) -> str | None:
        return self.id

    @property
    def failure_reason(self) -> str | None:
        if not isinstance(self.delivery_status, dict):
            return None
        return self.delivery_status.get("message") or self.delivery_status.get("description")


class ProviderDeliveryWebhookResult(BaseModel):
    status: str
    provider_event_id: UUID | None = None
    message_id: UUID | None = None
    provider_delivery_status: str | None = None
    reasons: list[str] = Field(default_factory=list)


class ProviderDeliveryWebhookResponse(BaseModel):
    processed_count: int = 0
    duplicate_count: int = 0
    ignored_count: int = 0
    results: list[ProviderDeliveryWebhookResult] = Field(default_factory=list)
