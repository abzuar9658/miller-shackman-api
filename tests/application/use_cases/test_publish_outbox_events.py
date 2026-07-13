from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.use_cases.publish_outbox_events import publish_outbox_events
from app.domain.events import (
    AggregateType,
    DomainEvent,
    DomainEventType,
    OutboxEvent,
    OutboxEventStatus,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
EVENT_ID = UUID("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("33333333-3333-3333-3333-333333333333")


class FakeOutboxRepository:
    def __init__(self, events: tuple[OutboxEvent, ...]) -> None:
        self.events = {event.outbox_event_id: event for event in events}
        self.failed_available_at: datetime | None = None

    async def append(self, event: DomainEvent, *, now: datetime) -> OutboxEvent:
        raise NotImplementedError

    async def claim_available_batch(
        self,
        *,
        now: datetime,
        limit: int,
        lease_duration: timedelta,
        max_attempts: int,
    ) -> tuple[OutboxEvent, ...]:
        return tuple(self.events.values())[:limit]

    async def mark_published(self, outbox_event_id: UUID, *, now: datetime) -> OutboxEvent:
        event = replace(
            self.events[outbox_event_id],
            status=OutboxEventStatus.PUBLISHED,
            published_at=now,
        )
        self.events[outbox_event_id] = event
        return event

    async def mark_failed(
        self,
        outbox_event_id: UUID,
        *,
        error: str,
        available_at: datetime,
    ) -> OutboxEvent:
        self.failed_available_at = available_at
        event = replace(
            self.events[outbox_event_id],
            status=OutboxEventStatus.FAILED,
            last_error=error,
            available_at=available_at,
        )
        self.events[outbox_event_id] = event
        return event


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[OutboxEvent] = []

    async def publish(self, event: OutboxEvent) -> None:
        if self.fail:
            raise RuntimeError("rabbit unavailable")
        self.published.append(event)


def _event(*, attempt_count: int = 1) -> OutboxEvent:
    return OutboxEvent(
        outbox_event_id=EVENT_ID,
        workspace_id=WORKSPACE_ID,
        aggregate_type=AggregateType.MESSAGE,
        aggregate_id=MESSAGE_ID,
        event_type=DomainEventType.MESSAGE_SENT,
        payload={"message_id": str(MESSAGE_ID)},
        status=OutboxEventStatus.PUBLISHING,
        attempt_count=attempt_count,
        available_at=NOW + timedelta(minutes=5),
        created_at=NOW,
    )


async def test_publishes_claimed_events_and_marks_them_published() -> None:
    repository = FakeOutboxRepository((_event(),))
    publisher = FakePublisher()

    result = await publish_outbox_events(
        outbox_repository=repository,
        publisher=publisher,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.published_count == 1
    assert result.failed_count == 0
    assert publisher.published == [_event()]
    assert repository.events[EVENT_ID].status == OutboxEventStatus.PUBLISHED


async def test_failed_publish_is_marked_retryable_with_backoff() -> None:
    repository = FakeOutboxRepository((_event(attempt_count=2),))

    result = await publish_outbox_events(
        outbox_repository=repository,
        publisher=FakePublisher(fail=True),
        now=NOW,
        retry_base_delay=timedelta(seconds=30),
    )

    assert result.published_count == 0
    assert result.failed_count == 1
    assert repository.events[EVENT_ID].status == OutboxEventStatus.FAILED
    assert repository.events[EVENT_ID].last_error == "rabbit unavailable"
    assert repository.failed_available_at == NOW + timedelta(seconds=60)
