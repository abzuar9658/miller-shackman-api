from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.events import DomainEvent, OutboxEvent


class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError


class OutboxEventRepository(Protocol):
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
        raise NotImplementedError

    async def mark_published(self, outbox_event_id: UUID, *, now: datetime) -> OutboxEvent:
        raise NotImplementedError

    async def mark_failed(
        self,
        outbox_event_id: UUID,
        *,
        error: str,
        available_at: datetime,
    ) -> OutboxEvent:
        raise NotImplementedError


class OutboxEventPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None:
        raise NotImplementedError
