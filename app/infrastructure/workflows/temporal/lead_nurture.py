from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from temporalio import workflow


@dataclass(frozen=True)
class LeadNurtureWorkflowInput:
    workspace_id: UUID
    lead_id: UUID


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
class WorkflowSignalActivityResult:
    status: str
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class LeadNurtureWorkflowSnapshot:
    workspace_id: UUID
    lead_id: UUID
    last_signal: str | None = None
    last_activity_status: str | None = None
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    skip_reason: str | None = None


@workflow.defn(name="lead-nurture-workflow")
class LeadNurtureWorkflow:
    def __init__(self) -> None:
        self._snapshot: LeadNurtureWorkflowSnapshot | None = None
        self._closed = False

    @workflow.run
    async def run(self, input_: LeadNurtureWorkflowInput) -> LeadNurtureWorkflowSnapshot:
        self._snapshot = LeadNurtureWorkflowSnapshot(
            workspace_id=input_.workspace_id,
            lead_id=input_.lead_id,
        )
        await workflow.wait_condition(lambda: self._closed)
        return self._snapshot

    @workflow.signal(name="inbound-reply-received")
    async def inbound_reply_received(self, signal: InboundReplySignal) -> None:
        await self._execute_signal_activity(
            signal_name="inbound_reply_received",
            activity_name="apply-inbound-workflow-transition",
            arg=signal,
        )

    @workflow.signal(name="handoff-created")
    async def handoff_created(self, signal: InboundReplySignal) -> None:
        await self._execute_signal_activity(
            signal_name="handoff_created",
            activity_name="apply-inbound-workflow-transition",
            arg=signal,
        )

    @workflow.signal(name="pause-requested")
    async def pause_requested(self, signal: PauseWorkflowSignal) -> None:
        await self._execute_signal_activity(
            signal_name="pause_requested",
            activity_name="record-pause-workflow-signal",
            arg=signal,
        )

    @workflow.signal(name="resume-requested")
    async def resume_requested(self, signal: ResumeWorkflowSignal) -> None:
        await self._execute_signal_activity(
            signal_name="resume_requested",
            activity_name="record-resume-workflow-signal",
            arg=signal,
        )

    @workflow.signal(name="close")
    def close(self) -> None:
        self._closed = True

    @workflow.query(name="snapshot")
    def snapshot(self) -> LeadNurtureWorkflowSnapshot | None:
        return self._snapshot

    async def _execute_signal_activity(
        self, *, signal_name: str, activity_name: str, arg: object
    ) -> None:
        result = await workflow.execute_activity(
            activity_name,
            arg,
            start_to_close_timeout=timedelta(seconds=30),
        )
        self._record_result(signal_name, result)

    def _record_result(self, signal_name: str, result: WorkflowSignalActivityResult) -> None:
        assert self._snapshot is not None
        self._snapshot = LeadNurtureWorkflowSnapshot(
            workspace_id=self._snapshot.workspace_id,
            lead_id=self._snapshot.lead_id,
            last_signal=signal_name,
            last_activity_status=result.status,
            workflow_id=result.workflow_id,
            transition_id=result.transition_id,
            skip_reason=result.skip_reason,
        )
