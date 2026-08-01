from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    CrmConversationEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminRepository,
)
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresUserRepository
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.lead_routing_review_repository import (
    PostgresLeadRoutingReviewRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_llm_client,
    build_notification_provider,
    build_temporal_workflow_starter,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadManualEnrollmentBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    campaign_admin_repository: CampaignAdminRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    lead_classification_artifact_repository: LeadClassificationArtifactRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    llm_client: LLMClient
    crm_conversation_event_repository: CrmConversationEventRepository
    paused_search_track_repository: PausedSearchTrackMappingRepository
    routing_review_repository: LeadRoutingReviewRepository
    default_openrouter_model: str
    handoff_repository: HandoffRepository
    handoff_completion_repository: HandoffCompletionRepository
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository
    crm_client: CRMClient
    notification_provider: NotificationProvider
    user_repository: UserRepository
    event_bus: EventBus


async def get_lead_manual_enrollment_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LeadManualEnrollmentBundle:
    lead_repository = PostgresLeadRepository(session)
    return LeadManualEnrollmentBundle(
        session=session,
        lead_repository=lead_repository,
        campaign_admin_repository=PostgresCampaignAdminRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        lead_classification_artifact_repository=PostgresLeadClassificationArtifactRepository(
            session
        ),
        paused_search_history_repository=lead_repository,
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        llm_client=build_llm_client(settings),
        crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        default_openrouter_model=settings.openrouter_model,
        handoff_repository=PostgresHandoffRepository(session),
        handoff_completion_repository=PostgresHandoffCompletionRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        crm_client=build_crm_client(settings),
        notification_provider=build_notification_provider(settings),
        user_repository=PostgresUserRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )
