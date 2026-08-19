from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageCRMCompletionRecord,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import (
    OutboundMessageCRMCompletionModel,
    OutboundMessageModel,
)


class PostgresOutboundMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.workspace_id == workspace_id)
            .where(OutboundMessageModel.lead_id == lead_id)
            .order_by(OutboundMessageModel.created_at.desc())
            .limit(limit),
        )
        return tuple(_model_to_message(model) for model in result.scalars().all())

    async def get_latest_sent_at_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        campaign_id: CampaignId | None = None,
        channel: ContactChannel | None = None,
    ) -> datetime | None:
        statement = (
            select(func.max(OutboundMessageModel.sent_at))
            .where(OutboundMessageModel.workspace_id == workspace_id)
            .where(OutboundMessageModel.lead_id == lead_id)
            .where(OutboundMessageModel.status == OutboundMessageStatus.SENT.value)
        )
        if campaign_id is not None:
            statement = statement.where(OutboundMessageModel.campaign_id == campaign_id)
        if channel is not None:
            statement = statement.where(OutboundMessageModel.channel == channel.value)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel).where(
                OutboundMessageModel.workspace_id == workspace_id,
                OutboundMessageModel.message_id == message_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.workspace_id == workspace_id)
            .where(OutboundMessageModel.message_id == message_id)
            .with_for_update(),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            _by_idempotency_key_statement(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
                for_update=False,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            _by_idempotency_key_statement(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
                for_update=True,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_provider_message_id_for_workspace(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.workspace_id == workspace_id)
            .where(OutboundMessageModel.provider_name == provider_name)
            .where(OutboundMessageModel.provider_message_id == provider_message_id)
            .order_by(
                OutboundMessageModel.sent_at.desc().nulls_last(),
                OutboundMessageModel.created_at.desc(),
            )
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_reply_routing_token(
        self,
        workspace_id: WorkspaceId,
        reply_routing_token: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.workspace_id == workspace_id)
            .where(OutboundMessageModel.reply_routing_token == reply_routing_token)
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_provider_message_id(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.provider_name == provider_name)
            .where(OutboundMessageModel.provider_message_id == provider_message_id),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def get_by_provider_message_id_for_update(
        self,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        result = await self._session.execute(
            select(OutboundMessageModel)
            .where(OutboundMessageModel.provider_name == provider_name)
            .where(OutboundMessageModel.provider_message_id == provider_message_id)
            .with_for_update(),
        )
        model = result.scalar_one_or_none()
        return _model_to_message(model) if model else None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        values = _message_to_values(message)
        update_values = {key: value for key, value in values.items() if key != "message_id"}
        statement = (
            insert(OutboundMessageModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["message_id"],
                set_=update_values,
            )
            .returning(OutboundMessageModel)
        )
        result = await self._session.execute(statement)
        return _model_to_message(result.scalar_one())


class PostgresOutboundMessageCRMCompletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundMessageCRMCompletionRecord | None:
        result = await self._session.execute(
            select(OutboundMessageCRMCompletionModel)
            .where(OutboundMessageCRMCompletionModel.workspace_id == workspace_id)
            .where(
                OutboundMessageCRMCompletionModel.outbound_message_id == outbound_message_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_outbound_message_crm_completion(model) if model else None

    async def save(
        self,
        record: OutboundMessageCRMCompletionRecord,
    ) -> OutboundMessageCRMCompletionRecord:
        values = _outbound_message_crm_completion_to_values(record)
        update_values = {
            key: value for key, value in values.items() if key != "outbound_message_id"
        }
        statement = (
            insert(OutboundMessageCRMCompletionModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["outbound_message_id"],
                set_=update_values,
            )
            .returning(OutboundMessageCRMCompletionModel)
        )
        result = await self._session.execute(statement)
        return _model_to_outbound_message_crm_completion(result.scalar_one())


def _message_to_values(message: OutboundMessage) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "workspace_id": message.workspace_id,
        "lead_id": message.lead_id,
        "campaign_id": message.campaign_id,
        "workflow_id": message.workflow_id,
        "cadence_step_id": message.cadence_step_id,
        "channel": message.channel.value,
        "status": message.status.value,
        "idempotency_key": message.idempotency_key,
        "body": message.body,
        "subject": message.subject,
        "html_body": message.html_body,
        "scheduled_for": message.scheduled_for,
        "planned_at": message.planned_at,
        "sent_at": message.sent_at,
        "message_version": message.message_version,
        "provider_send_status": message.provider_send_status.value,
        "provider_name": message.provider_name,
        "provider_message_id": message.provider_message_id,
        "reply_routing_token": message.reply_routing_token,
        "provider_delivery_status": (
            message.provider_delivery_status.value
            if message.provider_delivery_status is not None
            else None
        ),
        "provider_status_updated_at": message.provider_status_updated_at,
        "delivered_at": message.delivered_at,
        "failure_reason": message.failure_reason,
        "status_detail": message.status_detail,
        "provider_attempt_count": message.provider_attempt_count,
        "provider_last_attempt_at": message.provider_last_attempt_at,
        "provider_next_retry_at": message.provider_next_retry_at,
        "provider_last_failure_kind": message.provider_last_failure_kind,
        "draft_prompt_version": message.draft_prompt_version,
        "draft_model": message.draft_model,
        "draft_latency_ms": message.draft_latency_ms,
        "draft_usage_tokens": message.draft_usage_tokens,
        "draft_confidence": message.draft_confidence,
        "draft_personalization_notes": list(message.draft_personalization_notes),
        "draft_safety_flags": list(message.draft_safety_flags),
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }


def _model_to_message(model: OutboundMessageModel) -> OutboundMessage:
    return OutboundMessage(
        message_id=model.message_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        campaign_id=model.campaign_id,
        workflow_id=model.workflow_id,
        cadence_step_id=model.cadence_step_id,
        channel=ContactChannel(model.channel),
        status=OutboundMessageStatus(model.status),
        idempotency_key=model.idempotency_key,
        body=model.body,
        subject=model.subject,
        html_body=model.html_body,
        scheduled_for=model.scheduled_for,
        planned_at=model.planned_at,
        sent_at=model.sent_at,
        message_version=model.message_version,
        provider_send_status=ProviderSendStatus(model.provider_send_status),
        provider_name=model.provider_name,
        provider_message_id=model.provider_message_id,
        reply_routing_token=model.reply_routing_token,
        provider_delivery_status=(
            ProviderDeliveryStatus(model.provider_delivery_status)
            if model.provider_delivery_status is not None
            else None
        ),
        provider_status_updated_at=model.provider_status_updated_at,
        delivered_at=model.delivered_at,
        failure_reason=model.failure_reason,
        status_detail=model.status_detail,
        provider_attempt_count=model.provider_attempt_count,
        provider_last_attempt_at=model.provider_last_attempt_at,
        provider_next_retry_at=model.provider_next_retry_at,
        provider_last_failure_kind=model.provider_last_failure_kind,
        draft_prompt_version=model.draft_prompt_version,
        draft_model=model.draft_model,
        draft_latency_ms=model.draft_latency_ms,
        draft_usage_tokens=model.draft_usage_tokens,
        draft_confidence=model.draft_confidence,
        draft_personalization_notes=tuple(model.draft_personalization_notes),
        draft_safety_flags=tuple(model.draft_safety_flags),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _outbound_message_crm_completion_to_values(
    record: OutboundMessageCRMCompletionRecord,
) -> dict[str, object]:
    return {
        "outbound_message_id": record.outbound_message_id,
        "workspace_id": record.workspace_id,
        "crm_note_idempotency_key": record.crm_note_idempotency_key,
        "crm_note_written_at": record.crm_note_written_at,
        "crm_conversation_published_at": record.crm_conversation_published_at,
        "crm_snapshot_updated_at": record.crm_snapshot_updated_at,
        "completed_at": record.completed_at,
        "last_attempted_at": record.last_attempted_at,
        "failure_reason": record.failure_reason,
    }


def _model_to_outbound_message_crm_completion(
    model: OutboundMessageCRMCompletionModel,
) -> OutboundMessageCRMCompletionRecord:
    return OutboundMessageCRMCompletionRecord(
        outbound_message_id=model.outbound_message_id,
        workspace_id=model.workspace_id,
        crm_note_idempotency_key=model.crm_note_idempotency_key,
        crm_note_written_at=model.crm_note_written_at,
        crm_conversation_published_at=model.crm_conversation_published_at,
        crm_snapshot_updated_at=model.crm_snapshot_updated_at,
        completed_at=model.completed_at,
        last_attempted_at=model.last_attempted_at,
        failure_reason=model.failure_reason,
    )


def _by_idempotency_key_statement(
    *,
    workspace_id: WorkspaceId,
    idempotency_key: str,
    for_update: bool,
) -> Select[tuple[OutboundMessageModel]]:
    statement = select(OutboundMessageModel).where(
        OutboundMessageModel.workspace_id == workspace_id,
        OutboundMessageModel.idempotency_key == idempotency_key,
    )
    if for_update:
        statement = statement.with_for_update()
    return statement
