from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    WorkflowTransitionRepository,
)
from app.domain.common.ids import LeadId, UserId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionError,
    WorkflowTransitionReasonCode,
    transition_workflow,
)


class WorkflowStateTransitionStatus(StrEnum):
    UPDATED = "updated"
    NO_WORKFLOW = "no_workflow"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class WorkflowStateTransitionOutcome:
    status: WorkflowStateTransitionStatus
    workflow: LeadWorkflow | None = None
    transition_id: UUID | None = None
    skip_reason: str | None = None


async def apply_workflow_state_transition(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    to_state: WorkflowState,
    reason_code: WorkflowTransitionReasonCode,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    now: datetime,
    actor_user_id: UserId | None = None,
    external_event_id: UUID | None = None,
    metadata: Mapping[str, object] | None = None,
    pause_reason: str | None = None,
    resume_reason: str | None = None,
    transition_id_factory: Callable[[], UUID] | None = None,
) -> WorkflowStateTransitionOutcome:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return WorkflowStateTransitionOutcome(status=WorkflowStateTransitionStatus.NO_WORKFLOW)

    try:
        result = transition_workflow(
            workflow=workflow,
            to_state=to_state,
            reason_code=reason_code,
            transition_id=(transition_id_factory or uuid4)(),
            now=now,
            actor_user_id=actor_user_id,
            external_event_id=external_event_id,
            metadata=metadata or {},
            pause_reason=pause_reason,
            resume_reason=resume_reason,
        )
    except WorkflowTransitionError as error:
        return WorkflowStateTransitionOutcome(
            status=WorkflowStateTransitionStatus.SKIPPED,
            workflow=workflow,
            skip_reason=str(error),
        )

    saved_workflow = await lead_workflow_repository.save(result.workflow)
    saved_transition = await workflow_transition_repository.append(result.transition)
    if paused_search_occurrence_repository is not None and result.workflow.state in {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
        WorkflowState.SUPPRESSED,
        WorkflowState.COMPLETED,
        WorkflowState.CLOSED,
    }:
        await paused_search_occurrence_repository.cancel_open_for_workflow(
            workspace_id=workspace_id,
            workflow_id=saved_workflow.workflow_id,
            now=now,
            reason=reason_code.value,
        )
    return WorkflowStateTransitionOutcome(
        status=WorkflowStateTransitionStatus.UPDATED,
        workflow=saved_workflow,
        transition_id=saved_transition.transition_id,
    )
