from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import OutboundMessageModel


class PostgresOutboundMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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


def _message_to_values(message: OutboundMessage) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "workspace_id": message.workspace_id,
        "lead_id": message.lead_id,
        "campaign_id": message.campaign_id,
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
        "provider_message_id": message.provider_message_id,
        "failure_reason": message.failure_reason,
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
        provider_message_id=model.provider_message_id,
        failure_reason=model.failure_reason,
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