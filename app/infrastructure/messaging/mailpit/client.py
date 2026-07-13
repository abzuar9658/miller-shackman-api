import asyncio
import smtplib
from email.message import EmailMessage as SMTPEmailMessage
from email.utils import make_msgid

from app.application.ports.messaging import EmailMessage


class MailpitEmailProvider:
    provider_name = "mailpit"

    def __init__(self, *, smtp_host: str, smtp_port: int, from_email: str) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._from_email = from_email

    async def send(self, message: EmailMessage) -> str:
        return await asyncio.to_thread(self._send, message)

    def _send(self, message: EmailMessage) -> str:
        smtp_message = SMTPEmailMessage()
        smtp_message["From"] = message.from_email or self._from_email
        smtp_message["To"] = message.to_email
        smtp_message["Subject"] = message.subject
        smtp_message["Message-ID"] = make_msgid()
        smtp_message.set_content(message.body)
        if message.html_body is not None:
            smtp_message.add_alternative(message.html_body, subtype="html")

        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as client:
            client.send_message(smtp_message)

        return str(smtp_message["Message-ID"]).strip("<>")
