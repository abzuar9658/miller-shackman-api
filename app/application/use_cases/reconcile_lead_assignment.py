from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord


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


class LeadAssignmentReconciliationStatus(StrEnum):
    NO_CHANGE = "no_change"
    RECONCILED = "reconciled"


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

    _ = (
        lead_workflow_repository,
        workflow_transition_repository,
        temporal_signal_outbox_repository,
        outbound_message_repository,
    )
    pause_requested = False
    signal_queued = False
    cancelled_message_count = 0
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    workflow_transition_skip_reason: str | None = None

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


def _uuid_str(value: UUID | None) -> str | None:
    return str(value) if value is not None else None
