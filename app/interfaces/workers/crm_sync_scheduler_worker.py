import asyncio
from datetime import UTC, datetime

from app.application.use_cases.crm_sync import enqueue_due_follow_up_boss_crm_syncs
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.infrastructure.persistence.postgres.crm_sync_repository import PostgresCRMSyncJobRepository
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.workspace_crm_sync_config_repository import (
    PostgresWorkspaceCRMSyncConfigRepository,
)


async def run_once(*, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await enqueue_due_follow_up_boss_crm_syncs(
            workspace_crm_sync_config_repository=PostgresWorkspaceCRMSyncConfigRepository(session),
            crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
            default_interval_seconds=resolved_settings.crm_sync_incremental_interval_seconds,
            workspace_limit=resolved_settings.crm_sync_scheduler_workspace_limit,
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        await run_once(settings=settings)
        await asyncio.sleep(settings.crm_sync_scheduler_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
