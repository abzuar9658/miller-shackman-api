from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy


class LeadNurtureExecutionMode(StrEnum):
    STANDARD_CADENCE = "standard_cadence"
    PAUSED_SEARCH_RECURRING = "paused_search_recurring"


@dataclass(frozen=True)
class LeadNurtureWorkflowInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    workflow_id: UUID | None = None
    execution_mode: LeadNurtureExecutionMode = LeadNurtureExecutionMode.STANDARD_CADENCE
    paused_search_track_version_id: UUID | None = None


@dataclass(frozen=True)
class ScheduleNextCadenceStepInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class PausedSearchOccurrenceScheduleInput(ScheduleNextCadenceStepInput):
    workflow_id: UUID | None = None
    paused_search_track_version_id: UUID | None = None
    current_occurrence_id: UUID | None = None


@dataclass(frozen=True)
class ScheduleNextCadenceStepResult:
    status: str
    workflow_id: UUID | None = None
    cadence_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    skip_reason: str | None = None
    occurrence_id: UUID | None = None
    planner_outcome: str | None = None
    phase: str | None = None
    occurrence_number: int | None = None
    terminal: bool = False
    expired: bool = False


@dataclass(frozen=True)
class ExecuteCadenceStepInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    cadence_step_id: UUID
    scheduled_for: datetime
    occurred_at: datetime


@dataclass(frozen=True)
class PausedSearchOccurrenceExecutionInput(ExecuteCadenceStepInput):
    occurrence_id: UUID | None = None
    revalidate_all_pre_send_rules: bool = True


@dataclass(frozen=True)
class ExecuteCadenceStepResult:
    status: str
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    cadence_step_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    skip_reason: str | None = None
    has_more_steps: bool = False
    occurrence_id: UUID | None = None
    occurrence_status: str | None = None
    accepted_logical_touch: bool = False
    next_cursor_decision: str | None = None
    notification_events: tuple[str, ...] = ()
    fallback_used: bool = False
    reconciliation_id: UUID | None = None
    provider_failure_id: UUID | None = None
    request_id: UUID | None = None


@dataclass(frozen=True)
class TimeoutUncertainOccurrenceInput:
    workspace_id: UUID
    occurrence_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class TimeoutUncertainReconciliationInput:
    workspace_id: UUID
    reconciliation_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class PauseWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: str
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class ResumeWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: str
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class UnblockWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: str
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class InboundProcessedWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: str
    external_event_id: UUID | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    inbound_action: str | None = None
    reason: str | None = None
    paused_search_reply_decision: str | None = None


@dataclass(frozen=True)
class RescheduleWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: str
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class ConfigurePausedSearchWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    workflow_id: UUID
    paused_search_track_version_id: UUID
    occurred_at: str
    reason: str


@dataclass(frozen=True)
class PausedSearchTimingUpdatedSignal(RescheduleWorkflowSignal):
    pass


@dataclass(frozen=True)
class PausedSearchReviewResolvedSignal(UnblockWorkflowSignal):
    pass


@dataclass(frozen=True)
class PausedSearchOccurrenceCancelledSignal(RescheduleWorkflowSignal):
    occurrence_id: UUID | None = None


@dataclass(frozen=True)
class PausedSearchTerminalizedSignal(RescheduleWorkflowSignal):
    terminal_behavior: str | None = None


@dataclass(frozen=True)
class LeadNurtureWorkflowSnapshot:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    current_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    last_signal: str | None = None
    last_activity: str | None = None
    last_activity_status: str | None = None
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    skip_reason: str | None = None
    occurrence_id: UUID | None = None
    execution_mode: LeadNurtureExecutionMode = LeadNurtureExecutionMode.STANDARD_CADENCE
    paused_search_track_version_id: UUID | None = None
    occurrence_status: str | None = None
    accepted_touch_count: int = 0
    terminal_status: str | None = None


