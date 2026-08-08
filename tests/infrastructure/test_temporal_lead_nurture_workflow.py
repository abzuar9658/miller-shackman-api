from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.infrastructure.workflows.temporal.lead_nurture import (
    ExecuteCadenceStepResult,
    InboundProcessedWorkflowSignal,
    LeadNurtureExecutionMode,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
    LeadNurtureWorkflowSnapshot,
    PausedSearchOccurrenceExecutionInput,
    PausedSearchOccurrenceScheduleInput,
    PauseWorkflowSignal,
    RescheduleWorkflowSignal,
    ScheduleNextCadenceStepResult,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000004")
TRANSITION_ID = UUID("00000000-0000-0000-0000-000000000005")
STEP_ONE_ID = UUID("00000000-0000-0000-0000-000000000006")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000007")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000008")
NOW = datetime(2026, 7, 12, 15, 0, tzinfo=UTC)


async def test_lead_nurture_workflow_executes_year_long_wait_with_time_skipping() -> None:
    state = {"scheduled_calls": 0, "executed_calls": 0}
    task_queue = f"test-lead-nurture-long-wait-{uuid4()}"
    workflow_name = f"test-lead-nurture-long-wait-{uuid4()}"

    @activity.defn(name="schedule-next-campaign-cadence-step")
    async def schedule_activity(input_: dict[str, str]) -> dict[str, object]:
        occurred_at = datetime.fromisoformat(input_["occurred_at"])
        state["scheduled_calls"] += 1
        return {
            "status": "scheduled",
            "workflow_id": str(WORKFLOW_ID),
            "cadence_step_id": str(STEP_ONE_ID),
            "scheduled_for": (occurred_at + timedelta(days=365)).isoformat(),
            "skip_reason": None,
        }

    @activity.defn(name="execute-campaign-cadence-step")
    async def execute_activity(input_: dict[str, str]) -> dict[str, object]:
        state["executed_calls"] += 1
        return {
            "status": "sent",
            "workflow_id": str(WORKFLOW_ID),
            "transition_id": str(TRANSITION_ID),
            "cadence_step_id": str(STEP_ONE_ID),
            "outbound_message_id": str(MESSAGE_ID),
            "provider_message_id": "email-long-wait",
            "skip_reason": None,
            "has_more_steps": False,
        }

    env = await WorkflowEnvironment.start_time_skipping()
    async with env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[LeadNurtureWorkflow],
            activities=[schedule_activity, execute_activity],
        ):
            handle = await env.client.start_workflow(
                LeadNurtureWorkflow.run,
                LeadNurtureWorkflowInput(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    campaign_version_id=CAMPAIGN_VERSION_ID,
                ),
                id=workflow_name,
                task_queue=task_queue,
            )

            with env.auto_time_skipping_disabled():
                await env.sleep(1)
                waiting_snapshot = await handle.query("snapshot")

            assert waiting_snapshot["last_activity"] == "schedule_next_cadence_step"
            assert waiting_snapshot["last_activity_status"] == "scheduled"
            assert waiting_snapshot["current_step_id"] == str(STEP_ONE_ID)
            assert waiting_snapshot["workflow_id"] == str(WORKFLOW_ID)
            scheduled_for = datetime.fromisoformat(str(waiting_snapshot["scheduled_for"]))
            current_time = await env.get_current_time()
            assert scheduled_for - current_time >= timedelta(days=364, hours=23)

            await env.sleep(timedelta(days=365, seconds=1))
            await env.sleep(1)
            sent_snapshot = await handle.query("snapshot")

            assert sent_snapshot["last_activity"] == "execute_cadence_step"
            assert sent_snapshot["last_activity_status"] == "sent"
            assert sent_snapshot["provider_message_id"] == "email-long-wait"
            assert sent_snapshot["scheduled_for"] is None

            await handle.signal("close")
            result = await handle.result()

    assert state == {"scheduled_calls": 1, "executed_calls": 1}
    assert result.last_activity == "execute_cadence_step"
    assert result.last_activity_status == "sent"
    assert result.current_step_id == STEP_ONE_ID
    assert result.transition_id == TRANSITION_ID
    assert result.provider_message_id == "email-long-wait"


async def test_lead_nurture_workflow_loops_through_all_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_TWO_ID,
            scheduled_for=NOW,
        ),
    ]
    execute_results = [
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-1",
            has_more_steps=True,
        ),
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_TWO_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-2",
            has_more_steps=False,
        ),
    ]

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return schedule_results.pop(0)
        if name == "execute-campaign-cadence-step":
            return execute_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        _ = kwargs
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
    ]
    assert snapshot.current_step_id == STEP_TWO_ID
    assert snapshot.last_activity == "execute_cadence_step"
    assert snapshot.last_activity_status == "sent"
    assert snapshot.provider_message_id == "email-2"
    assert snapshot.scheduled_for is None


