import json

import aio_pika

from app.application.ports.event_bus import OutboxEventPublisher
from app.domain.events import OutboxEvent


class RabbitMQOutboxEventPublisher(OutboxEventPublisher):
    def __init__(
        self, *, rabbitmq_url: str, exchange_name: str = "miller_schackman.events"
    ) -> None:
        self._rabbitmq_url = rabbitmq_url
        self._exchange_name = exchange_name

    async def publish(self, event: OutboxEvent) -> None:
        connection = await aio_pika.connect_robust(self._rabbitmq_url)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                self._exchange_name,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
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
