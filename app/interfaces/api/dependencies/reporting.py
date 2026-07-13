from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.reporting import ReportingRepository
from app.core.database import get_session
from app.infrastructure.persistence.postgres.reporting_repository import PostgresReportingRepository


@dataclass
class ReportingServiceBundle:
    reporting_repository: ReportingRepository


async def get_reporting_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportingServiceBundle:
    return ReportingServiceBundle(reporting_repository=PostgresReportingRepository(session))
