from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.notifications import NotificationProvider, ReviewNotification
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    ConversationRepository,
    ConversationSummaryRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    InboundMessageCRMCompletionRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.crm_snapshot import has_crm_snapshot_fields
from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    InboundReplyRuleEvidence,
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
from app.application.use_cases.complete_handoff import (
    HandoffCompletionResult,
    HandoffCompletionStatus,
    complete_handoff,
)
from app.application.use_cases.complete_inbound_message_crm_sync import (
    CompleteInboundMessageCRMSyncResult,
    CompleteInboundMessageCRMSyncStatus,
    complete_inbound_message_crm_sync,
)
from app.application.use_cases.continue_ai_conversation_after_inbound import (
    ContinueAIResult,
    ContinueAIStatus,
    continue_ai_conversation_after_inbound,
)
from app.application.use_cases.evaluate_inbound_action import (
    InboundAction,
    InboundActionDecision,
    InboundActionReasonCode,
    evaluate_inbound_action,
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
    WorkspaceHandoffConfig,
    default_workspace_handoff_config,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, TemporalSignalName, TemporalSignalOutboxEntry


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
class ReviewNotificationResult:
    sent: bool = False
    recipient: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class ProcessInboundMessageEventResult:
    status: ProcessInboundMessageEventStatus
    external_event_id: UUID | None = None
    lead_id: LeadId | None = None
    conversation_id: UUID | None = None
    inbound_message_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    workflow_transition_id: UUID | None = None
    handoff_id: UUID | None = None
    intent: InboundReplyIntent | None = None
    inbound_action: InboundAction | None = None
    inbound_action_reason: InboundActionReasonCode | None = None
    handoff_required: bool = False
    handoff_completion_status: HandoffCompletionStatus | None = None
    handoff_completion_failure_reason: str | None = None
    crm_sync_status: CompleteInboundMessageCRMSyncStatus | None = None
    crm_sync_failure_reason: str | None = None
    opt_out_detected: bool = False
    signal_queued: bool = False
    review_tag_applied: bool = False
    review_notification_sent: bool = False
    review_notification_recipient: str | None = None
    review_notification_failure_reason: str | None = None
    continue_ai_status: ContinueAIStatus | None = None
    continue_ai_outbound_message_id: UUID | None = None
    continue_ai_provider_message_id: str | None = None
    continue_ai_pause_reason: str | None = None
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
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    notification_provider: NotificationProvider | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    event_bus: EventBus | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    workspace_repository: WorkspaceRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    workspace_outbound_drafting_config_repository: (
        WorkspaceOutboundDraftingConfigRepository | None
    ) = None,
    message_repository: OutboundMessageRepository | None = None,
    sms_provider: SMSProvider | None = None,
    email_provider: EmailProvider | None = None,
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

    workspace_handoff_config = await _load_workspace_handoff_config(
        workspace_id=event.workspace_id,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
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
    inbound_decision = evaluate_inbound_action(classification)
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
        saved_event = await external_event_repository.save(
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
            action=inbound_decision.action,
            decision_reason=inbound_decision.reason_code,
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
            inbound_action=inbound_decision.action,
            review_tag=await _review_tag_for_decision(
                workspace_id=event.workspace_id,
                inbound_action=inbound_decision.action,
                workspace_handoff_config_repository=workspace_handoff_config_repository,
            ),
            classification_rejected=True,
            workspace_handoff_config=workspace_handoff_config,
            snapshot_status="paused_for_review",
            crm_client=crm_client,
            inbound_message_crm_completion_repository=inbound_message_crm_completion_repository,
            now=now,
        )
        signal_queued = await _enqueue_inbound_processed_signal_if_configured(
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            event=event,
            external_event_id=saved_event.external_event_id,
            conversation_id=conversation.conversation_id,
            inbound_message_id=inbound_message.inbound_message_id,
            workflow_transition=workflow_transition,
            inbound_action=inbound_decision.action,
            inbound_action_reason=inbound_decision.reason_code,
            now=now,
        )
        rejected_review_tag = await _review_tag_for_decision(
            workspace_id=event.workspace_id,
            inbound_action=inbound_decision.action,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
        )
        rejected_review_tag_applied = _review_tag_applied(
            crm_sync_result=crm_sync_result,
            inbound_action=inbound_decision.action,
            review_tag=rejected_review_tag,
        )
        rejected_review_notification = await _send_review_notification_if_configured(
            event=event,
            lead=lead,
            inbound_message=inbound_message,
            inbound_action=inbound_decision.action,
            inbound_action_reason=inbound_decision.reason_code,
            summary_text=None,
            notification_provider=notification_provider,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
            crm_client=crm_client,
            now=now,
        )
        audit_summary = _build_inbound_processing_audit(
            classification=classification,
            inbound_decision=inbound_decision,
            handoff_required=False,
            continue_ai_result=None,
            workflow_transition=workflow_transition,
            crm_sync_result=crm_sync_result,
            review_tag=rejected_review_tag,
            review_tag_applied=rejected_review_tag_applied,
            review_notification=rejected_review_notification,
            handoff_completion_result=None,
            handoff=None,
            signal_queued=signal_queued,
        )
        await external_event_repository.save(
            replace(
                saved_event,
                payload_redacted={
                    **saved_event.payload_redacted,
                    "processing_audit": audit_summary,
                },
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
            temporal_workflow_id=workflow_transition.workflow.temporal_workflow_id
            if workflow_transition.workflow is not None
            else None,
            workflow_transition_id=workflow_transition.transition_id,
            inbound_action=inbound_decision.action,
            inbound_action_reason=inbound_decision.reason_code,
            reasons=(ProcessInboundMessageEventReasonCode.CLASSIFICATION_REJECTED,),
            classification_reasons=classification.reasons,
            crm_sync_status=crm_sync_result.status if crm_sync_result is not None else None,
            crm_sync_failure_reason=(
                crm_sync_result.failure_reason if crm_sync_result is not None else None
            ),
            signal_queued=signal_queued,
            review_tag_applied=rejected_review_tag_applied,
            review_notification_sent=rejected_review_notification.sent,
            review_notification_recipient=rejected_review_notification.recipient,
            review_notification_failure_reason=rejected_review_notification.failure_reason,
        )

    handoff_required = inbound_decision.action == InboundAction.HUMAN_HANDOFF
    is_continue_ai = inbound_decision.action == InboundAction.CONTINUE_AI
    review_tag = await _review_tag_for_decision(
        workspace_id=event.workspace_id,
        inbound_action=inbound_decision.action,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
    )

    continue_ai_workflow = await _try_resolve_continue_ai_workflow(
        workspace_id=event.workspace_id,
        lead_id=lead.lead_id,
        is_continue_ai=is_continue_ai,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        lead_repository=lead_repository,
        campaign_execution_repository=campaign_execution_repository,
        workspace_repository=workspace_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        llm_client=llm_client,
    )

    conversation_status = ConversationStatus.PAUSED
    if handoff_required:
        conversation_status = ConversationStatus.HUMAN_HANDOFF
    elif continue_ai_workflow is not None:
        conversation_status = ConversationStatus.ACTIVE_AI
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
    saved_summary = await conversation_summary_repository.save(
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
    pending_handoff_id = ((handoff_id_factory or uuid4)() if handoff_required else None)
    continue_ai_result: ContinueAIResult | None = None
    if continue_ai_workflow is not None:
        assert lead_repository is not None
        assert campaign_execution_repository is not None
        assert workspace_repository is not None
        assert workspace_contact_policy_repository is not None
        assert lead_workflow_repository is not None
        assert workflow_transition_repository is not None
        assert message_repository is not None
        assert sms_provider is not None
        assert email_provider is not None
        assert llm_client is not None
        continue_ai_result = await continue_ai_conversation_after_inbound(
            workspace_id=event.workspace_id,
            lead_id=lead.lead_id,
            campaign_id=continue_ai_workflow.campaign_id,
            inbound_channel=event.channel,
            inbound_body=event.body,
            conversation=conversation,
            latest_summary=saved_summary,
            conversation_repository=conversation_repository,
            lead_repository=lead_repository,
            campaign_execution_repository=campaign_execution_repository,
            workspace_repository=workspace_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            workspace_llm_config_repository=workspace_llm_config_repository,
            workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
            workspace_operational_control_repository=workspace_operational_control_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            message_repository=message_repository,
            sms_provider=sms_provider,
            email_provider=email_provider,
            llm_client=llm_client,
            crm_client=crm_client,
            outbound_message_crm_completion_repository=outbound_message_crm_completion_repository,
            workspace_handoff_config=workspace_handoff_config,
            now=now,
            default_openrouter_model=default_openrouter_model,
            external_event_id=saved_event.external_event_id,
            inbound_message_id=inbound_message.inbound_message_id,
            transition_id_factory=workflow_transition_id_factory,
        )
        if continue_ai_result.conversation is not None:
            conversation = continue_ai_result.conversation
        elif continue_ai_result.ai_interaction_count_increment:
            conversation = replace(
                conversation,
                ai_interaction_count=(
                    conversation.ai_interaction_count
                    + continue_ai_result.ai_interaction_count_increment
                ),
                updated_at=now,
            )
        workflow_transition = _workflow_transition_outcome_from_continue_ai_result(
            continue_ai_result,
        )
    else:
        workflow_transition = await _apply_workflow_transition_if_configured(
            workspace_id=event.workspace_id,
            lead_id=lead.lead_id,
            handoff_required=handoff_required,
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
            action=inbound_decision.action,
            decision_reason=inbound_decision.reason_code,
            transition_id_factory=workflow_transition_id_factory,
        )
    if workflow_transition.workflow is not None:
        conversation = await conversation_repository.save(
            replace(
                conversation,
                status=_conversation_status_after_inbound(
                    handoff_required=handoff_required,
                    continue_ai_result=continue_ai_result,
                ),
                campaign_id=workflow_transition.workflow.campaign_id,
                workflow_id=workflow_transition.workflow.workflow_id,
                updated_at=now,
            ),
        )
    if handoff_required and inbound_decision.handoff_reason is not None:
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
                reason_code=inbound_decision.handoff_reason,
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
        handoff_required=handoff_required,
        opt_out_detected=classification.opt_out_detected,
        inbound_action=inbound_decision.action,
        review_tag=review_tag,
        classification_rejected=False,
        workspace_handoff_config=workspace_handoff_config,
        snapshot_status=_crm_snapshot_status_for_inbound(
            inbound_action=inbound_decision.action,
            classification_rejected=False,
            handoff_required=handoff_required,
            opt_out_detected=classification.opt_out_detected,
            continue_ai_result=continue_ai_result,
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=inbound_message_crm_completion_repository,
        now=now,
    )

    saved_event = await external_event_repository.save(
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
    signal_queued = await _enqueue_inbound_processed_signal_if_configured(
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        event=event,
        external_event_id=saved_event.external_event_id,
        conversation_id=conversation.conversation_id,
        inbound_message_id=inbound_message.inbound_message_id,
        workflow_transition=workflow_transition,
        inbound_action=inbound_decision.action,
        inbound_action_reason=inbound_decision.reason_code,
        now=now,
    )
    review_notification = await _send_review_notification_if_configured(
        event=event,
        lead=lead,
        inbound_message=inbound_message,
        inbound_action=inbound_decision.action,
        inbound_action_reason=inbound_decision.reason_code,
        summary_text=classification.summary_text,
        notification_provider=notification_provider,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        crm_client=crm_client,
        now=now,
    )
    review_tag_applied = _review_tag_applied(
        crm_sync_result=crm_sync_result,
        inbound_action=inbound_decision.action,
        review_tag=review_tag,
    )
    audit_summary = _build_inbound_processing_audit(
        classification=classification,
        inbound_decision=inbound_decision,
        handoff_required=handoff_required,
        continue_ai_result=continue_ai_result,
        workflow_transition=workflow_transition,
        crm_sync_result=crm_sync_result,
        review_tag=review_tag,
        review_tag_applied=review_tag_applied,
        review_notification=review_notification,
        handoff_completion_result=handoff_completion_result,
        handoff=handoff,
        signal_queued=signal_queued,
    )
    await external_event_repository.save(
        replace(
            saved_event,
            payload_redacted={
                **saved_event.payload_redacted,
                "processing_audit": audit_summary,
            },
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
        temporal_workflow_id=workflow_transition.workflow.temporal_workflow_id
        if workflow_transition.workflow is not None
        else None,
        workflow_transition_id=workflow_transition.transition_id,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        intent=classification.intent,
        inbound_action=inbound_decision.action,
        inbound_action_reason=inbound_decision.reason_code,
        handoff_required=handoff_required,
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
        signal_queued=signal_queued,
        review_tag_applied=review_tag_applied,
        review_notification_sent=review_notification.sent,
        review_notification_recipient=review_notification.recipient,
        review_notification_failure_reason=review_notification.failure_reason,
        continue_ai_status=continue_ai_result.status if continue_ai_result is not None else None,
        continue_ai_outbound_message_id=(
            continue_ai_result.outbound_message_id if continue_ai_result is not None else None
        ),
        continue_ai_provider_message_id=(
            continue_ai_result.provider_message_id if continue_ai_result is not None else None
        ),
        continue_ai_pause_reason=(
            continue_ai_result.pause_reason if continue_ai_result is not None else None
        ),
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
            evidence=InboundReplyRuleEvidence(),
            opt_out_detected=True,
            summary_text=event.body.strip() or event.body,
            preferences={},
        )
    if classification.opt_out_detected:
        return classification
    return replace(
        classification,
        intent=InboundReplyIntent.OPT_OUT,
        evidence=InboundReplyRuleEvidence(),
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
    inbound_action: InboundAction,
    review_tag: str | None,
    classification_rejected: bool,
    workspace_handoff_config: WorkspaceHandoffConfig | None,
    snapshot_status: str | None,
    crm_client: CRMClient | None,
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository | None,
    now: datetime,
) -> CompleteInboundMessageCRMSyncResult | None:
    should_write_inbound_note = event.provider != crm_provider.value
    snapshot_enabled = has_crm_snapshot_fields(workspace_handoff_config)
    if crm_client is None or inbound_message_crm_completion_repository is None:
        return None
    if not should_write_inbound_note and review_tag is None and not snapshot_enabled:
        return None
    return await complete_inbound_message_crm_sync(
        lead=lead,
        inbound_message=inbound_message,
        summary_text=summary_text,
        intent=intent,
        handoff_required=handoff_required,
        opt_out_detected=opt_out_detected,
        inbound_action=inbound_action,
        review_tag=review_tag,
        classification_rejected=classification_rejected,
        write_inbound_note=should_write_inbound_note,
        workspace_handoff_config=workspace_handoff_config,
        snapshot_status=snapshot_status,
        crm_client=crm_client,
        crm_sync_completion_repository=inbound_message_crm_completion_repository,
        now=now,
    )


async def _load_workspace_handoff_config(
    *,
    workspace_id: WorkspaceId,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
) -> WorkspaceHandoffConfig | None:
    if workspace_handoff_config_repository is None:
        return None
    return await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)


def _crm_snapshot_status_for_inbound(
    *,
    inbound_action: InboundAction,
    classification_rejected: bool,
    handoff_required: bool,
    opt_out_detected: bool,
    continue_ai_result: ContinueAIResult | None,
) -> str:
    if opt_out_detected or inbound_action == InboundAction.SUPPRESS:
        return "suppressed"
    if classification_rejected or inbound_action == InboundAction.PAUSE_FOR_REVIEW:
        return "paused_for_review"
    if handoff_required or inbound_action == InboundAction.HUMAN_HANDOFF:
        return "human_handoff_required"
    if continue_ai_result is not None and continue_ai_result.status in {
        ContinueAIStatus.SENT,
        ContinueAIStatus.ALREADY_SENT,
    }:
        return "waiting_for_response"
    if continue_ai_result is not None:
        return "ai_follow_up_blocked"
    return inbound_action.value


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
    action: InboundAction | None = None,
    decision_reason: InboundActionReasonCode | None = None,
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
        action=action,
        decision_reason=decision_reason,
        classification_reasons=classification_reasons,
        transition_id_factory=transition_id_factory,
    )


async def _review_tag_for_decision(
    *,
    workspace_id: WorkspaceId,
    inbound_action: InboundAction,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
) -> str | None:
    if (
        inbound_action != InboundAction.PAUSE_FOR_REVIEW
        or workspace_handoff_config_repository is None
    ):
        return None
    config = await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)
    return config.crm_review_tag if config is not None else None


def _review_tag_applied(
    *,
    crm_sync_result: CompleteInboundMessageCRMSyncResult | None,
    inbound_action: InboundAction,
    review_tag: str | None,
) -> bool:
    return (
        inbound_action == InboundAction.PAUSE_FOR_REVIEW
        and review_tag is not None
        and crm_sync_result is not None
        and crm_sync_result.status
        in {
            CompleteInboundMessageCRMSyncStatus.COMPLETED,
            CompleteInboundMessageCRMSyncStatus.ALREADY_COMPLETED,
        }
    )


async def _send_review_notification_if_configured(
    *,
    event: InboundMessageEvent,
    lead: CanonicalLeadRecord,
    inbound_message: InboundMessage,
    inbound_action: InboundAction,
    inbound_action_reason: InboundActionReasonCode,
    summary_text: str | None,
    notification_provider: NotificationProvider | None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
    crm_client: CRMClient | None,
    now: datetime,
) -> ReviewNotificationResult:
    if inbound_action != InboundAction.PAUSE_FOR_REVIEW:
        return ReviewNotificationResult()
    if notification_provider is None or workspace_handoff_config_repository is None:
        return ReviewNotificationResult(failure_reason="review_notification_not_configured")

    config = await workspace_handoff_config_repository.get_by_workspace_id(event.workspace_id)
    handoff_config = config or default_workspace_handoff_config(event.workspace_id)
    fallback_email = handoff_config.fallback_recipient_email

    assigned_agent = None
    if crm_client is not None:
        try:
            assigned_agent = await crm_client.get_assigned_agent(
                event.workspace_id, lead.crm_lead_id
            )
        except Exception:
            assigned_agent = None

    recipient_destination = (
        assigned_agent.email
        if assigned_agent is not None and assigned_agent.email
        else fallback_email
    )
    recipient_id = (
        assigned_agent.crm_agent_id
        if assigned_agent is not None
        else fallback_email
    )
    if recipient_destination is None or recipient_id is None:
        return ReviewNotificationResult(failure_reason="missing_notification_destination")

    try:
        send_result = await notification_provider.send_review_notification(
            ReviewNotification(
                workspace_id=event.workspace_id,
                inbound_message_id=inbound_message.inbound_message_id,
                lead_id=lead.lead_id,
                recipient_id=recipient_id,
                recipient_destination=recipient_destination,
                lead_display_name=_lead_display_name(lead),
                lead_primary_email=lead.primary_email,
                lead_primary_phone=lead.primary_phone,
                latest_inbound_text=event.body,
                summary=summary_text or "No summary available.",
                review_reason=inbound_action_reason.value,
                channel=event.channel.value,
                idempotency_key=_review_notification_idempotency_key(
                    inbound_message.inbound_message_id
                ),
            ),
        )
    except Exception:
        return ReviewNotificationResult(failure_reason="notification_provider_exception")

    if send_result.uncertain or not send_result.accepted:
        return ReviewNotificationResult(
            failure_reason="notification_uncertain"
            if send_result.uncertain
            else "notification_failed"
        )
    return ReviewNotificationResult(sent=True, recipient=recipient_destination)


def _review_notification_idempotency_key(inbound_message_id: UUID) -> str:
    return f"inbound:{inbound_message_id}:review-notification:v1"


def _lead_display_name(lead: CanonicalLeadRecord) -> str:
    return lead.primary_email or lead.primary_phone or lead.crm_lead_id


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


async def _enqueue_inbound_processed_signal_if_configured(
    *,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    event: InboundMessageEvent,
    external_event_id: UUID,
    conversation_id: UUID,
    inbound_message_id: UUID,
    workflow_transition: InboundWorkflowTransitionOutcome,
    inbound_action: InboundAction,
    inbound_action_reason: InboundActionReasonCode,
    now: datetime,
) -> bool:
    workflow = workflow_transition.workflow
    if temporal_signal_outbox_repository is None or workflow is None:
        return False
    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=event.workspace_id,
            workflow_id=workflow.workflow_id,
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.INBOUND_PROCESSED,
            payload={
                "lead_id": str(workflow.lead_id),
                "occurred_at": event.received_at.isoformat(),
                "external_event_id": str(external_event_id),
                "conversation_id": str(conversation_id),
                "inbound_message_id": str(inbound_message_id),
                "workflow_transition_id": (
                    str(workflow_transition.transition_id)
                    if workflow_transition.transition_id is not None
                    else None
                ),
                "inbound_action": inbound_action.value,
                "reason": inbound_action_reason.value,
            },
            idempotency_key=f"inbound-processed:{external_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    return True



async def _try_resolve_continue_ai_workflow(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    is_continue_ai: bool,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    lead_repository: LeadRepository | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    workspace_repository: WorkspaceRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    message_repository: OutboundMessageRepository | None,
    sms_provider: SMSProvider | None,
    email_provider: EmailProvider | None,
    llm_client: LLMClient | None,
) -> LeadWorkflow | None:
    if not is_continue_ai:
        return None
    if lead_workflow_repository is None:
        return None
    if workflow_transition_repository is None:
        return None
    if lead_repository is None:
        return None
    if campaign_execution_repository is None:
        return None
    if workspace_repository is None:
        return None
    if workspace_contact_policy_repository is None:
        return None
    if message_repository is None:
        return None
    if sms_provider is None:
        return None
    if email_provider is None:
        return None
    if llm_client is None:
        return None
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    return workflow


def _workflow_transition_outcome_from_continue_ai_result(
    result: ContinueAIResult,
) -> InboundWorkflowTransitionOutcome:
    if result.status in {ContinueAIStatus.SENT, ContinueAIStatus.ALREADY_SENT}:
        return InboundWorkflowTransitionOutcome(
            status=InboundWorkflowTransitionStatus.UPDATED,
            workflow=result.workflow,
            transition_id=result.transition_id,
        )
    if result.status == ContinueAIStatus.BLOCKED and result.workflow is not None:
        return InboundWorkflowTransitionOutcome(
            status=InboundWorkflowTransitionStatus.UPDATED,
            workflow=result.workflow,
            transition_id=result.transition_id,
        )
    return InboundWorkflowTransitionOutcome(
        status=InboundWorkflowTransitionStatus.SKIPPED,
        workflow=result.workflow,
        skip_reason=result.block_explanation,
    )


def _conversation_status_after_inbound(
    *,
    handoff_required: bool,
    continue_ai_result: ContinueAIResult | None,
) -> ConversationStatus:
    if handoff_required:
        return ConversationStatus.HUMAN_HANDOFF
    if continue_ai_result is None:
        return ConversationStatus.PAUSED
    if continue_ai_result.status in {ContinueAIStatus.SENT, ContinueAIStatus.ALREADY_SENT}:
        return ConversationStatus.ACTIVE_AI
    return ConversationStatus.PAUSED


def _build_inbound_processing_audit(
    *,
    classification: ReplyClassificationResult,
    inbound_decision: InboundActionDecision,
    handoff_required: bool,
    continue_ai_result: ContinueAIResult | None,
    workflow_transition: InboundWorkflowTransitionOutcome,
    crm_sync_result: CompleteInboundMessageCRMSyncResult | None,
    review_tag: str | None,
    review_tag_applied: bool,
    review_notification: ReviewNotificationResult,
    handoff_completion_result: HandoffCompletionResult | None,
    handoff: Handoff | None,
    signal_queued: bool,
) -> dict[str, object]:
    return {
        "classifier": {
            "status": classification.status.value,
            "intent": (
                classification.intent.value if classification.intent is not None else None
            ),
            "confidence": classification.confidence,
            "prompt_version": classification.prompt_version,
            "model": classification.model,
            "latency_ms": classification.latency_ms,
            "usage_tokens": classification.usage_tokens,
            "opt_out_detected": classification.opt_out_detected,
            "evidence": {
                "asks_for_human": classification.evidence.asks_for_human,
                "shows_buying_interest": classification.evidence.shows_buying_interest,
                "shows_selling_interest": classification.evidence.shows_selling_interest,
                "asks_property_or_advice": classification.evidence.asks_property_or_advice,
            },
            "preferences": dict(classification.preferences),
            "classification_reasons": [reason.value for reason in classification.reasons],
        },
        "decision": {
            "inbound_action": inbound_decision.action.value,
            "decision_reason": inbound_decision.reason_code.value,
            "handoff_reason": (
                inbound_decision.handoff_reason.value
                if inbound_decision.handoff_reason is not None
                else None
            ),
            "handoff_required": handoff_required,
        },
        "continuation": {
            "continue_ai_status": (
                continue_ai_result.status.value if continue_ai_result is not None else None
            ),
            "ai_interaction_count_increment": (
                continue_ai_result.ai_interaction_count_increment
                if continue_ai_result is not None
                else 0
            ),
            "pause_reason": (
                continue_ai_result.pause_reason if continue_ai_result is not None else None
            ),
            "block_explanation": (
                continue_ai_result.block_explanation
                if continue_ai_result is not None
                else None
            ),
            "send_block_reasons": (
                [reason.value for reason in continue_ai_result.reasons]
                if continue_ai_result is not None
                else None
            ),
            "outbound_message_id": (
                str(continue_ai_result.outbound_message_id)
                if continue_ai_result is not None
                and continue_ai_result.outbound_message_id is not None
                else None
            ),
            "provider_message_id": (
                continue_ai_result.provider_message_id
                if continue_ai_result is not None
                else None
            ),
        },
        "workflow": {
            "workflow_id": (
                str(workflow_transition.workflow.workflow_id)
                if workflow_transition.workflow is not None
                else None
            ),
            "temporal_workflow_id": (
                workflow_transition.workflow.temporal_workflow_id
                if workflow_transition.workflow is not None
                else None
            ),
            "workflow_transition_id": (
                str(workflow_transition.transition_id)
                if workflow_transition.transition_id is not None
                else None
            ),
            "workflow_transition_status": workflow_transition.status.value,
            "to_state": (
                workflow_transition.workflow.state.value
                if workflow_transition.workflow is not None
                else None
            ),
            "workflow_transition_skip_reason": workflow_transition.skip_reason,
        },
        "crm": {
            "crm_sync_status": (
                crm_sync_result.status.value if crm_sync_result is not None else None
            ),
            "crm_sync_failure_reason": (
                crm_sync_result.failure_reason if crm_sync_result is not None else None
            ),
            "review_tag": review_tag,
            "review_tag_applied": review_tag_applied,
        },
        "review_notification": {
            "sent": review_notification.sent,
            "recipient": review_notification.recipient,
            "failure_reason": review_notification.failure_reason,
        },
        "handoff": {
            "handoff_id": (
                str(handoff.handoff_id) if handoff is not None else None
            ),
            "completion_status": (
                handoff_completion_result.status.value
                if handoff_completion_result is not None
                else None
            ),
            "completion_failure_reason": (
                handoff_completion_result.failure_reason
                if handoff_completion_result is not None
                else None
            ),
        },
        "signal_queued": signal_queued,
    }
