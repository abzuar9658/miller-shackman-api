from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowOverrideAuditLogRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    PausedSearchOccurrenceOperationsRepository,
    PausedSearchReviewRepository,
    PausedSearchTrackAdminAuditLogRepository,
    PausedSearchTrackAdminRepository,
    PausedSearchTrackMappingRepository,
    TemplateRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresWorkspaceRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_occurrence_repository import (
    PostgresPausedSearchOccurrenceRepository,
)
from app.infrastructure.persistence.postgres.paused_search_review_repository import (
    PostgresPausedSearchReviewRepository,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminAuditLogRepository,
    PostgresPausedSearchTrackAdminRepository,
)
from app.infrastructure.persistence.postgres.template_repository import PostgresTemplateRepository
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowOverrideAuditLogRepository,
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
class PausedSearchTrackServiceBundle:
    session: SessionCommitter
    track_repository: PausedSearchTrackAdminRepository
    audit_log_repository: PausedSearchTrackAdminAuditLogRepository
    event_bus: EventBus
    template_repository: TemplateRepository | None = None
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None


@dataclass
class PausedSearchTrackReadBundle:
    track_repository: PausedSearchTrackAdminRepository


@dataclass
class PausedSearchOperationsBundle:
    occurrence_repository: PausedSearchOccurrenceOperationsRepository
    review_repository: PausedSearchReviewRepository
    lead_repository: LeadReadLeadRepository
    action_lead_repository: LeadRepository
    message_repository: OutboundMessageRepository
    workflow_repository: LeadReadWorkflowRepository
    action_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    external_event_repository: ExternalEventRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    paused_search_track_repository: PausedSearchTrackMappingRepository
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository
    workspace_repository: WorkspaceRepository
    occurrence_transition_repository: PausedSearchOccurrenceOperationsRepository
    session: SessionCommitter


async def get_paused_search_track_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PausedSearchTrackServiceBundle:
    return PausedSearchTrackServiceBundle(
        session=session,
        track_repository=PostgresPausedSearchTrackAdminRepository(session),
        audit_log_repository=PostgresPausedSearchTrackAdminAuditLogRepository(session),
        template_repository=PostgresTemplateRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )


async def get_paused_search_track_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PausedSearchTrackReadBundle:
    return PausedSearchTrackReadBundle(
        track_repository=PostgresPausedSearchTrackAdminRepository(session),
    )


async def get_paused_search_operations_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PausedSearchOperationsBundle:
    return PausedSearchOperationsBundle(
        occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        review_repository=PostgresPausedSearchReviewRepository(session),
        lead_repository=PostgresLeadRepository(session),
        action_lead_repository=PostgresLeadRepository(session),
        message_repository=PostgresOutboundMessageRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        action_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        external_event_repository=PostgresExternalEventRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        paused_search_history_repository=PostgresLeadRepository(session),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        lead_workflow_override_audit_repository=PostgresLeadWorkflowOverrideAuditLogRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        occurrence_transition_repository=PostgresPausedSearchOccurrenceRepository(session),
        session=session,
    )
