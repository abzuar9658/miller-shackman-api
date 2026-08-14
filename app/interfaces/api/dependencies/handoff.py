from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import (
    HandoffRepository,
    LeadRepository,
    UserRepository,
    WorkspaceMembershipRepository,
)
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class HandoffReadBundle:
    handoff_repository: HandoffRepository
    lead_repository: LeadRepository
    user_repository: UserRepository


@dataclass
class HandoffActionBundle:
    session: SessionCommitter
    handoff_repository: HandoffRepository
    lead_repository: LeadRepository
    user_repository: UserRepository
    membership_repository: WorkspaceMembershipRepository


async def get_handoff_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HandoffReadBundle:
    return HandoffReadBundle(
        handoff_repository=PostgresHandoffRepository(session),
        lead_repository=PostgresLeadRepository(session),
        user_repository=PostgresUserRepository(session),
    )


async def get_handoff_action_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HandoffActionBundle:
    return HandoffActionBundle(
        session=session,
        handoff_repository=PostgresHandoffRepository(session),
        lead_repository=PostgresLeadRepository(session),
        user_repository=PostgresUserRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
    )
