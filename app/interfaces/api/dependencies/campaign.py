from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CampaignAdminAuditLogRepository,
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    CrmConversationEventRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_admin_repository import (
    PostgresCampaignAdminAuditLogRepository,
    PostgresCampaignAdminRepository,
)
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
)
from app.infrastructure.persistence.postgres.dormant_candidate_selector import (
    PostgresDormantCandidateSelector,
)
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
    PostgresPausedSearchTrackAssignmentRepository,
)
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
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
class CampaignServiceBundle:
    session: SessionCommitter
    campaign_admin_repository: CampaignAdminRepository
    campaign_admin_audit_log_repository: CampaignAdminAuditLogRepository
    campaign_execution_repository: CampaignExecutionRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    workspace_operational_control_repository: WorkspaceOperationalControlRepository
    dormant_candidate_selector: DormantCandidateSelector
    preflight_digest_repository: PreflightDigestRepository
    lead_repository: LeadRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    artifact_repository: LeadClassificationArtifactRepository
    crm_conversation_event_repository: CrmConversationEventRepository
    workspace_llm_config_repository: WorkspaceLLMConfigRepository
    lead_workflow_repository: LeadWorkflowRepository
    paused_search_track_repository: PausedSearchTrackRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    crm_client: CRMClient
    crm_agent_repository: CRMAgentRepository
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository
    llm_client: LLMClient
    default_openrouter_model: str
    notification_provider: NotificationProvider
    event_bus: EventBus
    routing_review_repository: LeadRoutingReviewRepository | None = None
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None
    rollback: Callable[[], Awaitable[None]] | None = None


@dataclass
class CampaignReadBundle:
    campaign_admin_repository: CampaignAdminRepository


async def get_campaign_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CampaignReadBundle:
    return CampaignReadBundle(
        campaign_admin_repository=PostgresCampaignAdminRepository(session),
    )


async def get_campaign_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CampaignServiceBundle:
    return CampaignServiceBundle(
        session=session,
        campaign_admin_repository=PostgresCampaignAdminRepository(session),
        campaign_admin_audit_log_repository=PostgresCampaignAdminAuditLogRepository(session),
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        dormant_candidate_selector=PostgresDormantCandidateSelector(session),
        preflight_digest_repository=PostgresPreflightDigestRepository(session),
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
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        crm_client=build_crm_client(settings),
        crm_agent_repository=PostgresCRMAgentRepository(session),
        workspace_agent_crm_mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        llm_client=build_llm_client(settings),
        default_openrouter_model=settings.openrouter_model,
        notification_provider=build_notification_provider(settings),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        rollback=session.rollback,
    )
