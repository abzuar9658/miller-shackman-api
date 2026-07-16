from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.listing_sources import ListingSourceRepository
from app.core.database import get_session
from app.infrastructure.persistence.postgres.listing_source_repository import (
    PostgresListingSourceRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class ListingSourceBundle:
    session: SessionCommitter
    source_repository: ListingSourceRepository


async def get_listing_source_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ListingSourceBundle:
    return ListingSourceBundle(
        session=session,
        source_repository=PostgresListingSourceRepository(session),
    )