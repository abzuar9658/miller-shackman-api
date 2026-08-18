from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    ExternalEventRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTerminalBehavior
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    evaluate_permission,
)
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class PausedSearchTerminalizationStatus(StrEnum):
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    INVALID = "invalid"


class PausedSearchTerminalizationReason(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    NO_WORKFLOW = "no_workflow"
    INVALID_TARGET = "invalid_target"
    INVALID_TRANSITION = "invalid_transition"


@dataclass(frozen=True)
class PausedSearchTerminalizationResult:
    status: PausedSearchTerminalizationStatus
    lead_id: LeadId | None = None
    workflow_id: UUID | None = None
    workflow_state: WorkflowState | None = None
    reasons: tuple[PausedSearchTerminalizationReason, ...] = ()
    signal_queued: bool = False


async def terminalize_paused_search(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    terminal_behavior: PausedSearchTerminalBehavior,
    reason: str,
    lead_repository: LeadReadLeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    external_event_repository: ExternalEventRepository,
    commit: Callable[[], Awaitable[None]],
    now: datetime,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
) -> PausedSearchTerminalizationResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PausedSearchTerminalizationResult(
            status=PausedSearchTerminalizationStatus.NOT_FOUND,
            reasons=(PausedSearchTerminalizationReason.LEAD_NOT_FOUND,),
        )
    permission = evaluate_permission(
        actor,
        PermissionCapability.ACT_ON_PAUSED_SEARCH_ANY,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )
    if not permission.allowed:
        return PausedSearchTerminalizationResult(
            status=PausedSearchTerminalizationStatus.REJECTED,
            lead_id=lead_id,
            reasons=(PausedSearchTerminalizationReason.PERMISSION_DENIED,),
        )
    target_state = {
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED: WorkflowState.COMPLETED,
        PausedSearchTerminalBehavior.PAUSE_FOR_REVIEW: WorkflowState.PAUSED,
        PausedSearchTerminalBehavior.CLOSE_AUTOMATION: WorkflowState.CLOSED,
    }.get(terminal_behavior)
    if target_state is None:
        return PausedSearchTerminalizationResult(
            status=PausedSearchTerminalizationStatus.INVALID,
            lead_id=lead_id,
            reasons=(PausedSearchTerminalizationReason.INVALID_TARGET,),
        )
    event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.paused_search_terminalized",
        now=now,
        payload_redacted={"actor_user_id": str(actor.user_id)},
    )
    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=target_state,
        reason_code=WorkflowTransitionReasonCode.PAUSED_SEARCH_TERMINALIZED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        now=now,
        actor_user_id=actor.user_id,
        external_event_id=event.external_event_id,
        metadata={"reason": reason, "terminal_behavior": terminal_behavior.value},
        pause_reason=(
            "paused_search_terminal_review" if target_state is WorkflowState.PAUSED else None
        ),
    )
    if transition.status is WorkflowStateTransitionStatus.NO_WORKFLOW:
        return PausedSearchTerminalizationResult(
            status=PausedSearchTerminalizationStatus.INVALID,
            lead_id=lead_id,
            reasons=(PausedSearchTerminalizationReason.NO_WORKFLOW,),
        )
    if (
        transition.status is not WorkflowStateTransitionStatus.UPDATED
        or transition.workflow is None
    ):
        return PausedSearchTerminalizationResult(
            status=PausedSearchTerminalizationStatus.INVALID,
            lead_id=lead_id,
            workflow_id=transition.workflow.workflow_id if transition.workflow else None,
            workflow_state=transition.workflow.state if transition.workflow else None,
            reasons=(PausedSearchTerminalizationReason.INVALID_TRANSITION,),
        )
    signal_queued = False
    if target_state is WorkflowState.PAUSED:
        await temporal_signal_outbox_repository.append(
            TemporalSignalOutboxEntry(
                temporal_signal_id=uuid4(),
                workspace_id=workspace_id,
                workflow_id=transition.workflow.workflow_id,
                temporal_workflow_id=transition.workflow.temporal_workflow_id,
                signal_name=TemporalSignalName.RESCHEDULE_REQUESTED,
                payload={"lead_id": str(lead_id), "reason": reason, "occurred_at": now.isoformat()},
                idempotency_key=f"paused-search-terminalized:{event.external_event_id}",
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        signal_queued = True
    await commit()
    return PausedSearchTerminalizationResult(
        status=PausedSearchTerminalizationStatus.UPDATED,
        lead_id=lead_id,
        workflow_id=transition.workflow.workflow_id,
        workflow_state=transition.workflow.state,
        signal_queued=signal_queued,
    )