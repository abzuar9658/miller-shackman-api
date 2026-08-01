import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from app.application.use_cases.crm_history_imports import (
    claim_ready_crm_history_imports,
    promote_crm_history_import,
)
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.domain.crm_history_imports import CrmHistoryImportJobStatus
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


async def run_once(*, limit: int = 100) -> int:
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        job_repository = PostgresCrmHistoryImportJobRepository(session)
        event_repository = PostgresCrmHistoryImportEventRepository(session)
        conversation_event_repository = PostgresCrmConversationEventRepository(session)
        audit_log_repository = PostgresAuthAuditLogRepository(session)
        now = datetime.now(UTC)
        jobs = await claim_ready_crm_history_imports(
            job_repository=job_repository,
            now=now,
            limit=limit,
        )
        await session.commit()
        for job in jobs:
            try:
                await promote_crm_history_import(
                    job=job,
                    job_repository=job_repository,
                    event_repository=event_repository,
                    conversation_event_repository=conversation_event_repository,
                    audit_log_repository=audit_log_repository,
                    now=now,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                await job_repository.save(
                    replace(
                        job,
                        status=CrmHistoryImportJobStatus.FAILED,
                        completed_at=now,
                        updated_at=now,
                        failure_reason="promotion_worker_failed",
                    )
                )
                await session.commit()
        return len(jobs)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        await run_once()
        await asyncio.sleep(1)