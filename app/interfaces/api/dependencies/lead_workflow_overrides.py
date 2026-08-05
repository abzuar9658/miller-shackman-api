from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowOverrideAuditLogRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    WorkspaceRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
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
    PostgresLeadWorkflowOverrideAuditLogRepository,
    PostgresLeadWorkflowRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadWorkflowOverrideActionBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    lead_workflow_repository: LeadWorkflowRepository
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository
    paused_search_track_repository: PausedSearchTrackMappingRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    workspace_repository: WorkspaceRepository
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None


async def get_lead_workflow_override_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadWorkflowOverrideActionBundle:
    return LeadWorkflowOverrideActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        paused_search_history_repository=PostgresLeadRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        lead_workflow_override_audit_repository=PostgresLeadWorkflowOverrideAuditLogRepository(
            session
        ),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        paused_search_occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
    )
