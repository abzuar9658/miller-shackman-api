from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import (
    AggregateType,
    DomainEvent,
    DomainEventType,
    OutboxEvent,
    OutboxEventStatus,
)
from app.infrastructure.persistence.postgres.models import OutboxEventModel


class PostgresTransactionalEventBus:
    def __init__(self, repository: "PostgresOutboxEventRepository") -> None:
        self._repository = repository

    async def publish(self, event: DomainEvent) -> None:
        await self._repository.append(event, now=datetime.now(UTC))


class PostgresOutboxEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: DomainEvent, *, now: datetime) -> OutboxEvent:
        result = await self._session.execute(
            insert(OutboxEventModel)
            .values(
                outbox_event_id=uuid4(),
                workspace_id=event.workspace_id,
                aggregate_type=event.aggregate_type.value,
                aggregate_id=event.aggregate_id,
                event_type=event.event_type.value,
                payload=dict(event.payload),
                status=OutboxEventStatus.PENDING.value,
                attempt_count=0,
                available_at=now,
                created_at=now,
                published_at=None,
                last_error=None,
            )
            .returning(OutboxEventModel)
        )
        return _model_to_event(result.scalar_one())

    async def claim_available_batch(
        self,
        *,
        now: datetime,
        limit: int,
        lease_duration: timedelta,
        max_attempts: int,
    ) -> tuple[OutboxEvent, ...]:
        claimable_ids = (
            select(OutboxEventModel.outbox_event_id)
            .where(
                OutboxEventModel.available_at <= now,
                OutboxEventModel.attempt_count < max_attempts,
                or_(
                    OutboxEventModel.status == OutboxEventStatus.PENDING.value,
                    OutboxEventModel.status == OutboxEventStatus.FAILED.value,
                    OutboxEventModel.status == OutboxEventStatus.PUBLISHING.value,
                ),
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.outbox_event_id.in_(claimable_ids))
            .values(
                status=OutboxEventStatus.PUBLISHING.value,
                attempt_count=OutboxEventModel.attempt_count + 1,
                available_at=now + lease_duration,
                last_error=None,
            )
            .returning(OutboxEventModel)
        )
        return tuple(_model_to_event(model) for model in result.scalars().all())

    async def mark_published(self, outbox_event_id: UUID, *, now: datetime) -> OutboxEvent:
        return await self._update_status(
            outbox_event_id,
            status=OutboxEventStatus.PUBLISHED,
            published_at=now,
            available_at=now,
            last_error=None,
        )

    async def mark_failed(
        self,
        outbox_event_id: UUID,
        *,
        error: str,
        available_at: datetime,
    ) -> OutboxEvent:
        return await self._update_status(
            outbox_event_id,
            status=OutboxEventStatus.FAILED,
            published_at=None,
            available_at=available_at,
            last_error=error[:1000],
        )

    async def _update_status(
        self,
        outbox_event_id: UUID,
        *,
        status: OutboxEventStatus,
        published_at: datetime | None,
        available_at: datetime,
        last_error: str | None,
    ) -> OutboxEvent:
        result = await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.outbox_event_id == outbox_event_id)
            .values(
                status=status.value,
                published_at=published_at,
                available_at=available_at,
                last_error=last_error,
            )
            .returning(OutboxEventModel)
        )
        return _model_to_event(result.scalar_one())


def _model_to_event(model: OutboxEventModel) -> OutboxEvent:
    return OutboxEvent(
        outbox_event_id=model.outbox_event_id,
        workspace_id=model.workspace_id,
        aggregate_type=AggregateType(model.aggregate_type),
        aggregate_id=model.aggregate_id,
        event_type=DomainEventType(model.event_type),
        payload=dict(model.payload),
        status=OutboxEventStatus(model.status),
        attempt_count=model.attempt_count,
        available_at=model.available_at,
        created_at=model.created_at,
        published_at=model.published_at,
        last_error=model.last_error,
    )
