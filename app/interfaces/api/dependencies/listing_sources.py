from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.listing_sources import (
    ListingCrawlRunRepository,
    ListingSearchScopeRepository,
    ListingSourceRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingCrawlRunRepository,
    PostgresListingSearchScopeRepository,
    PostgresListingSourceRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class ListingSourceBundle:
    session: SessionCommitter
    source_repository: ListingSourceRepository
    scope_repository: ListingSearchScopeRepository
    crawl_run_repository: ListingCrawlRunRepository
    event_bus: EventBus


async def get_listing_source_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ListingSourceBundle:
    return ListingSourceBundle(
        session=session,
        source_repository=PostgresListingSourceRepository(session),
        scope_repository=PostgresListingSearchScopeRepository(session),
        crawl_run_repository=PostgresListingCrawlRunRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )
