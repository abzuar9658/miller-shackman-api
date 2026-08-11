from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.outbound_provider_failure_repository import (
    PostgresOutboundProviderFailureRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_reconciliation_repository import (
    PostgresOutboundSendReconciliationRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_request_repository import (
    PostgresOutboundSendRequestRepository,
)


@dataclass
class OutboundSendExceptionReadBundle:
    request_repository: OutboundSendRequestRepository
    provider_failure_repository: OutboundProviderFailureRepository
    reconciliation_repository: OutboundSendReconciliationRepository


async def get_outbound_send_exception_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OutboundSendExceptionReadBundle:
    return OutboundSendExceptionReadBundle(
        request_repository=PostgresOutboundSendRequestRepository(session),
        provider_failure_repository=PostgresOutboundProviderFailureRepository(session),
        reconciliation_repository=PostgresOutboundSendReconciliationRepository(session),
    )