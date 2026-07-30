from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import HandoffRepository
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import Handoff, is_open_handoff
from app.domain.events import AggregateType, DomainEvent, DomainEventType


async def latest_open_handoff_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    handoff_repository: HandoffRepository,
) -> Handoff | None:
    for handoff in await handoff_repository.list_for_lead(workspace_id, lead_id, limit=10):
        if is_open_handoff(handoff):
            return handoff
    return None


async def publish_handoff_created_event(
    *,
    handoff: Handoff,
    event_bus: EventBus | None,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=handoff.workspace_id,
            aggregate_type=AggregateType.HANDOFF,
            aggregate_id=handoff.handoff_id,
            event_type=DomainEventType.HANDOFF_CREATED,
            payload={
                "handoff_id": str(handoff.handoff_id),
                "lead_id": str(handoff.lead_id),
                "conversation_id": (
                    str(handoff.conversation_id) if handoff.conversation_id is not None else None
                ),
                "inbound_message_id": (
                    str(handoff.inbound_message_id)
                    if handoff.inbound_message_id is not None
                    else None
                ),
                "reason_code": handoff.reason_code.value,
                "created_at": handoff.created_at.isoformat(),
            },
        )
    )