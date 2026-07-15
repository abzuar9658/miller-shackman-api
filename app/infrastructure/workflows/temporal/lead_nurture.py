from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from temporalio import workflow


@dataclass(frozen=True)
class LeadNurtureWorkflowInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID


@dataclass(frozen=True)
class ScheduleNextCadenceStepInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class ScheduleNextCadenceStepResult:
    status: str
    workflow_id: UUID | None = None
    cadence_step_id: UUID | None = None
    scheduled_for: datetime | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class ExecuteCadenceStepInput:
    workspace_id: UUID
    lead_id: UUID
    campaign_version_id: UUID
    cadence_step_id: UUID
    scheduled_for: datetime
    occurred_at: datetime


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


@dataclass(frozen=True)
class InboundReplySignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: datetime
    handoff_required: bool = False
    opt_out_detected: bool = False
    classification_rejected: bool = False
    external_event_id: UUID | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    handoff_id: UUID | None = None
    intent: str | None = None
    classification_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PauseWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class ResumeWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class UnblockWorkflowSignal:
    workspace_id: UUID
    lead_id: UUID
    occurred_at: datetime
    reason: str
    actor_user_id: UUID | None = None
    external_event_id: UUID | None = None


@dataclass(frozen=True)
class WorkflowSignalActivityResult:
    status: str
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    skip_reason: str | None = None


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


