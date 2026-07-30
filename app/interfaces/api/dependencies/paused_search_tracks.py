from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    PausedSearchTrackAdminAuditLogRepository,
    PausedSearchTrackAdminRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminAuditLogRepository,
    PostgresPausedSearchTrackAdminRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class PausedSearchTrackServiceBundle:
    session: SessionCommitter
    track_repository: PausedSearchTrackAdminRepository
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository
    event_bus: EventBus


@dataclass
class PausedSearchTrackReadBundle:
    track_repository: PausedSearchTrackAdminRepository


async def get_paused_search_track_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PausedSearchTrackServiceBundle:
    return PausedSearchTrackServiceBundle(
        session=session,
        track_repository=PostgresPausedSearchTrackAdminRepository(session),
        audit_log_repository=PostgresPausedSearchTrackAdminAuditLogRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )


async def get_paused_search_track_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PausedSearchTrackReadBundle:
    return PausedSearchTrackReadBundle(
        track_repository=PostgresPausedSearchTrackAdminRepository(session),
    )