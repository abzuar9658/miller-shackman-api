from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_read import (
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadUserRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresUserRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)


@dataclass
class LeadReadBundle:
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    workflow_transition_repository: LeadReadWorkflowTransitionRepository
    inbound_message_repository: LeadReadInboundMessageRepository
    outbound_message_repository: LeadReadOutboundMessageRepository
    handoff_repository: LeadReadHandoffRepository
    user_repository: LeadReadUserRepository


async def get_lead_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadReadBundle:
    return LeadReadBundle(
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        outbound_message_repository=PostgresOutboundMessageRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        user_repository=PostgresUserRepository(session),
    )