@workflow.defn(name="lead-nurture-workflow")
class LeadNurtureWorkflow:
    def __init__(self) -> None:
        self._snapshot: LeadNurtureWorkflowSnapshot | None = None
        self._closed = False
        self._send_blocked = False
        self._reschedule_requested = False
        self._execution_mode = LeadNurtureExecutionMode.STANDARD_CADENCE

    @workflow.run
    async def run(self, input_: LeadNurtureWorkflowInput) -> LeadNurtureWorkflowSnapshot:
        self._snapshot = LeadNurtureWorkflowSnapshot(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
            execution_mode=input_.execution_mode,
            paused_search_track_version_id=input_.paused_search_track_version_id,
        )
        self._execution_mode = input_.execution_mode

        while not self._closed:
            schedule_result = await self._execute_schedule_activity(
                (
                    PausedSearchOccurrenceScheduleInput
                    if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                    else ScheduleNextCadenceStepInput
                )(
                    workspace_id=input_.workspace_id,
                    lead_id=input_.lead_id,
                    campaign_version_id=input_.campaign_version_id,
                    occurred_at=workflow.now(),
                    **(
                        {
                            "workflow_id": input_.workflow_id,
                            "paused_search_track_version_id": input_.paused_search_track_version_id,
                            "current_occurrence_id": self._snapshot.occurrence_id,
                        }
                        if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                        else {}
                    ),
                )
            )
            self._record_schedule_result(schedule_result)
            if schedule_result.status == "terminal":
                self._snapshot = replace(
                    self._snapshot,
                    terminal_status=schedule_result.skip_reason or "terminal",
                )
                self._closed = True
                return self._snapshot
            if schedule_result.status in {"review", "hold"}:
                self._send_blocked = True
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
                if self._closed:
                    return self._snapshot
                continue
            if schedule_result.status != "scheduled" or schedule_result.scheduled_for is None:
                return self._snapshot

            delay = schedule_result.scheduled_for - workflow.now()
            if delay > timedelta():
                await self._wait_until_due_or_interrupted(delay)
            if self._closed:
                return self._snapshot
            if self._send_blocked:
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
            if self._closed:
                return self._snapshot
            if self._consume_reschedule_request():
                continue
            if schedule_result.cadence_step_id is None:
                return self._snapshot

            execute_result = await self._execute_cadence_activity(
                (
                    PausedSearchOccurrenceExecutionInput
                    if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                    else ExecuteCadenceStepInput
                )(
                    workspace_id=input_.workspace_id,
                    lead_id=input_.lead_id,
                    campaign_version_id=input_.campaign_version_id,
                    cadence_step_id=schedule_result.cadence_step_id,
                    scheduled_for=schedule_result.scheduled_for,
                    occurred_at=workflow.now(),
                    **(
                        {"occurrence_id": schedule_result.occurrence_id}
                        if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                        else {}
                    ),
                )
            )
            self._record_execution_result(execute_result)

            if execute_result.status == "dispatch_pending":
                await workflow.wait_condition(
                    lambda: self._closed or self._reschedule_requested
                )
                if self._closed:
                    return self._snapshot
                self._consume_reschedule_request()
                continue

            if execute_result.status == "uncertain":
                await self._wait_for_uncertain_resolution(execute_result)
                continue

            if execute_result.status == "review":
                self._send_blocked = True
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
                if self._closed:
                    return self._snapshot
                continue

            if execute_result.status in {"rejected", "failed"}:
                self._send_blocked = True
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
                if self._closed:
                    return self._snapshot
                continue

            if execute_result.status in {"deferred", "skipped"}:
                continue

            if execute_result.status not in {"sent", "already_sent"}:
                return self._snapshot

            if not execute_result.has_more_steps:
                await workflow.wait_condition(lambda: self._closed)
                return self._snapshot

        return self._snapshot

    @workflow.signal(name="pause-requested")
    def pause_requested(self, signal: PauseWorkflowSignal) -> None:
        self._send_blocked = True
        self._reschedule_requested = True
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            last_signal="pause_requested",
            last_activity="pause_requested",
            last_activity_status="blocked",
            skip_reason=signal.reason,
        )

    @workflow.signal(name="resume-requested")
    def resume_requested(self, signal: ResumeWorkflowSignal) -> None:
        self._send_blocked = False
        self._reschedule_requested = True
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            last_signal="resume_requested",
            last_activity="resume_requested",
            last_activity_status="unblocked",
            skip_reason=signal.reason,
        )

    @workflow.signal(name="blocked-review-completed")
    def blocked_review_completed(self, signal: UnblockWorkflowSignal) -> None:
        self._send_blocked = False
        self._reschedule_requested = True
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            last_signal="blocked_review_completed",
            last_activity="blocked_review_completed",
            last_activity_status="updated",
            skip_reason=signal.reason,
        )

    @workflow.signal(name="paused-search-timing-updated")
    def paused_search_timing_updated(self, signal: PausedSearchTimingUpdatedSignal) -> None:
        self.reschedule_requested(signal)

    @workflow.signal(name="paused-search-review-resolved")
    def paused_search_review_resolved(self, signal: PausedSearchReviewResolvedSignal) -> None:
        self.blocked_review_completed(signal)

    @workflow.signal(name="paused-search-occurrence-cancelled")
    def paused_search_occurrence_cancelled(
        self,
        signal: PausedSearchOccurrenceCancelledSignal,
    ) -> None:
        self._send_blocked = True
        self._reschedule_requested = True
        if self._snapshot is not None:
            self._snapshot = replace(
                self._snapshot,
                last_signal="paused_search_occurrence_cancelled",
                last_activity_status="cancelled",
                occurrence_id=signal.occurrence_id or self._snapshot.occurrence_id,
                skip_reason=signal.reason,
            )

    @workflow.signal(name="paused-search-terminalized")
    def paused_search_terminalized(self, signal: PausedSearchTerminalizedSignal) -> None:
        self._closed = True
        if self._snapshot is not None:
            self._snapshot = replace(
                self._snapshot,
                last_signal="paused_search_terminalized",
                last_activity_status="terminal",
                terminal_status=signal.terminal_behavior or signal.reason,
                skip_reason=signal.reason,
            )

    @workflow.signal(name="inbound-processed")
    def inbound_processed(self, signal: InboundProcessedWorkflowSignal) -> None:
        resumes_paused_search = signal.paused_search_reply_decision in {
            "continue",
            "reanchor",
            "end",
        }
        self._send_blocked = not resumes_paused_search
        self._reschedule_requested = True
        if self._snapshot is not None:
            self._snapshot = replace(
                self._snapshot,
                last_signal="inbound_processed",
                last_activity="inbound_processed",
                last_activity_status="unblocked" if resumes_paused_search else "blocked",
                skip_reason=signal.reason,
            )

    @workflow.signal(name="reschedule-requested")
    def reschedule_requested(self, signal: RescheduleWorkflowSignal) -> None:
        self._reschedule_requested = True
        if self._snapshot is not None:
            self._snapshot = replace(
                self._snapshot,
                last_signal="reschedule_requested",
                last_activity="reschedule_requested",
                last_activity_status="updated",
                skip_reason=signal.reason,
            )

    @workflow.signal(name="paused-search-configured")
    def paused_search_configured(self, signal: ConfigurePausedSearchWorkflowSignal) -> None:
        self._execution_mode = LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
        self._send_blocked = False
        self._reschedule_requested = True
        if self._snapshot is not None:
            self._snapshot = replace(
                self._snapshot,
                workflow_id=signal.workflow_id,
                execution_mode=LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING,
                paused_search_track_version_id=signal.paused_search_track_version_id,
                last_signal="paused_search_configured",
                last_activity="paused_search_configured",
                last_activity_status="updated",
                skip_reason=signal.reason,
            )

    @workflow.signal(name="close")
    def close(self) -> None:
        self._closed = True

    @workflow.query(name="snapshot")
    def snapshot(self) -> LeadNurtureWorkflowSnapshot | None:
        return self._snapshot

    async def _wait_until_due_or_interrupted(self, delay: timedelta) -> None:
        try:
            await workflow.wait_condition(
                lambda: self._closed or self._send_blocked or self._reschedule_requested,
                timeout=delay,
                timeout_summary="lead-nurture-next-action",
            )
        except TimeoutError:
            return

    def _consume_reschedule_request(self) -> bool:
        if not self._reschedule_requested:
            return False
        self._reschedule_requested = False
        return True

    async def _execute_schedule_activity(
        self,
        input_: ScheduleNextCadenceStepInput,
    ) -> ScheduleNextCadenceStepResult:
        result = await workflow.execute_activity(
            (
                "schedule-next-paused-search-occurrence"
                if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                else "schedule-next-campaign-cadence-step"
            ),
            input_,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_schedule_retry_policy(),
        )
        return _coerce_schedule_result(result)

    async def _execute_cadence_activity(
        self,
        input_: ExecuteCadenceStepInput,
    ) -> ExecuteCadenceStepResult:
        result = await workflow.execute_activity(
            (
                "execute-paused-search-occurrence"
                if self._execution_mode is LeadNurtureExecutionMode.PAUSED_SEARCH_RECURRING
                else "execute-campaign-cadence-step"
            ),
            input_,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_execution_retry_policy(),
        )
        return _coerce_execution_result(result)

    async def _wait_for_uncertain_resolution(
        self,
        result: ExecuteCadenceStepResult,
    ) -> None:
        if result.occurrence_id is None and result.reconciliation_id is None:
            self._send_blocked = True
            await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
            return
        self._send_blocked = True
        try:
            await workflow.wait_condition(
                lambda: self._closed or not self._send_blocked,
                timeout=timedelta(hours=24),
                timeout_summary="uncertain-send-resolution",
            )
        except TimeoutError:
            assert self._snapshot is not None
            if result.occurrence_id is not None:
                await workflow.execute_activity(
                    "timeout-uncertain-paused-search-occurrence",
                    TimeoutUncertainOccurrenceInput(
                        workspace_id=self._snapshot.workspace_id,
                        occurrence_id=result.occurrence_id,
                        occurred_at=workflow.now(),
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            else:
                assert result.reconciliation_id is not None
                await workflow.execute_activity(
                    "timeout-uncertain-outbound-send",
                    TimeoutUncertainReconciliationInput(
                        workspace_id=self._snapshot.workspace_id,
                        reconciliation_id=result.reconciliation_id,
                        occurred_at=workflow.now(),
                    ),
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            if not self._closed:
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)

    def _record_schedule_result(self, result: ScheduleNextCadenceStepResult) -> None:
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            current_step_id=result.cadence_step_id,
            scheduled_for=result.scheduled_for,
            last_activity="schedule_next_cadence_step",
            last_activity_status=result.status,
            workflow_id=result.workflow_id,
            occurrence_id=result.occurrence_id,
            skip_reason=result.skip_reason,
        )

    def _record_execution_result(self, result: ExecuteCadenceStepResult) -> None:
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            current_step_id=result.cadence_step_id,
            scheduled_for=None,
            last_activity="execute_cadence_step",
            last_activity_status=result.status,
            workflow_id=result.workflow_id,
            transition_id=result.transition_id,
            outbound_message_id=result.outbound_message_id,
            provider_message_id=result.provider_message_id,
            occurrence_id=result.occurrence_id,
            skip_reason=result.skip_reason,
            occurrence_status=result.occurrence_status,
            accepted_touch_count=(
                self._snapshot.accepted_touch_count + (1 if result.accepted_logical_touch else 0)
            ),
        )


