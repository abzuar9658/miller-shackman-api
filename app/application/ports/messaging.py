from typing import Protocol

from pydantic import BaseModel


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


class SMSProvider(Protocol):
    async def send(self, message: SMSMessage) -> str:
        """Return the provider's message identifier."""
        raise NotImplementedError


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> str:
        """Return the provider's message identifier."""
        raise NotImplementedError
