from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import (
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadWorkflowRepository,
)
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    ExternalEventRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import (
    LeadNurtureWorkflowSignaler,
    TemporalWorkflowStarter,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresHandoffRepository,
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
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
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_temporal_workflow_signaler,
    build_temporal_workflow_starter,
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
    workflow_repository: LeadWorkflowRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    inbound_message_repository: LeadReadInboundMessageRepository
    handoff_repository: LeadReadHandoffRepository
    campaign_enrollment_repository: CampaignEnrollmentRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler
    external_event_repository: ExternalEventRepository
    event_bus: EventBus
    workspace_operational_control_repository: WorkspaceOperationalControlRepository


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> LeadResumeActionBundle:
    return LeadResumeActionBundle(
        session=session,
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        inbound_message_repository=PostgresInboundMessageRepository(session),
        handoff_repository=PostgresHandoffRepository(session),
        campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        lead_nurture_workflow_signaler=await build_temporal_workflow_signaler(settings),
        external_event_repository=PostgresExternalEventRepository(session),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
        workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(session),
    )
