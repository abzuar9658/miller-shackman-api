from collections.abc import Sequence
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from app.core.config import Settings, get_settings
from app.infrastructure.workflows.temporal.activities import (
    apply_inbound_workflow_transition_activity,
    execute_campaign_cadence_step_activity,
    record_pause_workflow_signal_activity,
    record_resume_workflow_signal_activity,
    schedule_next_campaign_cadence_step_activity,
)
from app.infrastructure.workflows.temporal.lead_nurture import LeadNurtureWorkflow
from app.infrastructure.workflows.temporal.smoke import SmokePingWorkflow, smoke_ping_activity


def _registered_workflows() -> Sequence[type[Any]]:
    return [SmokePingWorkflow, LeadNurtureWorkflow]


def _registered_activities() -> Sequence[Any]:
    return [
        smoke_ping_activity,
        apply_inbound_workflow_transition_activity,
        schedule_next_campaign_cadence_step_activity,
        execute_campaign_cadence_step_activity,
        record_pause_workflow_signal_activity,
        record_resume_workflow_signal_activity,
    ]


async def connect_temporal_client(settings: Settings | None = None) -> Client:
    resolved_settings = settings or get_settings()
    return await Client.connect(resolved_settings.temporal_address)


def build_temporal_worker(client: Client, settings: Settings | None = None) -> Worker:
    resolved_settings = settings or get_settings()
    return Worker(
        client,
        task_queue=resolved_settings.temporal_task_queue,
        workflows=_registered_workflows(),
        activities=_registered_activities(),
    )


async def run_temporal_worker(settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    client = await connect_temporal_client(resolved_settings)
    worker = build_temporal_worker(client, resolved_settings)
    await worker.run()
