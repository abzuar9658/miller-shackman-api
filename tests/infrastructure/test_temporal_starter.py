from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from temporalio.client import Client

from app.application.ports.temporal import (
    PauseLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
)
from app.infrastructure.workflows.temporal.lead_nurture import (
    LeadNurtureWorkflow,
    PauseWorkflowSignal,
    ResumeWorkflowSignal,
)
from app.infrastructure.workflows.temporal.starter import TemporalClientWorkflowStarter


async def test_temporal_workflow_starter_sends_pause_signal() -> None:
    captured: dict[str, object] = {}

    class FakeHandle:
        async def signal(self, signal_method: object, signal_arg: object) -> None:
            captured["signal_method"] = signal_method
            captured["signal_arg"] = signal_arg

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
            captured["workflow_id"] = workflow_id
            return FakeHandle()

    starter = TemporalClientWorkflowStarter(
        cast(Client, FakeClient()),
        task_queue="test-task-queue",
    )

    await starter.signal_pause_lead_nurture_workflow(
        temporal_workflow_id="workflow-123",
        signal=PauseLeadNurtureWorkflowSignal(
            workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
            lead_id=UUID("60000000-0000-0000-0000-000000000002"),
            occurred_at=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
            reason="crm_note_added",
            external_event_id=UUID("60000000-0000-0000-0000-000000000003"),
        ),
    )

    assert captured["workflow_id"] == "workflow-123"
    assert captured["signal_method"] == LeadNurtureWorkflow.pause_requested
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, PauseWorkflowSignal)
    assert signal_arg.reason == "crm_note_added"


async def test_temporal_workflow_starter_sends_resume_signal() -> None:
    captured: dict[str, object] = {}

    class FakeHandle:
        async def signal(self, signal_method: object, signal_arg: object) -> None:
            captured["signal_method"] = signal_method
            captured["signal_arg"] = signal_arg

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
            captured["workflow_id"] = workflow_id
            return FakeHandle()

    starter = TemporalClientWorkflowStarter(
        cast(Client, FakeClient()),
        task_queue="test-task-queue",
    )

    await starter.signal_resume_lead_nurture_workflow(
        temporal_workflow_id="workflow-456",
        signal=ResumeLeadNurtureWorkflowSignal(
            workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
            lead_id=UUID("60000000-0000-0000-0000-000000000002"),
            occurred_at=datetime(2026, 7, 12, 12, 5, tzinfo=UTC),
            reason="agent approved follow-up",
            external_event_id=UUID("60000000-0000-0000-0000-000000000004"),
        ),
    )

    assert captured["workflow_id"] == "workflow-456"
    assert captured["signal_method"] == LeadNurtureWorkflow.resume_requested
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, ResumeWorkflowSignal)
    assert signal_arg.reason == "agent approved follow-up"
