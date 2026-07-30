import asyncio
from datetime import UTC, datetime

import structlog

from app.application.use_cases.crm_sync import enqueue_due_follow_up_boss_crm_syncs
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresCRMSyncJobRepository,
    PostgresCRMSyncWindowStateRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.workspace_crm_sync_config_repository import (
    PostgresWorkspaceCRMSyncConfigRepository,
)

logger = structlog.get_logger(__name__)


async def run_once(*, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        crm_sync_job_repository = PostgresCRMSyncJobRepository(session)
        stale_recovered = await crm_sync_job_repository.fail_stale_active_jobs(
            now=datetime.now(UTC),
            pending_timeout_seconds=resolved_settings.crm_sync_pending_stale_timeout_seconds,
            running_timeout_seconds=resolved_settings.crm_sync_running_stale_timeout_seconds,
        )
        result = await enqueue_due_follow_up_boss_crm_syncs(
            workspace_crm_sync_config_repository=PostgresWorkspaceCRMSyncConfigRepository(session),
            crm_sync_job_repository=crm_sync_job_repository,
            crm_sync_window_state_repository=PostgresCRMSyncWindowStateRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
            default_interval_seconds=resolved_settings.crm_sync_incremental_interval_seconds,
            workspace_limit=resolved_settings.crm_sync_scheduler_workspace_limit,
        )
        logger.info(
            "crm_sync_scheduler_tick",
            stale_jobs_recovered=stale_recovered,
            scanned_count=result.scanned_count,
            requested_count=result.requested_count,
            skipped_disabled_count=result.skipped_disabled_count,
            skipped_automation_blocked_count=result.skipped_automation_blocked_count,
            skipped_active_count=result.skipped_active_count,
            skipped_not_due_count=result.skipped_not_due_count,
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
