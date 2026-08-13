import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import aio_pika
import structlog
from pydantic import BaseModel

from app.application.use_cases.listing_source_crawls import execute_queued_listing_source_crawl
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.domain.events import DomainEventType
from app.domain.listing_sources.models import ListingCrawlStatus
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
    PostgresListingSearchScopeRepository,
    PostgresListingSnapshotRepository,
    PostgresListingSourceRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.providers import build_listing_search_client

logger = structlog.get_logger(__name__)


class _ListingSourceCrawlRequestedPayload(BaseModel):
    source_id: UUID
    crawl_run_id: UUID
    requested_at: str


class _ListingSourceCrawlRequestedMessage(BaseModel):
    workspace_id: UUID
    event_type: str
    payload: _ListingSourceCrawlRequestedPayload


async def run_once(body: bytes, *, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    message = _ListingSourceCrawlRequestedMessage.model_validate(json.loads(body.decode("utf-8")))
    if message.event_type != DomainEventType.LISTING_SOURCE_CRAWL_REQUESTED.value:
        return

    try:
        async with async_session_factory() as session:
            await enable_postgres_service_access(session)
            await execute_queued_listing_source_crawl(
                workspace_id=message.workspace_id,
                crawl_run_id=message.payload.crawl_run_id,
                source_repository=PostgresListingSourceRepository(session),
                scope_repository=PostgresListingSearchScopeRepository(session),
                crawl_run_repository=PostgresListingCrawlRunRepository(session),
                snapshot_repository=PostgresListingSnapshotRepository(session),
                listing_search_client=build_listing_search_client(resolved_settings),
                now=datetime.now(UTC),
                cache_ttl=timedelta(
                    minutes=resolved_settings.listing_context_enrichment_cache_ttl_minutes
                ),
                event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            )
            await session.commit()
    except Exception:
        # The message is dropped (requeue=False), so a run left PENDING/RUNNING
        # would count as "active" forever and block all future crawls of the
        # source. Mark it failed in a fresh session so the scheduler can retry.
        await _mark_crawl_run_failed(
            workspace_id=message.workspace_id,
            crawl_run_id=message.payload.crawl_run_id,
        )
        raise


async def _mark_crawl_run_failed(*, workspace_id: UUID, crawl_run_id: UUID) -> None:
    try:
        async with async_session_factory() as session:
            await enable_postgres_service_access(session)
            repository = PostgresListingCrawlRunRepository(session)
            crawl_run = await repository.get_by_id(workspace_id, crawl_run_id)
            if crawl_run is None or crawl_run.status not in (
                ListingCrawlStatus.PENDING,
                ListingCrawlStatus.RUNNING,
            ):
                return
            now = datetime.now(UTC)
            await repository.save(
                replace(
                    crawl_run,
                    status=ListingCrawlStatus.FAILED,
                    finished_at=now,
                    updated_at=now,
                    error_summary="crawl_worker_failed",
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "listing_source_crawl_mark_failed_error",
            workspace_id=str(workspace_id),
            crawl_run_id=str(crawl_run_id),
        )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.listing_source_crawl_worker_prefetch_count)
        exchange = await channel.declare_exchange(
            settings.crm_sync_exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        queue = await channel.declare_queue(settings.listing_source_crawl_queue_name, durable=True)
        await queue.bind(exchange, routing_key=DomainEventType.LISTING_SOURCE_CRAWL_REQUESTED.value)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                try:
                    async with message.process(requeue=False):
                        await run_once(message.body, settings=settings)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("listing_source_crawl_worker_message_failed")


if __name__ == "__main__":
    asyncio.run(main())
