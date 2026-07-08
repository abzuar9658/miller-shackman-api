from app.application.ports.messaging import EmailMessage, SMSMessage
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider


async def test_sink_sms_provider_returns_synthetic_id_and_captures_message() -> None:
    provider = SinkSMSProvider()
    message = SMSMessage(
        to_phone="+15551234567",
        body="Hello from the sink",
        idempotency_key="sink-sms-1",
    )

    result = await provider.send(message)

    assert result.startswith("sink-sms-")
    assert provider.messages == [message]


async def test_sink_email_provider_returns_synthetic_id_and_captures_message() -> None:
    provider = SinkEmailProvider()
    message = EmailMessage(
        to_email="lead@example.com",
        subject="Quick check-in",
        body="Hello from the sink",
        html_body="<p>Hello from the sink</p>",
        idempotency_key="sink-email-1",
    )

    result = await provider.send(message)

    assert result.startswith("sink-email-")
    assert provider.messages == [message]


async def test_sink_sms_provider_captures_multiple_messages_in_order() -> None:
    provider = SinkSMSProvider()
    first = SMSMessage(to_phone="+15551234567", body="One", idempotency_key="1")
    second = SMSMessage(to_phone="+15551234567", body="Two", idempotency_key="2")

    await provider.send(first)
    await provider.send(second)

    assert provider.messages == [first, second]
