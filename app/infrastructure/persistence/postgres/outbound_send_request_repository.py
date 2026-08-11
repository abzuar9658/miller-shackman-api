from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import OutboundSendRequestModel


class PostgresOutboundSendRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        request_id: UUID,
    ) -> OutboundSendRequest | None:
        result = await self._session.execute(
            select(OutboundSendRequestModel).where(
                OutboundSendRequestModel.workspace_id == workspace_id,
                OutboundSendRequestModel.request_id == request_id,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_request(model) if model is not None else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        request_id: UUID,
    ) -> OutboundSendRequest | None:
        result = await self._session.execute(
            select(OutboundSendRequestModel)
            .where(OutboundSendRequestModel.workspace_id == workspace_id)
            .where(OutboundSendRequestModel.request_id == request_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        return _model_to_request(model) if model is not None else None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendRequest | None:
        result = await self._session.execute(
            select(OutboundSendRequestModel).where(
                OutboundSendRequestModel.workspace_id == workspace_id,
                OutboundSendRequestModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_request(model) if model is not None else None

    async def create_or_get(self, request: OutboundSendRequest) -> OutboundSendRequest:
        result = await self._session.execute(
            insert(OutboundSendRequestModel)
            .values(**_request_to_values(request))
            .on_conflict_do_nothing()
            .returning(OutboundSendRequestModel)
        )
        model = result.scalar_one_or_none()
        if model is not None:
            return _model_to_request(model)
        existing = await self.get_by_idempotency_key(
            request.workspace_id,
            request.idempotency_key,
        )
        if existing is None:
            existing = await self.get_by_outbound_message_id(
                request.workspace_id,
                request.outbound_message_id,
            )
        if existing is None:
            raise RuntimeError("outbound send request was not persisted")
        return existing

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendRequest | None:
        result = await self._session.execute(
            select(OutboundSendRequestModel).where(
                OutboundSendRequestModel.workspace_id == workspace_id,
                OutboundSendRequestModel.outbound_message_id == outbound_message_id,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_request(model) if model is not None else None

    async def save(self, request: OutboundSendRequest) -> OutboundSendRequest:
        values = _request_to_values(request)
        result = await self._session.execute(
            insert(OutboundSendRequestModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["request_id"],
                set_={key: value for key, value in values.items() if key != "request_id"},
            )
            .returning(OutboundSendRequestModel)
        )
        return _model_to_request(result.scalar_one())

    async def claim_due_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        claimable_ids = (
            select(OutboundSendRequestModel.request_id)
            .where(
                OutboundSendRequestModel.status == OutboundSendRequestStatus.PENDING.value,
                OutboundSendRequestModel.available_at <= now,
            )
            .order_by(
                OutboundSendRequestModel.available_at.asc(),
                OutboundSendRequestModel.created_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(OutboundSendRequestModel)
            .where(OutboundSendRequestModel.request_id.in_(claimable_ids))
            .values(
                status=OutboundSendRequestStatus.DISPATCHING.value,
                attempt_count=OutboundSendRequestModel.attempt_count + 1,
                claimed_at=now,
                failure_kind=None,
                failure_reason=None,
                updated_at=now,
            )
            .returning(OutboundSendRequestModel)
        )
        return tuple(_model_to_request(model) for model in result.scalars().all())

    async def recover_stale_dispatching(
        self,
        *,
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        stale_ids = (
            select(OutboundSendRequestModel.request_id)
            .where(
                OutboundSendRequestModel.status == OutboundSendRequestStatus.DISPATCHING.value,
                OutboundSendRequestModel.claimed_at <= stale_before,
            )
            .order_by(OutboundSendRequestModel.claimed_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            update(OutboundSendRequestModel)
            .where(OutboundSendRequestModel.request_id.in_(stale_ids))
            .values(
                status=OutboundSendRequestStatus.UNCERTAIN.value,
                completed_at=now,
                failure_kind="uncertain",
                failure_reason="stale_dispatch_recovered_without_redispatch",
                updated_at=now,
            )
            .returning(OutboundSendRequestModel)
        )
        return tuple(_model_to_request(model) for model in result.scalars().all())

    async def get_due_pending_summary(
        self,
        *,
        now: datetime,
    ) -> tuple[int, datetime | None]:
        result = await self._session.execute(
            select(
                func.count(OutboundSendRequestModel.request_id),
                func.min(OutboundSendRequestModel.available_at),
            ).where(
                OutboundSendRequestModel.status == OutboundSendRequestStatus.PENDING.value,
                OutboundSendRequestModel.available_at <= now,
            )
        )
        pending_count, oldest_pending_at = result.one()
        return int(pending_count or 0), oldest_pending_at

    async def list_exceptions(
        self,
        *,
        workspace_id: WorkspaceId,
        statuses: tuple[OutboundSendRequestStatus, ...],
        stale_before: datetime,
        older_than: datetime | None = None,
        channel: ContactChannel | None = None,
        provider_name: str | None = None,
        limit: int = 100,
    ) -> tuple[OutboundSendRequest, ...]:
        status_values = tuple(status.value for status in statuses)
        regular_statuses = tuple(
            value
            for value in status_values
            if value != OutboundSendRequestStatus.DISPATCHING.value
        )
        status_filters: list[ColumnElement[bool]] = []
        if regular_statuses:
            status_filters.append(OutboundSendRequestModel.status.in_(regular_statuses))
        if OutboundSendRequestStatus.DISPATCHING.value in status_values:
            status_filters.append(
                and_(
                    OutboundSendRequestModel.status
                    == OutboundSendRequestStatus.DISPATCHING.value,
                    OutboundSendRequestModel.claimed_at <= stale_before,
                )
            )

        conditions: list[ColumnElement[bool]] = [
            OutboundSendRequestModel.workspace_id == workspace_id,
            or_(*status_filters),
        ]
        if older_than is not None:
            conditions.append(OutboundSendRequestModel.created_at <= older_than)
        if channel is not None:
            conditions.append(OutboundSendRequestModel.channel == channel.value)
        if provider_name is not None:
            conditions.append(OutboundSendRequestModel.provider_name == provider_name)

        result = await self._session.execute(
            select(OutboundSendRequestModel)
            .where(*conditions)
            .order_by(
                OutboundSendRequestModel.created_at.asc(),
                OutboundSendRequestModel.request_id.asc(),
            )
            .limit(limit)
        )
        return tuple(_model_to_request(model) for model in result.scalars().all())


def _request_to_values(request: OutboundSendRequest) -> dict[str, object]:
    return {
        "request_id": request.request_id,
        "workspace_id": request.workspace_id,
        "lead_id": request.lead_id,
        "workflow_id": request.workflow_id,
        "temporal_workflow_id": request.temporal_workflow_id,
        "outbound_message_id": request.outbound_message_id,
        "reconciliation_id": request.reconciliation_id,
        "idempotency_key": request.idempotency_key,
        "channel": request.channel.value,
        "provider_name": request.provider_name,
        "provider_payload": dict(request.provider_payload),
        "status": request.status.value,
        "attempt_count": request.attempt_count,
        "available_at": request.available_at,
        "claimed_at": request.claimed_at,
        "completed_at": request.completed_at,
        "provider_message_id": request.provider_message_id,
        "failure_kind": request.failure_kind,
        "failure_reason": request.failure_reason,
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }


def _model_to_request(model: OutboundSendRequestModel) -> OutboundSendRequest:
    return OutboundSendRequest(
        request_id=model.request_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        temporal_workflow_id=model.temporal_workflow_id,
        outbound_message_id=model.outbound_message_id,
        reconciliation_id=model.reconciliation_id,
        idempotency_key=model.idempotency_key,
        channel=ContactChannel(model.channel),
        provider_name=model.provider_name,
        provider_payload=dict(model.provider_payload),
        status=OutboundSendRequestStatus(model.status),
        attempt_count=model.attempt_count,
        available_at=model.available_at,
        claimed_at=model.claimed_at,
        completed_at=model.completed_at,
        provider_message_id=model.provider_message_id,
        failure_kind=model.failure_kind,
        failure_reason=model.failure_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )