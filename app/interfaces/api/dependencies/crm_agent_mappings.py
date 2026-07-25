from dataclasses import dataclass
from typing import Annotated, Protocol, cast

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMAgentDirectorySource
from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CRMAgentRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.providers import build_crm_client


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class CRMAgentMappingBundle:
    session: SessionCommitter
    crm_agent_repository: CRMAgentRepository
    mapping_repository: WorkspaceAgentCRMMappingRepository
    user_repository: UserRepository
    membership_repository: WorkspaceMembershipRepository
    lead_repository: LeadRepository
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    outbound_message_repository: OutboundMessageRepository
    event_bus: EventBus


@dataclass
class CRMAgentDirectorySyncBundle(CRMAgentMappingBundle):
    crm_agent_directory_source: CRMAgentDirectorySource


async def get_crm_agent_mapping_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CRMAgentMappingBundle:
    return CRMAgentMappingBundle(
        session=session,
        crm_agent_repository=PostgresCRMAgentRepository(session),
        mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        user_repository=PostgresUserRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        lead_repository=PostgresLeadRepository(session),
        workspace_agent_mapping_config_repository=PostgresWorkspaceAgentMappingConfigRepository(
            session
        ),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        outbound_message_repository=PostgresOutboundMessageRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )


async def get_crm_agent_directory_sync_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CRMAgentDirectorySyncBundle:
    return CRMAgentDirectorySyncBundle(
        session=session,
        crm_agent_repository=PostgresCRMAgentRepository(session),
        mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        user_repository=PostgresUserRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        lead_repository=PostgresLeadRepository(session),
        workspace_agent_mapping_config_repository=PostgresWorkspaceAgentMappingConfigRepository(
            session
        ),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        outbound_message_repository=PostgresOutboundMessageRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        crm_agent_directory_source=cast(CRMAgentDirectorySource, build_crm_client(settings)),
    )
