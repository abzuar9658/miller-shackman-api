from unittest.mock import MagicMock

import pytest

from app.application.ports.messaging import SMSMessage
from app.infrastructure.messaging.twilio.client import TwilioSMSProvider


@pytest.fixture
def provider() -> TwilioSMSProvider:
    return TwilioSMSProvider("ACsid", "token", "+15551234567")


async def test_send_returns_message_sid(
    monkeypatch: pytest.MonkeyPatch, provider: TwilioSMSProvider
) -> None:
    fake_message = MagicMock()
    fake_message.sid = "SM123"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message
    monkeypatch.setattr(provider, "_client", fake_client)

    message = SMSMessage(
        to_phone="+15559876543",
        body="Hello",
        idempotency_key="key-1",
    )
    result = await provider.send(message)
    assert result == "SM123"