async def test_lead_nurture_workflow_retries_after_blocked_step_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []
    wait_modes: list[str] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
    ]
    execute_results = [
        ExecuteCadenceStepResult(
            status="rejected",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            skip_reason="channel_not_contactable",
        ),
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-1",
            has_more_steps=False,
        ),
    ]

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return schedule_results.pop(0)
        if name == "execute-campaign-cadence-step":
            return execute_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        _ = kwargs
        if workflow_instance._send_blocked:
            wait_modes.append("blocked")
            workflow_instance._send_blocked = False
            return
        wait_modes.append("final")
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert wait_modes == ["blocked", "final"]
    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
    ]
    assert snapshot.last_activity_status == "sent"
    assert snapshot.provider_message_id == "email-1"


async def test_lead_nurture_workflow_accepts_dict_activity_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        if name == "schedule-next-campaign-cadence-step":
            return {
                "status": "scheduled",
                "workflow_id": str(WORKFLOW_ID),
                "cadence_step_id": str(STEP_ONE_ID),
                "scheduled_for": NOW.isoformat(),
                "skip_reason": None,
            }
        if name == "execute-campaign-cadence-step":
            return {
                "status": "sent",
                "workflow_id": str(WORKFLOW_ID),
                "transition_id": str(TRANSITION_ID),
                "cadence_step_id": str(STEP_ONE_ID),
                "outbound_message_id": str(MESSAGE_ID),
                "provider_message_id": "email-1",
                "skip_reason": None,
                "has_more_steps": False,
            }
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        _ = kwargs
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert snapshot.current_step_id == STEP_ONE_ID
    assert snapshot.workflow_id == WORKFLOW_ID
    assert snapshot.transition_id == TRANSITION_ID
    assert snapshot.outbound_message_id == MESSAGE_ID
    assert snapshot.provider_message_id == "email-1"


async def test_lead_nurture_workflow_terminal_schedule_closes_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    retry_attempts: list[int | None] = []
    activity_calls: list[str] = []

    async def fake_execute_activity(name: str, arg: object, **kwargs: object) -> object:
        _ = arg
        activity_calls.append(name)
        retry_policy = kwargs.get("retry_policy")
        retry_attempts.append(getattr(retry_policy, "maximum_attempts", None))
        assert name == "schedule-next-campaign-cadence-step"
        return {
            "status": "terminal",
            "workflow_id": str(WORKFLOW_ID),
            "cadence_step_id": None,
            "scheduled_for": None,
            "skip_reason": "touch_limit_reached",
            "occurrence_id": None,
        }

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == ["schedule-next-campaign-cadence-step"]
    assert retry_attempts == [3]
    assert snapshot.last_activity_status == "terminal"
    assert snapshot.skip_reason == "touch_limit_reached"


async def test_lead_nurture_workflow_inbound_processed_signal_blocks_sends() -> None:
    workflow_instance = LeadNurtureWorkflow()
    workflow_instance._snapshot = LeadNurtureWorkflowSnapshot(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
    )

    workflow_instance.inbound_processed(
        InboundProcessedWorkflowSignal(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            occurred_at=NOW.isoformat(),
            external_event_id=UUID("00000000-0000-0000-0000-000000000009"),
            conversation_id=UUID("00000000-0000-0000-0000-00000000000a"),
            inbound_message_id=UUID("00000000-0000-0000-0000-00000000000b"),
            workflow_transition_id=UUID("00000000-0000-0000-0000-00000000000c"),
            inbound_action="human_handoff",
            reason="human_requested",
        )
    )

    assert workflow_instance._send_blocked is True
    assert workflow_instance._snapshot.last_signal == "inbound_processed"
    assert workflow_instance._snapshot.last_activity == "inbound_processed"
    assert workflow_instance._snapshot.last_activity_status == "blocked"
    assert workflow_instance._snapshot.skip_reason == "human_requested"


def test_lead_nurture_workflow_inbound_paused_search_continue_unblocks() -> None:
    workflow_instance = LeadNurtureWorkflow()
    workflow_instance._snapshot = LeadNurtureWorkflowSnapshot(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
    )

    workflow_instance.inbound_processed(
        InboundProcessedWorkflowSignal(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            occurred_at=NOW.isoformat(),
            inbound_action="continue_ai",
            reason="general_reply",
            paused_search_reply_decision="continue",
        )
    )

    assert workflow_instance._send_blocked is False
    assert workflow_instance._snapshot.last_activity_status == "unblocked"


