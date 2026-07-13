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
