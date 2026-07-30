from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from app.application.ports.temporal import (
    InboundProcessedLeadNurtureWorkflowSignal,
    LeadNurtureWorkflowSignaler,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowNotFoundError,
    TemporalWorkflowStarter,
    UnblockLeadNurtureWorkflowSignal,
)
from app.core.config import Settings, get_settings
from app.domain.common.ids import CampaignVersionId, LeadId, WorkspaceId
from app.infrastructure.workflows.temporal.lead_nurture import (
    InboundProcessedWorkflowSignal,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
    PauseWorkflowSignal,
    RescheduleWorkflowSignal,
    ResumeWorkflowSignal,
    UnblockWorkflowSignal,
)
from app.infrastructure.workflows.temporal.worker import connect_temporal_client


class TemporalClientWorkflowStarter:
    def __init__(self, client: Client, *, task_queue: str) -> None:
        self._client = client
        self._task_queue = task_queue

    async def start_lead_nurture_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        campaign_version_id: CampaignVersionId,
        temporal_workflow_id: str,
    ) -> None:
        await self._client.start_workflow(
            LeadNurtureWorkflow.run,
            LeadNurtureWorkflowInput(
                workspace_id=workspace_id,
                lead_id=lead_id,
                campaign_version_id=campaign_version_id,
            ),
            id=temporal_workflow_id,
            task_queue=self._task_queue,
        )

    async def signal_pause_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: PauseLeadNurtureWorkflowSignal,
    ) -> None:
        await self._signal(
            temporal_workflow_id=temporal_workflow_id,
            signal_name="pause-requested",
            signal_arg=PauseWorkflowSignal(
                workspace_id=signal.workspace_id,
                lead_id=signal.lead_id,
                occurred_at=signal.occurred_at.isoformat(),
                reason=signal.reason,
                actor_user_id=signal.actor_user_id,
                external_event_id=signal.external_event_id,
            ),
        )

    async def signal_resume_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: ResumeLeadNurtureWorkflowSignal,
    ) -> None:
        await self._signal(
            temporal_workflow_id=temporal_workflow_id,
            signal_name="resume-requested",
            signal_arg=ResumeWorkflowSignal(
                workspace_id=signal.workspace_id,
                lead_id=signal.lead_id,
                occurred_at=signal.occurred_at.isoformat(),
                reason=signal.reason,
                actor_user_id=signal.actor_user_id,
                external_event_id=signal.external_event_id,
            ),
        )

    async def signal_unblock_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: UnblockLeadNurtureWorkflowSignal,
    ) -> None:
        await self._signal(
            temporal_workflow_id=temporal_workflow_id,
            signal_name="blocked-review-completed",
            signal_arg=UnblockWorkflowSignal(
                workspace_id=signal.workspace_id,
                lead_id=signal.lead_id,
                occurred_at=signal.occurred_at.isoformat(),
                reason=signal.reason,
                actor_user_id=signal.actor_user_id,
                external_event_id=signal.external_event_id,
            ),
        )

    async def signal_inbound_processed_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: InboundProcessedLeadNurtureWorkflowSignal,
    ) -> None:
        await self._signal(
            temporal_workflow_id=temporal_workflow_id,
            signal_name="inbound-processed",
            signal_arg=InboundProcessedWorkflowSignal(
                workspace_id=signal.workspace_id,
                lead_id=signal.lead_id,
                occurred_at=signal.occurred_at.isoformat(),
                external_event_id=signal.external_event_id,
                conversation_id=signal.conversation_id,
                inbound_message_id=signal.inbound_message_id,
                workflow_transition_id=signal.workflow_transition_id,
                inbound_action=signal.inbound_action,
                reason=signal.reason,
            ),
        )

    async def signal_reschedule_lead_nurture_workflow(
        self,
        *,
        temporal_workflow_id: str,
        signal: RescheduleLeadNurtureWorkflowSignal,
    ) -> None:
        await self._signal(
            temporal_workflow_id=temporal_workflow_id,
            signal_name="reschedule-requested",
            signal_arg=RescheduleWorkflowSignal(
                workspace_id=signal.workspace_id,
                lead_id=signal.lead_id,
                occurred_at=signal.occurred_at.isoformat(),
                reason=signal.reason,
                actor_user_id=signal.actor_user_id,
                external_event_id=signal.external_event_id,
            ),
        )

    async def _signal(
        self,
        *,
        temporal_workflow_id: str,
        signal_name: str,
        signal_arg: object,
    ) -> None:
        handle = self._client.get_workflow_handle(temporal_workflow_id)
        try:
            await handle.signal(signal_name, signal_arg)
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                raise TemporalWorkflowNotFoundError(str(exc) or exc.__class__.__name__) from exc
            raise


async def build_temporal_workflow_starter(
    settings: Settings | None = None,
) -> TemporalWorkflowStarter:
    resolved_settings = settings or get_settings()
    client = await connect_temporal_client(resolved_settings)
    return TemporalClientWorkflowStarter(
        client,
        task_queue=resolved_settings.temporal_task_queue,
    )


async def build_temporal_workflow_signaler(
    settings: Settings | None = None,
) -> LeadNurtureWorkflowSignaler:
    resolved_settings = settings or get_settings()
    client = await connect_temporal_client(resolved_settings)
    return TemporalClientWorkflowStarter(
        client,
        task_queue=resolved_settings.temporal_task_queue,
    )
