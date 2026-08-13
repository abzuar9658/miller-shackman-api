import asyncio

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Header, Mail

from app.application.ports.messaging import (
    EmailMessage,
    ProviderFailureKind,
    ProviderSendFailure,
)
from app.infrastructure.messaging.provider_errors import classify_http_status


class SendGridEmailProvider:
    provider_name = "sendgrid"

    def __init__(self, api_key: str, from_email: str, timeout_seconds: float = 15.0) -> None:
        self._client = SendGridAPIClient(api_key)
        # SendGridAPIClient does not expose a timeout kwarg; the underlying
        # python_http_client Client honors a `timeout` attribute per request.
        self._client.client.timeout = timeout_seconds
        self._from_email = from_email

    async def send(self, message: EmailMessage) -> str:
        def _send() -> str:
            mail = Mail(
                from_email=message.from_email or self._from_email,
                to_emails=message.to_email,
                subject=message.subject,
                plain_text_content=message.body,
                html_content=message.html_body,
            )
            if message.message_id is not None:
                mail.add_header(Header("Message-ID", _format_message_id_header(message.message_id)))
            if message.reply_to is not None:
                mail.reply_to = message.reply_to
            if message.in_reply_to_message_id is not None:
                mail.add_header(
                    Header(
                        "In-Reply-To",
                        _format_message_id_header(message.in_reply_to_message_id),
                    )
                )
            references = _format_references_header(message.reference_message_ids)
            if references is not None:
                mail.add_header(Header("References", references))
            response = self._client.send(mail)
            return str(response.headers.get("X-Message-Id", ""))

        try:
            return await asyncio.to_thread(_send)
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            raise ProviderSendFailure(
                classify_http_status(status_code)
                if isinstance(status_code, int)
                else ProviderFailureKind.UNCERTAIN,
                str(exc),
            ) from exc


def _format_message_id_header(message_id: str) -> str:
    normalized = message_id.strip().strip("<>")
    return f"<{normalized}>"


def _format_references_header(reference_message_ids: tuple[str, ...]) -> str | None:
    formatted = [
        _format_message_id_header(message_id)
        for message_id in reference_message_ids
        if message_id.strip().strip("<>")
    ]
    return " ".join(formatted) if formatted else None
