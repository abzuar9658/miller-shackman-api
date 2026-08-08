from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

import structlog

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.notifications import NotificationProvider, ReviewNotification
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    ConversationRepository,
    ConversationSummaryRepository,
    CrmConversationEventRepository,
    ExternalEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    InboundMessageCRMCompletionRepository,
    InboundMessageRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    PausedSearchAgentReminderRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.crm_attention_tag_sync import (
    remove_conflicting_crm_tag_if_present,
)
from app.application.services.crm_snapshot import has_crm_snapshot_fields
from app.application.services.email_threading import (
    resolve_lead_email_threading_headers,
    resolve_reply_email_subject,
)
from app.application.services.handoff_support import (
    latest_open_handoff_for_lead,
    publish_handoff_created_event,
)
from app.application.services.lead_routing_review import (
    create_or_refresh_pending_routing_review,
    supersede_pending_routing_reviews_for_lead,
)
from app.application.services.llm.handoff_acknowledgment_drafting import (
    draft_handoff_acknowledgment,
    resolve_lead_acknowledgment_prompt_text,
)
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
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
from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationStatus,
    apply_lead_state_classification,
)
from app.application.use_cases.complete_handoff import (
    HandoffCompletionResult,
    HandoffCompletionStatus,
    complete_handoff,
    handoff_notification_idempotency_key,
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
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    send_outbound_message,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_reply_policy import (
    PausedSearchReplyContext,
    PausedSearchReplyDecision,
    decide_paused_search_reply,
    has_valid_explicit_new_timing,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchReplyPolicy,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactSuppressionKind,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
    evaluate_contactability,
)
from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationSummary,
    CrmConversationEvent,
    CrmConversationEventDirection,
    Handoff,
    HandoffCompletionRecord,
    InboundMessage,
    InboundMessageClassificationStatus,
    WorkspaceHandoffConfig,
    default_workspace_handoff_config,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadStateClassificationOutcome,
    PausedSearchTrackSelectionStatus,
    lead_paused_search_profile,
)
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
)

logger = structlog.get_logger(__name__)

_HANDOFF_ACKNOWLEDGMENT_RECENT_MESSAGE_FETCH_LIMIT = 12
_HANDOFF_ACKNOWLEDGMENT_RECENT_TRANSCRIPT_LIMIT = 6


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
_MAX_CONVERSATION_SUMMARY_CHARS = 600
_DEFAULT_LEAD_ACKNOWLEDGMENT_SMS_BODY = (
    "Thanks for reaching out — our team will get back to you as soon as possible."
)
_DEFAULT_LEAD_ACKNOWLEDGMENT_EMAIL_SUBJECT = "We received your request"
_DEFAULT_LEAD_ACKNOWLEDGMENT_EMAIL_BODY = (
    "Thanks for reaching out. Our team will review your message and get back to you as soon "
    "as possible."
)


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
    email_subject: str | None = None
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
    paused_search_reply_decision: PausedSearchReplyDecision | None = None


