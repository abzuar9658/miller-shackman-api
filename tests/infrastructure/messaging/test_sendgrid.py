from typing import Any, cast

import pytest

from app.application.ports.messaging import EmailMessage
from app.infrastructure.messaging.sendgrid.client import SendGridEmailProvider


class _FakeResponse:
    headers = {"X-Message-Id": "msg-123"}


@pytest.fixture
def provider() -> SendGridEmailProvider:
    return SendGridEmailProvider("api-key", "sender@example.com")


def test_timeout_is_applied_to_underlying_client() -> None:
    provider = SendGridEmailProvider("api-key", "sender@example.com", timeout_seconds=9.5)

    assert provider._client.client.timeout == 9.5


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


async def test_send_sets_custom_message_id_header(
    monkeypatch: pytest.MonkeyPatch, provider: SendGridEmailProvider
) -> None:
    captured_mail: object | None = None

    def _send(mail: object) -> _FakeResponse:
        nonlocal captured_mail
        captured_mail = mail
        return _FakeResponse()

    monkeypatch.setattr(provider._client, "send", _send)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Hello",
            body="Plain text",
            idempotency_key="key-2",
            message_id="outbound-message.123@example.test",
        )
    )

    assert captured_mail is not None
    serialized = cast(dict[str, Any], cast(Any, captured_mail).get())
    assert serialized["headers"]["Message-ID"] == "<outbound-message.123@example.test>"


async def test_send_sets_reply_to(
    monkeypatch: pytest.MonkeyPatch, provider: SendGridEmailProvider
) -> None:
    captured_mail: object | None = None

    def _send(mail: object) -> _FakeResponse:
        nonlocal captured_mail
        captured_mail = mail
        return _FakeResponse()

    monkeypatch.setattr(provider._client, "send", _send)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Hello",
            body="Plain text",
            idempotency_key="key-3",
            reply_to="reply+token@example.test",
        )
    )

    assert captured_mail is not None
    serialized = cast(dict[str, Any], cast(Any, captured_mail).get())
    assert serialized["reply_to"]["email"] == "reply+token@example.test"


async def test_send_sets_threading_headers(
    monkeypatch: pytest.MonkeyPatch, provider: SendGridEmailProvider
) -> None:
    captured_mail: object | None = None

    def _send(mail: object) -> _FakeResponse:
        nonlocal captured_mail
        captured_mail = mail
        return _FakeResponse()

    monkeypatch.setattr(provider._client, "send", _send)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Re: Hello",
            body="Plain text",
            idempotency_key="key-4",
            in_reply_to_message_id="inbound-message-123@example.test",
            reference_message_ids=(
                "thread-root@example.test",
                "inbound-message-123@example.test",
            ),
        )
    )

    assert captured_mail is not None
    serialized = cast(dict[str, Any], cast(Any, captured_mail).get())
    assert serialized["headers"]["In-Reply-To"] == "<inbound-message-123@example.test>"
    assert serialized["headers"]["References"] == (
        "<thread-root@example.test> <inbound-message-123@example.test>"
    )
