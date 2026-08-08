from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.infrastructure.workflows.temporal.lead_nurture import (
    ExecuteCadenceStepResult,
    LeadNurtureExecutionMode,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
    PausedSearchOccurrenceExecutionInput,
    PausedSearchOccurrenceScheduleInput,
    ScheduleNextCadenceStepResult,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000030")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000031")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000032")
TRACK_VERSION_ID = UUID("00000000-0000-0000-0000-000000000033")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000034")
STEP_ID = UUID("00000000-0000-0000-0000-000000000035")
STEP_TWO_ID = UUID("00000000-0000-0000-0000-000000000037")
OCCURRENCE_ID = UUID("00000000-0000-0000-0000-000000000036")
OCCURRENCE_TWO_ID = UUID("00000000-0000-0000-0000-000000000038")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


async def test_recurring_temporal_matrix_schedules_the_pinned_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    calls: list[tuple[str, object]] = []

    async def execute_activity(name: str, argument: object, **_: object) -> object:
        calls.append((name, argument))
        if name == "schedule-next-paused-search-occurrence":
            return ScheduleNextCadenceStepResult(
                status="scheduled",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ID,
                scheduled_for=NOW,
                occurrence_id=OCCURRENCE_ID,
            )
        if name == "execute-paused-search-occurrence":
            return ExecuteCadenceStepResult(
                status="sent",
                workflow_id=WORKFLOW_ID,
                cadence_step_id=STEP_ID,
                occurrence_id=OCCURRENCE_ID,
                provider_message_id="provider-recurring-1",
                has_more_steps=False,
            )
        raise AssertionError(f"unexpected activity {name}")

    async def wait_condition(predicate: object, **_: object) -> None:
        del predicate
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        wait_condition,
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
            paused_search_track_version_id=TRACK_VERSION_ID,
        )
    )

    assert [name for name, _ in calls] == [
        "schedule-next-paused-search-occurrence",
        "execute-paused-search-occurrence",
    ]
    schedule_input = cast(PausedSearchOccurrenceScheduleInput, calls[0][1])
    assert schedule_input.paused_search_track_version_id == TRACK_VERSION_ID
    assert snapshot.occurrence_id == OCCURRENCE_ID
    assert snapshot.provider_message_id == "provider-recurring-1"


async def test_recurring_temporal_matrix_runs_sequential_steps_then_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_instance = LeadNurtureWorkflow()
    calls: list[tuple[str, object]] = []
    schedule_results = [
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ID,
            scheduled_for=NOW,
            occurrence_id=OCCURRENCE_ID,
        ),
        ScheduleNextCadenceStepResult(
            status="scheduled",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_TWO_ID,
            scheduled_for=NOW,
            occurrence_id=OCCURRENCE_TWO_ID,
        ),
    ]
    execution_results = [
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_ID,
            occurrence_id=OCCURRENCE_ID,
            provider_message_id="phase4-email",
            has_more_steps=True,
        ),
        ExecuteCadenceStepResult(
            status="sent",
            workflow_id=WORKFLOW_ID,
            cadence_step_id=STEP_TWO_ID,
            occurrence_id=OCCURRENCE_TWO_ID,
            provider_message_id="phase4-sms",
            has_more_steps=False,
        ),
    ]

    async def execute_activity(name: str, argument: object, **_: object) -> object:
        calls.append((name, argument))
        if name == "schedule-next-paused-search-occurrence":
            return schedule_results.pop(0)
        if name == "execute-paused-search-occurrence":
            return execution_results.pop(0)
        raise AssertionError(f"unexpected activity {name}")

    async def wait_condition(predicate: object, **_: object) -> None:
        del predicate
        workflow_instance.close()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.execute_activity",
        execute_activity,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.lead_nurture.workflow.wait_condition",
        wait_condition,
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
            paused_search_track_version_id=TRACK_VERSION_ID,
        )
    )

    assert [name for name, _ in calls] == [
        "schedule-next-paused-search-occurrence",
        "execute-paused-search-occurrence",
        "schedule-next-paused-search-occurrence",
        "execute-paused-search-occurrence",
    ]
    first_execution = cast(PausedSearchOccurrenceExecutionInput, calls[1][1])
    second_execution = cast(PausedSearchOccurrenceExecutionInput, calls[3][1])
    assert first_execution.occurrence_id == OCCURRENCE_ID
    assert second_execution.occurrence_id == OCCURRENCE_TWO_ID
    assert snapshot.provider_message_id == "phase4-sms"
    assert snapshot.occurrence_id == OCCURRENCE_TWO_ID
    assert schedule_results == []
    assert execution_results == []