from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CrmConversationEventRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.lead_routing_review_repository import (
    PostgresLeadRoutingReviewRepository,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
    PostgresPausedSearchTrackAssignmentRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.providers import build_llm_client, build_temporal_workflow_starter


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadClassificationActionBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    artifact_repository: LeadClassificationArtifactRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    lead_workflow_repository: LeadWorkflowRepository
    paused_search_track_repository: PausedSearchTrackRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    llm_client: LLMClient
    default_openrouter_model: str
    routing_review_repository: LeadRoutingReviewRepository | None = None
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None
    workflow_transition_repository: WorkflowTransitionRepository | None = None
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None
    temporal_workflow_starter: TemporalWorkflowStarter | None = None


async def get_lead_classification_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LeadClassificationActionBundle:
    return LeadClassificationActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        paused_search_history_repository=PostgresLeadRepository(session),
        artifact_repository=PostgresLeadClassificationArtifactRepository(session),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        llm_client=build_llm_client(settings),
        default_openrouter_model=settings.openrouter_model,
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        paused_search_occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
    )
