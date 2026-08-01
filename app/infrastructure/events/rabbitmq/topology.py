import aio_pika

from app.domain.events import DomainEventType


async def ensure_crm_sync_topology(
    *,
    rabbitmq_url: str,
    exchange_name: str,
    queue_name: str,
) -> None:
    connection = await aio_pika.connect_robust(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await ensure_crm_sync_topology_on_channel(
            channel=channel,
            exchange_name=exchange_name,
            queue_name=queue_name,
        )


async def ensure_crm_sync_topology_on_channel(
    *,
    channel: aio_pika.abc.AbstractChannel,
    exchange_name: str,
    queue_name: str,
) -> tuple[aio_pika.abc.AbstractExchange, aio_pika.abc.AbstractQueue]:
    exchange = await channel.declare_exchange(
        exchange_name,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    queue = await channel.declare_queue(queue_name, durable=True)
    await queue.bind(exchange, routing_key=DomainEventType.CRM_SYNC_REQUESTED.value)
    return exchange, queue
