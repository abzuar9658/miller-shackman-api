from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    ConversationRepository,
    ConversationSummaryRepository,
    ExternalEventRepository,
    HandoffRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.providers import build_llm_client


@dataclass
class InboundServiceBundle:
    lead_repository: LeadRepository
    external_event_repository: ExternalEventRepository
    conversation_repository: ConversationRepository
    inbound_message_repository: InboundMessageRepository
    conversation_summary_repository: ConversationSummaryRepository
    handoff_repository: HandoffRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    llm_client: LLMClient


async def get_inbound_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundServiceBundle:
    return InboundServiceBundle(
        lead_repository=PostgresLeadRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        conversation_repository=PostgresConversationRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        conversation_summary_repository=PostgresConversationSummaryRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        llm_client=build_llm_client(settings),
    )
