from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel


class ProviderFailureKind(StrEnum):
    PERMANENT = "permanent"
    TEMPORARY = "temporary"
    UNCERTAIN = "uncertain"


class ProviderSendFailure(Exception):
    def __init__(self, kind: ProviderFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class SMSMessage(BaseModel):
    to_phone: str
    body: str
    idempotency_key: str


class EmailMessage(BaseModel):
    to_email: str
    subject: str
    body: str
    html_body: str | None = None
    idempotency_key: str
    from_email: str | None = None
    message_id: str | None = None
    reply_to: str | None = None
    in_reply_to_message_id: str | None = None
    reference_message_ids: tuple[str, ...] = ()


class SMSProvider(Protocol):
    async def send(self, message: SMSMessage) -> str:
        """Return the provider's message identifier."""
        raise NotImplementedError


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> str:
        """Return the provider's message identifier."""
        raise NotImplementedError
