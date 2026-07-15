from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
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
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.providers import build_temporal_workflow_starter


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class LeadManualEnrollmentBundle:
    session: SessionCommitter
    lead_repository: LeadReadLeadRepository
    campaign_admin_repository: CampaignAdminRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    event_bus: EventBus


async def get_lead_manual_enrollment_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LeadManualEnrollmentBundle:
    return LeadManualEnrollmentBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        campaign_admin_repository=PostgresCampaignAdminRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )