from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    ConversationRepository,
    ConversationSummaryRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    InboundMessageCRMCompletionRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    ReplyClassificationReasonCode,
    ReplyClassificationResult,
    ReplyClassificationStatus,
    classify_inbound_reply,
)
from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_openrouter_model,
)
from app.application.use_cases.apply_inbound_workflow_transition import (
    InboundWorkflowTransitionOutcome,
    InboundWorkflowTransitionStatus,
    apply_inbound_workflow_transition,
)
from app.application.use_cases.complete_handoff import HandoffCompletionStatus, complete_handoff
from app.application.use_cases.complete_inbound_message_crm_sync import (
    CompleteInboundMessageCRMSyncResult,
    CompleteInboundMessageCRMSyncStatus,
    complete_inbound_message_crm_sync,
)
from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel, ContactSuppressionKind
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Handoff,
    InboundMessage,
    InboundMessageClassificationStatus,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord, CRMProvider


class ProcessInboundMessageEventStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessInboundMessageEventReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    LEAD_NOT_FOUND = "lead_not_found"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    CLASSIFICATION_REJECTED = "classification_rejected"


_SMS_OPT_OUT_KEYWORDS = frozenset({"stop", "stopall", "unsubscribe", "cancel", "end", "quit"})
_EMAIL_OPT_OUT_KEYWORDS = frozenset({"unsubscribe"})


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
    crm_provider: CRMProvider | None = None
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
    handoff_completion_status: HandoffCompletionStatus | None = None
    handoff_completion_failure_reason: str | None = None
    crm_sync_status: CompleteInboundMessageCRMSyncStatus | None = None
    crm_sync_failure_reason: str | None = None
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
    crm_client: CRMClient | None = None,
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository | None = None,
    notification_provider: NotificationProvider | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    event_bus: EventBus | None = None,
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

    crm_provider = event.crm_provider or _crm_provider(event.provider)
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

    if crm_provider is None:
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

    lead = await lead_repository.get_by_crm_id(event.workspace_id, crm_provider, event.crm_lead_id)
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

    openrouter_model = await resolve_workspace_openrouter_model(
        workspace_id=event.workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )

    classification = await classify_inbound_reply(
        lead=lead,
        inbound_text=event.body,
        llm_client=llm_client,
        model=openrouter_model,
    )
    classification = _apply_explicit_opt_out_override(
        event=event,
        classification=classification,
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
        await _publish_inbound_events(
            event_bus=event_bus,
            event=event,
            inbound_message=inbound_message,
            workflow_transition=workflow_transition,
            handoff=None,
            opt_out_detected=False,
            now=now,
        )
        crm_sync_result = await _sync_inbound_message_to_crm_if_configured(
            event=event,
            crm_provider=crm_provider,
            lead=lead,
            inbound_message=inbound_message,
            summary_text=None,
            intent=None,
            handoff_required=False,
            opt_out_detected=False,
            classification_rejected=True,
            crm_client=crm_client,
            inbound_message_crm_completion_repository=inbound_message_crm_completion_repository,
            now=now,
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
            crm_sync_status=crm_sync_result.status if crm_sync_result is not None else None,
            crm_sync_failure_reason=(
                crm_sync_result.failure_reason if crm_sync_result is not None else None
            ),
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
    if classification.opt_out_detected:
        lead = await apply_contact_suppression_to_lead(
            lead=lead,
            suppression_kind=_contact_suppression_kind(event.channel),
            source_provider=event.provider,
            source_event_id=event.provider_event_id,
            occurred_at=event.received_at,
            lead_repository=lead_repository,
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
        handoff_completion_result = None
        if (
            crm_client is not None
            and notification_provider is not None
            and workspace_handoff_config_repository is not None
            and handoff_completion_repository is not None
        ):
            handoff_completion_result = await complete_handoff(
                workspace_id=event.workspace_id,
                handoff_id=handoff.handoff_id,
                handoff_repository=handoff_repository,
                handoff_completion_repository=handoff_completion_repository,
                workspace_handoff_config_repository=workspace_handoff_config_repository,
                lead_repository=lead_repository,
                crm_client=crm_client,
                notification_provider=notification_provider,
                now=now,
            )
    else:
        handoff_completion_result = None

    crm_sync_result = await _sync_inbound_message_to_crm_if_configured(
        event=event,
        crm_provider=crm_provider,
        lead=lead,
        inbound_message=inbound_message,
        summary_text=classification.summary_text or event.body,
        intent=classification.intent,
        handoff_required=classification.handoff_required,
        opt_out_detected=classification.opt_out_detected,
        classification_rejected=False,
        crm_client=crm_client,
        inbound_message_crm_completion_repository=inbound_message_crm_completion_repository,
        now=now,
    )

    await external_event_repository.save(
        replace(
            saved_event,
            status=ExternalEventStatus.PROCESSED,
            processed_at=now,
            updated_at=now,
        ),
    )
    await _publish_inbound_events(
        event_bus=event_bus,
        event=event,
        inbound_message=inbound_message,
        workflow_transition=workflow_transition,
        handoff=handoff,
        opt_out_detected=classification.opt_out_detected,
        now=now,
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
        handoff_completion_status=handoff_completion_result.status
        if handoff_completion_result is not None
        else None,
        handoff_completion_failure_reason=handoff_completion_result.failure_reason
        if handoff_completion_result is not None
        else None,
        crm_sync_status=crm_sync_result.status if crm_sync_result is not None else None,
        crm_sync_failure_reason=(
            crm_sync_result.failure_reason if crm_sync_result is not None else None
        ),
        opt_out_detected=classification.opt_out_detected,
    )


def _crm_provider(raw_provider: str) -> CRMProvider | None:
    try:
        return CRMProvider(raw_provider)
    except ValueError:
        return None


def _contact_suppression_kind(channel: ContactChannel) -> ContactSuppressionKind:
    if channel == ContactChannel.SMS:
        return ContactSuppressionKind.SMS_OPT_OUT
    return ContactSuppressionKind.EMAIL_UNSUBSCRIBED


def _apply_explicit_opt_out_override(
    *,
    event: InboundMessageEvent,
    classification: ReplyClassificationResult,
) -> ReplyClassificationResult:
    if not _is_explicit_opt_out(event.channel, event.body):
        return classification
    if classification.status == ReplyClassificationStatus.REJECTED:
        return ReplyClassificationResult(
            status=ReplyClassificationStatus.CLASSIFIED,
            prompt_version=classification.prompt_version,
            model=classification.model,
            latency_ms=classification.latency_ms,
            usage_tokens=classification.usage_tokens,
            intent=InboundReplyIntent.OPT_OUT,
            confidence=classification.confidence,
            handoff_required=False,
            handoff_reason=None,
            opt_out_detected=True,
            summary_text=event.body.strip() or event.body,
            preferences={},
        )
    if classification.opt_out_detected:
        return classification
    return replace(
        classification,
        intent=InboundReplyIntent.OPT_OUT,
        opt_out_detected=True,
    )


def _is_explicit_opt_out(channel: ContactChannel, body: str) -> bool:
    normalized = "".join(character.lower() for character in body if character.isalnum())
    if channel == ContactChannel.SMS:
        return normalized in _SMS_OPT_OUT_KEYWORDS
    if channel == ContactChannel.EMAIL:
        return normalized in _EMAIL_OPT_OUT_KEYWORDS
    return False


def _is_explicit_sms_opt_out(body: str) -> bool:
    return _is_explicit_opt_out(ContactChannel.SMS, body)


async def _sync_inbound_message_to_crm_if_configured(
    *,
    event: InboundMessageEvent,
    crm_provider: CRMProvider,
    lead: CanonicalLeadRecord,
    inbound_message: InboundMessage,
    summary_text: str | None,
    intent: InboundReplyIntent | None,
    handoff_required: bool,
    opt_out_detected: bool,
    classification_rejected: bool,
    crm_client: CRMClient | None,
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository | None,
    now: datetime,
) -> CompleteInboundMessageCRMSyncResult | None:
    if (
        crm_client is None
        or inbound_message_crm_completion_repository is None
        or event.provider == crm_provider.value
    ):
        return None
    return await complete_inbound_message_crm_sync(
        lead=lead,
        inbound_message=inbound_message,
        summary_text=summary_text,
        intent=intent,
        handoff_required=handoff_required,
        opt_out_detected=opt_out_detected,
        classification_rejected=classification_rejected,
        crm_client=crm_client,
        crm_sync_completion_repository=inbound_message_crm_completion_repository,
        now=now,
    )


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


async def _publish_inbound_events(
    *,
    event_bus: EventBus | None,
    event: InboundMessageEvent,
    inbound_message: InboundMessage,
    workflow_transition: InboundWorkflowTransitionOutcome,
    handoff: Handoff | None,
    opt_out_detected: bool,
    now: datetime,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=event.workspace_id,
            aggregate_type=AggregateType.MESSAGE,
            aggregate_id=inbound_message.inbound_message_id,
            event_type=DomainEventType.MESSAGE_RECEIVED,
            payload={
                "inbound_message_id": str(inbound_message.inbound_message_id),
                "conversation_id": str(inbound_message.conversation_id),
                "lead_id": str(inbound_message.lead_id),
                "channel": inbound_message.channel.value,
                "provider": inbound_message.provider,
                "provider_message_id": inbound_message.provider_message_id,
                "received_at": inbound_message.received_at.isoformat(),
                "processed_at": now.isoformat(),
            },
        ),
    )
    if opt_out_detected:
        await event_bus.publish(
            DomainEvent(
                workspace_id=event.workspace_id,
                aggregate_type=AggregateType.LEAD,
                aggregate_id=inbound_message.lead_id,
                event_type=DomainEventType.LEAD_OPTED_OUT,
                payload={
                    "lead_id": str(inbound_message.lead_id),
                    "channel": inbound_message.channel.value,
                    "provider": event.provider,
                    "provider_event_id": event.provider_event_id,
                    "occurred_at": event.received_at.isoformat(),
                },
            ),
        )
    if handoff is not None:
        await event_bus.publish(
            DomainEvent(
                workspace_id=handoff.workspace_id,
                aggregate_type=AggregateType.HANDOFF,
                aggregate_id=handoff.handoff_id,
                event_type=DomainEventType.HANDOFF_CREATED,
                payload={
                    "handoff_id": str(handoff.handoff_id),
                    "lead_id": str(handoff.lead_id),
                    "conversation_id": str(handoff.conversation_id),
                    "inbound_message_id": str(handoff.inbound_message_id),
                    "reason_code": handoff.reason_code.value,
                    "created_at": handoff.created_at.isoformat(),
                },
            ),
        )
    if workflow_transition.status == InboundWorkflowTransitionStatus.UPDATED:
        assert workflow_transition.workflow is not None
        assert workflow_transition.transition_id is not None
        await event_bus.publish(
            DomainEvent(
                workspace_id=event.workspace_id,
                aggregate_type=AggregateType.WORKFLOW,
                aggregate_id=workflow_transition.workflow.workflow_id,
                event_type=DomainEventType.WORKFLOW_TRANSITIONED,
                payload={
                    "workflow_id": str(workflow_transition.workflow.workflow_id),
                    "transition_id": str(workflow_transition.transition_id),
                    "lead_id": str(workflow_transition.workflow.lead_id),
                    "campaign_id": str(workflow_transition.workflow.campaign_id),
                    "to_state": workflow_transition.workflow.state.value,
                    "occurred_at": now.isoformat(),
                },
            ),
        )
