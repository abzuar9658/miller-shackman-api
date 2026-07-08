from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    ConversationRepository,
    ConversationSummaryRepository,
    ExternalEventRepository,
    HandoffRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
)
from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    ReplyClassificationReasonCode,
    ReplyClassificationStatus,
    classify_inbound_reply,
)
from app.application.use_cases.apply_inbound_workflow_transition import (
    InboundWorkflowTransitionOutcome,
    InboundWorkflowTransitionStatus,
    apply_inbound_workflow_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Handoff,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CRMProvider


class ProcessInboundMessageEventStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessInboundMessageEventReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    LEAD_NOT_FOUND = "lead_not_found"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    CLASSIFICATION_REJECTED = "classification_rejected"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class InboundMessageEvent:
    workspace_id: WorkspaceId
    provider: str
    provider_event_id: str
    provider_message_id: str
    crm_lead_id: str
    channel: ContactChannel
    body: str
    received_at: datetime
    event_type: str = "inbound_message.received"
    from_address_redacted: str | None = None
    to_address_redacted: str | None = None
    payload_redacted: Mapping[str, object] = field(default_factory=_empty_payload)


@dataclass(frozen=True)
class ProcessInboundMessageEventResult:
    status: ProcessInboundMessageEventStatus
    external_event_id: UUID | None = None
    lead_id: LeadId | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    workflow_id: UUID | None = None
    workflow_transition_id: UUID | None = None
    handoff_id: UUID | None = None
    intent: InboundReplyIntent | None = None
    handoff_required: bool = False
    opt_out_detected: bool = False
    reasons: tuple[ProcessInboundMessageEventReasonCode, ...] = ()
    classification_reasons: tuple[ReplyClassificationReasonCode, ...] = ()


async def process_inbound_message_event(
    *,
    event: InboundMessageEvent,
    lead_repository: LeadRepository,
    external_event_repository: ExternalEventRepository,
    conversation_repository: ConversationRepository,
    inbound_message_repository: InboundMessageRepository,
    conversation_summary_repository: ConversationSummaryRepository,
    handoff_repository: HandoffRepository,
    llm_client: LLMClient,
    now: datetime,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    external_event_id_factory: Callable[[], UUID] | None = None,
    conversation_id_factory: Callable[[], UUID] | None = None,
    inbound_message_id_factory: Callable[[], UUID] | None = None,
    summary_id_factory: Callable[[], UUID] | None = None,
    handoff_id_factory: Callable[[], UUID] | None = None,
    workflow_transition_id_factory: Callable[[], UUID] | None = None,
) -> ProcessInboundMessageEventResult:
    existing = await external_event_repository.get_by_provider_event_id(
        event.workspace_id,
        event.provider,
        event.provider_event_id,
    )
    if existing is not None:
        return ProcessInboundMessageEventResult(
            status=ProcessInboundMessageEventStatus.DUPLICATE,
            external_event_id=existing.external_event_id,
            lead_id=existing.lead_id,
            reasons=(ProcessInboundMessageEventReasonCode.DUPLICATE_EVENT,),
        )

    provider = _crm_provider(event.provider)
    external_event = ExternalEvent(
        external_event_id=(external_event_id_factory or uuid4)(),
        workspace_id=event.workspace_id,
        provider=event.provider,
        event_type=event.event_type,
        provider_event_id=event.provider_event_id,
        crm_lead_id=event.crm_lead_id,
        lead_id=None,
        received_at=event.received_at,
        processed_at=None,
        status=ExternalEventStatus.PENDING,
        payload_redacted=dict(event.payload_redacted),
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )

    if provider is None:
        saved_event = await external_event_repository.save(
            replace(
                external_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessInboundMessageEventReasonCode.UNSUPPORTED_PROVIDER.value,
                updated_at=now,
            ),
        )
        return ProcessInboundMessageEventResult(
            status=ProcessInboundMessageEventStatus.IGNORED,
            external_event_id=saved_event.external_event_id,
            reasons=(ProcessInboundMessageEventReasonCode.UNSUPPORTED_PROVIDER,),
        )

    lead = await lead_repository.get_by_crm_id(event.workspace_id, provider, event.crm_lead_id)
    if lead is None:
        saved_event = await external_event_repository.save(
            replace(
                external_event,
                status=ExternalEventStatus.IGNORED,
                processed_at=now,
                failure_reason=ProcessInboundMessageEventReasonCode.LEAD_NOT_FOUND.value,
                updated_at=now,
            ),
        )
        return ProcessInboundMessageEventResult(
            status=ProcessInboundMessageEventStatus.IGNORED,
            external_event_id=saved_event.external_event_id,
            reasons=(ProcessInboundMessageEventReasonCode.LEAD_NOT_FOUND,),
        )

    saved_event = await external_event_repository.save(
        replace(external_event, lead_id=lead.lead_id),
    )
    conversation = await conversation_repository.get_latest_for_lead(
        event.workspace_id,
        lead.lead_id,
    )
    if conversation is None:
        conversation = Conversation(
            conversation_id=(conversation_id_factory or uuid4)(),
            workspace_id=event.workspace_id,
            lead_id=lead.lead_id,
            status=ConversationStatus.ACTIVE_AI,
            ai_interaction_count=0,
            last_message_at=event.received_at,
            created_at=now,
            updated_at=now,
        )

    conversation = await conversation_repository.save(
        replace(conversation, last_message_at=event.received_at, updated_at=now),
    )
    inbound_message = await inbound_message_repository.save(
        InboundMessage(
            inbound_message_id=(inbound_message_id_factory or uuid4)(),
            workspace_id=event.workspace_id,
            conversation_id=conversation.conversation_id,
            lead_id=lead.lead_id,
            channel=event.channel,
            provider=event.provider,
            provider_message_id=event.provider_message_id,
            external_event_id=saved_event.external_event_id,
            from_address_redacted=event.from_address_redacted,
            to_address_redacted=event.to_address_redacted,
            body=event.body,
            received_at=event.received_at,
            processed_at=None,
            classification_status=InboundMessageClassificationStatus.PENDING,
            created_at=now,
        ),
    )

    classification = await classify_inbound_reply(
        lead=lead,
        inbound_text=event.body,
        llm_client=llm_client,
    )
    if classification.status == ReplyClassificationStatus.REJECTED:
        await conversation_repository.save(
            replace(conversation, status=ConversationStatus.PAUSED, updated_at=now),
        )
        await inbound_message_repository.save(
            replace(
                inbound_message,
                classification_status=InboundMessageClassificationStatus.FAILED,
                processed_at=now,
            ),
        )
        await external_event_repository.save(
            replace(
                saved_event,
                status=ExternalEventStatus.PROCESSED,
                processed_at=now,
                updated_at=now,
            ),
        )
        workflow_transition = await _apply_workflow_transition_if_configured(
            workspace_id=event.workspace_id,
            lead_id=lead.lead_id,
            handoff_required=False,
            opt_out_detected=False,
            classification_rejected=True,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            external_event_id=saved_event.external_event_id,
            conversation_id=conversation.conversation_id,
            inbound_message_id=inbound_message.inbound_message_id,
            intent=None,
            classification_reasons=tuple(reason.value for reason in classification.reasons),
            transition_id_factory=workflow_transition_id_factory,
        )
        return ProcessInboundMessageEventResult(
            status=ProcessInboundMessageEventStatus.PROCESSED,
            external_event_id=saved_event.external_event_id,
            lead_id=lead.lead_id,
            conversation_id=conversation.conversation_id,
            inbound_message_id=inbound_message.inbound_message_id,
            workflow_id=workflow_transition.workflow.workflow_id
            if workflow_transition.workflow is not None
            else None,
            workflow_transition_id=workflow_transition.transition_id,
            reasons=(ProcessInboundMessageEventReasonCode.CLASSIFICATION_REJECTED,),
            classification_reasons=classification.reasons,
        )

    conversation_status = ConversationStatus.PAUSED
    if classification.handoff_required:
        conversation_status = ConversationStatus.HUMAN_HANDOFF
    conversation = await conversation_repository.save(
        replace(conversation, status=conversation_status, updated_at=now),
    )
    inbound_message = await inbound_message_repository.save(
        replace(
            inbound_message,
            classification_status=InboundMessageClassificationStatus.CLASSIFIED,
            processed_at=now,
        ),
    )
    await conversation_summary_repository.save(
        ConversationSummary(
            summary_id=(summary_id_factory or uuid4)(),
            workspace_id=event.workspace_id,
            conversation_id=conversation.conversation_id,
            lead_id=lead.lead_id,
            summary_text=classification.summary_text or event.body,
            preferences=classification.preferences,
            prompt_version=classification.prompt_version,
            model=classification.model or "unknown",
            confidence=classification.confidence,
            created_at=now,
        ),
    )

    handoff: Handoff | None = None
    pending_handoff_id = (
        (handoff_id_factory or uuid4)() if classification.handoff_required else None
    )
    workflow_transition = await _apply_workflow_transition_if_configured(
        workspace_id=event.workspace_id,
        lead_id=lead.lead_id,
        handoff_required=classification.handoff_required,
        opt_out_detected=classification.opt_out_detected,
        classification_rejected=False,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        external_event_id=saved_event.external_event_id,
        conversation_id=conversation.conversation_id,
        inbound_message_id=inbound_message.inbound_message_id,
        handoff_id=pending_handoff_id,
        intent=classification.intent,
        transition_id_factory=workflow_transition_id_factory,
    )
    if workflow_transition.workflow is not None:
        conversation = await conversation_repository.save(
            replace(
                conversation,
                campaign_id=workflow_transition.workflow.campaign_id,
                workflow_id=workflow_transition.workflow.workflow_id,
                updated_at=now,
            ),
        )
    if classification.handoff_required and classification.handoff_reason is not None:
        handoff = await handoff_repository.save(
            Handoff(
                handoff_id=pending_handoff_id or (handoff_id_factory or uuid4)(),
                workspace_id=event.workspace_id,
                lead_id=lead.lead_id,
                campaign_id=workflow_transition.workflow.campaign_id
                if workflow_transition.workflow is not None
                else None,
                workflow_id=workflow_transition.workflow.workflow_id
                if workflow_transition.workflow is not None
                else None,
                conversation_id=conversation.conversation_id,
                inbound_message_id=inbound_message.inbound_message_id,
                assigned_agent_crm_id=lead.assigned_agent_crm_id,
                reason_code=classification.handoff_reason,
                summary=classification.summary_text or event.body,
                latest_inbound_text=event.body,
                preferences=classification.preferences,
                created_at=now,
            ),
        )

    await external_event_repository.save(
        replace(
            saved_event,
            status=ExternalEventStatus.PROCESSED,
            processed_at=now,
            updated_at=now,
        ),
    )
    return ProcessInboundMessageEventResult(
        status=ProcessInboundMessageEventStatus.PROCESSED,
        external_event_id=saved_event.external_event_id,
        lead_id=lead.lead_id,
        conversation_id=conversation.conversation_id,
        inbound_message_id=inbound_message.inbound_message_id,
        workflow_id=workflow_transition.workflow.workflow_id
        if workflow_transition.workflow is not None
        else None,
        workflow_transition_id=workflow_transition.transition_id,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        intent=classification.intent,
        handoff_required=classification.handoff_required,
        opt_out_detected=classification.opt_out_detected,
    )


def _crm_provider(raw_provider: str) -> CRMProvider | None:
    try:
        return CRMProvider(raw_provider)
    except ValueError:
        return None


async def _apply_workflow_transition_if_configured(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    handoff_required: bool,
    opt_out_detected: bool,
    classification_rejected: bool,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    now: datetime,
    external_event_id: UUID | None,
    conversation_id: UUID | None,
    inbound_message_id: UUID | None,
    handoff_id: UUID | None = None,
    intent: InboundReplyIntent | None = None,
    classification_reasons: tuple[str, ...] = (),
    transition_id_factory: Callable[[], UUID] | None = None,
) -> InboundWorkflowTransitionOutcome:
    if lead_workflow_repository is None or workflow_transition_repository is None:
        return InboundWorkflowTransitionOutcome(status=InboundWorkflowTransitionStatus.NO_WORKFLOW)
    return await apply_inbound_workflow_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        handoff_required=handoff_required,
        opt_out_detected=opt_out_detected,
        classification_rejected=classification_rejected,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        external_event_id=external_event_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        handoff_id=handoff_id,
        intent=intent,
        classification_reasons=classification_reasons,
        transition_id_factory=transition_id_factory,
    )
