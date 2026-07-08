from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import LeadWorkflowRepository, WorkflowTransitionRepository
from app.application.services.llm.reply_classification import InboundReplyIntent
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
    handoff_required: bool,
    opt_out_detected: bool,
    classification_rejected: bool,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    now: datetime,
    external_event_id: UUID | None = None,
    conversation_id: UUID | None = None,
    inbound_message_id: UUID | None = None,
    handoff_id: UUID | None = None,
    intent: InboundReplyIntent | None = None,
    classification_reasons: tuple[str, ...] = (),
    transition_id_factory: Callable[[], UUID] | None = None,
) -> InboundWorkflowTransitionOutcome:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return InboundWorkflowTransitionOutcome(status=InboundWorkflowTransitionStatus.NO_WORKFLOW)

    reason_code = _reason_code(
        handoff_required=handoff_required,
        opt_out_detected=opt_out_detected,
        classification_rejected=classification_rejected,
    )
    to_state = WorkflowState.HUMAN_HANDOFF if handoff_required else WorkflowState.PAUSED
    metadata = _metadata(
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        handoff_id=handoff_id,
        intent=intent,
        classification_reasons=classification_reasons,
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
    return InboundWorkflowTransitionOutcome(
        status=InboundWorkflowTransitionStatus.UPDATED,
        workflow=saved_workflow,
        transition_id=saved_transition.transition_id,
    )


def _reason_code(
    *,
    handoff_required: bool,
    opt_out_detected: bool,
    classification_rejected: bool,
) -> WorkflowTransitionReasonCode:
    if handoff_required:
        return WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED
    if opt_out_detected:
        return WorkflowTransitionReasonCode.OPT_OUT_DETECTED
    if classification_rejected:
        return WorkflowTransitionReasonCode.REPLY_CLASSIFICATION_REJECTED
    return WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED


def _metadata(
    *,
    conversation_id: UUID | None,
    inbound_message_id: UUID | None,
    handoff_id: UUID | None,
    intent: InboundReplyIntent | None,
    classification_reasons: tuple[str, ...],
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
    if classification_reasons:
        values["classification_reasons"] = list(classification_reasons)
    return values
