import asyncio
from datetime import UTC, datetime

from app.application.use_cases.listing_source_crawls import enqueue_due_listing_source_crawls
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
    PostgresListingSearchScopeRepository,
    PostgresListingSourceRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)


async def run_once(*, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await enqueue_due_listing_source_crawls(
            source_repository=PostgresListingSourceRepository(session),
            scope_repository=PostgresListingSearchScopeRepository(session),
            crawl_run_repository=PostgresListingCrawlRunRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
            source_limit=resolved_settings.listing_source_crawl_scheduler_source_limit,
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        await run_once(settings=settings)
        await asyncio.sleep(settings.listing_source_crawl_scheduler_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())