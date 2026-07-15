from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.temporal import LeadNurtureWorkflowSignaler
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresWorkspaceRepository
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
from app.infrastructure.providers import (
    build_email_provider,
    build_sms_provider,
    build_temporal_workflow_signaler,
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
    message_repository: OutboundMessageRepository
    sms_provider: SMSProvider
    email_provider: EmailProvider
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler


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
        message_repository=PostgresOutboundMessageRepository(session),
        sms_provider=build_sms_provider(settings),
        email_provider=build_email_provider(settings),
        lead_nurture_workflow_signaler=await build_temporal_workflow_signaler(settings),
    )