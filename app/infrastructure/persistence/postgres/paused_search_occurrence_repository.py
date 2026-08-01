from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns import (
    PausedSearchTrackStepPhase,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.common.ids import PausedSearchTrackVersionId, WorkspaceId
from app.infrastructure.persistence.postgres.models import RecurringOccurrenceModel


class PostgresPausedSearchOccurrenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        lead_id: UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> tuple[RecurringOccurrence, ...]:
        statement = (
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .order_by(
                RecurringOccurrenceModel.scheduled_for.desc(),
                RecurringOccurrenceModel.occurrence_id.desc(),
            )
            .limit(limit)
        )
        if lead_id is not None:
            statement = statement.where(RecurringOccurrenceModel.lead_id == lead_id)
        if status is not None:
            statement = statement.where(RecurringOccurrenceModel.status == status)
        result = await self._session.execute(statement)
        return tuple(_from_model(model) for model in result.scalars().all())

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel).where(
                RecurringOccurrenceModel.workspace_id == workspace_id,
                RecurringOccurrenceModel.occurrence_id == occurrence_id,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_latest_for_step(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.workflow_id == workflow_id)
            .where(RecurringOccurrenceModel.track_version_id == track_version_id)
            .where(RecurringOccurrenceModel.step_id == step_id)
            .order_by(
                RecurringOccurrenceModel.occurrence_number.desc(),
                RecurringOccurrenceModel.scheduled_for.desc(),
            )
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_by_identity(
        self,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: datetime,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.workflow_id == workflow_id)
            .where(RecurringOccurrenceModel.track_version_id == track_version_id)
            .where(RecurringOccurrenceModel.step_id == step_id)
            .where(RecurringOccurrenceModel.occurrence_number == occurrence_number)
            .where(RecurringOccurrenceModel.scheduled_for == scheduled_for)
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel).where(
                RecurringOccurrenceModel.workspace_id == workspace_id,
                RecurringOccurrenceModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        await self._session.execute(
            insert(RecurringOccurrenceModel)
            .values(**_to_values(occurrence))
            .on_conflict_do_nothing()
        )
        saved = await self.get_by_idempotency_key(
            occurrence.workspace_id, occurrence.idempotency_key
        )
        if saved is None:
            saved = await self.get_by_identity(
                occurrence.workspace_id,
                occurrence.workflow_id,
                occurrence.track_version_id,
                occurrence.step_id,
                occurrence.occurrence_number,
                occurrence.scheduled_for,
            )
        assert saved is not None
        return saved

    async def get_by_provider_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        provider_message_id: str,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.provider_message_id == provider_message_id)
            .with_for_update()
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def update_status(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        fallback_used: bool | None = None,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.occurrence_id == occurrence_id)
            .with_for_update(),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None

        current_status = RecurringOccurrenceStatus(model.status)
        requested_status = RecurringOccurrenceStatus(status)
        if current_status in _TERMINAL_STATUSES and requested_status != current_status:
            return _from_model(model)

        model.status = requested_status.value
        if (
            requested_status == RecurringOccurrenceStatus.SENT
            and current_status != RecurringOccurrenceStatus.SENT
        ):
            model.logical_touch_count += 1
            model.closed_at = model.closed_at or now
        elif requested_status in _TERMINAL_STATUSES:
            model.closed_at = model.closed_at or now
        if provider_message_id is not None:
            model.provider_message_id = provider_message_id
        if provider_delivery_status is not None:
            model.provider_delivery_status = provider_delivery_status.value
        if failure_reason is not None:
            model.failure_reason = failure_reason
        if fallback_used is not None:
            model.fallback_used = fallback_used
        return _from_model(model)

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
        reason: str,
    ) -> int:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.workflow_id == workflow_id)
            .where(
                RecurringOccurrenceModel.status.in_(
                    [
                        RecurringOccurrenceStatus.PLANNED.value,
                        RecurringOccurrenceStatus.DEFERRED.value,
                        RecurringOccurrenceStatus.REVIEW_REQUESTED.value,
                        RecurringOccurrenceStatus.APPROVED.value,
                    ]
                )
            )
            .with_for_update()
        )
        occurrences = result.scalars().all()
        for model in occurrences:
            model.status = RecurringOccurrenceStatus.CANCELLED.value
            model.closed_at = model.closed_at or now
            model.failure_reason = reason
        return len(occurrences)

    async def resolve_uncertain(
        self,
        *,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
        status: str,
        now: datetime,
        reason: str,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.occurrence_id == occurrence_id)
            .with_for_update(),
        )
        model = result.scalar_one_or_none()
        if model is None or model.status != RecurringOccurrenceStatus.UNCERTAIN.value:
            return None

        resolved_status = RecurringOccurrenceStatus(status)
        if resolved_status not in {
            RecurringOccurrenceStatus.SENT,
            RecurringOccurrenceStatus.FAILED,
            RecurringOccurrenceStatus.SKIPPED,
        }:
            raise ValueError("Uncertain occurrences may resolve only to sent, failed, or skipped.")
        model.status = resolved_status.value
        model.logical_touch_count = 1 if resolved_status is RecurringOccurrenceStatus.SENT else 0
        model.closed_at = model.closed_at or now
        model.failure_reason = reason
        return _from_model(model)

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        occurrence_id: UUID,
    ) -> RecurringOccurrence | None:
        result = await self._session.execute(
            select(RecurringOccurrenceModel)
            .where(RecurringOccurrenceModel.workspace_id == workspace_id)
            .where(RecurringOccurrenceModel.occurrence_id == occurrence_id)
            .with_for_update(),
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None


_TERMINAL_STATUSES = frozenset(
    {
        RecurringOccurrenceStatus.SENT,
        RecurringOccurrenceStatus.SKIPPED,
        RecurringOccurrenceStatus.CANCELLED,
        RecurringOccurrenceStatus.EXPIRED,
        RecurringOccurrenceStatus.FAILED,
        RecurringOccurrenceStatus.MIGRATED_LEGACY,
    }
)


def _to_values(occurrence: RecurringOccurrence) -> dict[str, object]:
    return {
        "occurrence_id": occurrence.occurrence_id,
        "workspace_id": occurrence.workspace_id,
        "lead_id": occurrence.lead_id,
        "workflow_id": occurrence.workflow_id,
        "track_version_id": occurrence.track_version_id,
        "step_id": occurrence.step_id,
        "phase": occurrence.phase.value,
        "occurrence_number": occurrence.occurrence_number,
        "scheduled_for": occurrence.scheduled_for,
        "due_at": occurrence.due_at,
        "status": occurrence.status.value,
        "idempotency_key": occurrence.idempotency_key,
        "logical_touch_count": occurrence.logical_touch_count,
        "fallback_used": occurrence.fallback_used,
        "provider_message_id": occurrence.provider_message_id,
        "provider_delivery_status": (
            occurrence.provider_delivery_status.value
            if occurrence.provider_delivery_status is not None
            else None
        ),
        "correlation_id": occurrence.correlation_id,
        "failure_reason": occurrence.failure_reason,
        "created_at": occurrence.created_at,
        "closed_at": occurrence.closed_at,
        "timezone_snapshot": occurrence.timezone_snapshot,
    }


def _from_model(model: RecurringOccurrenceModel) -> RecurringOccurrence:
    return RecurringOccurrence(
        occurrence_id=model.occurrence_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        track_version_id=model.track_version_id,
        step_id=model.step_id,
        phase=PausedSearchTrackStepPhase(model.phase),
        occurrence_number=model.occurrence_number,
        scheduled_for=model.scheduled_for,
        due_at=model.due_at,
        status=RecurringOccurrenceStatus(model.status),
        idempotency_key=model.idempotency_key,
        logical_touch_count=model.logical_touch_count,
        fallback_used=model.fallback_used,
        provider_message_id=model.provider_message_id,
        provider_delivery_status=(
            ProviderDeliveryStatus(model.provider_delivery_status)
            if model.provider_delivery_status is not None
            else None
        ),
        correlation_id=model.correlation_id,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        closed_at=model.closed_at,
        timezone_snapshot=model.timezone_snapshot,
    )
