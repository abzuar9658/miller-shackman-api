import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import aio_pika
import structlog
from pydantic import BaseModel, Field

from app.application.ports.crm_sync import CanonicalLeadSnapshotSource
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.crm_sync import (
    CRMActivitySource,
    execute_queued_follow_up_boss_crm_sync,
)
from app.core.config import Settings, get_settings
from app.core.database import async_session_factory, enable_postgres_service_access
from app.core.logging import configure_logging
from app.domain.crm_sync import CRMSyncLeadSort
from app.domain.events import DomainEventType
from app.infrastructure.events.rabbitmq.topology import ensure_crm_sync_topology_on_channel
from app.infrastructure.persistence.postgres.campaign_enrollment_repository import (
    PostgresCampaignEnrollmentRepository,
)
from app.infrastructure.persistence.postgres.campaign_execution_repository import (
    PostgresCampaignExecutionRepository,
)
from app.infrastructure.persistence.postgres.conversation_repository import (
    PostgresCrmConversationEventRepository,
    PostgresHandoffCompletionRepository,
    PostgresHandoffRepository,
)
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresCRMSyncJobRepository,
    PostgresCRMSyncWindowStateRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.persistence.postgres.lead_classification_artifact_repository import (
    PostgresLeadClassificationArtifactRepository,
)
from app.infrastructure.persistence.postgres.lead_repository import PostgresLeadRepository
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)
from app.infrastructure.persistence.postgres.paused_search_track_repository import (
    PostgresPausedSearchTrackAdminRepository,
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
from app.infrastructure.persistence.postgres.workspace_handoff_config_repository import (
    PostgresWorkspaceHandoffConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)
from app.infrastructure.providers import (
    build_crm_client,
    build_llm_client,
    build_notification_provider,
    build_temporal_workflow_starter,
)

logger = structlog.get_logger(__name__)


class _SyncRequestedPayload(BaseModel):
    sync_job_id: UUID
    crm_provider: str | None = None
    sync_type: str | None = None
    max_leads: int | None = Field(default=None, ge=1)
    latest_by: CRMSyncLeadSort | None = None
    resume_cursor: str | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


class _SyncRequestedMessage(BaseModel):
    workspace_id: UUID
    event_type: str
    payload: _SyncRequestedPayload


async def _run_running_sync_heartbeat_loop(
    *,
    workspace_id: UUID,
    sync_job_id: UUID,
    settings: Settings,
    stop_event: asyncio.Event,
    lease_lost_event: asyncio.Event,
) -> None:
    saw_running = False
    while True:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.crm_sync_running_heartbeat_interval_seconds,
            )
            return
        except TimeoutError:
            pass

        try:
            async with async_session_factory() as session:
                await enable_postgres_service_access(session)
                touched = await PostgresCRMSyncJobRepository(session).touch_running_heartbeat(
                    workspace_id,
                    sync_job_id,
                    now=datetime.now(UTC),
                )
                await session.commit()
        except Exception:
            logger.exception(
                "crm_sync_heartbeat_failed",
                workspace_id=str(workspace_id),
                sync_job_id=str(sync_job_id),
            )
            continue

        if touched is not None:
            saw_running = True
            continue
        if saw_running:
            lease_lost_event.set()
            logger.info(
                "crm_sync_heartbeat_lease_lost",
                workspace_id=str(workspace_id),
                sync_job_id=str(sync_job_id),
            )
            return


