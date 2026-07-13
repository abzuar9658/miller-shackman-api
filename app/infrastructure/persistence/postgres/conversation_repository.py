from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Handoff,
    HandoffCompletionRecord,
    HandoffReasonCode,
    HandoffStatus,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.infrastructure.persistence.postgres.models import (
    ConversationModel,
    ConversationSummaryModel,
    HandoffCompletionModel,
    HandoffModel,
    InboundMessageModel,
)


class PostgresConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Conversation | None:
        statement = (
            select(ConversationModel)
            .where(ConversationModel.workspace_id == workspace_id)
            .where(ConversationModel.lead_id == lead_id)
            .order_by(ConversationModel.updated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        model = result.scalar_one_or_none()
        return _model_to_conversation(model) if model is not None else None

    async def save(self, conversation: Conversation) -> Conversation:
        values = _conversation_to_values(conversation)
        update_values = {key: value for key, value in values.items() if key != "conversation_id"}
        statement = (
            insert(ConversationModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["conversation_id"], set_=update_values)
            .returning(ConversationModel)
        )
        result = await self._session.execute(statement)
        return _model_to_conversation(result.scalar_one())


class PostgresInboundMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[InboundMessage, ...]:
        result = await self._session.execute(
            select(InboundMessageModel)
            .where(InboundMessageModel.workspace_id == workspace_id)
            .where(InboundMessageModel.lead_id == lead_id)
            .order_by(InboundMessageModel.received_at.desc())
            .limit(limit),
        )
        return tuple(_model_to_inbound_message(model) for model in result.scalars().all())

    async def save(self, message: InboundMessage) -> InboundMessage:
        values = _inbound_message_to_values(message)
        update_values = {
            key: value
            for key, value in values.items()
            if key not in ("inbound_message_id", "workspace_id", "provider", "provider_message_id")
        }
        statement = (
            insert(InboundMessageModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "provider", "provider_message_id"],
                set_=update_values,
            )
            .returning(InboundMessageModel)
        )
        result = await self._session.execute(statement)
        return _model_to_inbound_message(result.scalar_one())


class PostgresConversationSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        values = _conversation_summary_to_values(summary)
        update_values = {key: value for key, value in values.items() if key != "summary_id"}
        statement = (
            insert(ConversationSummaryModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["summary_id"], set_=update_values)
            .returning(ConversationSummaryModel)
        )
        result = await self._session.execute(statement)
        return _model_to_conversation_summary(result.scalar_one())


class PostgresHandoffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        result = await self._session.execute(
            select(HandoffModel)
            .where(HandoffModel.workspace_id == workspace_id)
            .where(HandoffModel.lead_id == lead_id)
            .order_by(HandoffModel.created_at.desc(), HandoffModel.handoff_id.desc())
            .limit(limit),
        )
        models = result.scalars().all()
        return tuple(_model_to_handoff(model) for model in models)

    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        result = await self._session.execute(
            select(HandoffModel)
            .where(HandoffModel.workspace_id == workspace_id)
            .order_by(HandoffModel.created_at.desc(), HandoffModel.handoff_id.desc())
            .limit(limit),
        )
        models = result.scalars().all()
        return tuple(_model_to_handoff(model) for model in models)

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        handoff_id: UUID,
    ) -> Handoff | None:
        result = await self._session.execute(
            select(HandoffModel)
            .where(HandoffModel.workspace_id == workspace_id)
            .where(HandoffModel.handoff_id == handoff_id),
        )
        model = result.scalar_one_or_none()
        return _model_to_handoff(model) if model is not None else None

    async def save(self, handoff: Handoff) -> Handoff:
        values = _handoff_to_values(handoff)
        update_values = {key: value for key, value in values.items() if key != "handoff_id"}
        statement = (
            insert(HandoffModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["handoff_id"], set_=update_values)
            .returning(HandoffModel)
        )
        result = await self._session.execute(statement)
        return _model_to_handoff(result.scalar_one())


class PostgresHandoffCompletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_handoff_id(
        self,
        workspace_id: WorkspaceId,
        handoff_id: UUID,
    ) -> HandoffCompletionRecord | None:
        result = await self._session.execute(
            select(HandoffCompletionModel)
            .where(HandoffCompletionModel.workspace_id == workspace_id)
            .where(HandoffCompletionModel.handoff_id == handoff_id),
        )
        model = result.scalar_one_or_none()
        return _model_to_handoff_completion(model) if model is not None else None

    async def save(self, record: HandoffCompletionRecord) -> HandoffCompletionRecord:
        values = _handoff_completion_to_values(record)
        update_values = {key: value for key, value in values.items() if key != "handoff_id"}
        statement = (
            insert(HandoffCompletionModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["handoff_id"], set_=update_values)
            .returning(HandoffCompletionModel)
        )
        result = await self._session.execute(statement)
        return _model_to_handoff_completion(result.scalar_one())


def _conversation_to_values(conversation: Conversation) -> dict[str, object]:
    return {
        "conversation_id": conversation.conversation_id,
        "workspace_id": conversation.workspace_id,
        "lead_id": conversation.lead_id,
        "campaign_id": conversation.campaign_id,
        "workflow_id": conversation.workflow_id,
        "status": conversation.status.value,
        "ai_interaction_count": conversation.ai_interaction_count,
        "last_message_at": conversation.last_message_at,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
    }


