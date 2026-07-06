import pytest

from app.application.ports.messaging import EmailMessage
from app.infrastructure.messaging.sendgrid.client import SendGridEmailProvider


class _FakeResponse:
    headers = {"X-Message-Id": "msg-123"}


@pytest.fixture
def provider() -> SendGridEmailProvider:
    return SendGridEmailProvider("api-key", "sender@example.com")


async def test_send_returns_message_id(
    monkeypatch: pytest.MonkeyPatch, provider: SendGridEmailProvider
) -> None:
    monkeypatch.setattr(provider._client, "send", lambda _mail: _FakeResponse())
    message = EmailMessage(
        to_email="lead@example.com",
        subject="Hello",
        body="Plain text",
        html_body="<p>Hello</p>",
        idempotency_key="key-1",
    )
    result = await provider.send(message)
    assert result == "msg-123"
