from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    ConversationRepository,
    ConversationSummaryRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    InboundMessageCRMCompletionRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.ports.temporal import LeadNurtureWorkflowSignaler
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
    PostgresConversationSummaryRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageCRMCompletionRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_llm_client,
    build_notification_provider,
    build_temporal_workflow_signaler,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class InboundServiceBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    external_event_repository: ExternalEventRepository
    conversation_repository: ConversationRepository
    inbound_message_repository: InboundMessageRepository
    conversation_summary_repository: ConversationSummaryRepository
    handoff_repository: HandoffRepository
    handoff_completion_repository: HandoffCompletionRepository
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    crm_client: CRMClient
    notification_provider: NotificationProvider
    llm_client: LLMClient
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler
    event_bus: EventBus
    default_openrouter_model: str


async def get_inbound_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundServiceBundle:
    return InboundServiceBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        conversation_repository=PostgresConversationRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        conversation_summary_repository=PostgresConversationSummaryRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        handoff_completion_repository=PostgresHandoffCompletionRepository(session),
        inbound_message_crm_completion_repository=PostgresInboundMessageCRMCompletionRepository(
            session
        ),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        crm_client=build_crm_client(settings),
        notification_provider=build_notification_provider(settings),
        llm_client=build_llm_client(settings),
        lead_nurture_workflow_signaler=await build_temporal_workflow_signaler(settings),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        default_openrouter_model=settings.openrouter_model,
    )
