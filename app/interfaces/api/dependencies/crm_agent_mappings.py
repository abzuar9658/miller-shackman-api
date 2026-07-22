from dataclasses import dataclass
from typing import Annotated, Protocol, cast

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm import CRMAgentDirectorySource
from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceMembershipRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.providers import build_crm_client


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class CRMAgentMappingBundle:
    session: SessionCommitter
    crm_agent_repository: CRMAgentRepository
    mapping_repository: WorkspaceAgentCRMMappingRepository
    user_repository: UserRepository
    membership_repository: WorkspaceMembershipRepository


@dataclass
class CRMAgentDirectorySyncBundle(CRMAgentMappingBundle):
    crm_agent_directory_source: CRMAgentDirectorySource


async def get_crm_agent_mapping_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CRMAgentMappingBundle:
    return CRMAgentMappingBundle(
        session=session,
        crm_agent_repository=PostgresCRMAgentRepository(session),
        mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        user_repository=PostgresUserRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
    )


async def get_crm_agent_directory_sync_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CRMAgentDirectorySyncBundle:
    return CRMAgentDirectorySyncBundle(
        session=session,
        crm_agent_repository=PostgresCRMAgentRepository(session),
        mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(session),
        user_repository=PostgresUserRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        crm_agent_directory_source=cast(CRMAgentDirectorySource, build_crm_client(settings)),
    )
