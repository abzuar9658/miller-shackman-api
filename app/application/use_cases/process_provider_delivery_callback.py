from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    ProviderDeliveryMessageRepository,
    ProviderMessageEventRepository,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    ProviderDeliveryStatus,
    ProviderMessageEvent,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType

_FAILURE_STATUSES = frozenset(
    {
        ProviderDeliveryStatus.FAILED,
        ProviderDeliveryStatus.UNDELIVERED,
        ProviderDeliveryStatus.BOUNCED,
        ProviderDeliveryStatus.DROPPED,
    },
)


class ProcessProviderDeliveryCallbackStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessProviderDeliveryCallbackReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    OUTBOUND_MESSAGE_NOT_FOUND = "outbound_message_not_found"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class ProviderDeliveryCallback:
    provider: str
    provider_event_id: str
    provider_message_id: str
    event_type: str
    status: ProviderDeliveryStatus
    occurred_at: datetime
    failure_reason: str | None = None
    payload_redacted: Mapping[str, object] = field(default_factory=_empty_payload)


@dataclass(frozen=True)
class ProcessProviderDeliveryCallbackResult:
    status: ProcessProviderDeliveryCallbackStatus
    provider_event_id: UUID | None = None
    message_id: UUID | None = None
    provider_delivery_status: ProviderDeliveryStatus | None = None
    reasons: tuple[ProcessProviderDeliveryCallbackReasonCode, ...] = ()


async def process_provider_delivery_callback(
    *,
    callback: ProviderDeliveryCallback,
    message_repository: ProviderDeliveryMessageRepository,
    provider_message_event_repository: ProviderMessageEventRepository,
    now: datetime,
    event_bus: EventBus | None = None,
    provider_message_event_id_factory: Callable[[], UUID] | None = None,
) -> ProcessProviderDeliveryCallbackResult:
    existing = await provider_message_event_repository.get_by_external_provider_event_id(
        callback.provider,
        callback.provider_event_id,
    )
    if existing is not None:
        return ProcessProviderDeliveryCallbackResult(
            status=ProcessProviderDeliveryCallbackStatus.DUPLICATE,
            provider_event_id=existing.provider_event_id,
            message_id=existing.outbound_message_id,
            provider_delivery_status=existing.status,
            reasons=(ProcessProviderDeliveryCallbackReasonCode.DUPLICATE_EVENT,),
        )

    message = await message_repository.get_by_provider_message_id_for_update(
        callback.provider,
        callback.provider_message_id,
    )
    if message is None:
        return ProcessProviderDeliveryCallbackResult(
            status=ProcessProviderDeliveryCallbackStatus.IGNORED,
            reasons=(ProcessProviderDeliveryCallbackReasonCode.OUTBOUND_MESSAGE_NOT_FOUND,),
        )

    saved_event = await provider_message_event_repository.save(
        ProviderMessageEvent(
            provider_event_id=(provider_message_event_id_factory or uuid4)(),
            workspace_id=message.workspace_id,
            provider=callback.provider,
            provider_message_id=callback.provider_message_id,
            outbound_message_id=message.message_id,
            external_provider_event_id=callback.provider_event_id,
            event_type=callback.event_type,
            status=callback.status,
            received_at=callback.occurred_at,
            payload_redacted=dict(callback.payload_redacted),
            created_at=now,
        ),
    )
    updated_message = _reconcile_message(message=message, callback=callback, now=now)
    if updated_message != message:
        updated_message = await message_repository.save(updated_message)
        await _publish_delivery_event(
            event_bus=event_bus,
            callback=callback,
            message=updated_message,
            now=now,
        )

    return ProcessProviderDeliveryCallbackResult(
        status=ProcessProviderDeliveryCallbackStatus.PROCESSED,
        provider_event_id=saved_event.provider_event_id,
        message_id=updated_message.message_id,
        provider_delivery_status=updated_message.provider_delivery_status,
    )


def _reconcile_message(
    *,
    message: OutboundMessage,
    callback: ProviderDeliveryCallback,
    now: datetime,
) -> OutboundMessage:
    current_status = message.provider_delivery_status
    current_status_updated_at = message.provider_status_updated_at

    if current_status == ProviderDeliveryStatus.DELIVERED:
        return message

    if callback.status == ProviderDeliveryStatus.DELIVERED:
        delivered_at = (
            min(message.delivered_at, callback.occurred_at)
            if message.delivered_at is not None
            else callback.occurred_at
        )
        return replace(
            message,
            provider_delivery_status=ProviderDeliveryStatus.DELIVERED,
            provider_status_updated_at=callback.occurred_at,
            delivered_at=delivered_at,
            failure_reason=None,
            updated_at=now,
        )

    if current_status in _FAILURE_STATUSES and callback.status not in _FAILURE_STATUSES:
        return message

    if callback.status in _FAILURE_STATUSES:
        if current_status in _FAILURE_STATUSES and _is_older(
            callback.occurred_at, current_status_updated_at
        ):
            return message
        return replace(
            message,
            provider_delivery_status=callback.status,
            provider_status_updated_at=callback.occurred_at,
            failure_reason=callback.failure_reason,
            updated_at=now,
        )

    if _is_older(callback.occurred_at, current_status_updated_at):
        return message

    return replace(
        message,
        provider_delivery_status=callback.status,
        provider_status_updated_at=callback.occurred_at,
        failure_reason=None,
        updated_at=now,
    )


def _is_older(incoming_at: datetime, current_at: datetime | None) -> bool:
    return current_at is not None and incoming_at < current_at


async def _publish_delivery_event(
    *,
    event_bus: EventBus | None,
    callback: ProviderDeliveryCallback,
    message: OutboundMessage,
    now: datetime,
) -> None:
    if event_bus is None:
        return
    event_type = DomainEventType.MESSAGE_DELIVERED
    if callback.status in _FAILURE_STATUSES:
        event_type = DomainEventType.MESSAGE_DELIVERY_FAILED
    await event_bus.publish(
        DomainEvent(
            workspace_id=message.workspace_id,
            aggregate_type=AggregateType.MESSAGE,
            aggregate_id=message.message_id,
            event_type=event_type,
            payload={
                "message_id": str(message.message_id),
                "lead_id": str(message.lead_id),
                "campaign_id": str(message.campaign_id),
                "provider": callback.provider,
                "provider_event_id": callback.provider_event_id,
                "provider_message_id": callback.provider_message_id,
                "provider_delivery_status": callback.status.value,
                "provider_event_type": callback.event_type,
                "failure_reason": callback.failure_reason,
                "occurred_at": callback.occurred_at.isoformat(),
                "processed_at": now.isoformat(),
            },
        ),
    )
