from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.application.use_cases.seed_default_paused_search_tracks import (
    DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES,
    _DefaultPausedSearchTrackTemplate,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTimingReasonCode,
    PausedSearchTrackFamily,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    capability_profile_for_reason,
    plan_next_paused_search_occurrence,
    plan_paused_search_next_action,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import (
    LeadPausedSearchProfile,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.infrastructure.workflows.temporal.lead_nurture import (
    InboundProcessedWorkflowSignal,
    LeadNurtureExecutionMode,
    LeadNurtureWorkflow,
    LeadNurtureWorkflowInput,
    PausedSearchOccurrenceExecutionInput,
    PausedSearchOccurrenceScheduleInput,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000701")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000702")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000703")
NOW = datetime(2026, 7, 27, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _TrackCase:
    reason_code: PausedSearchReasonCode
    track_version_id: UUID
    maintenance_interval_days: int
    reactivation_window_days: int
    max_total_touches: int
    max_duration_days: int


def _track_case(template: _DefaultPausedSearchTrackTemplate) -> _TrackCase:
    reason_code = template.reason_code
    capability_profile = capability_profile_for_reason(reason_code)
    assert capability_profile is not None
    return _TrackCase(
        reason_code=reason_code,
        track_version_id=uuid5(NAMESPACE_URL, f"paused-search:{reason_code.value}"),
        maintenance_interval_days=template.maintenance_interval_days,
        reactivation_window_days=template.reactivation_window_days,
        max_total_touches=template.max_total_touches,
        max_duration_days=capability_profile.max_duration_days,
    )


TRACK_CASES = tuple(_track_case(template) for template in DEFAULT_PAUSED_SEARCH_TRACK_TEMPLATES)


def _planner_fixtures(
    track_case: _TrackCase,
) -> tuple[
    LeadPausedSearchProfile,
    PausedSearchTrackVersion,
    PausedSearchTrackStep,
    LeadWorkflow,
]:
    track_id = uuid5(NAMESPACE_URL, f"track:{track_case.reason_code.value}")
    step_id = uuid5(NAMESPACE_URL, f"planner-step:{track_case.reason_code.value}")
    profile = LeadPausedSearchProfile(
        paused_search_active=True,
        pause_reason_code=track_case.reason_code,
        reengagement_not_before=NOW + timedelta(days=track_case.max_duration_days),
        paused_search_source=PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
        paused_search_recorded_at=NOW,
    )
    version = PausedSearchTrackVersion(
        track_version_id=track_case.track_version_id,
        workspace_id=WORKSPACE_ID,
        track_id=track_id,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        default_for_reason_codes=(track_case.reason_code,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=track_case.maintenance_interval_days,
        reactivation_window_days=track_case.reactivation_window_days,
        max_total_touches=track_case.max_total_touches,
        requires_review_before_publish=False,
        created_by_user_id=uuid5(NAMESPACE_URL, "paused-search-test-user"),
        created_at=NOW,
        published_at=NOW,
        max_duration_days=track_case.max_duration_days,
    )
    step = PausedSearchTrackStep(
        step_id=step_id,
        workspace_id=WORKSPACE_ID,
        track_version_id=track_case.track_version_id,
        step_order=1,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        delay_hours=24 * track_case.maintenance_interval_days,
        message_goal="Check in on paused-search timing.",
        template_key=f"paused-search-{track_case.reason_code.value}-maintenance-email-1",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
        interval_days=track_case.maintenance_interval_days,
        max_occurrences=2,
    )
    workflow = LeadWorkflow(
        workflow_id=uuid5(NAMESPACE_URL, f"planner-workflow:{track_case.reason_code.value}"),
        temporal_workflow_id=f"planner-{track_case.reason_code.value}",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=uuid5(NAMESPACE_URL, "paused-search-enrollment"),
        campaign_id=uuid5(NAMESPACE_URL, "paused-search-campaign"),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=track_case.track_version_id,
        paused_search_track_step_id=step_id,
    )
    return profile, version, step, workflow


@pytest.mark.parametrize(
    "track_case",
    TRACK_CASES,
    ids=lambda case: case.reason_code.value,
)
def test_each_track_honors_recurring_interval_and_terminal_limits(
    track_case: _TrackCase,
) -> None:
    profile, version, step, workflow = _planner_fixtures(track_case)

    first = plan_next_paused_search_occurrence(
        profile=profile,
        track_version=version,
        step=step,
        steps=(step,),
        workflow=workflow,
        timezone="America/Chicago",
        now=NOW,
        occurrence_number=1,
        previous_due_at=None,
    )
    assert first.reason_code is PausedSearchTimingReasonCode.SCHEDULED
    assert first.due_at is not None
    chicago = ZoneInfo("America/Chicago")
    expected_first_date = NOW.astimezone(chicago).date() + timedelta(
        days=track_case.maintenance_interval_days
    )
    assert first.due_at.astimezone(chicago).date() == expected_first_date

    second = plan_next_paused_search_occurrence(
        profile=profile,
        track_version=version,
        step=step,
        steps=(step,),
        workflow=workflow,
        timezone="America/Chicago",
        now=first.due_at or NOW,
        occurrence_number=2,
        previous_due_at=first.due_at,
    )
    assert second.reason_code is PausedSearchTimingReasonCode.SCHEDULED
    assert second.due_at is not None
    expected_second_date = first.due_at.astimezone(chicago).date() + timedelta(
        days=track_case.maintenance_interval_days
    )
    assert second.due_at.astimezone(chicago).date() == expected_second_date

    occurrence_limit = plan_next_paused_search_occurrence(
        profile=profile,
        track_version=version,
        step=step,
        steps=(step,),
        workflow=workflow,
        timezone="America/Chicago",
        now=second.due_at or NOW,
        occurrence_number=3,
        previous_due_at=second.due_at,
    )
    assert occurrence_limit.reason_code is PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED

    touch_limit = plan_paused_search_next_action(
        profile=profile,
        track_version=version,
        steps=(step,),
        workflow=replace(workflow, logical_touch_count=track_case.max_total_touches),
        timezone="America/Chicago",
        now=NOW,
    )
    assert touch_limit.reason_code is PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED

    reactivation_step = replace(
        step,
        step_id=uuid5(NAMESPACE_URL, f"reactivation-step:{track_case.reason_code.value}"),
        step_order=2,
        phase=PausedSearchTrackStepPhase.REACTIVATION,
        delay_hours=0,
    )
    duration_expired = plan_next_paused_search_occurrence(
        profile=profile,
        track_version=version,
        step=reactivation_step,
        steps=(step, reactivation_step),
        workflow=workflow,
        timezone="America/Chicago",
        now=NOW + timedelta(days=track_case.max_duration_days + 1),
        occurrence_number=1,
        previous_due_at=None,
    )
    assert duration_expired.reason_code is PausedSearchTimingReasonCode.DURATION_EXPIRED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "track_case",
    TRACK_CASES,
    ids=lambda case: case.reason_code.value,
)
async def test_each_seeded_paused_search_track_sends_after_configured_interval(
    track_case: _TrackCase,
) -> None:
    scheduled_inputs: list[PausedSearchOccurrenceScheduleInput] = []
    executed_inputs: list[PausedSearchOccurrenceExecutionInput] = []
    task_queue = f"paused-search-track-{track_case.reason_code.value}"
    workflow_id = uuid5(NAMESPACE_URL, f"workflow:{track_case.reason_code.value}")
    step_id = uuid5(NAMESPACE_URL, f"step:{track_case.reason_code.value}")
    occurrence_id = uuid5(NAMESPACE_URL, f"occurrence:{track_case.reason_code.value}")

    @activity.defn(name="schedule-next-paused-search-occurrence")
    async def schedule_activity(
        input_: PausedSearchOccurrenceScheduleInput,
    ) -> dict[str, object]:
        scheduled_inputs.append(input_)
        scheduled_for = input_.occurred_at + timedelta(days=track_case.maintenance_interval_days)
        return {
            "status": "scheduled",
            "workflow_id": str(workflow_id),
            "cadence_step_id": str(step_id),
            "scheduled_for": scheduled_for.isoformat(),
            "occurrence_id": str(occurrence_id),
        }

    @activity.defn(name="execute-paused-search-occurrence")
    async def execute_activity(
        input_: PausedSearchOccurrenceExecutionInput,
    ) -> dict[str, object]:
        executed_inputs.append(input_)
        return {
            "status": "sent",
            "workflow_id": str(workflow_id),
            "cadence_step_id": str(step_id),
            "occurrence_id": str(occurrence_id),
            "provider_message_id": f"email-{track_case.reason_code.value}",
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
                    workflow_id=workflow_id,
                    execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                    paused_search_track_version_id=track_case.track_version_id,
                ),
                id=f"paused-search-{track_case.reason_code.value}",
                task_queue=task_queue,
            )

            with env.auto_time_skipping_disabled():
                await env.sleep(1)
                waiting = await handle.query("snapshot")

            assert waiting["last_activity_status"] == "scheduled"
            assert waiting["paused_search_track_version_id"] == str(track_case.track_version_id)
            scheduled_for = datetime.fromisoformat(str(waiting["scheduled_for"]))
            assert scheduled_for == scheduled_inputs[0].occurred_at + timedelta(
                days=track_case.maintenance_interval_days
            )

            await env.sleep(timedelta(days=track_case.maintenance_interval_days, seconds=1))
            await env.sleep(1)
            sent = await handle.query("snapshot")

            assert sent["last_activity_status"] == "sent"
            assert sent["provider_message_id"] == f"email-{track_case.reason_code.value}"
            assert sent["accepted_touch_count"] == 1
            await handle.signal("close")
            result = await handle.result()

    assert len(scheduled_inputs) == 1
    assert len(executed_inputs) == 1
    assert scheduled_inputs[0].paused_search_track_version_id == track_case.track_version_id
    assert executed_inputs[0].occurrence_id == occurrence_id
    assert result.accepted_touch_count == 1


@pytest.mark.asyncio
async def test_inbound_reply_during_paused_search_wait_blocks_due_send() -> None:
    executed = 0
    task_queue = "paused-search-inbound-interruption"
    workflow_id = UUID("00000000-0000-0000-0000-000000000704")
    track_version_id = UUID("00000000-0000-0000-0000-000000000705")
    step_id = UUID("00000000-0000-0000-0000-000000000706")
    occurrence_id = UUID("00000000-0000-0000-0000-000000000707")

    @activity.defn(name="schedule-next-paused-search-occurrence")
    async def schedule_activity(
        input_: PausedSearchOccurrenceScheduleInput,
    ) -> dict[str, object]:
        return {
            "status": "scheduled",
            "workflow_id": str(workflow_id),
            "cadence_step_id": str(step_id),
            "scheduled_for": (input_.occurred_at + timedelta(days=30)).isoformat(),
            "occurrence_id": str(occurrence_id),
        }

    @activity.defn(name="execute-paused-search-occurrence")
    async def execute_activity(
        input_: PausedSearchOccurrenceExecutionInput,
    ) -> dict[str, object]:
        nonlocal executed
        del input_
        executed += 1
        return {"status": "sent", "has_more_steps": False}

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
                    workflow_id=workflow_id,
                    execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                    paused_search_track_version_id=track_version_id,
                ),
                id="paused-search-inbound-interruption",
                task_queue=task_queue,
            )

            with env.auto_time_skipping_disabled():
                await env.sleep(1)
                await handle.signal(
                    "inbound-processed",
                    InboundProcessedWorkflowSignal(
                        workspace_id=WORKSPACE_ID,
                        lead_id=LEAD_ID,
                        occurred_at=NOW.isoformat(),
                        inbound_action="human_handoff",
                        reason="meaningful_reply_requires_reclassification",
                    ),
                )
                await env.sleep(1)
                blocked = await handle.query("snapshot")

            assert blocked["last_signal"] == "inbound_processed"
            assert blocked["last_activity_status"] == "blocked"
            assert blocked["skip_reason"] == "meaningful_reply_requires_reclassification"

            await env.sleep(timedelta(days=31))
            await env.sleep(1)
            still_blocked = await handle.query("snapshot")
            assert still_blocked["last_activity_status"] == "blocked"
            assert executed == 0
            await handle.signal("close")
            result = await handle.result()

    assert result.last_signal == "inbound_processed"
    assert executed == 0
