from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import OutboundSendReconciliationModel


class PostgresOutboundSendReconciliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        result = await self._session.execute(
            select(OutboundSendReconciliationModel).where(
                OutboundSendReconciliationModel.workspace_id == workspace_id,
                OutboundSendReconciliationModel.reconciliation_id == reconciliation_id,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_reconciliation(model) if model is not None else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        result = await self._session.execute(
            select(OutboundSendReconciliationModel)
            .where(OutboundSendReconciliationModel.workspace_id == workspace_id)
            .where(OutboundSendReconciliationModel.reconciliation_id == reconciliation_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _model_to_reconciliation(model) if model is not None else None

    async def get_by_outbound_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendReconciliation | None:
        result = await self._session.execute(
            select(OutboundSendReconciliationModel)
            .where(OutboundSendReconciliationModel.workspace_id == workspace_id)
            .where(OutboundSendReconciliationModel.outbound_message_id == outbound_message_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _model_to_reconciliation(model) if model is not None else None

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        result = await self._session.execute(
            select(OutboundSendReconciliationModel)
            .where(OutboundSendReconciliationModel.workspace_id == workspace_id)
            .where(OutboundSendReconciliationModel.idempotency_key == idempotency_key)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _model_to_reconciliation(model) if model is not None else None

    async def create_or_get(
        self,
        reconciliation: OutboundSendReconciliation,
    ) -> OutboundSendReconciliation:
        values = _reconciliation_to_values(reconciliation)
        result = await self._session.execute(
            insert(OutboundSendReconciliationModel)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_outbound_reconciliations_workspace_idempotency",
            )
            .returning(OutboundSendReconciliationModel)
        )
        model = result.scalar_one_or_none()
        if model is not None:
            return _model_to_reconciliation(model)
        existing = await self.get_by_idempotency_key_for_update(
            reconciliation.workspace_id,
            reconciliation.idempotency_key,
        )
        if existing is None:
            raise RuntimeError("outbound send reconciliation was not persisted")
        return existing

    async def resolve(
        self,
        *,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
        status: OutboundSendReconciliationStatus,
        now: datetime,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
    ) -> OutboundSendReconciliation | None:
        existing = await self.get_by_id_for_update(workspace_id, reconciliation_id)
        if existing is None or existing.status is not OutboundSendReconciliationStatus.PENDING:
            return existing
        resolved = OutboundSendReconciliation(
            **{
                **existing.__dict__,
                "status": status,
                "provider_message_id": provider_message_id or existing.provider_message_id,
                "provider_delivery_status": provider_delivery_status
                or existing.provider_delivery_status,
                "updated_at": now,
                "resolved_at": (
                    existing.resolved_at
                    if status is OutboundSendReconciliationStatus.PENDING
                    else now
                ),
                "failure_reason": failure_reason,
            }
        )
        values = _reconciliation_to_values(resolved)
        result = await self._session.execute(
            insert(OutboundSendReconciliationModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["reconciliation_id"],
                set_={key: value for key, value in values.items() if key != "reconciliation_id"},
            )
            .returning(OutboundSendReconciliationModel)
        )
        return _model_to_reconciliation(result.scalar_one())


def _reconciliation_to_values(
    reconciliation: OutboundSendReconciliation,
) -> dict[str, object]:
    return {
        "reconciliation_id": reconciliation.reconciliation_id,
        "workspace_id": reconciliation.workspace_id,
        "lead_id": reconciliation.lead_id,
        "workflow_id": reconciliation.workflow_id,
        "temporal_workflow_id": reconciliation.temporal_workflow_id,
        "outbound_message_id": reconciliation.outbound_message_id,
        "idempotency_key": reconciliation.idempotency_key,
        "status": reconciliation.status.value,
        "provider_name": reconciliation.provider_name,
        "provider_message_id": reconciliation.provider_message_id,
        "provider_delivery_status": (
            reconciliation.provider_delivery_status.value
            if reconciliation.provider_delivery_status is not None
            else None
        ),
        "created_at": reconciliation.created_at,
        "updated_at": reconciliation.updated_at,
        "resolved_at": reconciliation.resolved_at,
        "failure_reason": reconciliation.failure_reason,
    }


def _model_to_reconciliation(
    model: OutboundSendReconciliationModel,
) -> OutboundSendReconciliation:
    return OutboundSendReconciliation(
        reconciliation_id=model.reconciliation_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        temporal_workflow_id=model.temporal_workflow_id,
        outbound_message_id=model.outbound_message_id,
        idempotency_key=model.idempotency_key,
        status=OutboundSendReconciliationStatus(model.status),
        provider_name=model.provider_name,
        provider_message_id=model.provider_message_id,
        provider_delivery_status=(
            ProviderDeliveryStatus(model.provider_delivery_status)
            if model.provider_delivery_status is not None
            else None
        ),
        created_at=model.created_at,
        updated_at=model.updated_at,
        resolved_at=model.resolved_at,
        failure_reason=model.failure_reason,
    )