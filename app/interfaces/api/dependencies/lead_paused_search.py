from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.core.database import get_session
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
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadPausedSearchActionBundle:
    session: SessionCommitter
    lead_repository: LeadRepository
    paused_search_history_repository: LeadPausedSearchHistoryRepository
    lead_workflow_repository: LeadWorkflowRepository
    paused_search_track_repository: PausedSearchTrackRepository
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository
    occurrence_repository: PausedSearchOccurrenceRepository | None = None
    workflow_transition_repository: WorkflowTransitionRepository | None = None


async def get_lead_paused_search_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LeadPausedSearchActionBundle:
    return LeadPausedSearchActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        paused_search_history_repository=PostgresLeadRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
        paused_search_track_assignment_repository=PostgresPausedSearchTrackAssignmentRepository(
            session
        ),
        temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
        occurrence_repository=PostgresPausedSearchOccurrenceRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
    )
