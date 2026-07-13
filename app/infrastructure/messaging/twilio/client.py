import asyncio

from twilio.rest import Client

from app.application.ports.messaging import SMSMessage


class TwilioSMSProvider:
    provider_name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_phone: str) -> None:
        self._client = Client(account_sid, auth_token)
        self._from_phone = from_phone

    async def send(self, message: SMSMessage) -> str:
        def _send() -> str:
            sent = self._client.messages.create(
                to=message.to_phone,
                from_=self._from_phone,
                body=message.body,
            )
            return str(sent.sid)

        return await asyncio.to_thread(_send)
