from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageCRMCompletionRepository,
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.rejected_draft_review_repository import (
    PostgresRejectedDraftReviewRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
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
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_email_provider,
    build_sms_provider,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadDraftReviewActionBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    review_repository: RejectedDraftReviewRepository
    workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    campaign_execution_repository: CampaignExecutionRepository
    workspace_repository: WorkspaceRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    message_repository: OutboundMessageRepository
    external_event_repository: ExternalEventRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    crm_client: CRMClient
    crm_agent_repository: CRMAgentRepository
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository
    workspace_membership_repository: WorkspaceMembershipRepository
    user_repository: UserRepository
    outbound_message_crm_completion_repository: OutboundMessageCRMCompletionRepository
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository
    sms_provider: SMSProvider
    email_provider: EmailProvider


async def get_lead_draft_review_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LeadDraftReviewActionBundle:
    return LeadDraftReviewActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        review_repository=PostgresRejectedDraftReviewRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        message_repository=PostgresOutboundMessageRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        crm_client=build_crm_client(settings),
        crm_agent_repository=PostgresCRMAgentRepository(session),
        workspace_agent_crm_mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        workspace_agent_mapping_config_repository=PostgresWorkspaceAgentMappingConfigRepository(
            session,
        ),
        workspace_membership_repository=PostgresWorkspaceMembershipRepository(session),
        user_repository=PostgresUserRepository(session),
        outbound_message_crm_completion_repository=(
            PostgresOutboundMessageCRMCompletionRepository(session)
        ),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        sms_provider=build_sms_provider(settings),
        email_provider=build_email_provider(settings),
    )
