from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.preflight_digest import PreflightDigestRepository
from app.core.database import get_session
from app.infrastructure.persistence.postgres.preflight_digest_repository import (
    PostgresPreflightDigestRepository,
)


@dataclass
class PreflightReadBundle:
    repository: PreflightDigestRepository


async def get_preflight_read_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PreflightReadBundle:
    return PreflightReadBundle(repository=PostgresPreflightDigestRepository(session))
