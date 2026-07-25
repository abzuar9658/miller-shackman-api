from typing import cast

import httpx
import pytest

from app.application.ports.messaging import EmailMessage
from app.infrastructure.messaging.mailgun import client as mailgun_client
from app.infrastructure.messaging.mailgun.client import MailgunEmailProvider


@pytest.fixture
def provider() -> MailgunEmailProvider:
    return MailgunEmailProvider(
        api_key="api-key",
        domain="example.test",
        from_email="sender@example.test",
    )


async def test_send_returns_message_id(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "<msg-123@example.test>"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    message = EmailMessage(
        to_email="lead@example.com",
        subject="Hello",
        body="Plain text",
        html_body="<p>Hello</p>",
        idempotency_key="key-1",
    )
    result = await provider.send(message)
    assert result == "msg-123@example.test"


async def test_send_returns_empty_string_when_id_missing(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": "Queued"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    message = EmailMessage(
        to_email="lead@example.com",
        subject="Hello",
        body="Plain text",
        idempotency_key="key-2",
    )
    result = await provider.send(message)
    assert result == ""


async def test_send_uses_message_from_email(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    captured_data: dict[str, str] | None = None

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal captured_data
        raw_data = kwargs.get("data") or (args[2] if len(args) > 2 else None)
        captured_data = cast(dict[str, str], raw_data)
        return httpx.Response(
            200,
            json={"id": "<msg-123@example.test>"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    message = EmailMessage(
        to_email="lead@example.com",
        subject="Hello",
        body="Plain text",
        from_email="override@example.test",
        idempotency_key="key-3",
    )
    await provider.send(message)
    assert isinstance(captured_data, dict)
    assert captured_data["from"] == "override@example.test"


async def test_send_sets_custom_message_id_header(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    captured_data: dict[str, str] | None = None

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal captured_data
        raw_data = kwargs.get("data") or (args[2] if len(args) > 2 else None)
        captured_data = cast(dict[str, str], raw_data)
        return httpx.Response(
            200,
            json={"id": "<msg-123@example.test>"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Hello",
            body="Plain text",
            idempotency_key="key-4",
            message_id="outbound-message.123@example.test",
        )
    )

    assert isinstance(captured_data, dict)
    assert captured_data["h:Message-Id"] == "<outbound-message.123@example.test>"


async def test_send_sets_reply_to_header(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    captured_data: dict[str, str] | None = None

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal captured_data
        raw_data = kwargs.get("data") or (args[2] if len(args) > 2 else None)
        captured_data = cast(dict[str, str], raw_data)
        return httpx.Response(
            200,
            json={"id": "<msg-123@example.test>"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Hello",
            body="Plain text",
            idempotency_key="key-5",
            reply_to="reply+token@example.test",
        )
    )

    assert isinstance(captured_data, dict)
    assert captured_data["h:Reply-To"] == "reply+token@example.test"


async def test_send_sets_threading_headers(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    captured_data: dict[str, str] | None = None

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        nonlocal captured_data
        raw_data = kwargs.get("data") or (args[2] if len(args) > 2 else None)
        captured_data = cast(dict[str, str], raw_data)
        return httpx.Response(
            200,
            json={"id": "<msg-123@example.test>"},
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    monkeypatch.setattr(provider._client, "post", _post)
    await provider.send(
        EmailMessage(
            to_email="lead@example.com",
            subject="Re: Hello",
            body="Plain text",
            idempotency_key="key-6",
            in_reply_to_message_id="inbound-message-123@example.test",
            reference_message_ids=(
                "thread-root@example.test",
                "inbound-message-123@example.test",
            ),
        )
    )

    assert isinstance(captured_data, dict)
    assert captured_data["h:In-Reply-To"] == "<inbound-message-123@example.test>"
    assert captured_data["h:References"] == (
        "<thread-root@example.test> <inbound-message-123@example.test>"
    )


async def test_send_logs_http_status_failures_with_mailgun_response(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    logged: dict[str, object] = {}

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            403,
            text="Forbidden: sandbox domain is not allowed to send to this recipient",
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    def _warning(event: str, **kwargs: object) -> None:
        logged["event"] = event
        logged["kwargs"] = kwargs

    monkeypatch.setattr(provider._client, "post", _post)
    monkeypatch.setattr(mailgun_client.logger, "warning", _warning)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.send(
            EmailMessage(
                to_email="lead@example.com",
                subject="Hello",
                body="Plain text",
                idempotency_key="key-7",
            )
        )

    assert "sandbox domain is not allowed to send to this recipient" in str(exc_info.value)
    assert logged["event"] == "mailgun_send_failed"
    assert logged["kwargs"] == {
        "status_code": 403,
        "request_url": "https://api.mailgun.net/v3/example.test/messages",
        "response_body_excerpt": (
            "Forbidden: sandbox domain is not allowed to send to this recipient"
        ),
        "to_address_redacted": "***@example.com",
        "from_address_redacted": "***@example.test",
        "subject_present": True,
        "has_html_body": False,
        "has_message_id": False,
        "has_reply_to": False,
        "has_in_reply_to": False,
        "has_references": False,
    }


async def test_send_logs_request_errors(
    monkeypatch: pytest.MonkeyPatch, provider: MailgunEmailProvider
) -> None:
    logged: dict[str, object] = {}

    async def _post(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError(
            "dns failed",
            request=httpx.Request("POST", "https://api.mailgun.net/v3/example.test/messages"),
        )

    def _warning(event: str, **kwargs: object) -> None:
        logged["event"] = event
        logged["kwargs"] = kwargs

    monkeypatch.setattr(provider._client, "post", _post)
    monkeypatch.setattr(mailgun_client.logger, "warning", _warning)

    with pytest.raises(httpx.ConnectError, match="dns failed"):
        await provider.send(
            EmailMessage(
                to_email="lead@example.com",
                subject="Hello",
                body="Plain text",
                idempotency_key="key-8",
            )
        )

    assert logged["event"] == "mailgun_send_request_error"
    assert logged["kwargs"] == {
        "request_url": "https://api.mailgun.net/v3/example.test/messages",
        "error": "dns failed",
        "to_address_redacted": "***@example.com",
        "from_address_redacted": "***@example.test",
        "subject_present": True,
        "has_html_body": False,
        "has_message_id": False,
        "has_reply_to": False,
        "has_in_reply_to": False,
        "has_references": False,
    }
