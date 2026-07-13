from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    ProviderDeliveryMessageRepository,
    ProviderMessageEventRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.provider_message_event_repository import (
    PostgresProviderMessageEventRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class ProviderDeliveryServiceBundle:
    session: SessionCommitter
    message_repository: ProviderDeliveryMessageRepository
    provider_message_event_repository: ProviderMessageEventRepository
    event_bus: EventBus


async def get_provider_delivery_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProviderDeliveryServiceBundle:
    return ProviderDeliveryServiceBundle(
        session=session,
        message_repository=PostgresOutboundMessageRepository(session),
        provider_message_event_repository=PostgresProviderMessageEventRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )
