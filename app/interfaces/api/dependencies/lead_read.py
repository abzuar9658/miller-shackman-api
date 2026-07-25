from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_activity import LeadActivityRepository
from app.application.ports.lead_read import (
    LeadReadCrmConversationEventRepository,
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadUserRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceContactPolicyRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresUserRepository
from app.infrastructure.persistence.postgres.lead_activity_repository import (
    PostgresLeadActivityRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.rejected_draft_review_repository import (
    PostgresRejectedDraftReviewRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)


@dataclass
class LeadReadBundle:
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    workflow_transition_repository: LeadReadWorkflowTransitionRepository
    activity_repository: LeadActivityRepository
    rejected_draft_review_repository: RejectedDraftReviewRepository
    inbound_message_repository: LeadReadInboundMessageRepository
    outbound_message_repository: LeadReadOutboundMessageRepository
    crm_conversation_event_repository: LeadReadCrmConversationEventRepository
    handoff_repository: LeadReadHandoffRepository
    user_repository: LeadReadUserRepository
    crm_agent_repository: CRMAgentRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository


async def get_lead_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadReadBundle:
    return LeadReadBundle(
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        activity_repository=PostgresLeadActivityRepository(session),
        rejected_draft_review_repository=PostgresRejectedDraftReviewRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        outbound_message_repository=PostgresOutboundMessageRepository(session),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        user_repository=PostgresUserRepository(session),
        crm_agent_repository=PostgresCRMAgentRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
    )
