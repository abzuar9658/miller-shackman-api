import asyncio
from datetime import UTC, datetime

import structlog

from app.application.use_cases.publish_outbox_events import publish_outbox_events
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.infrastructure.events.rabbitmq import RabbitMQOutboxEventPublisher
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
)

logger = structlog.get_logger(__name__)


async def run_once() -> None:
    settings = get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        result = await publish_outbox_events(
            outbox_repository=PostgresOutboxEventRepository(session),
            publisher=RabbitMQOutboxEventPublisher(
                rabbitmq_url=settings.rabbitmq_url,
                exchange_name=settings.crm_sync_exchange_name,
                crm_sync_queue_name=settings.crm_sync_queue_name,
            ),
            now=datetime.now(UTC),
        )
        if result.claimed_count > 0 or result.failed_count > 0:
            logger.info(
                "outbox_publish_cycle",
                claimed_count=result.claimed_count,
                published_count=result.published_count,
                failed_count=result.failed_count,
            )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox_publisher_run_failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
