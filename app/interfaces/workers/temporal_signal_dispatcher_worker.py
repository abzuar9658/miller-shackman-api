import asyncio
from datetime import UTC, datetime

from app.application.ports.temporal import LeadNurtureWorkflowSignaler
from app.application.use_cases.dispatch_temporal_signals import dispatch_temporal_signals
from app.core.config import get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.providers import build_temporal_workflow_signaler


async def run_once(*, lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler) -> None:
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        await dispatch_temporal_signals(
            temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
            lead_nurture_workflow_signaler=lead_nurture_workflow_signaler,
            now=datetime.now(UTC),
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    lead_nurture_workflow_signaler = await build_temporal_workflow_signaler(settings)
    while True:
        await run_once(lead_nurture_workflow_signaler=lead_nurture_workflow_signaler)
        await asyncio.sleep(1)