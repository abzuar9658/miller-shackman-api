import json

import aio_pika

from app.application.ports.event_bus import OutboxEventPublisher
from app.domain.events import OutboxEvent
from app.infrastructure.events.rabbitmq.topology import ensure_crm_sync_topology_on_channel


class RabbitMQOutboxEventPublisher(OutboxEventPublisher):
    def __init__(
        self,
        *,
        rabbitmq_url: str,
        exchange_name: str = "miller_schackman.events",
        crm_sync_queue_name: str = "miller_schackman.crm_sync",
    ) -> None:
        self._rabbitmq_url = rabbitmq_url
        self._exchange_name = exchange_name
        self._crm_sync_queue_name = crm_sync_queue_name

    async def publish(self, event: OutboxEvent) -> None:
        connection = await aio_pika.connect_robust(self._rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            exchange, _ = await ensure_crm_sync_topology_on_channel(
                channel=channel,
                exchange_name=self._exchange_name,
                queue_name=self._crm_sync_queue_name,
            )
            message = aio_pika.Message(
                body=json.dumps(_message_body(event), sort_keys=True).encode("utf-8"),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=str(event.outbox_event_id),
                type=event.event_type.value,
                headers={
                    "workspace_id": str(event.workspace_id),
                    "aggregate_type": event.aggregate_type.value,
                    "aggregate_id": str(event.aggregate_id),
                },
            )
            await exchange.publish(message, routing_key=event.event_type.value)


def _message_body(event: OutboxEvent) -> dict[str, object]:
    return {
        "outbox_event_id": str(event.outbox_event_id),
        "workspace_id": str(event.workspace_id),
        "aggregate_type": event.aggregate_type.value,
        "aggregate_id": str(event.aggregate_id),
        "event_type": event.event_type.value,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
        "attempt_count": event.attempt_count,
    }
