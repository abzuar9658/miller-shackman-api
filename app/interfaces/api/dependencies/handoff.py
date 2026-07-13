from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import HandoffRepository, LeadRepository, UserRepository
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import PostgresUserRepository
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository


@dataclass
class HandoffReadBundle:
    handoff_repository: HandoffRepository
    lead_repository: LeadRepository
    user_repository: UserRepository


async def get_handoff_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HandoffReadBundle:
    return HandoffReadBundle(
        handoff_repository=PostgresHandoffRepository(session),
        lead_repository=PostgresLeadRepository(session),
        user_repository=PostgresUserRepository(session),
    )