async def test_lead_nurture_workflow_reschedule_signal_interrupts_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW.replace(hour=16),
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
    ]
    execute_results = [
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-1",
            has_more_steps=False,
        ),
    ]
    timed_waits = 0

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return schedule_results.pop(0)
        if name == "execute-campaign-cadence-step":
            return execute_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        nonlocal timed_waits
        _ = predicate
        if kwargs.get("timeout") is not None:
            timed_waits += 1
            workflow_instance.reschedule_requested(
                RescheduleWorkflowSignal(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    occurred_at=NOW.isoformat(),
                    reason="paused_search_profile_updated",
                )
            )
            return
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert timed_waits == 1
    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
    ]
    assert snapshot.last_signal == "reschedule_requested"
    assert snapshot.last_activity == "execute_cadence_step"
    assert snapshot.last_activity_status == "sent"


async def test_lead_nurture_workflow_duplicate_reschedule_signals_recompute_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW.replace(hour=16),
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
    ]
    execute_results = [
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-dup",
            has_more_steps=False,
        ),
    ]
    timed_waits = 0

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return schedule_results.pop(0)
        if name == "execute-campaign-cadence-step":
            return execute_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        nonlocal timed_waits
        _ = predicate
        if kwargs.get("timeout") is not None:
            timed_waits += 1
            workflow_instance.reschedule_requested(
                RescheduleWorkflowSignal(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    occurred_at=NOW.isoformat(),
                    reason="paused_search_profile_updated",
                )
            )
            workflow_instance.reschedule_requested(
                RescheduleWorkflowSignal(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    occurred_at=NOW.isoformat(),
                    reason="paused_search_profile_updated_duplicate",
                )
            )
            return
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert timed_waits == 1
    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
    ]
    assert snapshot.last_activity_status == "sent"
    assert snapshot.provider_message_id == "email-dup"


async def test_lead_nurture_workflow_recomputes_after_skipped_stale_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ONE_ID,
            scheduled_for=NOW,
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_TWO_ID,
            scheduled_for=NOW,
        ),
    ]
    execute_results = [
        ExecuteCadenceStepResult(
            status="skipped",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_ONE_ID,
            skip_reason="Paused-search timing changed before execution.",
        ),
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            transition_id=TRANSITION_ID,
            cadence_step_id=STEP_TWO_ID,
            outbound_message_id=MESSAGE_ID,
            provider_message_id="email-stale-recomputed",
            has_more_steps=False,
        ),
    ]

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return schedule_results.pop(0)
        if name == "execute-campaign-cadence-step":
            return execute_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        _ = kwargs
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
    ]
    assert snapshot.current_step_id == STEP_TWO_ID
    assert snapshot.last_activity == "execute_cadence_step"
    assert snapshot.last_activity_status == "sent"
    assert snapshot.provider_message_id == "email-stale-recomputed"


async def test_lead_nurture_workflow_pause_signal_during_wait_blocks_due_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return ScheduleNextCadenceStepResult(
                status="scheduled",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ONE_ID,
                scheduled_for=NOW.replace(hour=16),
            )
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        if kwargs.get("timeout") is not None:
            workflow_instance.pause_requested(
                PauseWorkflowSignal(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    occurred_at=NOW.isoformat(),
                    reason="crm_note_added",
                )
            )
            return
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == ["schedule-next-campaign-cadence-step"]
    assert snapshot.last_signal == "pause_requested"
    assert snapshot.last_activity == "pause_requested"
    assert snapshot.last_activity_status == "blocked"
    assert snapshot.skip_reason == "crm_note_added"


async def test_lead_nurture_workflow_inbound_signal_during_wait_blocks_due_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return ScheduleNextCadenceStepResult(
                status="scheduled",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ONE_ID,
                scheduled_for=NOW.replace(hour=16),
            )
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        if kwargs.get("timeout") is not None:
            workflow_instance.inbound_processed(
                InboundProcessedWorkflowSignal(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    occurred_at=NOW.isoformat(),
                    inbound_action="human_handoff",
                    reason="meaningful_reply_requires_reclassification",
                )
            )
            return
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == ["schedule-next-campaign-cadence-step"]
    assert snapshot.last_signal == "inbound_processed"
    assert snapshot.last_activity == "inbound_processed"
    assert snapshot.last_activity_status == "blocked"
    assert snapshot.skip_reason == "meaningful_reply_requires_reclassification"


async def test_lead_nurture_workflow_times_out_uncertain_send_and_stays_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        del arg
        activity_calls.append(name)
        if name == "schedule-next-campaign-cadence-step":
            return ScheduleNextCadenceStepResult(
                status="scheduled",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ONE_ID,
                scheduled_for=NOW,
                occurrence_id=STEP_TWO_ID,
            )
        if name == "execute-campaign-cadence-step":
            return ExecuteCadenceStepResult(
                status="uncertain",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ONE_ID,
                occurrence_id=STEP_TWO_ID,
            )
        if name == "timeout-uncertain-paused-search-occurrence":
            return None
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        if kwargs.get("timeout") is not None:
            raise TimeoutError
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
        )
    )

    assert activity_calls == [
        "schedule-next-campaign-cadence-step",
        "execute-campaign-cadence-step",
        "timeout-uncertain-paused-search-occurrence",
    ]
    assert snapshot.last_activity_status == "uncertain"
    assert snapshot.occurrence_id == STEP_TWO_ID