def _coerce_schedule_result(value: object) -> ScheduleNextCadenceStepResult:
    if isinstance(value, ScheduleNextCadenceStepResult):
        return value
    if isinstance(value, Mapping):
        return ScheduleNextCadenceStepResult(
            status=str(value["status"]),
            workflow_id=_coerce_uuid(value.get("workflow_id")),
            cadence_step_id=_coerce_uuid(value.get("cadence_step_id")),
            scheduled_for=_coerce_datetime(value.get("scheduled_for")),
            skip_reason=_coerce_optional_str(value.get("skip_reason")),
            occurrence_id=_coerce_uuid(value.get("occurrence_id")),
            planner_outcome=_coerce_optional_str(value.get("planner_outcome")),
            phase=_coerce_optional_str(value.get("phase")),
            occurrence_number=(
                int(value["occurrence_number"])
                if value.get("occurrence_number") is not None
                else None
            ),
            terminal=bool(value.get("terminal", False)),
            expired=bool(value.get("expired", False)),
        )
    raise TypeError(f"Unsupported schedule result payload: {type(value)!r}")


def _coerce_execution_result(value: object) -> ExecuteCadenceStepResult:
    if isinstance(value, ExecuteCadenceStepResult):
        return value
    if isinstance(value, Mapping):
        return ExecuteCadenceStepResult(
            status=str(value["status"]),
            workflow_id=_coerce_uuid(value.get("workflow_id")),
            transition_id=_coerce_uuid(value.get("transition_id")),
            cadence_step_id=_coerce_uuid(value.get("cadence_step_id")),
            outbound_message_id=_coerce_uuid(value.get("outbound_message_id")),
            provider_message_id=_coerce_optional_str(value.get("provider_message_id")),
            skip_reason=_coerce_optional_str(value.get("skip_reason")),
            has_more_steps=bool(value.get("has_more_steps", False)),
            occurrence_id=_coerce_uuid(value.get("occurrence_id")),
            occurrence_status=_coerce_optional_str(value.get("occurrence_status")),
            accepted_logical_touch=bool(value.get("accepted_logical_touch", False)),
            next_cursor_decision=_coerce_optional_str(value.get("next_cursor_decision")),
            notification_events=tuple(str(item) for item in value.get("notification_events", ())),
            fallback_used=bool(value.get("fallback_used", False)),
            reconciliation_id=_coerce_uuid(value.get("reconciliation_id")),
            provider_failure_id=_coerce_uuid(value.get("provider_failure_id")),
            request_id=_coerce_uuid(value.get("request_id")),
        )
    raise TypeError(f"Unsupported execution result payload: {type(value)!r}")


def _coerce_uuid(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise TypeError(f"Unsupported UUID payload: {type(value)!r}")


def _coerce_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"Unsupported datetime payload: {type(value)!r}")


def _coerce_optional_str(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise TypeError(f"Unsupported string payload: {type(value)!r}")


def _schedule_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
    )


def _execution_retry_policy() -> RetryPolicy:
    # Provider dispatch is owned by the durable send-request worker. Activity
    # replay only creates-or-gets the same idempotent request, so a crash after
    # commit but before the Temporal acknowledgement is safe to retry.
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=3,
    )
