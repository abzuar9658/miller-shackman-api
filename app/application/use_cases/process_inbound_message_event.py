from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, time
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.notifications import NotificationProvider, ReviewNotification
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
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
from app.application.services.llm.reply_classification import (
    InboundReplyIntent,
    InboundReplyRuleEvidence,
    ReplyClassificationReasonCode,
    ReplyClassificationResult,
    ReplyClassificationStatus,
    classify_inbound_reply,
)
from app.application.services.llm.reply_route_classification import (
    ReplyRouteClassificationResult,
    ReplyRouteClassificationStatus,
    ReplyRouteJourneyContext,
    ReplyRouteJourneyKind,
    classify_reply_route,
)
from app.application.services.llm.workspace_model_resolution import (
    WorkspaceLLMSelection,
    resolve_workspace_llm_config,
    workspace_llm_selection_for_task,
)
from app.application.services.pinned_campaign_version import (
    resolve_pinned_campaign_config_for_campaign,
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
    handoff_reason_to_action_reason,
)
from app.application.use_cases.process_contact_suppression_event import (
    apply_contact_suppression_to_lead,
)
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    send_outbound_message,
)
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_tracks import (
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
    ReplyRouteAction,
    ReplyRouteDecisionResult,
    ReplyRouteEvidence,
    WorkspaceHandoffConfig,
    decide_reply_route,
    default_workspace_handoff_config,
)
from app.domain.crm_sync import (
    INBOUND_MESSAGE_RECEIVED_EVENT_TYPE,
    ExternalEvent,
    ExternalEventStatus,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadStateClassificationOutcome,
    PausedSearchAction,
    PausedSearchTrackSelectionStatus,
    lead_paused_search_profile,
)
from app.domain.llm import LLMTaskKind
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
    event_type: str = INBOUND_MESSAGE_RECEIVED_EVENT_TYPE
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
    reply_route_decision: str | None = None
    reengagement_adjusted: bool = False


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
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
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
    claimed_external_event: ExternalEvent | None = None,
) -> ProcessInboundMessageEventResult:
    if claimed_external_event is None:
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
    if claimed_external_event is not None:
        external_event = replace(
            claimed_external_event,
            status=ExternalEventStatus.PENDING,
            processed_at=None,
            payload_redacted=dict(event.payload_redacted),
            failure_reason=None,
            failure_kind=None,
            next_retry_at=None,
            updated_at=now,
        )
    else:
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

    workspace_llm_config = await resolve_workspace_llm_config(
        workspace_id=event.workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )
    classification_selection = workspace_llm_selection_for_task(
        workspace_llm_config, LLMTaskKind.CLASSIFICATION
    )
    drafting_selection = workspace_llm_selection_for_task(
        workspace_llm_config, LLMTaskKind.DRAFTING
    )

    classification = await classify_inbound_reply(
        lead=lead,
        inbound_text=event.body,
        llm_client=llm_client,
        model=classification_selection.model,
        provider=classification_selection.provider,
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
    paused_profile = lead_paused_search_profile(lead)
    reply_route_result: ReplyRouteClassificationResult | None = None
    reply_route_journey: ReplyRouteJourneyContext | None = None
    reply_route_decision_action: ReplyRouteAction | None = None
    adjusted_reengagement_at: datetime | None = None
    if inbound_decision.action == InboundAction.CONTINUE_AI:
        reply_route_journey = await _build_reply_route_journey_context(
            lead=lead,
            track_version=paused_search_track_version,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            campaign_execution_repository=campaign_execution_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
        )
        reply_route_result = await _classify_reply_route(
            event=event,
            lead=lead,
            conversation=conversation,
            journey=reply_route_journey,
            external_event_id=saved_event.external_event_id,
            now=now,
            crm_conversation_event_repository=crm_conversation_event_repository,
            conversation_summary_repository=conversation_summary_repository,
            llm_client=llm_client,
            llm_selection=classification_selection,
        )
        proposed_reengagement_at = await _resolve_proposed_reengagement_datetime(
            route_result=reply_route_result,
            workspace_repository=workspace_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            workspace_id=event.workspace_id,
        )
        route_decision = decide_reply_route(
            router_decision=(
                reply_route_result.decision
                if reply_route_result.status is ReplyRouteClassificationStatus.CLASSIFIED
                else None
            ),
            router_rejected=(
                reply_route_result.status is ReplyRouteClassificationStatus.REJECTED
            ),
            evidence=ReplyRouteEvidence(
                asks_for_human=classification.evidence.asks_for_human,
                shows_buying_interest=classification.evidence.shows_buying_interest,
                shows_selling_interest=classification.evidence.shows_selling_interest,
                asks_property_or_advice=classification.evidence.asks_property_or_advice,
                intent=classification.intent.value if classification.intent else None,
            ),
            proposed_reengagement_not_before=proposed_reengagement_at,
            current_reengagement_not_before=(
                paused_profile.reengagement_not_before if paused_profile else None
            ),
            now=now,
        )
        reply_route_decision_action = route_decision.action
        adjusted_reengagement_at = route_decision.adjusted_reengagement_not_before
        inbound_decision = _inbound_decision_from_reply_route(route_decision)
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
            paused_search_reply_route=None,
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
    # Only dormant leads get a conversational AI reply; a paused-search lead
    # continuing its track resumes scheduled touches instead of an ad-hoc draft.
    is_continue_ai = (
        inbound_decision.action == InboundAction.CONTINUE_AI and paused_profile is None
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
    if classification.opt_out_detected or (
        reply_route_decision_action is ReplyRouteAction.SUPPRESS
    ):
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
            campaign_enrollment_repository=campaign_enrollment_repository,
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
            paused_search_track_repository=paused_search_track_repository,
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
            resume_paused_search=(
                inbound_decision.action == InboundAction.CONTINUE_AI
                and paused_profile is not None
            ),
            reply_route=(
                reply_route_decision_action.value
                if reply_route_decision_action is not None
                else None
            ),
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
    reengagement_adjusted = False
    if adjusted_reengagement_at is not None:
        lead, reengagement_adjusted = await _apply_reengagement_adjustment(
            lead=lead,
            adjusted_at=adjusted_reengagement_at,
            window_label=(
                reply_route_result.adjusted_reengagement_window_label
                if reply_route_result is not None
                else None
            ),
            now=now,
            lead_repository=lead_repository,
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
            llm_selection=drafting_selection,
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
        paused_search_reply_route=(
            reply_route_decision_action.value
            if reply_route_decision_action is not None and paused_profile is not None
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
        reply_route_result=reply_route_result,
        reply_route_action=reply_route_decision_action,
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
    await _store_reply_route_artifact_and_sync_review(
        lead=lead,
        workspace_id=event.workspace_id,
        route_result=reply_route_result,
        route_action=reply_route_decision_action,
        journey=reply_route_journey,
        track_version=paused_search_track_version,
        adjusted_reengagement_at=adjusted_reengagement_at,
        artifact_repository=lead_classification_artifact_repository,
        routing_review_repository=routing_review_repository,
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
        reply_route_decision=(
            reply_route_decision_action.value
            if reply_route_decision_action is not None
            else None
        ),
        reengagement_adjusted=reengagement_adjusted,
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


async def _build_reply_route_journey_context(
    *,
    lead: CanonicalLeadRecord,
    track_version: PausedSearchTrackVersion | None,
    lead_workflow_repository: LeadWorkflowRepository | None,
    paused_search_track_repository: PausedSearchTrackRepository | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
) -> ReplyRouteJourneyContext:
    """Snapshot the lead's current journey so the router decides in context."""
    profile = lead_paused_search_profile(lead)
    workflow = (
        await lead_workflow_repository.get_latest_for_lead_for_update(
            lead.workspace_id, lead.lead_id
        )
        if lead_workflow_repository is not None
        else None
    )
    next_touch = (
        workflow.next_action_at.isoformat()
        if workflow is not None and workflow.next_action_at is not None
        else None
    )
    if profile is None:
        next_step_goal = await _dormant_next_step_goal(
            lead=lead,
            workflow=workflow,
            campaign_execution_repository=campaign_execution_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
        )
        return ReplyRouteJourneyContext(
            journey=ReplyRouteJourneyKind.DORMANT,
            next_step_goal=next_step_goal,
            next_touch_scheduled_for=next_touch,
        )
    track_name: str | None = None
    last_step_goal: str | None = None
    if track_version is not None and paused_search_track_repository is not None:
        track = await paused_search_track_repository.get_track(
            lead.workspace_id, track_version.track_id
        )
        track_name = track.display_name if track is not None else None
        if workflow is not None and workflow.paused_search_track_step_id is not None:
            steps = await paused_search_track_repository.get_steps(
                lead.workspace_id, track_version.track_version_id
            )
            last_step_goal = next(
                (
                    step.message_goal
                    for step in steps
                    if step.step_id == workflow.paused_search_track_step_id
                ),
                None,
            )
    return ReplyRouteJourneyContext(
        journey=ReplyRouteJourneyKind.PAUSED_SEARCH,
        track_key=profile.paused_search_track_key,
        track_name=track_name,
        reengagement_not_before=(
            profile.reengagement_not_before.date()
            if profile.reengagement_not_before is not None
            else None
        ),
        reengagement_window_label=profile.reengagement_window_label,
        last_completed_step_goal=last_step_goal,
        next_touch_scheduled_for=next_touch,
    )


async def _dormant_next_step_goal(
    *,
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
) -> str | None:
    if workflow is None or campaign_execution_repository is None:
        return None
    config: CampaignExecutionConfig | None = await resolve_pinned_campaign_config_for_campaign(
        workspace_id=lead.workspace_id,
        campaign_id=workflow.campaign_id,
        workflow=workflow,
        campaign_execution_repository=campaign_execution_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
    )
    if config is None or not config.cadence_steps:
        return None
    if workflow.current_step_id is not None:
        for step in config.cadence_steps:
            if step.cadence_step_id == workflow.current_step_id:
                return step.message_goal
    return config.cadence_steps[0].message_goal


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


async def _classify_reply_route(
    *,
    event: InboundMessageEvent,
    lead: CanonicalLeadRecord,
    conversation: Conversation,
    journey: ReplyRouteJourneyContext,
    external_event_id: UUID,
    now: datetime,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
    conversation_summary_repository: ConversationSummaryRepository,
    llm_client: LLMClient,
    llm_selection: WorkspaceLLMSelection,
) -> ReplyRouteClassificationResult:
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
        body=event.body,
        occurred_at=event.received_at,
        now=now,
    )
    previous_summary = await conversation_summary_repository.get_latest_for_conversation(
        lead.workspace_id,
        conversation.conversation_id,
    )
    recent_events: list[dict[str, object]] = []
    for crm_event in sorted(
        (*crm_events, *supplemental_events), key=lambda item: item.occurred_at
    ):
        if not crm_event.content:
            continue
        recent_events.append(
            {
                "direction": (
                    crm_event.direction.value if crm_event.direction is not None else None
                ),
                "occurred_at": crm_event.occurred_at.isoformat(),
                "content": crm_event.content[:400],
            }
        )
    return await classify_reply_route(
        workspace_id=event.workspace_id,
        lead_id=lead.lead_id,
        channel=event.channel,
        inbound_text=event.body,
        journey=journey,
        now=now,
        conversation_summary=previous_summary.summary_text if previous_summary else None,
        recent_events=tuple(recent_events[-10:]),
        llm_client=llm_client,
        model=llm_selection.model,
        provider=llm_selection.provider,
    )


async def _resolve_proposed_reengagement_datetime(
    *,
    route_result: ReplyRouteClassificationResult,
    workspace_repository: WorkspaceRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    workspace_id: WorkspaceId,
) -> datetime | None:
    """Convert the reply's stated date into a send-safe moment in the brokerage timezone.

    Date-only model output lands at the start of the workspace's contact window
    in the workspace timezone — never UTC midnight, which would shift the date
    for western brokerages.
    """
    proposed_date = route_result.adjusted_reengagement_date
    if proposed_date is None:
        return None
    timezone_name = "UTC"
    if workspace_repository is not None:
        workspace = await workspace_repository.get_by_id(workspace_id)
        if workspace is not None and workspace.default_timezone:
            timezone_name = workspace.default_timezone
    policy = (
        await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
        if workspace_contact_policy_repository is not None
        else None
    )
    if policy is None:
        policy = default_workspace_contact_policy(workspace_id)
    send_time = (
        policy.quiet_hours_start
        if policy.quiet_hours_enabled and policy.quiet_hours_start is not None
        else time(10, 0)
    )
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.combine(proposed_date, send_time, tzinfo=timezone)


def _inbound_decision_from_reply_route(
    decision: ReplyRouteDecisionResult,
) -> InboundActionDecision:
    if decision.action is ReplyRouteAction.HUMAN_HANDOFF and decision.handoff_reason is not None:
        return InboundActionDecision(
            action=InboundAction.HUMAN_HANDOFF,
            reason_code=handoff_reason_to_action_reason(decision.handoff_reason),
            handoff_reason=decision.handoff_reason,
        )
    if decision.action is ReplyRouteAction.SUPPRESS:
        return InboundActionDecision(
            action=InboundAction.SUPPRESS,
            reason_code=InboundActionReasonCode.REPLY_ROUTE_SUPPRESSED,
        )
    if decision.action is ReplyRouteAction.REVIEW:
        return InboundActionDecision(
            action=InboundAction.PAUSE_FOR_REVIEW,
            reason_code=InboundActionReasonCode.REPLY_ROUTE_REJECTED,
        )
    return InboundActionDecision(
        action=InboundAction.CONTINUE_AI,
        reason_code=InboundActionReasonCode.REPLY_ROUTE_CONTINUE,
    )


async def _apply_reengagement_adjustment(
    *,
    lead: CanonicalLeadRecord,
    adjusted_at: datetime,
    window_label: str | None,
    now: datetime,
    lead_repository: LeadRepository,
) -> tuple[CanonicalLeadRecord, bool]:
    """Write a reply-stated earlier timing onto the lead's paused-search profile.

    Timing-only update: track choice, ownership, and source stay exactly as the
    operator set them. Recorded in the paused-search history so the timeline
    shows why the date moved.
    """
    previous_profile = lead_paused_search_profile(lead)
    if previous_profile is None:
        return lead, False
    saved = await lead_repository.upsert(
        replace(
            lead,
            reengagement_not_before=adjusted_at,
            reengagement_window_label=window_label or lead.reengagement_window_label,
            paused_search_last_confirmed_at=now,
        )
    )
    history_repository = cast(LeadPausedSearchHistoryRepository, lead_repository)
    await history_repository.append(
        LeadPausedSearchHistoryEntry(
            history_id=uuid4(),
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            action=PausedSearchAction.UPDATED,
            previous_profile=previous_profile,
            current_profile=lead_paused_search_profile(saved),
            actor_user_id=None,
            created_at=now,
        )
    )
    return saved, True


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
    llm_selection: WorkspaceLLMSelection,
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
        contactability_decision = evaluate_contactability(contactability_facts, channel)
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
                model=llm_selection.model,
                provider=llm_selection.provider,
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
            inbound_message_repository=inbound_message_repository,
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
    resume_paused_search: bool = False,
    reply_route: str | None = None,
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
        resume_paused_search=resume_paused_search,
        reply_route=reply_route,
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
    paused_search_reply_route: str | None,
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
                "paused_search_reply_decision": paused_search_reply_route,
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
    reply_route_result: ReplyRouteClassificationResult | None = None,
    reply_route_action: ReplyRouteAction | None = None,
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
            "reply_route": (
                reply_route_action.value if reply_route_action is not None else None
            ),
            "reply_route_classifier": (
                {
                    "status": reply_route_result.status.value,
                    "decision": (
                        reply_route_result.decision.value
                        if reply_route_result.decision is not None
                        else None
                    ),
                    "option_percentages": (
                        {
                            option.value: percent
                            for option, percent in reply_route_result.option_percentages.items()
                        }
                        if reply_route_result.option_percentages
                        else None
                    ),
                    "confidence": reply_route_result.confidence,
                    "prompt_version": reply_route_result.prompt_version,
                    "model": reply_route_result.model,
                }
                if reply_route_result is not None
                else None
            ),
        },
        "continuation": {
            "continue_ai_status": (
                continue_ai_result.status.value if continue_ai_result is not None else None
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


async def _store_reply_route_artifact_and_sync_review(
    *,
    lead: CanonicalLeadRecord,
    workspace_id: WorkspaceId,
    route_result: ReplyRouteClassificationResult | None,
    route_action: ReplyRouteAction | None,
    journey: ReplyRouteJourneyContext | None,
    track_version: PausedSearchTrackVersion | None,
    adjusted_reengagement_at: datetime | None,
    artifact_repository: LeadClassificationArtifactRepository | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    now: datetime,
) -> None:
    """Persist the reply-route classification for observability and sync review queues.

    The artifact is stored with the outcome mapped onto the existing lead-state
    vocabulary so the decision tree and classifier trace keep working unchanged;
    the raw per-option percentages stay in the parsed response.
    """
    if route_result is None:
        return
    artifact = None
    if artifact_repository is not None:
        continuing_paused_search = (
            route_action is ReplyRouteAction.CONTINUE
            and journey is not None
            and journey.journey is ReplyRouteJourneyKind.PAUSED_SEARCH
        )
        selected_track_key: str | None = None
        selected_track_version_id: UUID | None = None
        if continuing_paused_search and journey is not None:
            selected_track_key = journey.track_key
            if track_version is not None:
                selected_track_version_id = track_version.track_version_id
        artifact = await artifact_repository.save(
            LeadClassificationArtifact(
                artifact_id=uuid4(),
                workspace_id=workspace_id,
                lead_id=lead.lead_id,
                source="inbound_reply_route",
                outcome=_artifact_outcome_for_route(route_action, journey),
                reengagement_not_before=adjusted_reengagement_at,
                reengagement_window_label=route_result.adjusted_reengagement_window_label,
                confidence=route_result.confidence or 0.0,
                evidence=(route_result.summary,) if route_result.summary else (),
                summary=route_result.summary,
                model=route_result.model or "unknown",
                prompt_version=route_result.prompt_version,
                latency_ms=route_result.latency_ms or 0,
                usage_tokens=route_result.usage_tokens,
                applied_status=(
                    LeadClassificationAppliedStatus.APPLIED
                    if route_action is not None and route_action is not ReplyRouteAction.REVIEW
                    else LeadClassificationAppliedStatus.REVIEW
                ),
                applied_at=(
                    now
                    if route_action is not None and route_action is not ReplyRouteAction.REVIEW
                    else None
                ),
                created_at=now,
                selected_track_key=selected_track_key,
                track_selection_status=(
                    PausedSearchTrackSelectionStatus.SELECTED
                    if continuing_paused_search
                    else None
                ),
                track_version_id=selected_track_version_id,
                prompt_text=route_result.prompt_text,
                input_context=route_result.input_context,
                raw_llm_response_text=route_result.raw_llm_response_text,
                parsed_llm_response=route_result.parsed_llm_response,
            )
        )
    if routing_review_repository is None:
        return
    if route_action is ReplyRouteAction.REVIEW and artifact is not None:
        await create_or_refresh_pending_routing_review(
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            artifact=artifact,
            reason_codes=("reply_route_classification_rejected",),
            routing_review_repository=routing_review_repository,
            now=now,
        )
        return
    if route_action is not None:
        await supersede_pending_routing_reviews_for_lead(
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            routing_review_repository=routing_review_repository,
            now=now,
        )


def _artifact_outcome_for_route(
    route_action: ReplyRouteAction | None,
    journey: ReplyRouteJourneyContext | None,
) -> LeadStateClassificationOutcome:
    if route_action is ReplyRouteAction.HUMAN_HANDOFF:
        return LeadStateClassificationOutcome.HUMAN_HANDOFF
    if route_action is ReplyRouteAction.SUPPRESS:
        return LeadStateClassificationOutcome.BLOCKED
    if route_action is ReplyRouteAction.CONTINUE:
        return (
            LeadStateClassificationOutcome.PAUSED_SEARCH
            if journey is not None and journey.journey is ReplyRouteJourneyKind.PAUSED_SEARCH
            else LeadStateClassificationOutcome.DORMANT
        )
    return LeadStateClassificationOutcome.REVIEW_HOLD


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
