from datetime import UTC, datetime
from uuid import UUID

from app.domain.events import AggregateType, DomainEventType, OutboxEvent, OutboxEventStatus
from app.infrastructure.events.rabbitmq.publisher import _message_body

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
EVENT_ID = UUID("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("33333333-3333-3333-3333-333333333333")


def test_rabbitmq_message_body_contains_canonical_event_envelope() -> None:
    body = _message_body(
        OutboxEvent(
            outbox_event_id=EVENT_ID,
            workspace_id=WORKSPACE_ID,
            aggregate_type=AggregateType.MESSAGE,
            aggregate_id=MESSAGE_ID,
            event_type=DomainEventType.MESSAGE_SENT,
            payload={"message_id": str(MESSAGE_ID)},
            status=OutboxEventStatus.PUBLISHING,
            attempt_count=1,
            available_at=NOW,
            created_at=NOW,
        )
    )

    assert body == {
        "outbox_event_id": str(EVENT_ID),
        "workspace_id": str(WORKSPACE_ID),
        "aggregate_type": "message",
        "aggregate_id": str(MESSAGE_ID),
        "event_type": "message.sent",
        "payload": {"message_id": str(MESSAGE_ID)},
        "created_at": NOW.isoformat(),
        "attempt_count": 1,
    }
