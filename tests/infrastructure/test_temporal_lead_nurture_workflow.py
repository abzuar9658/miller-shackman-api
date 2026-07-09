from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.infrastructure.workflows.temporal.lead_nurture import (
    ExecuteCadenceStepResult,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
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

    async def fake_wait_condition(predicate: object) -> None:
        _ = predicate
        workflow_instance.close()

    async def fake_sleep(_: object) -> None:
        return None

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.sleep",
        fake_sleep,
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

    async def fake_wait_condition(predicate: object) -> None:
        _ = predicate
        if workflow_instance._send_blocked:
            wait_modes.append("blocked")
            workflow_instance._send_blocked = False
            return
        wait_modes.append("final")
        workflow_instance.close()

    async def fake_sleep(_: object) -> None:
        return None

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        fake_execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        fake_wait_condition,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.sleep",
        fake_sleep,
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
