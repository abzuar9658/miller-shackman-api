from dataclasses import dataclass
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.crm_history_imports import (
    CrmHistoryImportEventRepository,
    CrmHistoryImportJobRepository,
)
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    CrmConversationEventRepository,
    LeadRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
)
from app.infrastructure.persistence.postgres.crm_history_import_repository import (
    PostgresCrmHistoryImportEventRepository,
    PostgresCrmHistoryImportJobRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class CrmHistoryImportBundle:
    session: SessionCommitter
    settings: Settings
    job_repository: CrmHistoryImportJobRepository
    event_repository: CrmHistoryImportEventRepository
    lead_repository: LeadRepository
    conversation_event_repository: CrmConversationEventRepository
    audit_log_repository: AuthAuditLogRepository


async def get_crm_history_import_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CrmHistoryImportBundle:
    return CrmHistoryImportBundle(
        session=session,
        settings=settings,
        job_repository=PostgresCrmHistoryImportJobRepository(session),
        event_repository=PostgresCrmHistoryImportEventRepository(session),
        lead_repository=PostgresLeadRepository(session),
        conversation_event_repository=PostgresCrmConversationEventRepository(session),
        audit_log_repository=PostgresAuthAuditLogRepository(session),
    )