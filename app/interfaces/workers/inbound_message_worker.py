"""Poll for queued inbound message events and run the LLM processing pipeline.

Webhooks persist inbound messages as PENDING external events and return
immediately; this worker claims those events (FOR UPDATE SKIP LOCKED) and
executes process_inbound_message_event outside the webhook request path.
"""

import asyncio
from datetime import UTC, datetime

import structlog

from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventResult,
)
from app.application.use_cases.process_queued_inbound_message_events import (
    process_queued_inbound_message_events,
)
from app.core.config import Settings, get_settings
from app.core.database import (
    async_session_factory,
    enable_postgres_service_access,
    service_access_commit,
    service_access_rollback,
)
from app.core.logging import configure_logging
from app.domain.crm_sync import ExternalEvent
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresExternalEventRepository,
)
from app.interfaces.api.dependencies.inbound import (
    InboundServiceBundle,
    get_inbound_service_bundle,
    process_inbound_message_event_with_bundle,
)

logger = structlog.get_logger(__name__)


class _BundleProcessor:
    def __init__(self, bundle: InboundServiceBundle) -> None:
        self._bundle = bundle

    async def __call__(
        self,
        event: InboundMessageEvent,
        claimed_external_event: ExternalEvent,
        now: datetime,
    ) -> ProcessInboundMessageEventResult:
        return await process_inbound_message_event_with_bundle(
            event=event,
            bundle=self._bundle,
            now=now,
            claimed_external_event=claimed_external_event,
        )


async def run_once(*, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        bundle = await get_inbound_service_bundle(session, resolved_settings)
        repository = PostgresExternalEventRepository(session)
        result = await process_queued_inbound_message_events(
            queue_repository=repository,
            external_event_repository=repository,
            processor=_BundleProcessor(bundle),
            commit=service_access_commit(session),
            rollback=service_access_rollback(session),
            now=datetime.now(UTC),
            limit=resolved_settings.inbound_message_worker_batch_size,
        )
        if result.claimed_count > 0:
            logger.info(
                "inbound_message_worker_cycle",
                claimed_count=result.claimed_count,
                processed_count=result.processed_count,
                invalid_count=result.invalid_count,
                failed_count=result.failed_count,
                exhausted_count=result.exhausted_count,
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
            logger.exception("inbound_message_worker_run_failed")
        await asyncio.sleep(settings.inbound_message_worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
