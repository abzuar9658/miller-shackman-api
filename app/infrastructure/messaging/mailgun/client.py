import httpx
import structlog

from app.application.ports.messaging import EmailMessage

logger = structlog.get_logger(__name__)
_MAILGUN_RESPONSE_EXCERPT_LIMIT = 500


class MailgunEmailProvider:
    provider_name = "mailgun"

    def __init__(self, *, api_key: str, domain: str, from_email: str) -> None:
        self._api_key = api_key
        self._domain = domain
        self._from_email = from_email
        self._client = httpx.AsyncClient(
            auth=("api", api_key),
            base_url=f"https://api.mailgun.net/v3/{domain}",
            timeout=30.0,
        )

    async def send(self, message: EmailMessage) -> str:
        from_email = message.from_email or self._from_email
        data = {
            "from": from_email,
            "to": message.to_email,
            "subject": message.subject,
            "text": message.body,
        }
        if message.message_id is not None:
            data["h:Message-Id"] = _format_message_id_header(message.message_id)
        if message.reply_to is not None:
            data["h:Reply-To"] = message.reply_to
        if message.in_reply_to_message_id is not None:
            data["h:In-Reply-To"] = _format_message_id_header(message.in_reply_to_message_id)
        references = _format_references_header(message.reference_message_ids)
        if references is not None:
            data["h:References"] = references
        if message.html_body is not None:
            data["html"] = message.html_body

        try:
            response = await self._client.post("/messages", data=data)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_body_excerpt = _response_body_excerpt(exc.response)
            logger.warning(
                "mailgun_send_failed",
                status_code=exc.response.status_code,
                request_url=str(exc.request.url),
                response_body_excerpt=response_body_excerpt,
                to_address_redacted=_redact_email_address(message.to_email),
                from_address_redacted=_redact_email_address(from_email),
                subject_present=bool(message.subject.strip()),
                has_html_body=message.html_body is not None,
                has_message_id=message.message_id is not None,
                has_reply_to=message.reply_to is not None,
                has_in_reply_to=message.in_reply_to_message_id is not None,
                has_references=bool(message.reference_message_ids),
            )
            raise httpx.HTTPStatusError(
                _build_http_error_message(exc, response_body_excerpt),
                request=exc.request,
                response=exc.response,
            ) from exc
        except httpx.RequestError as exc:
            logger.warning(
                "mailgun_send_request_error",
                request_url=str(exc.request.url),
                error=str(exc),
                to_address_redacted=_redact_email_address(message.to_email),
                from_address_redacted=_redact_email_address(from_email),
                subject_present=bool(message.subject.strip()),
                has_html_body=message.html_body is not None,
                has_message_id=message.message_id is not None,
                has_reply_to=message.reply_to is not None,
                has_in_reply_to=message.in_reply_to_message_id is not None,
                has_references=bool(message.reference_message_ids),
            )
            raise

        payload = response.json()
        provider_message_id = str(payload.get("id", "")).strip("<>")
        if not provider_message_id:
            logger.warning(
                "mailgun_send_missing_id",
                to_email=message.to_email,
                subject=message.subject,
            )
        return provider_message_id


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


def _redact_email_address(email_address: str | None) -> str | None:
    if email_address is None:
        return None
    normalized = email_address.strip().lower()
    if not normalized or "@" not in normalized:
        return "***"
    _, domain = normalized.split("@", 1)
    return f"***@{domain}"


def _response_body_excerpt(response: httpx.Response) -> str | None:
    body = response.text.strip()
    if not body:
        return None
    compact = " ".join(body.split())
    if len(compact) <= _MAILGUN_RESPONSE_EXCERPT_LIMIT:
        return compact
    return compact[: _MAILGUN_RESPONSE_EXCERPT_LIMIT - 1] + "…"


def _build_http_error_message(exc: httpx.HTTPStatusError, response_body_excerpt: str | None) -> str:
    message = (
        f"Mailgun send failed with status {exc.response.status_code} "
        f"for {exc.request.method} {exc.request.url}"
    )
    if response_body_excerpt:
        return f"{message}: {response_body_excerpt}"
    return message