async def test_recurring_mode_uses_pinned_occurrence_activity_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    activity_calls: list[str] = []

    async def fake_execute_activity(name: str, arg: object, **_: object) -> object:
        del arg
        activity_calls.append(name)
        if name == "schedule-next-paused-search-occurrence":
            return {
                "status": "scheduled",
                "workflow_id": str(WORKFLOW_ID),
                "cadence_step_id": str(STEP_ONE_ID),
                "scheduled_for": NOW.isoformat(),
                "occurrence_id": str(STEP_TWO_ID),
            }
        if name == "execute-paused-search-occurrence":
            return {
                "status": "sent",
                "workflow_id": str(WORKFLOW_ID),
                "cadence_step_id": str(STEP_ONE_ID),
                "occurrence_id": str(STEP_TWO_ID),
                "has_more_steps": False,
                "accepted_logical_touch": True,
            }
        raise AssertionError(f"unexpected activity {name}")

    async def fake_wait_condition(predicate: object, **kwargs: object) -> None:
        _ = predicate
        _ = kwargs
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.now",
        lambda: NOW,
    )

    snapshot = await workflow_instance.run(
        LeadNurtureWorkflowInput(
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            campaign_version_id=CAMPAIGN_VERSION_ID,
            workflow_id=WORKFLOW_ID,
            execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
            paused_search_track_version_id=STEP_ONE_ID,
        )
    )

    assert activity_calls == [
        "schedule-next-paused-search-occurrence",
        "execute-paused-search-occurrence",
    ]
    assert snapshot.execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
    assert snapshot.paused_search_track_version_id == STEP_ONE_ID
    assert snapshot.accepted_touch_count == 1


async def test_recurring_mode_survives_long_wait_and_replays_activity_contract() -> None:
    state = {"scheduled": 0, "executed": 0}
    task_queue = f"test-paused-search-recurring-{uuid4()}"
    workflow_name = f"test-paused-search-recurring-{uuid4()}"

    @activity.defn(name="schedule-next-paused-search-occurrence")
    async def schedule_activity(
        input_: PausedSearchOccurrenceScheduleInput,
    ) -> dict[str, object]:
        occurred_at = input_.occurred_at
        state["scheduled"] += 1
        return {
            "status": "scheduled",
            "workflow_id": str(WORKFLOW_ID),
            "cadence_step_id": str(STEP_ONE_ID),
            "scheduled_for": (occurred_at + timedelta(days=30)).isoformat(),
            "occurrence_id": str(STEP_TWO_ID),
        }

    @activity.defn(name="execute-paused-search-occurrence")
    async def execute_activity(
        input_: PausedSearchOccurrenceExecutionInput,
    ) -> dict[str, object]:
        del input_
        state["executed"] += 1
        return {
            "status": "sent",
            "workflow_id": str(WORKFLOW_ID),
            "cadence_step_id": str(STEP_ONE_ID),
            "occurrence_id": str(STEP_TWO_ID),
            "has_more_steps": False,
            "accepted_logical_touch": True,
        }

    env = await WorkflowEnvironment.start_time_skipping()
    async with env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[LeadNurtureWorkflow],
            activities=[schedule_activity, execute_activity],
        ):
            handle = await env.client.start_workflow(
                LeadNurtureWorkflow.run,
                LeadNurtureWorkflowInput(
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    campaign_version_id=CAMPAIGN_VERSION_ID,
                    workflow_id=WORKFLOW_ID,
                    execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                    paused_search_track_version_id=STEP_ONE_ID,
                ),
                id=workflow_name,
                task_queue=task_queue,
            )

            with env.auto_time_skipping_disabled():
                await env.sleep(1)
                waiting_snapshot = await handle.query("snapshot")
            assert waiting_snapshot["execution_mode"] == "paused_search_recurring"
            assert waiting_snapshot["last_activity_status"] == "scheduled"

            await env.sleep(timedelta(days=30, seconds=1))
            await env.sleep(1)
            sent_snapshot = await handle.query("snapshot")
            assert sent_snapshot["last_activity_status"] == "sent"
            await handle.signal("close")
            result = await handle.result()

    assert state == {"scheduled": 1, "executed": 1}
    assert result.execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
    assert result.accepted_touch_count == 1
