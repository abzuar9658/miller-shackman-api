from dataclasses import dataclass
from typing import Annotated, Protocol, cast

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm_history_imports import (
    CrmHistoryImportEventRepository,
    CrmHistoryImportJobRepository,
)
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CrmConversationEventRepository,
    LeadRepository,
)
from app.application.services.crm_lead_refresh import CrmTagEnrollmentDependencies
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.crm_history_import_repository import (
    PostgresCrmHistoryImportEventRepository,
    PostgresCrmHistoryImportJobRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresUserRepository,
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
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_llm_client,
    build_notification_provider,
    build_temporal_workflow_starter,
)

logger = structlog.get_logger(__name__)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class CrmHistoryImportBundle:
    session: SessionCommitter
    settings: Settings
    job_repository: CrmHistoryImportJobRepository
    event_repository: CrmHistoryImportEventRepository
    lead_repository: LeadRepository
    conversation_event_repository: CrmConversationEventRepository
    audit_log_repository: AuthAuditLogRepository
    lead_refresh_source: CanonicalLeadRefreshSource | None = None
    enrollment_dependencies: CrmTagEnrollmentDependencies | None = None


async def get_crm_history_import_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CrmHistoryImportBundle:
    lead_repository = PostgresLeadRepository(session)
    conversation_event_repository = PostgresCrmConversationEventRepository(session)
    lead_refresh_source, enrollment_dependencies = await _build_lead_refresh_dependencies(
        session=session,
        settings=settings,
        lead_repository=lead_repository,
        conversation_event_repository=conversation_event_repository,
    )
    return CrmHistoryImportBundle(
        session=session,
        settings=settings,
        job_repository=PostgresCrmHistoryImportJobRepository(session),
        event_repository=PostgresCrmHistoryImportEventRepository(session),
        lead_repository=lead_repository,
        conversation_event_repository=conversation_event_repository,
        audit_log_repository=PostgresAuthAuditLogRepository(session),
        lead_refresh_source=lead_refresh_source,
        enrollment_dependencies=enrollment_dependencies,
    )


async def _build_lead_refresh_dependencies(
    *,
    session: AsyncSession,
    settings: Settings,
    lead_repository: LeadRepository,
    conversation_event_repository: CrmConversationEventRepository,
) -> tuple[CanonicalLeadRefreshSource | None, CrmTagEnrollmentDependencies | None]:
    # The CRM refresh on export is best-effort: a missing CRM/LLM/Temporal
    # configuration must not take down the history import surface.
    try:
        crm_client = build_crm_client(settings)
        llm_client = build_llm_client(settings)
        temporal_workflow_starter = await build_temporal_workflow_starter(settings)
        notification_provider = build_notification_provider(settings)
    except Exception as exc:
        logger.warning(
            "crm_history_import_refresh_unavailable",
            error=str(exc) or exc.__class__.__name__,
        )
        return None, None
    enrollment_dependencies = CrmTagEnrollmentDependencies(
        campaign_execution_repository=PostgresCampaignExecutionRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_workflow_starter=temporal_workflow_starter,
        lead_repository=lead_repository,
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        artifact_repository=PostgresLeadClassificationArtifactRepository(session),
        crm_conversation_event_repository=conversation_event_repository,
        workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
        llm_client=llm_client,
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
            session
        ),
        handoff_repository=PostgresHandoffRepository(session),
        handoff_completion_repository=PostgresHandoffCompletionRepository(session),
        workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(session),
        crm_client=crm_client,
        notification_provider=notification_provider,
        user_repository=PostgresUserRepository(session),
        routing_review_repository=PostgresLeadRoutingReviewRepository(session),
        commit=session.commit,
        rollback=session.rollback,
        default_openrouter_model=settings.openrouter_model,
    )
    return cast(CanonicalLeadRefreshSource, crm_client), enrollment_dependencies