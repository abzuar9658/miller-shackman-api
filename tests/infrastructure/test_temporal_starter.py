from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from app.application.ports.temporal import (
    InboundProcessedLeadNurtureWorkflowSignal,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowNotFoundError,
)
from app.infrastructure.workflows.temporal.lead_nurture import (
    ConfigurePausedSearchWorkflowSignal,
    InboundProcessedWorkflowSignal,
    PauseWorkflowSignal,
    RescheduleWorkflowSignal,
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
    assert captured["signal_method"] == "pause-requested"
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, PauseWorkflowSignal)
    assert signal_arg.reason == "crm_note_added"
    assert signal_arg.occurred_at == "2026-07-12T12:00:00+00:00"


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
    assert captured["signal_method"] == "resume-requested"
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, ResumeWorkflowSignal)
    assert signal_arg.reason == "agent approved follow-up"
    assert signal_arg.occurred_at == "2026-07-12T12:05:00+00:00"


async def test_temporal_workflow_starter_sends_inbound_processed_signal() -> None:
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

    signal = InboundProcessedLeadNurtureWorkflowSignal(
        workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
        lead_id=UUID("60000000-0000-0000-0000-000000000002"),
        occurred_at=datetime(2026, 7, 12, 12, 10, tzinfo=UTC),
        external_event_id=UUID("60000000-0000-0000-0000-000000000005"),
        conversation_id=UUID("60000000-0000-0000-0000-000000000006"),
        inbound_message_id=UUID("60000000-0000-0000-0000-000000000007"),
        workflow_transition_id=UUID("60000000-0000-0000-0000-000000000008"),
        inbound_action="human_handoff",
        reason="human_requested",
    )
    await starter.signal_inbound_processed_lead_nurture_workflow(
        temporal_workflow_id="workflow-789",
        signal=signal,
    )

    assert captured["workflow_id"] == "workflow-789"
    assert captured["signal_method"] == "inbound-processed"
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, InboundProcessedWorkflowSignal)
    assert signal_arg.inbound_action == "human_handoff"
    assert signal_arg.reason == "human_requested"
    assert signal_arg.occurred_at == "2026-07-12T12:10:00+00:00"


async def test_temporal_workflow_starter_sends_reschedule_signal() -> None:
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

    await starter.signal_reschedule_lead_nurture_workflow(
        temporal_workflow_id="workflow-999",
        signal=RescheduleLeadNurtureWorkflowSignal(
            workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
            lead_id=UUID("60000000-0000-0000-0000-000000000002"),
            occurred_at=datetime(2026, 7, 12, 12, 15, tzinfo=UTC),
            reason="paused_search_profile_updated",
            external_event_id=UUID("60000000-0000-0000-0000-000000000009"),
        ),
    )

    assert captured["workflow_id"] == "workflow-999"
    assert captured["signal_method"] == "reschedule-requested"
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, RescheduleWorkflowSignal)
    assert signal_arg.reason == "paused_search_profile_updated"
    assert signal_arg.occurred_at == "2026-07-12T12:15:00+00:00"


async def test_temporal_workflow_starter_configures_paused_search_workflow() -> None:
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
    workflow_id = UUID("60000000-0000-0000-0000-000000000010")
    track_version_id = UUID("60000000-0000-0000-0000-000000000011")

    await starter.configure_paused_search_workflow(
        temporal_workflow_id="workflow-configure",
        workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
        lead_id=UUID("60000000-0000-0000-0000-000000000002"),
        workflow_id=workflow_id,
        paused_search_track_version_id=track_version_id,
        occurred_at=datetime(2026, 7, 12, 12, 20, tzinfo=UTC),
        reason="operator_selected_paused_search_track",
    )

    assert captured["workflow_id"] == "workflow-configure"
    assert captured["signal_method"] == "paused-search-configured"
    signal_arg = captured["signal_arg"]
    assert isinstance(signal_arg, ConfigurePausedSearchWorkflowSignal)
    assert signal_arg.workflow_id == workflow_id
    assert signal_arg.paused_search_track_version_id == track_version_id
    assert signal_arg.occurred_at == "2026-07-12T12:20:00+00:00"


async def test_temporal_workflow_starter_translates_not_found_signal_errors() -> None:
    class FakeHandle:
        async def signal(self, signal_method: object, signal_arg: object) -> None:  # noqa: ARG002
            raise RPCError("workflow missing", RPCStatusCode.NOT_FOUND, b"")

    class FakeClient:
        def get_workflow_handle(self, workflow_id: str) -> FakeHandle:  # noqa: ARG002
            return FakeHandle()

    starter = TemporalClientWorkflowStarter(
        cast(Client, FakeClient()),
        task_queue="test-task-queue",
    )

    signal = InboundProcessedLeadNurtureWorkflowSignal(
        workspace_id=UUID("60000000-0000-0000-0000-000000000001"),
        lead_id=UUID("60000000-0000-0000-0000-000000000002"),
        occurred_at=datetime(2026, 7, 12, 12, 10, tzinfo=UTC),
    )

    try:
        await starter.signal_inbound_processed_lead_nurture_workflow(
            temporal_workflow_id="workflow-missing",
            signal=signal,
        )
    except TemporalWorkflowNotFoundError as exc:
        assert "workflow missing" in str(exc)
    else:
        raise AssertionError("expected TemporalWorkflowNotFoundError")
