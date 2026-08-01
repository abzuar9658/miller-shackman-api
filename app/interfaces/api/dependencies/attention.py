from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.repositories import AttentionAcknowledgementRepository
from app.core.database import get_session
from app.infrastructure.persistence.postgres.attention_repository import (
    PostgresAttentionAcknowledgementRepository,
)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class AttentionAcknowledgementBundle:
    session: SessionCommitter
    repository: AttentionAcknowledgementRepository


async def get_attention_acknowledgement_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AttentionAcknowledgementBundle:
    return AttentionAcknowledgementBundle(
        session=session,
        repository=PostgresAttentionAcknowledgementRepository(session),
    )
