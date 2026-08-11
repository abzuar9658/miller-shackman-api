from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_provider_failure import (
    OutboundProviderFailure,
    OutboundProviderFailureStatus,
)
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import OutboundProviderFailureModel


class PostgresOutboundProviderFailureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        failure: OutboundProviderFailure,
    ) -> OutboundProviderFailure:
        values = _failure_to_values(failure)
        result = await self._session.execute(
            insert(OutboundProviderFailureModel)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_outbound_provider_failures_workspace_message",
            )
            .returning(OutboundProviderFailureModel)
        )
        model = result.scalar_one_or_none()
        if model is not None:
            return _model_to_failure(model)
        existing_result = await self._session.execute(
            select(OutboundProviderFailureModel)
            .where(OutboundProviderFailureModel.workspace_id == failure.workspace_id)
            .where(OutboundProviderFailureModel.outbound_message_id == failure.outbound_message_id)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is None:
            raise RuntimeError("outbound provider failure was not persisted")
        return _model_to_failure(existing)

    async def list_open(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> list[OutboundProviderFailure]:
        result = await self._session.execute(
            select(OutboundProviderFailureModel)
            .where(OutboundProviderFailureModel.workspace_id == workspace_id)
            .where(OutboundProviderFailureModel.status == OutboundProviderFailureStatus.OPEN.value)
            .order_by(OutboundProviderFailureModel.created_at.asc())
            .limit(limit)
        )
        return [_model_to_failure(model) for model in result.scalars().all()]

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundProviderFailure | None:
        result = await self._session.execute(
            select(OutboundProviderFailureModel).where(
                OutboundProviderFailureModel.workspace_id == workspace_id,
                OutboundProviderFailureModel.outbound_message_id == outbound_message_id,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_failure(model) if model is not None else None


def _failure_to_values(failure: OutboundProviderFailure) -> dict[str, object]:
    return {
        "failure_id": failure.failure_id,
        "workspace_id": failure.workspace_id,
        "lead_id": failure.lead_id,
        "outbound_message_id": failure.outbound_message_id,
        "workflow_id": failure.workflow_id,
        "channel": failure.channel.value,
        "provider_name": failure.provider_name,
        "failure_kind": failure.failure_kind,
        "failure_reason": failure.failure_reason,
        "attempt_count": failure.attempt_count,
        "status": failure.status.value,
        "first_failed_at": failure.first_failed_at,
        "last_failed_at": failure.last_failed_at,
        "created_at": failure.created_at,
        "resolved_at": failure.resolved_at,
    }


def _model_to_failure(model: OutboundProviderFailureModel) -> OutboundProviderFailure:
    return OutboundProviderFailure(
        failure_id=model.failure_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        outbound_message_id=model.outbound_message_id,
        workflow_id=model.workflow_id,
        channel=ContactChannel(model.channel),
        provider_name=model.provider_name,
        failure_kind=model.failure_kind,
        failure_reason=model.failure_reason,
        attempt_count=model.attempt_count,
        status=OutboundProviderFailureStatus(model.status),
        first_failed_at=model.first_failed_at,
        last_failed_at=model.last_failed_at,
        created_at=model.created_at,
        resolved_at=model.resolved_at,
    )