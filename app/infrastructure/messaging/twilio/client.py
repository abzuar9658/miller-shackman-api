import asyncio

from twilio.rest import Client

from app.application.ports.messaging import SMSMessage

_WHATSAPP_PREFIX = "whatsapp:"


def _is_whatsapp_address(value: str) -> bool:
    return value.strip().lower().startswith(_WHATSAPP_PREFIX)


def _normalize_whatsapp_recipient(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.lower().startswith(_WHATSAPP_PREFIX):
        return normalized
    return f"{_WHATSAPP_PREFIX}{normalized}"


class TwilioSMSProvider:
    provider_name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_phone: str) -> None:
        self._client = Client(account_sid, auth_token)
        self._from_phone = from_phone.strip()

    async def send(self, message: SMSMessage) -> str:
        def _send() -> str:
            to_phone = (
                _normalize_whatsapp_recipient(message.to_phone)
                if _is_whatsapp_address(self._from_phone)
                else message.to_phone
            )
            sent = self._client.messages.create(
                to=to_phone,
                from_=self._from_phone,
                body=message.body,
            )
            return str(sent.sid)

        return await asyncio.to_thread(_send)
