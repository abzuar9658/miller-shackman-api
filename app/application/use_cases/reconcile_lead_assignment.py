from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)

_PAUSE_REASON = "crm_ownership_changed"
_CANCEL_REASON = "lead_assignment_reconciled"


class LeadAssignmentReconciliationStatus(StrEnum):
    NO_CHANGE = "no_change"
    RECONCILED = "reconciled"


class LeadAssignmentMessageRepository(Protocol):
    async def list_for_lead(
        self,
        workspace_id: UUID,
        lead_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        raise NotImplementedError

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        raise NotImplementedError


@dataclass(frozen=True)
class LeadAssignmentReconciliationResult:
    status: LeadAssignmentReconciliationStatus
    ownership_changed: bool = False
    resolution_changed: bool = False
    pause_requested: bool = False
    signal_queued: bool = False
    cancelled_message_count: int = 0
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    workflow_transition_skip_reason: str | None = None


async def reconcile_lead_assignment_change(
    *,
    previous_lead: CanonicalLeadRecord | None,
    current_lead: CanonicalLeadRecord,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    outbound_message_repository: LeadAssignmentMessageRepository | None,
    event_bus: EventBus | None,
    now: datetime,
) -> LeadAssignmentReconciliationResult:
    if previous_lead is None:
        return LeadAssignmentReconciliationResult(
            status=LeadAssignmentReconciliationStatus.NO_CHANGE,
        )

    ownership_changed = _ownership_changed(previous_lead, current_lead)
    resolution_changed = _resolution_changed(previous_lead, current_lead)
    if not ownership_changed and not resolution_changed:
        return LeadAssignmentReconciliationResult(
            status=LeadAssignmentReconciliationStatus.NO_CHANGE,
        )

    pause_requested = False
    signal_queued = False
    cancelled_message_count = 0
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    workflow_transition_skip_reason: str | None = None

    if ownership_changed and _can_pause_for_reconciliation(
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
    ):
        assert lead_workflow_repository is not None
        assert workflow_transition_repository is not None
        transition = await apply_workflow_state_transition(
            workspace_id=current_lead.workspace_id,
            lead_id=current_lead.lead_id,
            to_state=WorkflowState.PAUSED,
            reason_code=WorkflowTransitionReasonCode.CRM_OWNERSHIP_CHANGED,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            metadata=_reconciliation_metadata(previous_lead, current_lead),
            pause_reason=_PAUSE_REASON,
        )
        pause_requested = transition.status == WorkflowStateTransitionStatus.UPDATED
        workflow_transition_skip_reason = transition.skip_reason
        if transition.workflow is not None:
            workflow_id = transition.workflow.workflow_id
            cancelled_message_count = await _cancel_pending_outbound_messages(
                outbound_message_repository=outbound_message_repository,
                lead=current_lead,
                now=now,
            )
        workflow_transition_id = transition.transition_id
        if (
            pause_requested
            and transition.workflow is not None
            and temporal_signal_outbox_repository is not None
        ):
            assignment_resolved_at = (
                current_lead.assignment_last_resolved_at.isoformat()
                if current_lead.assignment_last_resolved_at
                else now.isoformat()
            )
            await temporal_signal_outbox_repository.append(
                TemporalSignalOutboxEntry(
                    temporal_signal_id=uuid4(),
                    workspace_id=current_lead.workspace_id,
                    workflow_id=transition.workflow.workflow_id,
                    temporal_workflow_id=transition.workflow.temporal_workflow_id,
                    signal_name=TemporalSignalName.PAUSE_REQUESTED,
                    payload={
                        "lead_id": str(current_lead.lead_id),
                        "reason": _PAUSE_REASON,
                        "occurred_at": now.isoformat(),
                    },
                    idempotency_key=(
                        f"pause-requested:crm-ownership:{current_lead.workspace_id}:{current_lead.lead_id}:"
                        f"{assignment_resolved_at}"
                    ),
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            )
            signal_queued = True
        if pause_requested and transition.workflow is not None and event_bus is not None:
            await event_bus.publish(
                DomainEvent(
                    workspace_id=current_lead.workspace_id,
                    aggregate_type=AggregateType.WORKFLOW,
                    aggregate_id=transition.workflow.workflow_id,
                    event_type=DomainEventType.WORKFLOW_TRANSITIONED,
                    payload={
                        "workflow_id": str(transition.workflow.workflow_id),
                        "transition_id": str(transition.transition_id),
                        "lead_id": str(current_lead.lead_id),
                        "campaign_id": str(transition.workflow.campaign_id),
                        "to_state": transition.workflow.state.value,
                        "reason_code": WorkflowTransitionReasonCode.CRM_OWNERSHIP_CHANGED.value,
                        "occurred_at": now.isoformat(),
                    },
                ),
            )

    if event_bus is not None:
        await event_bus.publish(
            DomainEvent(
                workspace_id=current_lead.workspace_id,
                aggregate_type=AggregateType.LEAD,
                aggregate_id=current_lead.lead_id,
                event_type=DomainEventType.LEAD_ASSIGNMENT_RECONCILED,
                payload={
                    "lead_id": str(current_lead.lead_id),
                    "crm_lead_id": current_lead.crm_lead_id,
                    "ownership_changed": ownership_changed,
                    "resolution_changed": resolution_changed,
                    "previous_assigned_agent_user_id": _uuid_str(
                        previous_lead.assigned_agent_user_id,
                    ),
                    "assigned_agent_user_id": _uuid_str(current_lead.assigned_agent_user_id),
                    "previous_effective_owner_user_id": _uuid_str(
                        previous_lead.effective_owner_user_id,
                    ),
                    "effective_owner_user_id": _uuid_str(current_lead.effective_owner_user_id),
                    "previous_effective_owner_source": (
                        previous_lead.effective_owner_source.value
                        if previous_lead.effective_owner_source is not None
                        else None
                    ),
                    "effective_owner_source": (
                        current_lead.effective_owner_source.value
                        if current_lead.effective_owner_source is not None
                        else None
                    ),
                    "previous_assignment_resolution_status": (
                        previous_lead.assignment_resolution_status.value
                    ),
                    "assignment_resolution_status": current_lead.assignment_resolution_status.value,
                    "pause_requested": pause_requested,
                    "signal_queued": signal_queued,
                    "cancelled_message_count": cancelled_message_count,
                    "occurred_at": now.isoformat(),
                },
            ),
        )

    return LeadAssignmentReconciliationResult(
        status=LeadAssignmentReconciliationStatus.RECONCILED,
        ownership_changed=ownership_changed,
        resolution_changed=resolution_changed,
        pause_requested=pause_requested,
        signal_queued=signal_queued,
        cancelled_message_count=cancelled_message_count,
        workflow_id=workflow_id,
        workflow_transition_id=workflow_transition_id,
        workflow_transition_skip_reason=workflow_transition_skip_reason,
    )


def _ownership_changed(
    previous_lead: CanonicalLeadRecord,
    current_lead: CanonicalLeadRecord,
) -> bool:
    return (
        previous_lead.assigned_agent_user_id != current_lead.assigned_agent_user_id
        or previous_lead.effective_owner_user_id != current_lead.effective_owner_user_id
    )


def _resolution_changed(
    previous_lead: CanonicalLeadRecord,
    current_lead: CanonicalLeadRecord,
) -> bool:
    return (
        previous_lead.assignment_resolution_status != current_lead.assignment_resolution_status
        or previous_lead.effective_owner_source != current_lead.effective_owner_source
    )


def _can_pause_for_reconciliation(
    *,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
) -> bool:
    return lead_workflow_repository is not None and workflow_transition_repository is not None


async def _cancel_pending_outbound_messages(
    *,
    outbound_message_repository: LeadAssignmentMessageRepository | None,
    lead: CanonicalLeadRecord,
    now: datetime,
) -> int:
    if outbound_message_repository is None:
        return 0
    cancelled_count = 0
    for message in await outbound_message_repository.list_for_lead(lead.workspace_id, lead.lead_id):
        if message.status != OutboundMessageStatus.PENDING:
            continue
        await outbound_message_repository.save(
            replace(
                message,
                status=OutboundMessageStatus.CANCELLED,
                failure_reason=_CANCEL_REASON,
                updated_at=now,
            ),
        )
        cancelled_count += 1
    return cancelled_count


def _reconciliation_metadata(
    previous_lead: CanonicalLeadRecord,
    current_lead: CanonicalLeadRecord,
) -> Mapping[str, object]:
    return {
        "previous_assigned_agent_user_id": _uuid_str(previous_lead.assigned_agent_user_id),
        "assigned_agent_user_id": _uuid_str(current_lead.assigned_agent_user_id),
        "previous_effective_owner_user_id": _uuid_str(previous_lead.effective_owner_user_id),
        "effective_owner_user_id": _uuid_str(current_lead.effective_owner_user_id),
        "previous_assignment_resolution_status": previous_lead.assignment_resolution_status.value,
        "assignment_resolution_status": current_lead.assignment_resolution_status.value,
    }


def _uuid_str(value: UUID | None) -> str | None:
    return str(value) if value is not None else None