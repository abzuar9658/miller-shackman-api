from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    ExternalEventRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
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


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadResumeReadBundle:
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository


@dataclass
class LeadResumeActionBundle:
    session: SessionCommitter
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    lead_workflow_repository: LeadWorkflowRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    external_event_repository: ExternalEventRepository
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None
    rejected_draft_review_repository: RejectedDraftReviewRepository | None = None
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None


async def get_lead_resume_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadResumeReadBundle:
    return LeadResumeReadBundle(
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
    )


async def get_lead_resume_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadResumeActionBundle:
    return LeadResumeActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        paused_search_occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        rejected_draft_review_repository=PostgresRejectedDraftReviewRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
    )
