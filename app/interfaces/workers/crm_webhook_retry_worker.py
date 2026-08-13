import asyncio
from datetime import UTC, datetime

import structlog

from app.application.use_cases.retry_external_events import retry_due_external_events
from app.core.config import Settings, get_settings
from app.core.database import (
    async_session_factory,
    enable_postgres_service_access,
    service_access_commit,
    service_access_rollback,
)
from app.core.logging import configure_logging
from app.domain.leads import CRMProvider
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.interfaces.api.dependencies.follow_up_boss_webhook import (
    build_follow_up_boss_webhook_event_handler,
)
from app.interfaces.api.dependencies.inbound import get_inbound_service_bundle

logger = structlog.get_logger(__name__)


async def run_once(*, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        bundle = await get_inbound_service_bundle(session, resolved_settings)
        result = await retry_due_external_events(
            provider_name=CRMProvider.FOLLOW_UP_BOSS.value,
            external_event_repository=PostgresExternalEventRepository(session),
            webhook_handler=build_follow_up_boss_webhook_event_handler(bundle),
            commit=service_access_commit(session),
            rollback=service_access_rollback(session),
            now=datetime.now(UTC),
            limit=resolved_settings.crm_webhook_retry_batch_size,
        )
        if result.claimed_count > 0 or result.failed_count > 0:
            logger.info(
                "crm_webhook_retry_cycle",
                claimed_count=result.claimed_count,
                processed_count=result.processed_count,
                terminal_failure_count=result.terminal_failure_count,
                failed_count=result.failed_count,
            )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        try:
            await run_once(settings=settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("crm_webhook_retry_run_failed")
        await asyncio.sleep(settings.crm_webhook_retry_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())