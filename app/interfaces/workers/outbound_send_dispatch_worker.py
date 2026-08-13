import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from time import perf_counter
from typing import cast

import structlog
from prometheus_client import start_http_server

from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.services.pre_send_crm_refresh import PreSendCRMRefreshContext
from app.application.use_cases.dispatch_outbound_send_requests import (
    DispatchOutboundSendRequestsResult,
    dispatch_outbound_send_requests,
)
from app.application.use_cases.refresh_outbound_send_request import (
    refresh_outbound_send_request,
)
from app.application.use_cases.revalidate_outbound_send_request import (
    revalidate_outbound_send_request,
)
from app.core.config import Settings, get_settings
from app.core.database import (
    async_session_factory,
    enable_postgres_service_access,
    service_access_commit,
)
from app.core.logging import configure_logging
from app.core.metrics import outbound_send_dispatch_metrics
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresInboundMessageRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbound_provider_failure_repository import (
    PostgresOutboundProviderFailureRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_reconciliation_repository import (
    PostgresOutboundSendReconciliationRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_request_repository import (
    PostgresOutboundSendRequestRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.temporal_signal_outbox_repository import (
    PostgresTemporalSignalOutboxRepository,
)
from app.infrastructure.persistence.postgres.workflow_repository import (
    PostgresLeadWorkflowRepository,
    PostgresWorkflowTransitionRepository,
)
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_email_provider,
    build_sms_provider,
)

logger = structlog.get_logger(__name__)


def start_metrics_http_server(settings: Settings) -> None:
    if not settings.metrics_enabled:
        return
    start_http_server(
        settings.outbound_send_dispatch_metrics_port,
        addr=settings.outbound_send_dispatch_metrics_host,
        registry=outbound_send_dispatch_metrics.registry,
    )
    logger.info(
        "outbound_send_dispatch_metrics_started",
        host=settings.outbound_send_dispatch_metrics_host,
        port=settings.outbound_send_dispatch_metrics_port,
    )


async def run_once(
    *,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    settings: Settings | None = None,
) -> None:
    resolved_settings = settings or get_settings()
    started_at = perf_counter()
    now = datetime.now(UTC)
    try:
        result, pending_count, oldest_pending_at = await _run_once(
            sms_provider=sms_provider,
            email_provider=email_provider,
            settings=resolved_settings,
            now=now,
        )
    except Exception:
        if resolved_settings.metrics_enabled:
            outbound_send_dispatch_metrics.record_failure(
                now=now,
                elapsed_seconds=perf_counter() - started_at,
            )
        logger.exception("outbound_send_dispatch_cycle_failed")
        raise

    if resolved_settings.metrics_enabled:
        outbound_send_dispatch_metrics.record_cycle(
            now=now,
            elapsed_seconds=perf_counter() - started_at,
            recovered_uncertain_count=result.recovered_uncertain_count,
            claimed_count=result.claimed_count,
            sent_count=result.sent_count,
            retry_scheduled_count=result.retry_scheduled_count,
            policy_rejected_count=result.policy_rejected_count,
            failed_count=result.failed_count,
            uncertain_count=result.uncertain_count,
            pending_count=pending_count,
            oldest_pending_at=oldest_pending_at,
        )
    if result.claimed_count or result.recovered_uncertain_count:
        logger.info(
            "outbound_send_dispatch_cycle",
            recovered_uncertain_count=result.recovered_uncertain_count,
            claimed_count=result.claimed_count,
            sent_count=result.sent_count,
            retry_scheduled_count=result.retry_scheduled_count,
            policy_rejected_count=result.policy_rejected_count,
            failed_count=result.failed_count,
            uncertain_count=result.uncertain_count,
        )


async def _run_once(
    *,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    settings: Settings,
    now: datetime,
) -> tuple[DispatchOutboundSendRequestsResult, int | None, datetime | None]:
    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        request_repository = PostgresOutboundSendRequestRepository(session)
        message_repository = PostgresOutboundMessageRepository(session)
        reconciliation_repository = PostgresOutboundSendReconciliationRepository(session)
        lead_repository = PostgresLeadRepository(session)
        workflow_repository = PostgresLeadWorkflowRepository(session)
        temporal_signal_outbox_repository = PostgresTemporalSignalOutboxRepository(session)
        crm_client = build_crm_client(settings)
        event_bus = PostgresTransactionalEventBus(PostgresOutboxEventRepository(session))
        result = await dispatch_outbound_send_requests(
            request_repository=request_repository,
            message_repository=message_repository,
            reconciliation_repository=reconciliation_repository,
            provider_failure_repository=PostgresOutboundProviderFailureRepository(session),
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            pre_dispatch_refresh=partial(
                refresh_outbound_send_request,
                lead_repository=lead_repository,
                message_repository=message_repository,
                crm_refresh_context=PreSendCRMRefreshContext(
                    lead_refresh_source=cast(CanonicalLeadRefreshSource, crm_client),
                    crm_activity_source=crm_client,
                    crm_agent_repository=PostgresCRMAgentRepository(session),
                    workspace_agent_crm_mapping_repository=(
                        PostgresWorkspaceAgentCRMMappingRepository(session)
                    ),
                    workspace_agent_mapping_config_repository=(
                        PostgresWorkspaceAgentMappingConfigRepository(session)
                    ),
                    workspace_membership_repository=PostgresWorkspaceMembershipRepository(session),
                    user_repository=PostgresUserRepository(session),
                    lead_workflow_repository=workflow_repository,
                    workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                ),
                event_bus=event_bus,
            ),
            revalidate_request=partial(
                revalidate_outbound_send_request,
                lead_repository=lead_repository,
                workflow_repository=workflow_repository,
                message_repository=message_repository,
                request_repository=request_repository,
                reconciliation_repository=reconciliation_repository,
                campaign_repository=PostgresCampaignExecutionRepository(session),
                workspace_repository=PostgresWorkspaceRepository(session),
                workspace_control_repository=PostgresWorkspaceOperationalControlRepository(
                    session
                ),
                contact_policy_repository=PostgresWorkspaceContactPolicyRepository(session),
                inbound_message_repository=PostgresInboundMessageRepository(session),
            ),
            sms_provider=sms_provider,
            email_provider=email_provider,
            commit=service_access_commit(session),
            now=now,
            batch_size=settings.outbound_send_dispatch_batch_size,
            stale_after=timedelta(
                seconds=settings.outbound_send_dispatch_stale_seconds
            ),
        )
        try:
            pending_count, oldest_pending_at = await request_repository.get_due_pending_summary(
                now=now
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "outbound_send_dispatch_queue_metrics_failed",
                error=str(exc) or exc.__class__.__name__,
            )
            pending_count = None
            oldest_pending_at = None
        return result, pending_count, oldest_pending_at


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    start_metrics_http_server(settings)
    sms_provider = build_sms_provider(settings)
    email_provider = build_email_provider(settings)
    logger.info(
        "outbound_send_dispatch_worker_started",
        poll_seconds=settings.outbound_send_dispatch_poll_seconds,
        batch_size=settings.outbound_send_dispatch_batch_size,
    )
    while True:
        try:
            await run_once(
                sms_provider=sms_provider,
                email_provider=email_provider,
                settings=settings,
            )
        except asyncio.CancelledError:
            logger.info("outbound_send_dispatch_worker_stopped", reason="cancelled")
            raise
        except Exception:
            logger.exception("outbound_send_dispatch_run_failed")
        await asyncio.sleep(settings.outbound_send_dispatch_poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())