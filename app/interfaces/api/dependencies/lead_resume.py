from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import WorkspaceContactPolicyRepository
from app.application.ports.temporal import LeadNurtureWorkflowSignaler
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.providers import build_temporal_workflow_signaler


@dataclass
class LeadResumeReadBundle:
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository


@dataclass
class LeadResumeActionBundle:
    lead_repository: LeadReadLeadRepository
    workflow_repository: LeadReadWorkflowRepository
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler


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
        lead_repository=PostgresLeadRepository(session),
        workflow_repository=PostgresLeadWorkflowRepository(session),
        workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
        lead_nurture_workflow_signaler=await build_temporal_workflow_signaler(settings),
    )
