from unittest.mock import MagicMock

import pytest

from app.application.ports.messaging import SMSMessage
from app.infrastructure.messaging.twilio.client import TwilioSMSProvider


@pytest.fixture
def provider() -> TwilioSMSProvider:
    return TwilioSMSProvider("ACsid", "token", "+15551234567")


@pytest.fixture
def whatsapp_provider() -> TwilioSMSProvider:
    return TwilioSMSProvider("ACsid", "token", "whatsapp:+14155238886")


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
    fake_client.messages.create.assert_called_once_with(
        to="+15559876543",
        from_="+15551234567",
        body="Hello",
    )


async def test_send_prefixes_plain_destination_for_whatsapp(
    monkeypatch: pytest.MonkeyPatch, whatsapp_provider: TwilioSMSProvider
) -> None:
    fake_message = MagicMock()
    fake_message.sid = "SM123"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message
    monkeypatch.setattr(whatsapp_provider, "_client", fake_client)

    result = await whatsapp_provider.send(
        SMSMessage(to_phone="+15559876543", body="Hello", idempotency_key="key-1")
    )

    assert result == "SM123"
    fake_client.messages.create.assert_called_once_with(
        to="whatsapp:+15559876543",
        from_="whatsapp:+14155238886",
        body="Hello",
    )


async def test_send_preserves_prefixed_whatsapp_destination(
    monkeypatch: pytest.MonkeyPatch, whatsapp_provider: TwilioSMSProvider
) -> None:
    fake_message = MagicMock()
    fake_message.sid = "SM123"
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message
    monkeypatch.setattr(whatsapp_provider, "_client", fake_client)

    result = await whatsapp_provider.send(
        SMSMessage(
            to_phone="whatsapp:+15559876543",
            body="Hello",
            idempotency_key="key-1",
        )
    )

    assert result == "SM123"
    fake_client.messages.create.assert_called_once_with(
        to="whatsapp:+15559876543",
        from_="whatsapp:+14155238886",
        body="Hello",
    )
