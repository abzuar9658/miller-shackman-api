from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransition,
    WorkflowTransitionReasonCode,
)


class ReactivateTimingBlockedWorkflowStatus(StrEnum):
    REACTIVATED = "reactivated"
    NOT_TIMING_BLOCKED = "not_timing_blocked"
    NO_WORKFLOW = "no_workflow"
    TRANSITION_FAILED = "transition_failed"


@dataclass(frozen=True)
class ReactivateTimingBlockedWorkflowResult:
    status: ReactivateTimingBlockedWorkflowStatus
    workflow_id: UUID | None = None
    signal_queued: bool = False


async def reactivate_timing_blocked_workflows_for_workspace(
    *,
    workspace_id: WorkspaceId,
    quiet_hours_previously_enabled: bool,
    quiet_hours_now_enabled: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
    id_generator: Callable[[], UUID] = uuid4,
) -> tuple[ReactivateTimingBlockedWorkflowResult, ...]:
    if quiet_hours_previously_enabled and not quiet_hours_now_enabled:
        paused_workflows = await lead_workflow_repository.list_paused_for_workspace(
            workspace_id,
            limit=1000,
        )
        results: list[ReactivateTimingBlockedWorkflowResult] = []
        for workflow in paused_workflows:
            result = await reactivate_timing_blocked_workflow(
                workspace_id=workspace_id,
                lead_id=workflow.lead_id,
                lead_workflow_repository=lead_workflow_repository,
                workflow_transition_repository=workflow_transition_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                now=now,
                id_generator=id_generator,
            )
            results.append(result)
        return tuple(results)
    return ()


async def reactivate_timing_blocked_workflow(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
    id_generator: Callable[[], UUID] = uuid4,
) -> ReactivateTimingBlockedWorkflowResult:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is None:
        return ReactivateTimingBlockedWorkflowResult(
            status=ReactivateTimingBlockedWorkflowStatus.NO_WORKFLOW,
        )

    if not _is_timing_only_pause(workflow):
        return ReactivateTimingBlockedWorkflowResult(
            status=ReactivateTimingBlockedWorkflowStatus.NOT_TIMING_BLOCKED,
        )

    transitions = await workflow_transition_repository.list_for_workflow(
        workspace_id,
        workflow.workflow_id,
        limit=1,
    )
    latest_transition: WorkflowTransition | None = transitions[0] if transitions else None
    if not _is_outside_hours_only_block(latest_transition):
        return ReactivateTimingBlockedWorkflowResult(
            status=ReactivateTimingBlockedWorkflowStatus.NOT_TIMING_BLOCKED,
        )

    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.ACTIVE_NURTURE,
        reason_code=WorkflowTransitionReasonCode.CONTACT_POLICY_UPDATED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "explanation": "Quiet hours disabled — workflow auto-resumed",
            "previous_pause_reason": workflow.pause_reason,
            "pre_send_reasons": ["outside_allowed_hours"],
        },
        transition_id_factory=id_generator,
    )
    if (
        transition.status != WorkflowStateTransitionStatus.UPDATED
        or transition.workflow is None
    ):
        return ReactivateTimingBlockedWorkflowResult(
            status=ReactivateTimingBlockedWorkflowStatus.TRANSITION_FAILED,
            workflow_id=workflow.workflow_id,
        )

    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=id_generator(),
            workspace_id=workspace_id,
            workflow_id=transition.workflow.workflow_id,
            temporal_workflow_id=transition.workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.RESUME_REQUESTED,
            payload={
                "lead_id": str(lead_id),
                "occurred_at": now.isoformat(),
                "reason": "Quiet hours disabled — workflow auto-resumed",
            },
            idempotency_key=f"auto-resume-quiet-hours:{workspace_id}:{lead_id}:{transition.transition_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    return ReactivateTimingBlockedWorkflowResult(
        status=ReactivateTimingBlockedWorkflowStatus.REACTIVATED,
        workflow_id=transition.workflow.workflow_id,
        signal_queued=True,
    )


def _is_timing_only_pause(workflow: LeadWorkflow) -> bool:
    return (
        workflow.state == WorkflowState.PAUSED
        and workflow.pause_reason == "cadence_step_blocked"
    )


def _is_outside_hours_only_block(
    transition: WorkflowTransition | None,
) -> bool:
    if transition is None:
        return False
    if (
        transition.reason_code != WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
        or transition.to_state != WorkflowState.PAUSED
    ):
        return False
    pre_send_reasons = transition.metadata.get("pre_send_reasons")
    return isinstance(pre_send_reasons, list) and pre_send_reasons == [
        "outside_allowed_hours"
    ]
