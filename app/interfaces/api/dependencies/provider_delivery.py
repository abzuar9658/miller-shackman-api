from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    LeadWorkflowRepository,
    OutboundSendReconciliationRepository,
    PausedSearchOccurrenceRepository,
    ProviderDeliveryMessageRepository,
    ProviderMessageEventRepository,
    TemporalSignalOutboxRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_reconciliation_repository import (
    PostgresOutboundSendReconciliationRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.provider_message_event_repository import (
    PostgresProviderMessageEventRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
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
    reconciliation_repository: OutboundSendReconciliationRepository | None = None
    occurrence_repository: PausedSearchOccurrenceRepository | None = None
    lead_workflow_repository: LeadWorkflowRepository | None = None
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None


async def get_provider_delivery_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProviderDeliveryServiceBundle:
    return ProviderDeliveryServiceBundle(
        session=session,
        message_repository=PostgresOutboundMessageRepository(session),
        provider_message_event_repository=PostgresProviderMessageEventRepository(session),
        reconciliation_repository=PostgresOutboundSendReconciliationRepository(session),
        occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )
