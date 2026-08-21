from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    PausedSearchAgentReminderRepository,
    PausedSearchOccurrenceRepository,
    WorkflowTransitionRepository,
)
from app.application.services.llm.reply_classification import InboundReplyIntent
from app.application.use_cases.evaluate_inbound_action import InboundAction, InboundActionReasonCode
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionError,
    WorkflowTransitionReasonCode,
    transition_workflow,
)


class InboundWorkflowTransitionStatus(StrEnum):
    UPDATED = "updated"
    NO_WORKFLOW = "no_workflow"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class InboundWorkflowTransitionOutcome:
    status: InboundWorkflowTransitionStatus
    workflow: LeadWorkflow | None = None
    transition_id: UUID | None = None
    skip_reason: str | None = None


async def apply_inbound_workflow_transition(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    action: InboundAction,
    decision_reason: InboundActionReasonCode,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    paused_search_reminder_repository: PausedSearchAgentReminderRepository | None = None,
    now: datetime,
    external_event_id: UUID | None = None,
    conversation_id: UUID | None = None,
    inbound_message_id: UUID | None = None,
    handoff_id: UUID | None = None,
    intent: InboundReplyIntent | None = None,
    classification_reasons: tuple[str, ...] = (),
    resume_paused_search: bool = False,
    reply_route: str | None = None,
    transition_id_factory: Callable[[], UUID] | None = None,
) -> InboundWorkflowTransitionOutcome:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return InboundWorkflowTransitionOutcome(status=InboundWorkflowTransitionStatus.NO_WORKFLOW)

    if resume_paused_search:
        if paused_search_occurrence_repository is not None:
            await paused_search_occurrence_repository.cancel_open_for_workflow(
                workspace_id=workspace_id,
                workflow_id=workflow.workflow_id,
                now=now,
                reason="reply_route_continue",
            )
        if paused_search_reminder_repository is not None:
            await paused_search_reminder_repository.cancel_open_for_workflow(
                workspace_id=workspace_id,
                workflow_id=workflow.workflow_id,
                now=now,
            )
    to_state = WorkflowState.ACTIVE_NURTURE if resume_paused_search else _to_state(action)
    reason_code = _reason_code(action=action, decision_reason=decision_reason)
    metadata = _metadata(
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        handoff_id=handoff_id,
        intent=intent,
        action=action,
        decision_reason=decision_reason,
        classification_reasons=classification_reasons,
        reply_route=reply_route,
    )
    try:
        result = transition_workflow(
            workflow=workflow,
            to_state=to_state,
            reason_code=reason_code,
            transition_id=(transition_id_factory or uuid4)(),
            now=now,
            external_event_id=external_event_id,
            metadata=metadata,
            pause_reason=reason_code.value,
        )
    except WorkflowTransitionError as error:
        return InboundWorkflowTransitionOutcome(
            status=InboundWorkflowTransitionStatus.SKIPPED,
            workflow=workflow,
            skip_reason=str(error),
        )

    saved_workflow = await lead_workflow_repository.save(result.workflow)
    saved_transition = await workflow_transition_repository.append(result.transition)
    if saved_workflow.state in {
        WorkflowState.PAUSED,
        WorkflowState.HUMAN_HANDOFF,
        WorkflowState.HUMAN_OWNED,
        WorkflowState.SUPPRESSED,
        WorkflowState.COMPLETED,
        WorkflowState.CLOSED,
    }:
        if paused_search_occurrence_repository is not None:
            await paused_search_occurrence_repository.cancel_open_for_workflow(
                workspace_id=workspace_id,
                workflow_id=saved_workflow.workflow_id,
                now=now,
                reason=reason_code.value,
            )
        if paused_search_reminder_repository is not None:
            await paused_search_reminder_repository.cancel_open_for_workflow(
                workspace_id=workspace_id,
                workflow_id=saved_workflow.workflow_id,
                now=now,
            )
    return InboundWorkflowTransitionOutcome(
        status=InboundWorkflowTransitionStatus.UPDATED,
        workflow=saved_workflow,
        transition_id=saved_transition.transition_id,
    )


def _reason_code(
    *,
    action: InboundAction,
    decision_reason: InboundActionReasonCode,
) -> WorkflowTransitionReasonCode:
    if action == InboundAction.HUMAN_HANDOFF:
        return WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED
    if action == InboundAction.SUPPRESS:
        return WorkflowTransitionReasonCode.OPT_OUT_DETECTED
    if action == InboundAction.COMPLETE_AUTOMATION:
        return WorkflowTransitionReasonCode.LEAD_NOT_INTERESTED
    if decision_reason == InboundActionReasonCode.CLASSIFICATION_REJECTED:
        return WorkflowTransitionReasonCode.REPLY_CLASSIFICATION_REJECTED
    if action == InboundAction.PAUSE_FOR_REVIEW:
        return WorkflowTransitionReasonCode.INBOUND_REVIEW_REQUIRED
    return WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED


def _to_state(action: InboundAction) -> WorkflowState:
    if action == InboundAction.HUMAN_HANDOFF:
        return WorkflowState.HUMAN_HANDOFF
    if action == InboundAction.SUPPRESS:
        return WorkflowState.SUPPRESSED
    if action == InboundAction.COMPLETE_AUTOMATION:
        return WorkflowState.COMPLETED
    return WorkflowState.PAUSED


def _metadata(
    *,
    conversation_id: UUID | None,
    inbound_message_id: UUID | None,
    handoff_id: UUID | None,
    intent: InboundReplyIntent | None,
    action: InboundAction | None,
    decision_reason: InboundActionReasonCode | None,
    classification_reasons: tuple[str, ...],
    reply_route: str | None,
) -> Mapping[str, object]:
    values: dict[str, object] = {}
    if conversation_id is not None:
        values["conversation_id"] = str(conversation_id)
    if inbound_message_id is not None:
        values["inbound_message_id"] = str(inbound_message_id)
    if handoff_id is not None:
        values["handoff_id"] = str(handoff_id)
    if intent is not None:
        values["intent"] = intent.value
    if action is not None:
        values["inbound_action"] = action.value
    if decision_reason is not None:
        values["decision_reason"] = decision_reason.value
    if reply_route is not None:
        values["reply_route"] = reply_route
    if classification_reasons:
        values["classification_reasons"] = list(classification_reasons)
    return values
