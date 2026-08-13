import asyncio
from datetime import UTC, datetime

import structlog

from app.application.ports.temporal import LeadNurtureWorkflowSignaler, TemporalWorkflowStarter
from app.application.use_cases.dispatch_temporal_signals import dispatch_temporal_signals
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
)
from app.infrastructure.providers import (
    build_temporal_workflow_signaler,
    build_temporal_workflow_starter,
)

logger = structlog.get_logger(__name__)


async def run_once(
    *,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
    temporal_workflow_starter: TemporalWorkflowStarter,
) -> None:
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await dispatch_temporal_signals(
            temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
            lead_nurture_workflow_signaler=lead_nurture_workflow_signaler,
            lead_workflow_repository=PostgresLeadWorkflowRepository(session),
            campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
            temporal_workflow_starter=temporal_workflow_starter,
            now=datetime.now(UTC),
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    lead_nurture_workflow_signaler = await build_temporal_workflow_signaler(settings)
    temporal_workflow_starter = await build_temporal_workflow_starter(settings)
    while True:
        try:
            await run_once(
                lead_nurture_workflow_signaler=lead_nurture_workflow_signaler,
                temporal_workflow_starter=temporal_workflow_starter,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("temporal_signal_dispatcher_run_failed")
        await asyncio.sleep(1)
