import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import aio_pika
from pydantic import BaseModel

from app.application.use_cases.crm_sync import execute_queued_follow_up_boss_crm_sync
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.domain.events import DomainEventType
from app.infrastructure.persistence.postgres.crm_sync_repository import PostgresCRMSyncJobRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.providers import build_crm_lead_snapshot_source


class _SyncRequestedMessage(BaseModel):
    workspace_id: UUID
    event_type: str
    payload: dict[str, object]


async def run_once(body: bytes, *, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    message = _SyncRequestedMessage.model_validate(json.loads(body.decode("utf-8")))
    if message.event_type != DomainEventType.CRM_SYNC_REQUESTED.value:
        return
    sync_job_id_value = message.payload.get("sync_job_id")
    if not isinstance(sync_job_id_value, str):
        raise ValueError("crm_sync.requested payload missing sync_job_id")

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await execute_queued_follow_up_boss_crm_sync(
            workspace_id=message.workspace_id,
            sync_job_id=UUID(sync_job_id_value),
            lead_snapshot_source=build_crm_lead_snapshot_source(resolved_settings),
            lead_repository=PostgresLeadRepository(session),
            crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
            now=datetime.now(UTC),
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.crm_sync_worker_prefetch_count)
        exchange = await channel.declare_exchange(
            settings.crm_sync_exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        queue = await channel.declare_queue(settings.crm_sync_queue_name, durable=True)
        await queue.bind(exchange, routing_key=DomainEventType.CRM_SYNC_REQUESTED.value)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=False):
                    await run_once(message.body, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