async def run_once(
    body: bytes,
    *,
    settings: Settings | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
) -> None:
    resolved_settings = settings or get_settings()
    message = _SyncRequestedMessage.model_validate(json.loads(body.decode("utf-8")))
    if message.event_type != DomainEventType.CRM_SYNC_REQUESTED.value:
        logger.info(
            "crm_sync_worker_message_ignored",
            workspace_id=str(message.workspace_id),
            event_type=message.event_type,
        )
        return

    logger.info(
        "crm_sync_worker_message_received",
        workspace_id=str(message.workspace_id),
        sync_job_id=str(message.payload.sync_job_id),
        max_leads=message.payload.max_leads,
        latest_by=(
            message.payload.latest_by.value if message.payload.latest_by is not None else None
        ),
        resume_cursor_present=message.payload.resume_cursor is not None,
        updated_after=(
            message.payload.updated_after.isoformat()
            if message.payload.updated_after is not None
            else None
        ),
        updated_before=(
            message.payload.updated_before.isoformat()
            if message.payload.updated_before is not None
            else None
        ),
    )

    starter = temporal_workflow_starter or await build_temporal_workflow_starter(resolved_settings)

    async with async_session_factory() as session:
        await enable_postgres_service_access(session)
        crm_client = build_crm_client(resolved_settings)
        heartbeat_stop_event = asyncio.Event()
        heartbeat_lease_lost_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _run_running_sync_heartbeat_loop(
                workspace_id=message.workspace_id,
                sync_job_id=message.payload.sync_job_id,
                settings=resolved_settings,
                stop_event=heartbeat_stop_event,
                lease_lost_event=heartbeat_lease_lost_event,
            )
        )
        try:
            result = await execute_queued_follow_up_boss_crm_sync(
                workspace_id=message.workspace_id,
                sync_job_id=message.payload.sync_job_id,
                lead_snapshot_source=cast(CanonicalLeadSnapshotSource, crm_client),
                crm_activity_source=cast(CRMActivitySource, crm_client),
                lead_repository=PostgresLeadRepository(session),
                crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
                crm_conversation_event_repository=PostgresCrmConversationEventRepository(session),
                crm_sync_window_state_repository=PostgresCRMSyncWindowStateRepository(session),
                campaign_execution_repository=PostgresCampaignExecutionRepository(session),
                workspace_contact_policy_repository=PostgresWorkspaceContactPolicyRepository(
                    session
                ),
                campaign_enrollment_repository=PostgresCampaignEnrollmentRepository(session),
                lead_workflow_repository=PostgresLeadWorkflowRepository(session),
                workflow_transition_repository=PostgresWorkflowTransitionRepository(session),
                paused_search_track_repository=PostgresPausedSearchTrackAdminRepository(session),
                temporal_workflow_starter=starter,
                event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
                workspace_operational_control_repository=PostgresWorkspaceOperationalControlRepository(
                    session,
                ),
                handoff_repository=PostgresHandoffRepository(session),
                handoff_completion_repository=PostgresHandoffCompletionRepository(session),
                workspace_handoff_config_repository=PostgresWorkspaceHandoffConfigRepository(
                    session,
                ),
                notification_provider=build_notification_provider(resolved_settings),
                crm_agent_repository=PostgresCRMAgentRepository(session),
                workspace_agent_crm_mapping_repository=PostgresWorkspaceAgentCRMMappingRepository(
                    session,
                ),
                workspace_agent_mapping_config_repository=PostgresWorkspaceAgentMappingConfigRepository(
                    session,
                ),
                workspace_membership_repository=PostgresWorkspaceMembershipRepository(session),
                user_repository=PostgresUserRepository(session),
                temporal_signal_outbox_repository=PostgresTemporalSignalOutboxRepository(session),
                outbound_message_repository=PostgresOutboundMessageRepository(session),
                lead_classification_artifact_repository=PostgresLeadClassificationArtifactRepository(
                    session
                ),
                workspace_llm_config_repository=PostgresWorkspaceLLMConfigRepository(session),
                llm_client=build_llm_client(resolved_settings),
                default_openrouter_model=resolved_settings.openrouter_model,
                commit=session.commit,
                now=datetime.now(UTC),
                max_leads=message.payload.max_leads,
                latest_by=message.payload.latest_by,
                resume_cursor=message.payload.resume_cursor,
                updated_after=message.payload.updated_after,
                updated_before=message.payload.updated_before,
                heartbeat_now_factory=lambda: datetime.now(UTC),
                lease_lost_checker=heartbeat_lease_lost_event.is_set,
            )
        except Exception:
            heartbeat_stop_event.set()
            await heartbeat_task
            logger.exception(
                "crm_sync_worker_sync_failed",
                workspace_id=str(message.workspace_id),
                sync_job_id=str(message.payload.sync_job_id),
            )
            raise

        heartbeat_stop_event.set()
        await heartbeat_task

        logger.info(
            "crm_sync_worker_sync_finished",
            workspace_id=str(message.workspace_id),
            sync_job_id=str(message.payload.sync_job_id),
            status=result.status.value,
            page_count=result.page_count,
            job_status=(result.job.status.value if result.job is not None else None),
            total_seen=(result.job.total_seen if result.job is not None else None),
            total_upserted=(result.job.total_upserted if result.job is not None else None),
            total_failed=(result.job.total_failed if result.job is not None else None),
        )
        await session.commit()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    temporal_workflow_starter = await build_temporal_workflow_starter(settings)
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=settings.crm_sync_worker_prefetch_count)
        _, queue = await ensure_crm_sync_topology_on_channel(
            channel=channel,
            exchange_name=settings.crm_sync_exchange_name,
            queue_name=settings.crm_sync_queue_name,
        )
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=True):
                    await run_once(
                        message.body,
                        settings=settings,
                        temporal_workflow_starter=temporal_workflow_starter,
                    )


if __name__ == "__main__":
    asyncio.run(main())
