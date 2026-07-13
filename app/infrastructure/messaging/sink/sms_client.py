import uuid

from app.application.ports.messaging import SMSMessage, SMSProvider


class SinkSMSProvider(SMSProvider):
    """Dev-only SMS provider that never contacts an external service.

    Captures every message in an in-memory list and returns a synthetic
    provider message identifier so the normal send flow can be exercised
    safely in tests and local development.
    """

    provider_name = "sink"

    def __init__(self) -> None:
        self.messages: list[SMSMessage] = []

    async def send(self, message: SMSMessage) -> str:
        self.messages.append(message)
        return f"sink-sms-{uuid.uuid4()}"
