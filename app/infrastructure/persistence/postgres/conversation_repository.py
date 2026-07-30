from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lead_read import LeadReadConversationSummary
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    CrmConversationEvent,
    CrmConversationEventDirection,
    CrmConversationTranscriptSegment,
    Handoff,
    HandoffCompletionRecord,
    HandoffReasonCode,
    HandoffStatus,
    InboundMessage,
    InboundMessageClassificationStatus,
    InboundMessageCRMCompletionRecord,
)
from app.infrastructure.persistence.postgres.models import (
    ConversationModel,
    ConversationSummaryModel,
    CrmConversationEventModel,
    HandoffCompletionModel,
    HandoffModel,
    InboundMessageCRMCompletionModel,
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

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> InboundMessage | None:
        result = await self._session.execute(
            select(InboundMessageModel).where(
                InboundMessageModel.workspace_id == workspace_id,
                InboundMessageModel.inbound_message_id == inbound_message_id,
            )
        )
        model = result.scalar_one_or_none()
        return _model_to_inbound_message(model) if model else None

    async def list_lead_summaries(
        self,
        workspace_id: WorkspaceId,
        lead_ids: tuple[LeadId, ...],
    ) -> tuple[LeadReadConversationSummary, ...]:
        if len(lead_ids) == 0:
            return ()

        lead_filter = InboundMessageModel.lead_id.in_(lead_ids)
        counts_subquery = (
            select(
                InboundMessageModel.lead_id.label("lead_id"),
                func.count().label("inbound_message_count"),
                func.max(InboundMessageModel.received_at).label("latest_inbound_at"),
            )
            .where(InboundMessageModel.workspace_id == workspace_id)
            .where(lead_filter)
            .group_by(InboundMessageModel.lead_id)
            .subquery()
        )
        latest_message_subquery = (
            select(
                InboundMessageModel.lead_id.label("lead_id"),
                InboundMessageModel.body.label("latest_inbound_body"),
                func.row_number()
                .over(
                    partition_by=InboundMessageModel.lead_id,
                    order_by=(
                        InboundMessageModel.received_at.desc(),
                        InboundMessageModel.inbound_message_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(InboundMessageModel.workspace_id == workspace_id)
            .where(lead_filter)
            .subquery()
        )
        result = await self._session.execute(
            select(
                counts_subquery.c.lead_id,
                counts_subquery.c.inbound_message_count,
                counts_subquery.c.latest_inbound_at,
                latest_message_subquery.c.latest_inbound_body,
            ).join(
                latest_message_subquery,
                and_(
                    latest_message_subquery.c.lead_id == counts_subquery.c.lead_id,
                    latest_message_subquery.c.row_number == 1,
                ),
            )
        )
        return tuple(
            LeadReadConversationSummary(
                lead_id=row.lead_id,
                inbound_message_count=int(row.inbound_message_count),
                latest_inbound_at=row.latest_inbound_at,
                latest_inbound_preview=_preview_inbound_text(row.latest_inbound_body),
            )
            for row in result.all()
            if row.latest_inbound_at is not None and row.latest_inbound_body is not None
        )

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

    async def get_latest_for_conversation(
        self,
        workspace_id: WorkspaceId,
        conversation_id: UUID,
    ) -> ConversationSummary | None:
        result = await self._session.execute(
            select(ConversationSummaryModel)
            .where(ConversationSummaryModel.workspace_id == workspace_id)
            .where(ConversationSummaryModel.conversation_id == conversation_id)
            .order_by(
                ConversationSummaryModel.created_at.desc(),
                ConversationSummaryModel.summary_id.desc(),
            )
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return _model_to_conversation_summary(model) if model is not None else None

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


class PostgresInboundMessageCRMCompletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_inbound_message_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> InboundMessageCRMCompletionRecord | None:
        result = await self._session.execute(
            select(InboundMessageCRMCompletionModel)
            .where(InboundMessageCRMCompletionModel.workspace_id == workspace_id)
            .where(InboundMessageCRMCompletionModel.inbound_message_id == inbound_message_id),
        )
        model = result.scalar_one_or_none()
        return _model_to_inbound_message_crm_completion(model) if model is not None else None

    async def save(
        self,
        record: InboundMessageCRMCompletionRecord,
    ) -> InboundMessageCRMCompletionRecord:
        values = _inbound_message_crm_completion_to_values(record)
        update_values = {
            key: value for key, value in values.items() if key != "inbound_message_id"
        }
        statement = (
            insert(InboundMessageCRMCompletionModel)
            .values(**values)
            .on_conflict_do_update(index_elements=["inbound_message_id"], set_=update_values)
            .returning(InboundMessageCRMCompletionModel)
        )
        result = await self._session.execute(statement)
        return _model_to_inbound_message_crm_completion(result.scalar_one())


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


def _preview_inbound_text(body: str, max_length: int = 120) -> str:
    normalized = " ".join(body.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


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
        "crm_snapshot_updated_at": record.crm_snapshot_updated_at,
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
        crm_snapshot_updated_at=model.crm_snapshot_updated_at,
        completed_at=model.completed_at,
        last_attempted_at=model.last_attempted_at,
        failure_reason=model.failure_reason,
    )


def _inbound_message_crm_completion_to_values(
    record: InboundMessageCRMCompletionRecord,
) -> dict[str, object]:
    return {
        "inbound_message_id": record.inbound_message_id,
        "workspace_id": record.workspace_id,
        "crm_note_idempotency_key": record.crm_note_idempotency_key,
        "crm_refreshed_at": record.crm_refreshed_at,
        "crm_lead_updated_at": record.crm_lead_updated_at,
        "crm_latest_activity_at": record.crm_latest_activity_at,
        "crm_updates_detected": record.crm_updates_detected,
        "crm_note_written_at": record.crm_note_written_at,
        "crm_review_tag_applied_at": record.crm_review_tag_applied_at,
        "crm_snapshot_updated_at": record.crm_snapshot_updated_at,
        "completed_at": record.completed_at,
        "last_attempted_at": record.last_attempted_at,
        "failure_reason": record.failure_reason,
    }


def _model_to_inbound_message_crm_completion(
    model: InboundMessageCRMCompletionModel,
) -> InboundMessageCRMCompletionRecord:
    return InboundMessageCRMCompletionRecord(
        inbound_message_id=model.inbound_message_id,
        workspace_id=model.workspace_id,
        crm_note_idempotency_key=model.crm_note_idempotency_key,
        crm_refreshed_at=model.crm_refreshed_at,
        crm_lead_updated_at=model.crm_lead_updated_at,
        crm_latest_activity_at=model.crm_latest_activity_at,
        crm_updates_detected=model.crm_updates_detected,
        crm_note_written_at=model.crm_note_written_at,
        crm_review_tag_applied_at=model.crm_review_tag_applied_at,
        crm_snapshot_updated_at=model.crm_snapshot_updated_at,
        completed_at=model.completed_at,
        last_attempted_at=model.last_attempted_at,
        failure_reason=model.failure_reason,
    )


class PostgresCrmConversationEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[CrmConversationEvent, ...]:
        result = await self._session.execute(
            select(CrmConversationEventModel)
            .where(CrmConversationEventModel.workspace_id == workspace_id)
            .where(CrmConversationEventModel.lead_id == lead_id)
            .order_by(CrmConversationEventModel.occurred_at.desc())
            .limit(limit),
        )
        return tuple(_model_to_crm_conversation_event(model) for model in result.scalars().all())

    async def save(self, event: CrmConversationEvent) -> CrmConversationEvent:
        values = _crm_conversation_event_to_values(event)
        update_values = {
            key: value
            for key, value in values.items()
            if key
            not in (
                "crm_conversation_event_id",
                "workspace_id",
                "crm_provider",
                "crm_activity_id",
            )
        }
        statement = (
            insert(CrmConversationEventModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["workspace_id", "crm_provider", "crm_activity_id"],
                set_=update_values,
            )
            .returning(CrmConversationEventModel)
        )
        result = await self._session.execute(statement)
        return _model_to_crm_conversation_event(result.scalar_one())


def _crm_conversation_event_to_values(event: CrmConversationEvent) -> dict[str, object]:
    return {
        "crm_conversation_event_id": event.crm_conversation_event_id,
        "workspace_id": event.workspace_id,
        "lead_id": event.lead_id,
        "conversation_id": event.conversation_id,
        "crm_provider": event.crm_provider,
        "crm_activity_id": event.crm_activity_id,
        "activity_type": event.activity_type,
        "direction": event.direction.value if event.direction is not None else None,
        "occurred_at": event.occurred_at,
        "content": event.content,
        "actor_agent_id": event.actor_agent_id,
        "actor_name": event.actor_name,
        "details": dict(event.details),
        "transcript_segments": [
            _transcript_segment_to_record(segment) for segment in event.transcript_segments
        ],
        "source_payload_version": event.source_payload_version,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _model_to_crm_conversation_event(model: CrmConversationEventModel) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=model.crm_conversation_event_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        conversation_id=model.conversation_id,
        crm_provider=model.crm_provider,
        crm_activity_id=model.crm_activity_id,
        activity_type=model.activity_type,
        direction=(
            CrmConversationEventDirection(model.direction)
            if model.direction is not None
            else None
        ),
        occurred_at=model.occurred_at,
        content=model.content,
        actor_agent_id=model.actor_agent_id,
        actor_name=model.actor_name,
        details=model.details or {},
        transcript_segments=tuple(
            _record_to_transcript_segment(record) for record in (model.transcript_segments or [])
        ),
        source_payload_version=model.source_payload_version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _transcript_segment_to_record(
    segment: CrmConversationTranscriptSegment,
) -> dict[str, object]:
    return {
        "text": segment.text,
        "speaker_name": segment.speaker_name,
        "speaker_role": segment.speaker_role,
        "started_at": segment.started_at.isoformat() if segment.started_at is not None else None,
    }


def _record_to_transcript_segment(record: dict[str, object]) -> CrmConversationTranscriptSegment:
    started_at = record.get("started_at")
    speaker_name = record.get("speaker_name")
    speaker_role = record.get("speaker_role")
    return CrmConversationTranscriptSegment(
        text=str(record.get("text") or ""),
        speaker_name=str(speaker_name) if speaker_name is not None else None,
        speaker_role=str(speaker_role) if speaker_role is not None else None,
        started_at=(
            datetime.fromisoformat(str(started_at))
            if isinstance(started_at, str) and started_at
            else None
        ),
    )
