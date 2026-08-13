from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionReasonCode,
    evaluate_permission,
)
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class UncertainOccurrenceResolution(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class UncertainOccurrenceResolutionStatus(StrEnum):
    REJECTED = "rejected"
    RESOLVED = "resolved"
    ALREADY_RESOLVED = "already_resolved"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class UncertainOccurrenceResolutionResult:
    status: UncertainOccurrenceResolutionStatus
    occurrence: RecurringOccurrence | None = None
    workflow_state: WorkflowState | None = None
    reasons: tuple[PermissionReasonCode, ...] = ()


async def resolve_uncertain_paused_search_occurrence(
    *,
    workspace_id: UUID,
    occurrence_id: UUID,
    resolution: UncertainOccurrenceResolution,
    reason: str,
    occurrence_repository: PausedSearchOccurrenceRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
    actor_user_id: UUID | None = None,
    actor: AuthenticatedActor | None = None,
    lead_repository: LeadRepository | None = None,
) -> UncertainOccurrenceResolutionResult:
    # Probe unlocked to learn the lead, then lock workflow before occurrence —
    # the canonical lock order shared with cadence execution and the delivery
    # callback path (workflow row first, occurrence row after).
    probe = await occurrence_repository.get_by_id(workspace_id, occurrence_id)
    if probe is None:
        return UncertainOccurrenceResolutionResult(
            status=UncertainOccurrenceResolutionStatus.NOT_FOUND,
        )
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        probe.lead_id,
    )
    current = await occurrence_repository.get_by_id_for_update(workspace_id, occurrence_id)
    if current is None:
        return UncertainOccurrenceResolutionResult(
            status=UncertainOccurrenceResolutionStatus.NOT_FOUND,
        )
    if actor is not None:
        if lead_repository is None:
            return UncertainOccurrenceResolutionResult(
                status=UncertainOccurrenceResolutionStatus.REJECTED,
                reasons=(PermissionReasonCode.ROLE_NOT_ALLOWED,),
            )
        lead = await lead_repository.get_by_id(workspace_id, current.lead_id)
        if lead is None:
            return UncertainOccurrenceResolutionResult(
                status=UncertainOccurrenceResolutionStatus.NOT_FOUND,
            )
        any_lead_decision = evaluate_permission(
            actor,
            PermissionCapability.RESOLVE_UNCERTAIN_PAUSED_SEARCH_ANY_LEAD,
        )
        own_lead_decision = evaluate_permission(
            actor,
            PermissionCapability.RESOLVE_UNCERTAIN_PAUSED_SEARCH_OWN_LEAD,
            PermissionContext(
                acts_on_assigned_lead=(
                    lead.effective_owner_user_id == actor.user_id
                    or lead.assigned_agent_user_id == actor.user_id
                )
            ),
        )
        if not any_lead_decision.allowed and not own_lead_decision.allowed:
            return UncertainOccurrenceResolutionResult(
                status=UncertainOccurrenceResolutionStatus.REJECTED,
                reasons=own_lead_decision.reasons or any_lead_decision.reasons,
            )
    if current.status is not RecurringOccurrenceStatus.UNCERTAIN:
        return UncertainOccurrenceResolutionResult(
            status=UncertainOccurrenceResolutionStatus.ALREADY_RESOLVED,
            occurrence=current,
        )

    occurrence = await occurrence_repository.resolve_uncertain(
        workspace_id=workspace_id,
        occurrence_id=occurrence_id,
        status=resolution.value,
        now=now,
        reason=reason,
    )
    if occurrence is None:
        return UncertainOccurrenceResolutionResult(
            status=UncertainOccurrenceResolutionStatus.NOT_FOUND,
        )
    if workflow is None or occurrence.lead_id != probe.lead_id:
        workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
            workspace_id,
            occurrence.lead_id,
        )
    if workflow is None:
        return UncertainOccurrenceResolutionResult(
            status=UncertainOccurrenceResolutionStatus.RESOLVED,
            occurrence=occurrence,
        )

    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=occurrence.lead_id,
        to_state=(
            WorkflowState.ACTIVE_NURTURE
            if resolution is UncertainOccurrenceResolution.SENT
            else WorkflowState.CLOSED
        ),
        reason_code=WorkflowTransitionReasonCode.UNCERTAIN_SEND_RESOLVED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=occurrence_repository,
        now=now,
        actor_user_id=actor_user_id,
        metadata={"occurrence_id": str(occurrence_id), "resolution": resolution.value},
        pause_reason="uncertain_send_resolved",
    )
    if transition.status is WorkflowStateTransitionStatus.UPDATED:
        await temporal_signal_outbox_repository.append(
            _resolution_signal(
                workspace_id=workspace_id,
                workflow_id=workflow.workflow_id,
                lead_id=occurrence.lead_id,
                temporal_workflow_id=workflow.temporal_workflow_id,
                occurrence_id=occurrence_id,
                reason=resolution.value,
                actor_user_id=actor_user_id,
                now=now,
            )
        )
    return UncertainOccurrenceResolutionResult(
        status=UncertainOccurrenceResolutionStatus.RESOLVED,
        occurrence=occurrence,
        workflow_state=transition.workflow.state if transition.workflow else workflow.state,
    )


def _resolution_signal(
    *,
    workspace_id: UUID,
    workflow_id: UUID,
    lead_id: UUID,
    temporal_workflow_id: str,
    occurrence_id: UUID,
    reason: str,
    actor_user_id: UUID | None,
    now: datetime,
) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=uuid4(),
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
        signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
        payload={
            "lead_id": str(lead_id),
            "occurrence_id": str(occurrence_id),
            "occurred_at": now.isoformat(),
            "reason": reason,
            "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
        },
        idempotency_key=f"uncertain-resolution:{workspace_id}:{occurrence_id}:{reason}",
        available_at=now,
        created_at=now,
        updated_at=now,
    )