@workflow.defn(name="lead-nurture-workflow")
class LeadNurtureWorkflow:
    def __init__(self) -> None:
        self._snapshot: LeadNurtureWorkflowSnapshot | None = None
        self._closed = False
        self._send_blocked = False

    @workflow.run
    async def run(self, input_: LeadNurtureWorkflowInput) -> LeadNurtureWorkflowSnapshot:
        self._snapshot = LeadNurtureWorkflowSnapshot(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
            campaign_version_id=input_.campaign_version_id,
        )

        while not self._closed:
            schedule_result = await self._execute_schedule_activity(
                ScheduleNextCadenceStepInput(
                    workspace_id=input_.workspace_id,
                    lead_id=input_.lead_id,
                    campaign_version_id=input_.campaign_version_id,
                    occurred_at=workflow.now(),
                )
            )
            self._record_schedule_result(schedule_result)
            if schedule_result.status != "scheduled" or schedule_result.scheduled_for is None:
                return self._snapshot

            delay = schedule_result.scheduled_for - workflow.now()
            if delay > timedelta():
                await workflow.sleep(delay)
            if self._send_blocked:
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
            if self._closed or schedule_result.cadence_step_id is None:
                return self._snapshot

            execute_result = await self._execute_cadence_activity(
                ExecuteCadenceStepInput(
                    workspace_id=input_.workspace_id,
                    lead_id=input_.lead_id,
                    campaign_version_id=input_.campaign_version_id,
                    cadence_step_id=schedule_result.cadence_step_id,
                    scheduled_for=schedule_result.scheduled_for,
                    occurred_at=workflow.now(),
                )
            )
            self._record_execution_result(execute_result)

            if execute_result.status in {"rejected", "failed", "uncertain"}:
                self._send_blocked = True
                await workflow.wait_condition(lambda: self._closed or not self._send_blocked)
                if self._closed:
                    return self._snapshot
                continue

            if execute_result.status not in {"sent", "already_sent"}:
                return self._snapshot

            if not execute_result.has_more_steps:
                await workflow.wait_condition(lambda: self._closed)
                return self._snapshot

        return self._snapshot

    @workflow.signal(name="inbound-reply-received")
    async def inbound_reply_received(self, signal: InboundReplySignal) -> None:
        result = await self._execute_signal_activity(
            signal_name="inbound_reply_received",
            activity_name="apply-inbound-workflow-transition",
            arg=signal,
        )
        self._send_blocked = True
        self._record_signal_result("inbound_reply_received", result)

    @workflow.signal(name="handoff-created")
    async def handoff_created(self, signal: InboundReplySignal) -> None:
        result = await self._execute_signal_activity(
            signal_name="handoff_created",
            activity_name="apply-inbound-workflow-transition",
            arg=signal,
        )
        self._send_blocked = True
        self._record_signal_result("handoff_created", result)

    @workflow.signal(name="pause-requested")
    async def pause_requested(self, signal: PauseWorkflowSignal) -> None:
        result = await self._execute_signal_activity(
            signal_name="pause_requested",
            activity_name="record-pause-workflow-signal",
            arg=signal,
        )
        self._send_blocked = True
        self._record_signal_result("pause_requested", result)

    @workflow.signal(name="resume-requested")
    async def resume_requested(self, signal: ResumeWorkflowSignal) -> None:
        result = await self._execute_signal_activity(
            signal_name="resume_requested",
            activity_name="record-resume-workflow-signal",
            arg=signal,
        )
        if result.status == "updated":
            self._send_blocked = False
        self._record_signal_result("resume_requested", result)

    @workflow.signal(name="blocked-review-completed")
    def blocked_review_completed(self, signal: UnblockWorkflowSignal) -> None:
        self._send_blocked = False
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            last_signal="blocked_review_completed",
            last_activity="blocked_review_completed",
            last_activity_status="updated",
            skip_reason=signal.reason,
        )

    @workflow.signal(name="close")
    def close(self) -> None:
        self._closed = True

    @workflow.query(name="snapshot")
    def snapshot(self) -> LeadNurtureWorkflowSnapshot | None:
        return self._snapshot

    async def _execute_signal_activity(
        self, *, signal_name: str, activity_name: str, arg: object
    ) -> WorkflowSignalActivityResult:
        result = await workflow.execute_activity(
            activity_name,
            arg,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return _coerce_signal_result(result)

    async def _execute_schedule_activity(
        self,
        input_: ScheduleNextCadenceStepInput,
    ) -> ScheduleNextCadenceStepResult:
        result = await workflow.execute_activity(
            "schedule-next-campaign-cadence-step",
            input_,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return _coerce_schedule_result(result)

    async def _execute_cadence_activity(
        self,
        input_: ExecuteCadenceStepInput,
    ) -> ExecuteCadenceStepResult:
        result = await workflow.execute_activity(
            "execute-campaign-cadence-step",
            input_,
            start_to_close_timeout=timedelta(minutes=2),
        )
        return _coerce_execution_result(result)

    def _record_schedule_result(self, result: ScheduleNextCadenceStepResult) -> None:
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            current_step_id=result.cadence_step_id,
            scheduled_for=result.scheduled_for,
            last_activity="schedule_next_cadence_step",
            last_activity_status=result.status,
            workflow_id=result.workflow_id,
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
            skip_reason=result.skip_reason,
        )

    def _record_signal_result(self, signal_name: str, result: WorkflowSignalActivityResult) -> None:
        assert self._snapshot is not None
        self._snapshot = replace(
            self._snapshot,
            last_signal=signal_name,
            last_activity=signal_name,
            last_activity_status=result.status,
            workflow_id=result.workflow_id,
            transition_id=result.transition_id,
            skip_reason=result.skip_reason,
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
        )
    raise TypeError(f"Unsupported execution result payload: {type(value)!r}")


def _coerce_signal_result(value: object) -> WorkflowSignalActivityResult:
    if isinstance(value, WorkflowSignalActivityResult):
        return value
    if isinstance(value, Mapping):
        return WorkflowSignalActivityResult(
            status=str(value["status"]),
            workflow_id=_coerce_uuid(value.get("workflow_id")),
            transition_id=_coerce_uuid(value.get("transition_id")),
            skip_reason=_coerce_optional_str(value.get("skip_reason")),
        )
    raise TypeError(f"Unsupported signal result payload: {type(value)!r}")


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