def _model_to_conversation(model: ConversationModel) -> Conversation:
    return Conversation(
        conversation_id=model.conversation_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        campaign_id=model.campaign_id,
        workflow_id=model.workflow_id,
        status=ConversationStatus(model.status),
        ai_interaction_count=model.ai_interaction_count,
        last_message_at=model.last_message_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _inbound_message_to_values(message: InboundMessage) -> dict[str, object]:
    return {
        "inbound_message_id": message.inbound_message_id,
        "workspace_id": message.workspace_id,
        "conversation_id": message.conversation_id,
        "lead_id": message.lead_id,
        "channel": message.channel.value,
        "provider": message.provider,
        "provider_message_id": message.provider_message_id,
        "external_event_id": message.external_event_id,
        "from_address_redacted": message.from_address_redacted,
        "to_address_redacted": message.to_address_redacted,
        "body": message.body,
        "received_at": message.received_at,
        "processed_at": message.processed_at,
        "classification_status": message.classification_status.value,
        "created_at": message.created_at,
    }


def _model_to_inbound_message(model: InboundMessageModel) -> InboundMessage:
    return InboundMessage(
        inbound_message_id=model.inbound_message_id,
        workspace_id=model.workspace_id,
        conversation_id=model.conversation_id,
        lead_id=model.lead_id,
        channel=ContactChannel(model.channel),
        provider=model.provider,
        provider_message_id=model.provider_message_id,
        external_event_id=model.external_event_id,
        from_address_redacted=model.from_address_redacted,
        to_address_redacted=model.to_address_redacted,
        body=model.body,
        received_at=model.received_at,
        processed_at=model.processed_at,
        classification_status=InboundMessageClassificationStatus(model.classification_status),
        created_at=model.created_at,
    )


def _conversation_summary_to_values(summary: ConversationSummary) -> dict[str, object]:
    return {
        "summary_id": summary.summary_id,
        "workspace_id": summary.workspace_id,
        "conversation_id": summary.conversation_id,
        "lead_id": summary.lead_id,
        "summary_text": summary.summary_text,
        "preferences": dict(summary.preferences),
        "prompt_version": summary.prompt_version,
        "model": summary.model,
        "confidence": summary.confidence,
        "created_at": summary.created_at,
    }


def _model_to_conversation_summary(model: ConversationSummaryModel) -> ConversationSummary:
    return ConversationSummary(
        summary_id=model.summary_id,
        workspace_id=model.workspace_id,
        conversation_id=model.conversation_id,
        lead_id=model.lead_id,
        summary_text=model.summary_text,
        preferences=model.preferences,
        prompt_version=model.prompt_version,
        model=model.model,
        confidence=model.confidence,
        created_at=model.created_at,
    )


def _handoff_to_values(handoff: Handoff) -> dict[str, object]:
    return {
        "handoff_id": handoff.handoff_id,
        "workspace_id": handoff.workspace_id,
        "lead_id": handoff.lead_id,
        "campaign_id": handoff.campaign_id,
        "workflow_id": handoff.workflow_id,
        "conversation_id": handoff.conversation_id,
        "inbound_message_id": handoff.inbound_message_id,
        "assigned_agent_user_id": handoff.assigned_agent_user_id,
        "assigned_agent_crm_id": handoff.assigned_agent_crm_id,
        "reason_code": handoff.reason_code.value,
        "summary": handoff.summary,
        "latest_inbound_text": handoff.latest_inbound_text,
        "preferences": dict(handoff.preferences),
        "status": handoff.status.value,
        "created_at": handoff.created_at,
        "notified_at": handoff.notified_at,
        "acknowledged_at": handoff.acknowledged_at,
    }


def _model_to_handoff(model: HandoffModel) -> Handoff:
    return Handoff(
        handoff_id=model.handoff_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        campaign_id=model.campaign_id,
        workflow_id=model.workflow_id,
        conversation_id=model.conversation_id,
        inbound_message_id=model.inbound_message_id,
        assigned_agent_user_id=model.assigned_agent_user_id,
        assigned_agent_crm_id=model.assigned_agent_crm_id,
        reason_code=HandoffReasonCode(model.reason_code),
        summary=model.summary,
        latest_inbound_text=model.latest_inbound_text,
        preferences=model.preferences,
        status=HandoffStatus(model.status),
        created_at=model.created_at,
        notified_at=model.notified_at,
        acknowledged_at=model.acknowledged_at,
    )


def _handoff_completion_to_values(record: HandoffCompletionRecord) -> dict[str, object]:
    return {
        "handoff_id": record.handoff_id,
        "workspace_id": record.workspace_id,
        "notification_idempotency_key": record.notification_idempotency_key,
        "notification_recipient_id": record.notification_recipient_id,
        "notification_recipient_destination": record.notification_recipient_destination,
        "notification_provider_reference": record.notification_provider_reference,
        "notification_sent_at": record.notification_sent_at,
        "crm_note_written_at": record.crm_note_written_at,
        "crm_tag_applied_at": record.crm_tag_applied_at,
        "crm_custom_fields_updated_at": record.crm_custom_fields_updated_at,
        "completed_at": record.completed_at,
        "last_attempted_at": record.last_attempted_at,
        "failure_reason": record.failure_reason,
    }


def _model_to_handoff_completion(model: HandoffCompletionModel) -> HandoffCompletionRecord:
    return HandoffCompletionRecord(
        handoff_id=model.handoff_id,
        workspace_id=model.workspace_id,
        notification_idempotency_key=model.notification_idempotency_key,
        notification_recipient_id=model.notification_recipient_id,
        notification_recipient_destination=model.notification_recipient_destination,
        notification_provider_reference=model.notification_provider_reference,
        notification_sent_at=model.notification_sent_at,
        crm_note_written_at=model.crm_note_written_at,
        crm_tag_applied_at=model.crm_tag_applied_at,
        crm_custom_fields_updated_at=model.crm_custom_fields_updated_at,
        completed_at=model.completed_at,
        last_attempted_at=model.last_attempted_at,
        failure_reason=model.failure_reason,
    )
