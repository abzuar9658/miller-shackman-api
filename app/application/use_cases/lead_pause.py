from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionDecision,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class LeadPauseActionStatus(StrEnum):
    REQUESTED = "requested"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    NOT_PAUSABLE = "not_pausable"


class LeadPauseActionReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    NO_WORKFLOW = "no_workflow"
    WORKFLOW_ALREADY_PAUSED = "workflow_already_paused"
    WORKFLOW_STATE_NOT_PAUSABLE = "workflow_state_not_pausable"


@dataclass(frozen=True)
class PauseLeadWorkflowResult:
    status: LeadPauseActionStatus
    workflow_id: UUID | None = None
    workflow_state: WorkflowState | None = None
    reasons: tuple[LeadPauseActionReasonCode, ...] = ()
    signal_queued: bool = False


async def pause_lead_workflow(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason: str,
    lead_repository: LeadReadLeadRepository,
    workflow_repository: LeadReadWorkflowRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    external_event_repository: ExternalEventRepository,
    commit: Callable[[], Awaitable[None]],
    now: datetime,
    id_generator: Callable[[], UUID] = uuid4,
) -> PauseLeadWorkflowResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PauseLeadWorkflowResult(
            status=LeadPauseActionStatus.NOT_FOUND,
            reasons=(LeadPauseActionReasonCode.LEAD_NOT_FOUND,),
        )

    if not _pause_permission(actor, lead).allowed:
        return PauseLeadWorkflowResult(
            status=LeadPauseActionStatus.REJECTED,
            reasons=(LeadPauseActionReasonCode.PERMISSION_DENIED,),
        )

    workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
    reasons = _pause_reasons(workflow_state=workflow.state if workflow is not None else None)
    if reasons or workflow is None:
        return PauseLeadWorkflowResult(
            status=LeadPauseActionStatus.NOT_PAUSABLE,
            workflow_id=workflow.workflow_id if workflow is not None else None,
            workflow_state=workflow.state if workflow is not None else None,
            reasons=reasons,
        )

    pause_reason = reason.strip()
    external_event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.manual_pause_requested",
        now=now,
        payload_redacted={"actor_user_id": str(actor.user_id)},
        id_generator=id_generator,
    )
    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=WorkflowTransitionReasonCode.MANUAL_PAUSE,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        actor_user_id=actor.user_id,
        external_event_id=external_event.external_event_id,
        metadata={"reason": pause_reason},
        pause_reason=WorkflowTransitionReasonCode.MANUAL_PAUSE.value,
    )
    if transition.status != WorkflowStateTransitionStatus.UPDATED or transition.workflow is None:
        return PauseLeadWorkflowResult(
            status=LeadPauseActionStatus.NOT_PAUSABLE,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(LeadPauseActionReasonCode.WORKFLOW_STATE_NOT_PAUSABLE,),
        )

    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=workspace_id,
            workflow_id=transition.workflow.workflow_id,
            temporal_workflow_id=transition.workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.PAUSE_REQUESTED,
            payload={
                "lead_id": str(lead_id),
                "occurred_at": now.isoformat(),
                "reason": pause_reason,
                "actor_user_id": str(actor.user_id),
                "external_event_id": str(external_event.external_event_id),
            },
            idempotency_key=f"pause-requested:{external_event.external_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await commit()

    return PauseLeadWorkflowResult(
        status=LeadPauseActionStatus.REQUESTED,
        workflow_id=transition.workflow.workflow_id,
        workflow_state=transition.workflow.state,
        signal_queued=True,
    )


def _pause_permission(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
) -> PermissionDecision:
    any_lead_permission = evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_ANY_LEAD,
    )
    if any_lead_permission.allowed:
        return any_lead_permission
    return evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_OWN_LEAD,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )


def _pause_reasons(
    *,
    workflow_state: WorkflowState | None,
) -> tuple[LeadPauseActionReasonCode, ...]:
    if workflow_state is None:
        return (LeadPauseActionReasonCode.NO_WORKFLOW,)
    if workflow_state == WorkflowState.PAUSED:
        return (LeadPauseActionReasonCode.WORKFLOW_ALREADY_PAUSED,)
    if workflow_state in {
        WorkflowState.QUEUED,
        WorkflowState.ACTIVE_NURTURE,
        WorkflowState.WAITING_FOR_RESPONSE,
        WorkflowState.RESPONSE_PROCESSING,
    }:
        return ()
    return (LeadPauseActionReasonCode.WORKFLOW_STATE_NOT_PAUSABLE,)