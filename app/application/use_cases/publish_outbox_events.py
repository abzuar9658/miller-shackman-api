from dataclasses import dataclass
from datetime import datetime, timedelta

from app.application.ports.event_bus import OutboxEventPublisher, OutboxEventRepository
from app.application.services.retry_backoff import exponential_retry_delay
from app.domain.events import OutboxEvent


@dataclass(frozen=True)
class PublishOutboxEventsResult:
    claimed_count: int
    published_count: int
    failed_count: int
    published_events: tuple[OutboxEvent, ...]


async def publish_outbox_events(
    *,
    outbox_repository: OutboxEventRepository,
    publisher: OutboxEventPublisher,
    now: datetime,
    batch_size: int = 100,
    lease_duration: timedelta = timedelta(minutes=5),
    retry_base_delay: timedelta = timedelta(seconds=30),
    retry_max_delay: timedelta = timedelta(minutes=15),
    max_attempts: int = 10,
) -> PublishOutboxEventsResult:
    claimed = await outbox_repository.claim_available_batch(
        now=now,
        limit=batch_size,
        lease_duration=lease_duration,
        max_attempts=max_attempts,
    )
    published: list[OutboxEvent] = []
    failed_count = 0

    for event in claimed:
        try:
            await publisher.publish(event)
        except Exception as exc:
            failed_count += 1
            await outbox_repository.mark_failed(
                event.outbox_event_id,
                error=str(exc) or exc.__class__.__name__,
                available_at=now
                + exponential_retry_delay(
                    event.attempt_count,
                    base_delay=retry_base_delay,
                    max_delay=retry_max_delay,
                ),
            )
            continue
        published.append(await outbox_repository.mark_published(event.outbox_event_id, now=now))

    return PublishOutboxEventsResult(
        claimed_count=len(claimed),
        published_count=len(published),
        failed_count=failed_count,
        published_events=tuple(published),
    )
