from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.ports.event_bus import EventBus
from app.application.ports.notifications import NotificationProvider
from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CampaignAdminAuditLogRepository,
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
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
from app.infrastructure.persistence.postgres.dormant_candidate_selector import (
    PostgresDormantCandidateSelector,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
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
    dormant_candidate_selector: DormantCandidateSelector
    preflight_digest_repository: PreflightDigestRepository
    lead_workflow_repository: LeadWorkflowRepository
    workflow_transition_repository: WorkflowTransitionRepository
    temporal_workflow_starter: TemporalWorkflowStarter
    crm_client: CRMClient
    notification_provider: NotificationProvider
    event_bus: EventBus


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
        dormant_candidate_selector=PostgresDormantCandidateSelector(session),
        preflight_digest_repository=PostgresPreflightDigestRepository(session),
        lead_workflow_repository=PostgresLeadWorkflowRepository(session),
        workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
        temporal_workflow_starter=await build_temporal_workflow_starter(settings),
        crm_client=build_crm_client(settings),
        notification_provider=build_notification_provider(settings),
        event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
    )
