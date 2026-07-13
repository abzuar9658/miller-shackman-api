from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import AggregateType, DomainEvent, DomainEventType, OutboxEventStatus
from app.infrastructure.persistence.postgres.models import WorkspaceModel
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
)

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
MESSAGE_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.asyncio
async def test_outbox_repository_appends_claims_and_marks_published(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace(postgres_session)
    repository = PostgresOutboxEventRepository(postgres_session)
    appended = await repository.append(_domain_event(), now=NOW)

    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert appended.status == OutboxEventStatus.PENDING
    assert len(claimed) == 1
    assert claimed[0].status == OutboxEventStatus.PUBLISHING
    assert claimed[0].attempt_count == 1
    assert claimed[0].available_at == NOW + timedelta(minutes=5)

    published = await repository.mark_published(claimed[0].outbox_event_id, now=NOW)
    assert published.status == OutboxEventStatus.PUBLISHED
    assert published.published_at == NOW


@pytest.mark.asyncio
async def test_outbox_repository_failed_events_are_reclaimed_after_available_at(
    postgres_session: AsyncSession,
) -> None:
    await _create_workspace(postgres_session)
    repository = PostgresOutboxEventRepository(postgres_session)
    await repository.append(_domain_event(), now=NOW)
    claimed = await repository.claim_available_batch(
        now=NOW,
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    failed = await repository.mark_failed(
        claimed[0].outbox_event_id,
        error="rabbit unavailable",
        available_at=NOW + timedelta(minutes=1),
    )

    not_ready = await repository.claim_available_batch(
        now=NOW + timedelta(seconds=30),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )
    ready = await repository.claim_available_batch(
        now=NOW + timedelta(minutes=1),
        limit=10,
        lease_duration=timedelta(minutes=5),
        max_attempts=3,
    )

    assert failed.status == OutboxEventStatus.FAILED
    assert failed.last_error == "rabbit unavailable"
    assert not_ready == ()
    assert len(ready) == 1
    assert ready[0].attempt_count == 2


def _domain_event() -> DomainEvent:
    return DomainEvent(
        workspace_id=WORKSPACE_ID,
        aggregate_type=AggregateType.MESSAGE,
        aggregate_id=MESSAGE_ID,
        event_type=DomainEventType.MESSAGE_SENT,
        payload={"message_id": str(MESSAGE_ID)},
    )


async def _create_workspace(postgres_session: AsyncSession) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
