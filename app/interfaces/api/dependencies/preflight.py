from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
)
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
)


@dataclass
class PreflightReadBundle:
    repository: PreflightDigestRepository
    crm_agent_repository: CRMAgentRepository
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository


async def get_preflight_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PreflightReadBundle:
    return PreflightReadBundle(
        repository=PostgresPreflightDigestRepository(session),
        crm_agent_repository=PostgresCRMAgentRepository(session),
        workspace_agent_crm_mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
    )
