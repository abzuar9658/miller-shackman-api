from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.workflows import TemporalSignalName, TemporalSignalOutboxEntry


async def enqueue_lead_nurture_reschedule_signal(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason: str,
    occurred_at: datetime,
    lead_workflow_repository: LeadWorkflowRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    actor_user_id: UUID | None = None,
    external_event_id: UUID | None = None,
) -> bool:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is None:
        return False

    actor_token = str(actor_user_id) if actor_user_id is not None else "none"
    event_token = str(external_event_id) if external_event_id is not None else "none"
    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=workspace_id,
            workflow_id=workflow.workflow_id,
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.RESCHEDULE_REQUESTED,
            payload={
                "lead_id": str(lead_id),
                "occurred_at": occurred_at.isoformat(),
                "reason": reason,
                "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                "external_event_id": (
                    str(external_event_id) if external_event_id is not None else None
                ),
            },
            idempotency_key=(
                "reschedule-requested:"
                f"{workflow.workflow_id}:{occurred_at.isoformat()}:{reason}:{actor_token}:{event_token}"
            ),
            available_at=occurred_at,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
    )
    return True
