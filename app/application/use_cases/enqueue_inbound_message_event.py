"""Persist an inbound message event for asynchronous processing.

Webhooks call this to record a PENDING external event and return immediately;
the inbound message worker later claims the event and runs the full
LLM/classification pipeline via process_inbound_message_event.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from app.application.ports.repositories import ExternalEventRepository
from app.application.use_cases.process_inbound_message_event import InboundMessageEvent
from app.domain.common.ids import LeadId
from app.domain.compliance.contactability import ContactChannel
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CRMProvider

_QUEUED_PAYLOAD_KEY = "queued_inbound_message"


class EnqueueInboundMessageEventStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class EnqueueInboundMessageEventResult:
    status: EnqueueInboundMessageEventStatus
    external_event_id: UUID | None = None
    lead_id: LeadId | None = None
    reasons: tuple[str, ...] = ()


async def enqueue_inbound_message_event(
    *,
    event: InboundMessageEvent,
    external_event_repository: ExternalEventRepository,
    now: datetime,
    lead_id: LeadId | None = None,
    external_event_id_factory: Callable[[], UUID] | None = None,
) -> EnqueueInboundMessageEventResult:
    existing = await external_event_repository.get_by_provider_event_id(
        event.workspace_id,
        event.provider,
        event.provider_event_id,
    )
    if existing is not None:
        return EnqueueInboundMessageEventResult(
            status=EnqueueInboundMessageEventStatus.DUPLICATE,
            external_event_id=existing.external_event_id,
            lead_id=existing.lead_id,
            reasons=("duplicate_event",),
        )

    saved = await external_event_repository.save(
        ExternalEvent(
            external_event_id=(external_event_id_factory or uuid4)(),
            workspace_id=event.workspace_id,
            provider=event.provider,
            event_type=event.event_type,
            provider_event_id=event.provider_event_id,
            crm_lead_id=event.crm_lead_id,
            lead_id=lead_id,
            received_at=event.received_at,
            processed_at=None,
            status=ExternalEventStatus.PENDING,
            payload_redacted={
                **dict(event.payload_redacted),
                _QUEUED_PAYLOAD_KEY: _queued_payload(event),
            },
            failure_reason=None,
            created_at=now,
            updated_at=now,
        ),
    )
    return EnqueueInboundMessageEventResult(
        status=EnqueueInboundMessageEventStatus.ACCEPTED,
        external_event_id=saved.external_event_id,
        lead_id=lead_id,
    )


def _queued_payload(event: InboundMessageEvent) -> dict[str, object]:
    return {
        "provider_message_id": event.provider_message_id,
        "channel": event.channel.value,
        "body": event.body,
        "crm_provider": event.crm_provider.value if event.crm_provider is not None else None,
        "email_subject": event.email_subject,
        "from_address_redacted": event.from_address_redacted,
        "to_address_redacted": event.to_address_redacted,
    }


def inbound_message_event_from_external_event(
    external_event: ExternalEvent,
) -> InboundMessageEvent | None:
    """Reconstruct the queued InboundMessageEvent; None when the payload is invalid."""
    raw = external_event.payload_redacted.get(_QUEUED_PAYLOAD_KEY)
    if not isinstance(raw, dict):
        return None
    data: dict[str, Any] = raw
    channel_value = data.get("channel")
    body = data.get("body")
    if not isinstance(channel_value, str) or not isinstance(body, str):
        return None
    try:
        channel = ContactChannel(channel_value)
    except ValueError:
        return None
    crm_provider_value = data.get("crm_provider")
    crm_provider: CRMProvider | None = None
    if isinstance(crm_provider_value, str) and crm_provider_value:
        try:
            crm_provider = CRMProvider(crm_provider_value)
        except ValueError:
            return None
    if external_event.crm_lead_id is None:
        return None
    payload_redacted = {
        key: value
        for key, value in external_event.payload_redacted.items()
        if key != _QUEUED_PAYLOAD_KEY
    }
    return InboundMessageEvent(
        workspace_id=external_event.workspace_id,
        provider=external_event.provider,
        provider_event_id=external_event.provider_event_id,
        provider_message_id=_optional_str(data.get("provider_message_id")) or "",
        crm_lead_id=external_event.crm_lead_id,
        channel=channel,
        body=body,
        received_at=external_event.received_at,
        crm_provider=crm_provider,
        event_type=external_event.event_type,
        email_subject=_optional_str(data.get("email_subject")),
        from_address_redacted=_optional_str(data.get("from_address_redacted")),
        to_address_redacted=_optional_str(data.get("to_address_redacted")),
        payload_redacted=payload_redacted,
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