async def process_inbound_message_event(
    *,
    event: InboundMessageEvent,
    lead_repository: LeadRepository,
    external_event_repository: ExternalEventRepository,
    conversation_repository: ConversationRepository,
    inbound_message_repository: InboundMessageRepository,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository | None = None,
    conversation_summary_repository: ConversationSummaryRepository,
    handoff_repository: HandoffRepository,
    llm_client: LLMClient,
    routing_review_repository: LeadRoutingReviewRepository | None = None,
    crm_client: CRMClient | None = None,
    inbound_message_crm_completion_repository: InboundMessageCRMCompletionRepository | None = None,
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    notification_provider: NotificationProvider | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    user_repository: UserRepository | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    paused_search_reminder_repository: PausedSearchAgentReminderRepository | None = None,
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
    paused_search_track_version = await _get_pinned_paused_search_track_version(
        lead=lead,
        paused_search_track_repository=paused_search_track_repository,
    )
    precomputed_lead_state_classification = await _classify_paused_search_timing_if_needed(
        lead=lead,
        conversation=conversation,
        external_event_id=saved_event.external_event_id,
        inbound_body=event.body,
        inbound_occurred_at=event.received_at,
        now=now,
        inbound_decision=inbound_decision,
        track_version=paused_search_track_version,
        paused_search_track_repository=paused_search_track_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        conversation_summary_repository=conversation_summary_repository,
        llm_client=llm_client,
        model=openrouter_model,
    )
    paused_search_reply_decision = await _resolve_paused_search_reply_decision(
        lead=lead,
        inbound_decision=inbound_decision,
        track_version=paused_search_track_version,
        lead_state_classification=precomputed_lead_state_classification,
        now=now,
    )
    inbound_decision = _apply_paused_search_reply_action(
        inbound_decision=inbound_decision,
        paused_search_reply_decision=paused_search_reply_decision,
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
            action=inbound_decision.action,
            decision_reason=inbound_decision.reason_code,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            paused_search_reminder_repository=paused_search_reminder_repository,
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
            paused_search_reply_decision=None,
            paused_search_restart_delay_days=None,
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
            existing_handoff_reused=False,
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
    is_continue_ai = (
        inbound_decision.action == InboundAction.CONTINUE_AI
        and paused_search_reply_decision is None
    )
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

    existing_open_handoff = (
        await latest_open_handoff_for_lead(
            workspace_id=event.workspace_id,
            lead_id=lead.lead_id,
            handoff_repository=handoff_repository,
        )
        if handoff_required
        else None
    )

    current_conversation_status = conversation.status
    conversation_status = _conversation_status_after_inbound(
        current_status=current_conversation_status,
        inbound_action=inbound_decision.action,
        continue_ai_result=None,
        existing_open_handoff=existing_open_handoff,
    )
    if continue_ai_workflow is not None:
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
    previous_summary = await conversation_summary_repository.get_latest_for_conversation(
        event.workspace_id,
        conversation.conversation_id,
    )
    saved_summary = await conversation_summary_repository.save(
        ConversationSummary(
            summary_id=(summary_id_factory or uuid4)(),
            workspace_id=event.workspace_id,
            conversation_id=conversation.conversation_id,
            lead_id=lead.lead_id,
            summary_text=_merged_conversation_summary_text(
                previous_summary=previous_summary,
                current_summary_text=classification.summary_text or event.body,
            ),
            preferences=_merged_conversation_preferences(
                previous_summary=previous_summary,
                current_preferences=classification.preferences,
            ),
            prompt_version=classification.prompt_version,
            model=classification.model or "unknown",
            confidence=classification.confidence,
            created_at=now,
        ),
    )
    supplemental_crm_conversation_events = _current_inbound_conversation_events(
        lead=lead,
        conversation=conversation,
        external_event_id=saved_event.external_event_id,
        body=event.body,
        occurred_at=event.received_at,
        now=now,
    )

    handoff: Handoff | None = existing_open_handoff
    created_handoff: Handoff | None = None
    pending_handoff_id = (handoff_id_factory or uuid4)() if handoff_required else None
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
            inbound_email_subject=event.email_subject,
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
            inbound_message_repository=inbound_message_repository,
            sms_provider=sms_provider,
            email_provider=email_provider,
            llm_client=llm_client,
            lead_classification_artifact_repository=lead_classification_artifact_repository,
            routing_review_repository=routing_review_repository,
            crm_conversation_event_repository=crm_conversation_event_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=(
                paused_search_track_assignment_repository
            ),
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            crm_client=crm_client,
            outbound_message_crm_completion_repository=outbound_message_crm_completion_repository,
            workspace_handoff_config=workspace_handoff_config,
            now=now,
            default_openrouter_model=default_openrouter_model,
            external_event_id=saved_event.external_event_id,
            inbound_message_id=inbound_message.inbound_message_id,
            transition_id_factory=workflow_transition_id_factory,
            supplemental_crm_conversation_events=supplemental_crm_conversation_events,
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
            action=inbound_decision.action,
            decision_reason=inbound_decision.reason_code,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            paused_search_reminder_repository=paused_search_reminder_repository,
            now=now,
            external_event_id=saved_event.external_event_id,
            conversation_id=conversation.conversation_id,
            inbound_message_id=inbound_message.inbound_message_id,
            handoff_id=(
                existing_open_handoff.handoff_id
                if existing_open_handoff is not None
                else pending_handoff_id
            ),
            intent=classification.intent,
            paused_search_reply_decision=paused_search_reply_decision,
            transition_id_factory=workflow_transition_id_factory,
        )
    if workflow_transition.workflow is not None:
        conversation = await conversation_repository.save(
            replace(
                conversation,
                status=_conversation_status_after_inbound(
                    current_status=current_conversation_status,
                    inbound_action=inbound_decision.action,
                    continue_ai_result=continue_ai_result,
                    existing_open_handoff=existing_open_handoff,
                workflow_state=workflow_transition.workflow.state,
                ),
                campaign_id=workflow_transition.workflow.campaign_id,
                workflow_id=workflow_transition.workflow.workflow_id,
                updated_at=now,
            ),
        )
    if (
        handoff_required
        and inbound_decision.handoff_reason is not None
        and existing_open_handoff is None
    ):
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
        created_handoff = handoff
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
                user_repository=user_repository,
                now=now,
            )
    else:
        handoff_completion_result = None

    if handoff_required and existing_open_handoff is not None and created_handoff is None:
        await _ensure_handoff_tag_for_existing_handoff(
            workspace_id=event.workspace_id,
            lead=lead,
            handoff=existing_open_handoff,
            crm_client=crm_client,
            workspace_handoff_config=workspace_handoff_config,
            handoff_completion_repository=handoff_completion_repository,
            now=now,
        )

    if handoff_required and inbound_decision.handoff_reason is not None and handoff is not None:
        await _send_lead_handoff_acknowledgments_if_configured(
            handoff=handoff,
            inbound_event=event,
            inbound_message=inbound_message,
            workspace_handoff_config=workspace_handoff_config,
            llm_client=llm_client,
            openrouter_model=openrouter_model,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            workspace_repository=workspace_repository,
            campaign_execution_repository=campaign_execution_repository,
            inbound_message_repository=inbound_message_repository,
            lead_repository=lead_repository,
            message_repository=message_repository,
            sms_provider=sms_provider,
            email_provider=email_provider,
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            now=now,
        )

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
        handoff=created_handoff,
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
        paused_search_reply_decision=paused_search_reply_decision,
        paused_search_restart_delay_days=(
            paused_search_track_version.restart_delay_days
            if paused_search_track_version is not None
            else None
        ),
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
        existing_handoff_reused=existing_open_handoff is not None and created_handoff is None,
        signal_queued=signal_queued,
        paused_search_reply_decision=paused_search_reply_decision,
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
    if not (continue_ai_result is not None and continue_ai_result.lead_state_rerouted):
        classification_for_reclassification = _hold_invalid_paused_search_reanchor(
            lead=lead,
            track_version=paused_search_track_version,
            classification_result=precomputed_lead_state_classification,
            now=now,
        )
        await _maybe_reclassify_lead_state_after_inbound(
            lead=lead,
            workspace_id=event.workspace_id,
            lead_repository=lead_repository,
            artifact_repository=lead_classification_artifact_repository,
            routing_review_repository=routing_review_repository,
            crm_conversation_event_repository=crm_conversation_event_repository,
            workspace_llm_config_repository=workspace_llm_config_repository,
            llm_client=llm_client,
            default_openrouter_model=default_openrouter_model,
            conversation_summary=saved_summary.summary_text,
            supplemental_crm_conversation_events=supplemental_crm_conversation_events,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=(
                paused_search_track_assignment_repository
            ),
            precomputed_classification_result=classification_for_reclassification,
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
        temporal_workflow_id=workflow_transition.workflow.temporal_workflow_id
        if workflow_transition.workflow is not None
        else None,
        workflow_transition_id=workflow_transition.transition_id,
        handoff_id=handoff.handoff_id if handoff is not None else None,
        intent=classification.intent,
        inbound_action=inbound_decision.action,
        inbound_action_reason=inbound_decision.reason_code,
        paused_search_reply_decision=paused_search_reply_decision,
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


async def _resolve_paused_search_reply_decision(
    *,
    lead: CanonicalLeadRecord,
    inbound_decision: InboundActionDecision,
    track_version: PausedSearchTrackVersion | None,
    lead_state_classification: LeadStateClassificationResult | None,
    now: datetime,
) -> PausedSearchReplyDecision | None:
    if inbound_decision.action != InboundAction.CONTINUE_AI:
        return None
    profile = lead_paused_search_profile(lead)
    if profile is None:
        return None
    if track_version is None:
        return PausedSearchReplyDecision.REVIEW
    return decide_paused_search_reply(
        track_version.reply_policy,
        PausedSearchReplyContext(
            same_paused_search_track=True,
            explicit_new_timing=_has_valid_same_track_timing(
                lead=lead,
                lead_state_classification=lead_state_classification,
                now=now,
            ),
        ),
    )


async def _get_pinned_paused_search_track_version(
    *,
    lead: CanonicalLeadRecord,
    paused_search_track_repository: PausedSearchTrackRepository | None,
) -> PausedSearchTrackVersion | None:
    profile = lead_paused_search_profile(lead)
    if (
        profile is None
        or profile.paused_search_track_version_id is None
        or paused_search_track_repository is None
    ):
        return None
    return await paused_search_track_repository.get_version(
        lead.workspace_id,
        profile.paused_search_track_version_id,
    )


async def _classify_paused_search_timing_if_needed(
    *,
    lead: CanonicalLeadRecord,
    conversation: Conversation,
    external_event_id: UUID,
    inbound_body: str,
    inbound_occurred_at: datetime,
    now: datetime,
    inbound_decision: InboundActionDecision,
    track_version: PausedSearchTrackVersion | None,
    paused_search_track_repository: PausedSearchTrackRepository | None,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
    conversation_summary_repository: ConversationSummaryRepository,
    llm_client: LLMClient,
    model: str | None,
) -> LeadStateClassificationResult | None:
    if (
        inbound_decision.action != InboundAction.CONTINUE_AI
        or track_version is None
        or track_version.reply_policy is not PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING
        or paused_search_track_repository is None
    ):
        return None
    if lead_paused_search_profile(lead) is None:
        return None
    catalog = await paused_search_track_repository.list_active_catalog(lead.workspace_id)
    crm_events = (
        await crm_conversation_event_repository.list_for_lead(
            lead.workspace_id,
            lead.lead_id,
            limit=20,
        )
        if crm_conversation_event_repository is not None
        else ()
    )
    supplemental_events = _current_inbound_conversation_events(
        lead=lead,
        conversation=conversation,
        external_event_id=external_event_id,
        body=inbound_body,
        occurred_at=inbound_occurred_at,
        now=now,
    )
    previous_summary = await conversation_summary_repository.get_latest_for_conversation(
        lead.workspace_id,
        conversation.conversation_id,
    )
    return await classify_lead_from_conversation(
        lead=lead,
        now=now,
        conversation_summary=previous_summary.summary_text if previous_summary else None,
        crm_conversation_events=(*crm_events, *supplemental_events),
        llm_client=llm_client,
        model=model,
        paused_search_catalog=catalog,
    )


def _has_valid_same_track_timing(
    *,
    lead: CanonicalLeadRecord,
    lead_state_classification: LeadStateClassificationResult | None,
    now: datetime,
) -> bool:
    profile = lead_paused_search_profile(lead)
    if profile is None or lead_state_classification is None:
        return False
    return (
        lead_state_classification.status is LeadStateClassificationStatus.CLASSIFIED
        and lead_state_classification.outcome is LeadStateClassificationOutcome.PAUSED_SEARCH
        and lead_state_classification.track_selection_status
        is PausedSearchTrackSelectionStatus.SELECTED
        and lead_state_classification.selected_track_key == profile.paused_search_track_key
        and lead_state_classification.track_version_id == profile.paused_search_track_version_id
        and has_valid_explicit_new_timing(
            timing=lead_state_classification.reengagement_not_before,
            now=now,
        )
    )


def _hold_invalid_paused_search_reanchor(
    *,
    lead: CanonicalLeadRecord,
    track_version: PausedSearchTrackVersion | None,
    classification_result: LeadStateClassificationResult | None,
    now: datetime,
) -> LeadStateClassificationResult | None:
    if (
        classification_result is None
        or track_version is None
        or track_version.reply_policy is not PausedSearchReplyPolicy.REANCHOR_TO_NEW_TIMING
        or classification_result.outcome is not LeadStateClassificationOutcome.PAUSED_SEARCH
        or _has_valid_same_track_timing(
            lead=lead,
            lead_state_classification=classification_result,
            now=now,
        )
    ):
        return classification_result
    return replace(
        classification_result,
        outcome=LeadStateClassificationOutcome.REVIEW_HOLD,
        selected_track_key=None,
        track_selection_status=None,
        track_version_id=None,
        reengagement_not_before=None,
        reengagement_window_label=None,
    )


def _apply_paused_search_reply_action(
    *,
    inbound_decision: InboundActionDecision,
    paused_search_reply_decision: PausedSearchReplyDecision | None,
) -> InboundActionDecision:
    if paused_search_reply_decision is PausedSearchReplyDecision.REVIEW:
        return replace(
            inbound_decision,
            action=InboundAction.PAUSE_FOR_REVIEW,
            reason_code=InboundActionReasonCode.PAUSED_SEARCH_REPLY_REVIEW,
        )
    if paused_search_reply_decision is PausedSearchReplyDecision.END:
        return replace(
            inbound_decision,
            action=InboundAction.COMPLETE_AUTOMATION,
            reason_code=InboundActionReasonCode.PAUSED_SEARCH_REPLY_ENDED,
        )
    return inbound_decision


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


async def _ensure_handoff_tag_for_existing_handoff(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    handoff: Handoff,
    crm_client: CRMClient | None,
    workspace_handoff_config: WorkspaceHandoffConfig | None,
    handoff_completion_repository: HandoffCompletionRepository | None,
    now: datetime,
) -> None:
    handoff_tag = (
        workspace_handoff_config.crm_handoff_tag if workspace_handoff_config is not None else None
    )
    review_tag = (
        workspace_handoff_config.crm_review_tag if workspace_handoff_config is not None else None
    )
    if crm_client is None or not handoff_tag:
        return

    record = None
    if handoff_completion_repository is not None:
        record = await handoff_completion_repository.get_by_handoff_id(
            workspace_id,
            handoff.handoff_id,
        )

    try:
        crm_lead = await crm_client.get_lead(workspace_id, lead.crm_lead_id)
        await remove_conflicting_crm_tag_if_present(
            crm_client=crm_client,
            workspace_id=workspace_id,
            crm_lead_id=lead.crm_lead_id,
            existing_tags=(crm_lead.tags if crm_lead is not None else None),
            active_tag=handoff_tag,
            conflicting_tag=review_tag,
        )
        await crm_client.add_tag(workspace_id, lead.crm_lead_id, handoff_tag)
    except Exception as exc:
        if handoff_completion_repository is None:
            return
        ensured_record = record or HandoffCompletionRecord(
            handoff_id=handoff.handoff_id,
            workspace_id=workspace_id,
            notification_idempotency_key=handoff_notification_idempotency_key(
                handoff.handoff_id,
            ),
        )
        await handoff_completion_repository.save(
            replace(
                ensured_record,
                last_attempted_at=now,
                failure_reason=f"crm_handoff_tag_reuse:{exc.__class__.__name__}",
            )
        )
        return

    if handoff_completion_repository is None:
        return
    ensured_record = record or HandoffCompletionRecord(
        handoff_id=handoff.handoff_id,
        workspace_id=workspace_id,
        notification_idempotency_key=handoff_notification_idempotency_key(
            handoff.handoff_id,
        ),
    )
    await handoff_completion_repository.save(
        replace(
            ensured_record,
            crm_tag_applied_at=now,
            last_attempted_at=now,
            failure_reason=None,
        )
    )


async def _send_lead_handoff_acknowledgments_if_configured(
    *,
    handoff: Handoff,
    inbound_event: InboundMessageEvent,
    inbound_message: InboundMessage,
    workspace_handoff_config: WorkspaceHandoffConfig | None,
    llm_client: LLMClient,
    openrouter_model: str,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    workspace_repository: WorkspaceRepository | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    inbound_message_repository: InboundMessageRepository,
    lead_repository: LeadRepository,
    message_repository: OutboundMessageRepository | None,
    sms_provider: SMSProvider | None,
    email_provider: EmailProvider | None,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    now: datetime,
) -> None:
    config = workspace_handoff_config or default_workspace_handoff_config(handoff.workspace_id)
    if message_repository is None or campaign_execution_repository is None:
        logger.info(
            "lead_handoff_acknowledgment_skipped",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            reason="missing_message_or_campaign_repository",
        )
        return
    if handoff.campaign_id is None:
        logger.info(
            "lead_handoff_acknowledgment_skipped",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            reason="handoff_campaign_missing",
        )
        return

    campaign_config = await campaign_execution_repository.get_active_for_campaign(
        handoff.workspace_id,
        handoff.campaign_id,
    )
    if campaign_config is None:
        logger.info(
            "lead_handoff_acknowledgment_skipped",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            campaign_id=str(handoff.campaign_id),
            reason="campaign_not_active",
        )
        return

    lead = await lead_repository.get_by_id(handoff.workspace_id, handoff.lead_id)
    if lead is None:
        logger.info(
            "lead_handoff_acknowledgment_skipped",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            lead_id=str(handoff.lead_id),
            reason="lead_not_found",
        )
        return

    policy_from_repository = (
        await workspace_contact_policy_repository.get_by_workspace_id(handoff.workspace_id)
        if workspace_contact_policy_repository is not None
        else None
    )
    policy = policy_from_repository or default_workspace_contact_policy(handoff.workspace_id)
    workspace = (
        await workspace_repository.get_by_id(handoff.workspace_id)
        if workspace_repository is not None
        else None
    )
    timezone = workspace.default_timezone if workspace is not None else campaign_config.timezone
    pre_send_policy = _handoff_acknowledgment_pre_send_policy(policy, timezone)
    logger.info(
        "lead_handoff_acknowledgment_policy_loaded",
        workspace_id=str(handoff.workspace_id),
        handoff_id=str(handoff.handoff_id),
        lead_id=str(handoff.lead_id),
        policy_source="repository" if policy_from_repository is not None else "default",
        sms_compliance_state=policy.sms_compliance_state.value,
        quiet_hours_enabled=policy.quiet_hours_enabled,
        quiet_hours_start=(
            policy.quiet_hours_start.isoformat() if policy.quiet_hours_start is not None else None
        ),
        quiet_hours_end=(
            policy.quiet_hours_end.isoformat() if policy.quiet_hours_end is not None else None
        ),
        inbound_email_address=policy.inbound_email_address,
        pre_send_allowed_start_hour=pre_send_policy.allowed_send_start_hour,
        pre_send_allowed_end_hour=pre_send_policy.allowed_send_end_hour,
        pre_send_timezone=pre_send_policy.timezone,
    )
    email_threading_headers = await resolve_lead_email_threading_headers(
        workspace_id=handoff.workspace_id,
        lead_id=handoff.lead_id,
        inbound_message_repository=inbound_message_repository,
        message_repository=message_repository,
        anchor_inbound_message_id=inbound_message.inbound_message_id,
    )
    acknowledgment_prompt_text = resolve_lead_acknowledgment_prompt_text(
        config.lead_acknowledgment_prompt_text
    )
    recent_conversation_context = await _recent_handoff_acknowledgment_conversation_context(
        handoff=handoff,
        inbound_message=inbound_message,
        inbound_message_repository=inbound_message_repository,
        message_repository=message_repository,
    )

    for channel, fallback_body, fallback_subject in _lead_acknowledgment_templates(
        config,
        inbound_event.channel,
    ):
        if channel == ContactChannel.SMS and sms_provider is None:
            logger.info(
                "lead_handoff_acknowledgment_skipped",
                workspace_id=str(handoff.workspace_id),
                handoff_id=str(handoff.handoff_id),
                lead_id=str(handoff.lead_id),
                channel=channel.value,
                reason="sms_provider_unavailable",
            )
            continue
        if channel == ContactChannel.EMAIL and email_provider is None:
            logger.info(
                "lead_handoff_acknowledgment_skipped",
                workspace_id=str(handoff.workspace_id),
                handoff_id=str(handoff.handoff_id),
                lead_id=str(handoff.lead_id),
                channel=channel.value,
                reason="email_provider_unavailable",
            )
            continue

        contactability_facts = contactability_facts_from_canonical_lead(lead)
        contactability_decision = evaluate_contactability(contactability_facts, policy, channel)
        logger.info(
            "lead_handoff_acknowledgment_contactability",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            lead_id=str(handoff.lead_id),
            channel=channel.value,
            do_not_contact=contactability_facts.do_not_contact,
            has_sms_destination=contactability_facts.has_sms_destination,
            has_email_destination=contactability_facts.has_email_destination,
            sms_consent_status=(
                contactability_facts.sms_consent_status.value
                if contactability_facts.sms_consent_status is not None
                else None
            ),
            email_permission_status=(
                contactability_facts.email_permission_status.value
                if contactability_facts.email_permission_status is not None
                else None
            ),
            suppressions=[suppression.value for suppression in contactability_facts.suppressions],
            contactability_allowed=contactability_decision.allowed,
            contactability_reasons=[reason.value for reason in contactability_decision.reasons],
        )
        if not contactability_decision.allowed:
            continue

        drafted_body = fallback_body
        drafted_subject = fallback_subject
        draft_source = "fallback"
        try:
            draft_result = await draft_handoff_acknowledgment(
                lead=lead,
                channel=channel,
                inbound_text=inbound_event.body,
                inbound_email_subject=inbound_event.email_subject,
                handoff_reason_code=handoff.reason_code.value,
                handoff_summary=handoff.summary,
                recent_conversation_context=recent_conversation_context,
                brokerage_name=workspace.name if workspace is not None else None,
                assigned_agent_name=None,
                admin_prompt_text=acknowledgment_prompt_text,
                reply_in_existing_email_thread=(
                    channel == ContactChannel.EMAIL and email_threading_headers.has_thread
                ),
                llm_client=llm_client,
                model=openrouter_model,
            )
        except Exception as exc:
            draft_result = None
            logger.warning(
                "lead_handoff_acknowledgment_draft_failed",
                workspace_id=str(handoff.workspace_id),
                handoff_id=str(handoff.handoff_id),
                lead_id=str(handoff.lead_id),
                channel=channel.value,
                error=str(exc),
            )

        if draft_result is not None and draft_result.status.value == "drafted":
            drafted_body = draft_result.body or fallback_body
            if draft_result.subject is not None:
                drafted_subject = draft_result.subject
            draft_source = "llm"
        elif draft_result is not None:
            logger.info(
                "lead_handoff_acknowledgment_draft_fallback",
                workspace_id=str(handoff.workspace_id),
                handoff_id=str(handoff.handoff_id),
                lead_id=str(handoff.lead_id),
                channel=channel.value,
                draft_status=draft_result.status.value,
                draft_reasons=[reason.value for reason in draft_result.reasons],
                safety_flags=list(draft_result.safety_flags),
                confidence=draft_result.confidence,
                validation_error=draft_result.validation_error,
                raw_llm_response_text=draft_result.raw_llm_response_text,
            )

        subject = _lead_acknowledgment_subject(
            channel=channel,
            configured_subject=drafted_subject,
            inbound_event=inbound_event,
        )

        idempotency_key = lead_handoff_acknowledgment_idempotency_key(
            handoff.handoff_id,
            inbound_message.inbound_message_id,
            channel,
        )
        message = await message_repository.get_by_idempotency_key(
            handoff.workspace_id,
            idempotency_key,
        )
        if message is None:
            message = await message_repository.save(
                OutboundMessage(
                    message_id=uuid4(),
                    workspace_id=handoff.workspace_id,
                    lead_id=handoff.lead_id,
                    campaign_id=handoff.campaign_id,
                    cadence_step_id=f"handoff_acknowledgment_{channel.value}",
                    channel=channel,
                    status=OutboundMessageStatus.PENDING,
                    idempotency_key=idempotency_key,
                    body=drafted_body,
                    subject=subject,
                    scheduled_for=now,
                    planned_at=now,
                    created_at=now,
                    updated_at=now,
                    message_version=1,
                )
            )
        elif message.body != drafted_body or message.subject != subject:
            message = await message_repository.save(
                replace(
                    message,
                    body=drafted_body,
                    subject=subject,
                    updated_at=now,
                )
            )

        send_result = await send_outbound_message(
            workspace_id=handoff.workspace_id,
            idempotency_key=message.idempotency_key,
            context=OutboundSendContext(
                campaign_status=campaign_config.campaign_status,
                workflow_state=WorkflowState.HUMAN_HANDOFF,
                enabled_channels=(channel,),
                workspace_contact_policy=policy,
                current_message_version=message.message_version,
                pre_send_policy=_handoff_acknowledgment_pre_send_policy(policy, timezone),
            ),
            lead_repository=lead_repository,
            message_repository=message_repository,
            sms_provider=cast(SMSProvider, sms_provider),
            email_provider=cast(EmailProvider, email_provider),
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            now=now,
            email_in_reply_to_message_id=(
                email_threading_headers.in_reply_to_message_id
                if channel == ContactChannel.EMAIL
                else None
            ),
            email_reference_message_ids=(
                email_threading_headers.reference_message_ids
                if channel == ContactChannel.EMAIL
                else ()
            ),
        )
        logger.info(
            "lead_handoff_acknowledgment_send_result",
            workspace_id=str(handoff.workspace_id),
            handoff_id=str(handoff.handoff_id),
            lead_id=str(handoff.lead_id),
            inbound_message_id=str(inbound_message.inbound_message_id),
            outbound_message_id=str(message.message_id),
            campaign_id=str(handoff.campaign_id),
            channel=channel.value,
            draft_source=draft_source,
            send_status=send_result.status.value,
            send_reasons=[reason.value for reason in send_result.reasons],
            pre_send_reasons=(
                [reason.value for reason in send_result.pre_send_decision.reasons]
                if send_result.pre_send_decision is not None
                else []
            ),
            persisted_message_status=(
                send_result.message.status.value
                if send_result.message is not None
                else message.status.value
            ),
            provider_send_status=(
                send_result.message.provider_send_status.value
                if send_result.message is not None
                else message.provider_send_status.value
            ),
            provider_name=(
                send_result.message.provider_name
                if send_result.message is not None
                else message.provider_name
            ),
            provider_message_id=(
                send_result.message.provider_message_id
                if send_result.message is not None
                else message.provider_message_id
            ),
        )


def lead_handoff_acknowledgment_idempotency_key(
    handoff_id: UUID,
    inbound_message_id: UUID,
    channel: ContactChannel,
) -> str:
    return (
        f"handoff:{handoff_id}:inbound:{inbound_message_id}:lead-acknowledgment:{channel.value}:v1"
    )


def _lead_acknowledgment_templates(
    config: WorkspaceHandoffConfig,
    inbound_channel: ContactChannel,
) -> tuple[tuple[ContactChannel, str, str | None], ...]:
    templates: list[tuple[ContactChannel, str, str | None]] = []
    if inbound_channel == ContactChannel.SMS and config.lead_acknowledgment_sms_enabled:
        templates.append(
            (
                ContactChannel.SMS,
                config.lead_acknowledgment_sms_body or _DEFAULT_LEAD_ACKNOWLEDGMENT_SMS_BODY,
                None,
            )
        )
    if inbound_channel == ContactChannel.EMAIL and config.lead_acknowledgment_email_enabled:
        templates.append(
            (
                ContactChannel.EMAIL,
                config.lead_acknowledgment_email_body or _DEFAULT_LEAD_ACKNOWLEDGMENT_EMAIL_BODY,
                config.lead_acknowledgment_email_subject
                or _DEFAULT_LEAD_ACKNOWLEDGMENT_EMAIL_SUBJECT,
            )
        )
    return tuple(templates)


def _lead_acknowledgment_subject(
    *,
    channel: ContactChannel,
    configured_subject: str | None,
    inbound_event: InboundMessageEvent,
) -> str | None:
    if channel != ContactChannel.EMAIL:
        return configured_subject
    return resolve_reply_email_subject(
        inbound_channel=inbound_event.channel,
        inbound_email_subject=inbound_event.email_subject,
        drafted_subject=configured_subject,
    )


@dataclass(frozen=True)
class _AcknowledgmentConversationContextLine:
    occurred_at: datetime
    text: str


async def _recent_handoff_acknowledgment_conversation_context(
    *,
    handoff: Handoff,
    inbound_message: InboundMessage,
    inbound_message_repository: InboundMessageRepository,
    message_repository: OutboundMessageRepository,
) -> str | None:
    inbound_messages = await inbound_message_repository.list_for_lead(
        handoff.workspace_id,
        handoff.lead_id,
        limit=_HANDOFF_ACKNOWLEDGMENT_RECENT_MESSAGE_FETCH_LIMIT,
    )
    outbound_messages = await message_repository.list_for_lead(
        handoff.workspace_id,
        handoff.lead_id,
        limit=_HANDOFF_ACKNOWLEDGMENT_RECENT_MESSAGE_FETCH_LIMIT,
    )

    lines: list[_AcknowledgmentConversationContextLine] = []
    for message in inbound_messages:
        if message.conversation_id != inbound_message.conversation_id:
            continue
        formatted = _format_inbound_message_for_acknowledgment_context(message)
        if formatted is None:
            continue
        lines.append(
            _AcknowledgmentConversationContextLine(
                occurred_at=message.received_at,
                text=formatted,
            )
        )

    for message in outbound_messages:
        if message.campaign_id != handoff.campaign_id:
            continue
        if message.status != OutboundMessageStatus.SENT:
            continue
        formatted = _format_outbound_message_for_acknowledgment_context(message)
        if formatted is None:
            continue
        lines.append(
            _AcknowledgmentConversationContextLine(
                occurred_at=(message.sent_at or message.created_at),
                text=formatted,
            )
        )

    recent_lines = sorted(lines, key=lambda item: item.occurred_at)[
        -_HANDOFF_ACKNOWLEDGMENT_RECENT_TRANSCRIPT_LIMIT:
    ]
    if not recent_lines:
        return None
    return "\n".join(item.text for item in recent_lines)


def _format_inbound_message_for_acknowledgment_context(message: InboundMessage) -> str | None:
    body = message.body.strip()
    if not body:
        return None
    return f"lead [{message.channel.value}]: {body}"


def _format_outbound_message_for_acknowledgment_context(message: OutboundMessage) -> str | None:
    body = message.body.strip()
    if not body:
        return None
    return f"brokerage [{message.channel.value}]: {body}"


def _handoff_acknowledgment_pre_send_policy(
    policy: WorkspaceContactPolicy,
    timezone: str | None,
) -> PreSendPolicy:
    if not policy.quiet_hours_enabled:
        return PreSendPolicy(
            sendable_workflow_states=frozenset({WorkflowState.HUMAN_HANDOFF}),
            allowed_send_start_hour=0,
            allowed_send_end_hour=24,
            allow_simultaneous_channels=True,
            timezone=timezone,
        )
    return PreSendPolicy(
        sendable_workflow_states=frozenset({WorkflowState.HUMAN_HANDOFF}),
        allowed_send_start_hour=(policy.quiet_hours_start.hour if policy.quiet_hours_start else 10),
        allowed_send_end_hour=(policy.quiet_hours_end.hour if policy.quiet_hours_end else 17),
        allow_simultaneous_channels=True,
        timezone=timezone,
    )


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
    if inbound_action == InboundAction.COMPLETE_AUTOMATION:
        return "completed_no_interest"
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
    action: InboundAction,
    decision_reason: InboundActionReasonCode,
    lead_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    paused_search_reminder_repository: PausedSearchAgentReminderRepository | None = None,
    now: datetime,
    external_event_id: UUID | None,
    conversation_id: UUID | None,
    inbound_message_id: UUID | None,
    handoff_id: UUID | None = None,
    intent: InboundReplyIntent | None = None,
    classification_reasons: tuple[str, ...] = (),
    paused_search_reply_decision: PausedSearchReplyDecision | None = None,
    transition_id_factory: Callable[[], UUID] | None = None,
) -> InboundWorkflowTransitionOutcome:
    if lead_workflow_repository is None or workflow_transition_repository is None:
        return InboundWorkflowTransitionOutcome(status=InboundWorkflowTransitionStatus.NO_WORKFLOW)
    return await apply_inbound_workflow_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        action=action,
        decision_reason=decision_reason,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        paused_search_reminder_repository=paused_search_reminder_repository,
        now=now,
        external_event_id=external_event_id,
        conversation_id=conversation_id,
        inbound_message_id=inbound_message_id,
        handoff_id=handoff_id,
        intent=intent,
        classification_reasons=classification_reasons,
        paused_search_reply_decision=paused_search_reply_decision,
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
    recipient_id = assigned_agent.crm_agent_id if assigned_agent is not None else fallback_email
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
        await publish_handoff_created_event(handoff=handoff, event_bus=event_bus)
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
    paused_search_reply_decision: PausedSearchReplyDecision | None,
    paused_search_restart_delay_days: int | None,
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
                "paused_search_reply_decision": (
                    paused_search_reply_decision.value
                    if paused_search_reply_decision is not None
                    else None
                ),
            },
            idempotency_key=f"inbound-processed:{external_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    if paused_search_reply_decision is PausedSearchReplyDecision.RESTART:
        if paused_search_restart_delay_days is None or paused_search_restart_delay_days < 1:
            raise ValueError("restart policy requires a positive configured restart delay")
        resume_at = now + timedelta(days=paused_search_restart_delay_days)
        await temporal_signal_outbox_repository.append(
            TemporalSignalOutboxEntry(
                temporal_signal_id=uuid4(),
                workspace_id=event.workspace_id,
                workflow_id=workflow.workflow_id,
                temporal_workflow_id=workflow.temporal_workflow_id,
                signal_name=TemporalSignalName.RESUME_REQUESTED,
                payload={
                    "lead_id": str(workflow.lead_id),
                    "occurred_at": resume_at.isoformat(),
                    "external_event_id": str(external_event_id),
                    "reason": "paused_search_restart_delay_elapsed",
                },
                idempotency_key=f"paused-search-restart-resume:{external_event_id}",
                available_at=resume_at,
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
    current_status: ConversationStatus,
    inbound_action: InboundAction,
    continue_ai_result: ContinueAIResult | None,
    existing_open_handoff: Handoff | None,
    workflow_state: WorkflowState | None = None,
) -> ConversationStatus:
    if inbound_action == InboundAction.HUMAN_HANDOFF:
        if existing_open_handoff is not None and current_status == ConversationStatus.HUMAN_OWNED:
            return ConversationStatus.HUMAN_OWNED
        return ConversationStatus.HUMAN_HANDOFF
    if inbound_action in {InboundAction.SUPPRESS, InboundAction.COMPLETE_AUTOMATION}:
        return ConversationStatus.CLOSED
    if continue_ai_result is None:
        if workflow_state is not None:
            return _conversation_status_from_workflow_state(workflow_state)
        return ConversationStatus.PAUSED
    if continue_ai_result.status in {ContinueAIStatus.SENT, ContinueAIStatus.ALREADY_SENT}:
        return ConversationStatus.ACTIVE_AI
    if continue_ai_result.status == ContinueAIStatus.WORKFLOW_TRANSITION_SKIPPED:
        return _conversation_status_from_workflow_state(continue_ai_result.workflow_state)
    return ConversationStatus.PAUSED


def _conversation_status_from_workflow_state(
    workflow_state: WorkflowState | None,
) -> ConversationStatus:
    if workflow_state in {
        WorkflowState.ELIGIBLE,
        WorkflowState.QUEUED,
        WorkflowState.ACTIVE_NURTURE,
        WorkflowState.WAITING_FOR_RESPONSE,
        WorkflowState.RESPONSE_PROCESSING,
    }:
        return ConversationStatus.ACTIVE_AI
    if workflow_state == WorkflowState.HUMAN_HANDOFF:
        return ConversationStatus.HUMAN_HANDOFF
    if workflow_state == WorkflowState.HUMAN_OWNED:
        return ConversationStatus.HUMAN_OWNED
    if workflow_state in {
        WorkflowState.COMPLETED,
        WorkflowState.SUPPRESSED,
        WorkflowState.CLOSED,
    }:
        return ConversationStatus.CLOSED
    return ConversationStatus.PAUSED


def _merged_conversation_summary_text(
    *,
    previous_summary: ConversationSummary | None,
    current_summary_text: str | None,
) -> str:
    current = _normalized_summary_text(current_summary_text)
    previous = _normalized_summary_text(
        previous_summary.summary_text if previous_summary is not None else None
    )
    if previous is None:
        return current or "Lead replied."
    if current is None:
        return previous
    previous_folded = previous.casefold()
    current_folded = current.casefold()
    if current_folded in previous_folded:
        return previous
    if previous_folded in current_folded:
        return _truncate_summary_text(current)
    prefix = "Earlier context: "
    connector = " Latest reply: "
    previous_budget = max(
        80,
        _MAX_CONVERSATION_SUMMARY_CHARS - len(prefix) - len(connector) - len(current),
    )
    trimmed_previous = _truncate_summary_text(previous, limit=previous_budget)
    return _truncate_summary_text(f"{prefix}{trimmed_previous}{connector}{current}")


def _merged_conversation_preferences(
    *,
    previous_summary: ConversationSummary | None,
    current_preferences: Mapping[str, str],
) -> Mapping[str, str]:
    merged: dict[str, str] = {}
    if previous_summary is not None:
        merged.update(_clean_preference_mapping(previous_summary.preferences))
    merged.update(_clean_preference_mapping(current_preferences))
    return merged


def _clean_preference_mapping(preferences: Mapping[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in preferences.items():
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            cleaned[normalized_key] = normalized_value
    return cleaned


def _normalized_summary_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _truncate_summary_text(value: str, *, limit: int = _MAX_CONVERSATION_SUMMARY_CHARS) -> str:
    if len(value) <= limit:
        return value
    truncated = value[: max(limit - 1, 0)].rstrip()
    return f"{truncated}…"


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
    existing_handoff_reused: bool,
    signal_queued: bool,
    paused_search_reply_decision: PausedSearchReplyDecision | None = None,
) -> dict[str, object]:
    return {
        "classifier": {
            "status": classification.status.value,
            "intent": (classification.intent.value if classification.intent is not None else None),
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
            "paused_search_reply_decision": (
                paused_search_reply_decision.value
                if paused_search_reply_decision is not None
                else None
            ),
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
                continue_ai_result.block_explanation if continue_ai_result is not None else None
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
                continue_ai_result.provider_message_id if continue_ai_result is not None else None
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
            "handoff_id": (str(handoff.handoff_id) if handoff is not None else None),
            "reused_existing_handoff": existing_handoff_reused,
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


async def _maybe_reclassify_lead_state_after_inbound(
    *,
    lead: CanonicalLeadRecord,
    workspace_id: WorkspaceId,
    lead_repository: LeadRepository,
    artifact_repository: LeadClassificationArtifactRepository | None,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    llm_client: LLMClient,
    default_openrouter_model: str,
    conversation_summary: str | None,
    supplemental_crm_conversation_events: tuple[CrmConversationEvent, ...],
    lead_workflow_repository: LeadWorkflowRepository | None,
    paused_search_track_repository: PausedSearchTrackRepository | None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    now: datetime,
    routing_review_repository: LeadRoutingReviewRepository | None,
    precomputed_classification_result: LeadStateClassificationResult | None,
) -> None:
    if (
        artifact_repository is None
        or crm_conversation_event_repository is None
        or workspace_llm_config_repository is None
    ):
        return
    if lead.do_not_contact or lead.sms_opted_out or lead.email_unsubscribed:
        return
    classification_result = await apply_lead_state_classification(
        actor=None,
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        lead_repository=lead_repository,
        paused_search_history_repository=cast(LeadPausedSearchHistoryRepository, lead_repository),
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        now=now,
        default_openrouter_model=default_openrouter_model,
        allow_overwrite_human_state=True,
        conversation_summary=conversation_summary,
        supplemental_crm_conversation_events=supplemental_crm_conversation_events,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        precomputed_classification_result=precomputed_classification_result,
    )
    if routing_review_repository is not None:
        if classification_result.status == ApplyLeadStateClassificationStatus.REVIEW:
            if classification_result.artifact is not None:
                await create_or_refresh_pending_routing_review(
                    workspace_id=workspace_id,
                    lead_id=lead.lead_id,
                    artifact=classification_result.artifact,
                    reason_codes=classification_result.reasons,
                    routing_review_repository=routing_review_repository,
                    now=now,
                )
        elif classification_result.status in {
            ApplyLeadStateClassificationStatus.APPLIED,
            ApplyLeadStateClassificationStatus.BLOCKED,
            ApplyLeadStateClassificationStatus.UNCHANGED,
        }:
            await supersede_pending_routing_reviews_for_lead(
                workspace_id=workspace_id,
                lead_id=lead.lead_id,
                routing_review_repository=routing_review_repository,
                now=now,
            )
    if classification_result.status in {
        ApplyLeadStateClassificationStatus.APPLIED,
        ApplyLeadStateClassificationStatus.REVIEW,
        ApplyLeadStateClassificationStatus.BLOCKED,
    }:
        outcome_value = None
        if (
            classification_result.classification_result
            and classification_result.classification_result.outcome
        ):
            outcome_value = classification_result.classification_result.outcome.value
        logger.info(
            "lead_state_reclassification_after_inbound",
            workspace_id=str(workspace_id),
            lead_id=str(lead.lead_id),
            status=classification_result.status.value,
            outcome=outcome_value,
            reasons=list(classification_result.reasons),
        )


def _current_inbound_conversation_events(
    *,
    lead: CanonicalLeadRecord,
    conversation: Conversation,
    external_event_id: UUID,
    body: str,
    occurred_at: datetime,
    now: datetime,
) -> tuple[CrmConversationEvent, ...]:
    if not body.strip():
        return ()
    return (
        CrmConversationEvent(
            crm_conversation_event_id=external_event_id,
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            conversation_id=conversation.conversation_id,
            crm_provider=lead.crm_provider.value,
            crm_activity_id=f"inbound:{external_event_id}",
            occurred_at=occurred_at,
            direction=CrmConversationEventDirection.INBOUND,
            activity_type="inbound_message",
            actor_name="lead",
            content=body,
            source_payload_version="synthetic/inbound_message:v1",
            created_at=now,
            updated_at=now,
        ),
    )
