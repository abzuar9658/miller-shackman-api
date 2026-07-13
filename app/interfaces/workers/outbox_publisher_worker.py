import asyncio
from datetime import UTC, datetime

from app.application.use_cases.publish_outbox_events import publish_outbox_events
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.infrastructure.events.rabbitmq import RabbitMQOutboxEventPublisher
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
)


async def run_once() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await publish_outbox_events(
            outbox_repository=PostgresOutboxEventRepository(session),
            publisher=RabbitMQOutboxEventPublisher(rabbitmq_url=settings.rabbitmq_url),
            now=datetime.now(UTC),
        )
        await session.commit()


async def main() -> None:
    while True:
        await run_once()
        await asyncio.sleep(1)
