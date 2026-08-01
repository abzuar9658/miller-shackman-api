from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
)
from app.infrastructure.persistence.postgres.models import TemporalSignalOutboxModel


class PostgresTemporalSignalOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        result = await self._session.execute(
            insert(TemporalSignalOutboxModel)
            .values(**_entry_to_values(entry))
            .on_conflict_do_nothing(constraint="uq_temporal_signal_outbox_workspace_idempotency")
            .returning(TemporalSignalOutboxModel)
        )
        model = result.scalar_one_or_none()
        if model is not None:
            return _model_to_entry(model)
        existing = await self._session.execute(
            select(TemporalSignalOutboxModel).where(
                TemporalSignalOutboxModel.workspace_id == entry.workspace_id,
                TemporalSignalOutboxModel.idempotency_key == entry.idempotency_key,
            )
        )
        return _model_to_entry(existing.scalar_one())

    async def claim_available_batch(
        self,
        *,
        now: datetime,
        limit: int,
        lease_duration: timedelta,
        max_attempts: int,
    ) -> tuple[TemporalSignalOutboxEntry, ...]:
        claimable_ids = (
            select(TemporalSignalOutboxModel.temporal_signal_id)
            .where(
                TemporalSignalOutboxModel.attempt_count < max_attempts,
                or_(
                    and_(
                        TemporalSignalOutboxModel.status.in_(
                            [
                                TemporalSignalOutboxStatus.PENDING.value,
                                TemporalSignalOutboxStatus.FAILED.value,
                            ]
                        ),
                        TemporalSignalOutboxModel.available_at <= now,
                    ),
                    and_(
                        TemporalSignalOutboxModel.status
                        == TemporalSignalOutboxStatus.DISPATCHING.value,
                        TemporalSignalOutboxModel.claimed_until.is_not(None),
                        TemporalSignalOutboxModel.claimed_until <= now,
                    ),
                ),
            )
            .order_by(TemporalSignalOutboxModel.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(TemporalSignalOutboxModel)
            .where(TemporalSignalOutboxModel.temporal_signal_id.in_(claimable_ids))
            .values(
                status=TemporalSignalOutboxStatus.DISPATCHING.value,
                attempt_count=TemporalSignalOutboxModel.attempt_count + 1,
                claimed_until=now + lease_duration,
                last_error=None,
                updated_at=now,
            )
            .returning(TemporalSignalOutboxModel)
        )
        return tuple(_model_to_entry(model) for model in result.scalars().all())

    async def mark_sent(
        self,
        temporal_signal_id: UUID,
        *,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return await self._update_status(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.SENT,
            available_at=now,
            claimed_until=None,
            sent_at=now,
            last_error=None,
            updated_at=now,
        )

    async def mark_failed(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        available_at: datetime,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return await self._update_status(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.FAILED,
            available_at=available_at,
            claimed_until=None,
            sent_at=None,
            last_error=error[:1000],
            updated_at=now,
        )

    async def mark_terminal_failure(
        self,
        temporal_signal_id: UUID,
        *,
        error: str,
        now: datetime,
    ) -> TemporalSignalOutboxEntry:
        return await self._update_status(
            temporal_signal_id,
            status=TemporalSignalOutboxStatus.TERMINAL_FAILURE,
            available_at=now,
            claimed_until=None,
            sent_at=None,
            last_error=error[:1000],
            updated_at=now,
        )

    async def _update_status(
        self,
        temporal_signal_id: UUID,
        *,
        status: TemporalSignalOutboxStatus,
        available_at: datetime,
        claimed_until: datetime | None,
        sent_at: datetime | None,
        last_error: str | None,
        updated_at: datetime,
    ) -> TemporalSignalOutboxEntry:
        result = await self._session.execute(
            update(TemporalSignalOutboxModel)
            .where(TemporalSignalOutboxModel.temporal_signal_id == temporal_signal_id)
            .values(
                status=status.value,
                available_at=available_at,
                claimed_until=claimed_until,
                sent_at=sent_at,
                last_error=last_error,
                updated_at=updated_at,
            )
            .returning(TemporalSignalOutboxModel)
        )
        return _model_to_entry(result.scalar_one())


def _entry_to_values(entry: TemporalSignalOutboxEntry) -> dict[str, object]:
    return {
        "temporal_signal_id": entry.temporal_signal_id,
        "workspace_id": entry.workspace_id,
        "workflow_id": entry.workflow_id,
        "temporal_workflow_id": entry.temporal_workflow_id,
        "signal_name": entry.signal_name.value,
        "payload": dict(entry.payload),
        "idempotency_key": entry.idempotency_key,
        "status": entry.status.value,
        "attempt_count": entry.attempt_count,
        "available_at": entry.available_at,
        "claimed_until": entry.claimed_until,
        "sent_at": entry.sent_at,
        "last_error": entry.last_error,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


def _model_to_entry(model: TemporalSignalOutboxModel) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=model.temporal_signal_id,
        workspace_id=model.workspace_id,
        workflow_id=model.workflow_id,
        temporal_workflow_id=model.temporal_workflow_id,
        signal_name=TemporalSignalName(model.signal_name),
        payload=dict(model.payload),
        idempotency_key=model.idempotency_key,
        status=TemporalSignalOutboxStatus(model.status),
        attempt_count=model.attempt_count,
        available_at=model.available_at,
        claimed_until=model.claimed_until,
        sent_at=model.sent_at,
        last_error=model.last_error,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
