import smtplib
from email.message import EmailMessage as SMTPEmailMessage

import pytest

from app.application.ports.messaging import EmailMessage
from app.infrastructure.messaging.mailpit.client import MailpitEmailProvider


class _FakeSMTP:
    sent_messages: list[SMTPEmailMessage] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def send_message(self, message: SMTPEmailMessage) -> None:
        self.sent_messages.append(message)


@pytest.fixture(autouse=True)
def reset_fake_smtp() -> None:
    _FakeSMTP.sent_messages = []


async def test_send_delivers_message_via_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    provider = MailpitEmailProvider(
        smtp_host="localhost",
        smtp_port=51025,
        from_email="noreply@example.test",
    )

    result = await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Hello from Mailpit",
            body="Plain text body",
            html_body="<p>Plain text body</p>",
            idempotency_key="mailpit-1",
        )
    )

    assert result
    assert _FakeSMTP.sent_messages
    sent_message = _FakeSMTP.sent_messages[0]
    assert sent_message["From"] == "noreply@example.test"
    assert sent_message["To"] == "lead@example.com"
    assert sent_message["Subject"] == "Hello from Mailpit"
    assert sent_message["Message-ID"] == f"<{result}>"
    assert sent_message.get_body(preferencelist=("plain",)) is not None
    assert sent_message.get_body(preferencelist=("html",)) is not None
