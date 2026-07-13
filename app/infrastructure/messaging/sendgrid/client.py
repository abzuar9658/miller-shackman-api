import asyncio

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.application.ports.messaging import EmailMessage


class SendGridEmailProvider:
    provider_name = "sendgrid"

    def __init__(self, api_key: str, from_email: str) -> None:
        self._client = SendGridAPIClient(api_key)
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
            response = self._client.send(mail)
            return str(response.headers.get("X-Message-Id", ""))

        return await asyncio.to_thread(_send)
