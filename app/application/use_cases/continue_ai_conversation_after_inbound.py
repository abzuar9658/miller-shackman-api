from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.llm import LLMClient
from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.ports.repositories import (
    CampaignExecutionRepository,
    ConversationRepository,
    CrmConversationEventRepository,
    InboundMessageRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    OutboundMessageCRMCompletionRepository,
    OutboundMessageRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.email_threading import resolve_reply_email_subject
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.complete_outbound_message_crm_sync import (
    complete_outbound_message_crm_sync,
)
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import PlanOutboundMessageStatus
from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    AiNurtureRouteResult,
    route_ai_nurture_lead,
)
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.campaigns.pre_send import PreSendPolicy
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
)
from app.domain.conversations import (
    Conversation,
    ConversationSummary,
    CrmConversationEvent,
    WorkspaceHandoffConfig,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.outbound_drafting import OutboundJourneyKind
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode

_DEFAULT_CONTINUATION_GOAL = (
    "Continue the conversation naturally, answer safely if possible, "
    "and invite the assigned agent to help if needed."
)
_MAX_AI_INTERACTION_TURNS = 5


class ContinueAIStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    BLOCKED = "blocked"
    NO_WORKFLOW = "no_workflow"
    NO_CAMPAIGN_CONFIG = "no_campaign_config"
    NO_WORKSPACE = "no_workspace"
    WORKFLOW_TRANSITION_SKIPPED = "workflow_transition_skipped"


class ContinueAIReasonCode(StrEnum):
    LEAD_NOT_FOUND = "lead_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    CAMPAIGN_CONFIG_NOT_FOUND = "campaign_config_not_found"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    TURN_CAP_REACHED = "turn_cap_reached"
    WORKFLOW_TRANSITION_FAILED = "workflow_transition_failed"
    PLANNING_BLOCKED = "planning_blocked"
    REPLY_REROUTED = "reply_rerouted"
    SENDING_BLOCKED = "sending_blocked"
    SENDING_FAILED = "sending_failed"
    SENDING_UNCERTAIN = "sending_uncertain"


@dataclass(frozen=True)
class ContinueAIResult:
    status: ContinueAIStatus
    workflow: LeadWorkflow | None = None
    conversation: Conversation | None = None
    workflow_state: WorkflowState | None = None
    ai_interaction_count_increment: int = 0
    workflow_id: UUID | None = None
    transition_id: UUID | None = None
    outbound_message_id: UUID | None = None
    provider_message_id: str | None = None
    reasons: tuple[ContinueAIReasonCode, ...] = ()
    block_explanation: str | None = None
    pause_reason: str | None = None
    lead_state_rerouted: bool = False


async def continue_ai_conversation_after_inbound(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    inbound_channel: ContactChannel,
    inbound_body: str,
    inbound_email_subject: str | None = None,
    conversation: Conversation,
    latest_summary: ConversationSummary | None,
    conversation_repository: ConversationRepository,
    lead_repository: LeadRepository,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_repository: WorkspaceRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    message_repository: OutboundMessageRepository,
    inbound_message_repository: InboundMessageRepository | None,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    llm_client: LLMClient,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository | None = None,
    routing_review_repository: LeadRoutingReviewRepository | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    crm_client: CRMClient | None = None,
    outbound_message_crm_completion_repository: (
        OutboundMessageCRMCompletionRepository | None
    ) = None,
    workspace_handoff_config: WorkspaceHandoffConfig | None = None,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    external_event_id: UUID | None = None,
    inbound_message_id: UUID | None = None,
    transition_id_factory: Callable[[], UUID] | None = None,
    supplemental_crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
) -> ContinueAIResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return ContinueAIResult(
            status=ContinueAIStatus.BLOCKED,
            reasons=(ContinueAIReasonCode.LEAD_NOT_FOUND,),
        )

    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return ContinueAIResult(
            status=ContinueAIStatus.NO_WORKSPACE,
            reasons=(ContinueAIReasonCode.WORKSPACE_NOT_FOUND,),
        )

    config = await campaign_execution_repository.get_active_for_campaign(workspace_id, campaign_id)
    if config is None:
        return ContinueAIResult(
            status=ContinueAIStatus.NO_CAMPAIGN_CONFIG,
            reasons=(ContinueAIReasonCode.CAMPAIGN_CONFIG_NOT_FOUND,),
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return ContinueAIResult(
            status=ContinueAIStatus.NO_WORKFLOW,
            reasons=(ContinueAIReasonCode.WORKFLOW_NOT_FOUND,),
        )

    if workflow.state != WorkflowState.WAITING_FOR_RESPONSE:
        return ContinueAIResult(
            status=ContinueAIStatus.WORKFLOW_TRANSITION_SKIPPED,
            workflow=workflow,
            workflow_state=workflow.state,
            workflow_id=workflow.workflow_id,
            reasons=(ContinueAIReasonCode.WORKFLOW_TRANSITION_FAILED,),
            block_explanation=(
                f"Cannot continue AI from workflow state {workflow.state.value}; "
                "expected waiting_for_response."
            ),
        )

    reroute_result = await _maybe_route_reply_before_continuation(
        workspace_id=workspace_id,
        lead=lead,
        inbound_body=inbound_body,
        latest_summary=latest_summary,
        lead_repository=lead_repository,
        artifact_repository=lead_classification_artifact_repository,
        routing_review_repository=routing_review_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        now=now,
        default_openrouter_model=default_openrouter_model,
        supplemental_crm_conversation_events=supplemental_crm_conversation_events,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=(
            paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
    )
    if reroute_result is not None and reroute_result.route != AiNurtureRoute.DORMANT:
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow.workflow_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            pause_reason=f"ai_continuation_rerouted_to_{reroute_result.route.value}",
            block_explanation=(
                "Inbound reply changed the lead state before AI continuation "
                f"to {reroute_result.route.value}."
            ),
            reasons=(ContinueAIReasonCode.REPLY_REROUTED,),
            now=now,
            transition_id_factory=transition_id_factory,
            lead_state_rerouted=True,
        )

    if conversation.ai_interaction_count >= _MAX_AI_INTERACTION_TURNS:
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow.workflow_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            pause_reason="ai_continuation_turn_cap_reached",
            block_explanation=(
                f"AI continuation capped at {_MAX_AI_INTERACTION_TURNS} turns for V1 safety."
            ),
            reasons=(ContinueAIReasonCode.TURN_CAP_REACHED,),
            now=now,
            transition_id_factory=transition_id_factory,
        )

    response_processing_outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.RESPONSE_PROCESSING,
        reason_code=WorkflowTransitionReasonCode.INBOUND_REPLY_RECEIVED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        external_event_id=external_event_id,
        metadata={
            "inbound_message_id": (
                str(inbound_message_id) if inbound_message_id is not None else None
            ),
            "inbound_channel": inbound_channel.value,
        },
        transition_id_factory=transition_id_factory,
    )
    if response_processing_outcome.status != WorkflowStateTransitionStatus.UPDATED:
        return ContinueAIResult(
            status=ContinueAIStatus.WORKFLOW_TRANSITION_SKIPPED,
            workflow=workflow,
            workflow_state=workflow.state,
            workflow_id=workflow.workflow_id,
            reasons=(ContinueAIReasonCode.WORKFLOW_TRANSITION_FAILED,),
            block_explanation=response_processing_outcome.skip_reason,
        )

    response_processing_workflow = (
        response_processing_outcome.workflow
        if response_processing_outcome.workflow is not None
        else workflow
    )
    response_processing_workflow_id = response_processing_workflow.workflow_id

    step = _resolve_continuation_step(config, workflow.current_step_id)
    if step is None:
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=response_processing_workflow_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            pause_reason="ai_continuation_no_cadence_step",
            block_explanation="No cadence step available for AI continuation.",
            reasons=(ContinueAIReasonCode.PLANNING_BLOCKED,),
            now=now,
            transition_id_factory=transition_id_factory,
        )
    cadence_step_id = (
        f"ai-continuation:{inbound_message_id}" if inbound_message_id else str(step.cadence_step_id)
    )
    campaign_goal = step.message_goal

    workspace_contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id,
    )
    if workspace_contact_policy is None:
        workspace_contact_policy = default_workspace_contact_policy(workspace_id)

    plan_result = await plan_next_outbound_message_for_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        context=PlanNextOutboundMessageContext(
            campaign_status=config.campaign_status,
            workflow_state=WorkflowState.RESPONSE_PROCESSING,
            enabled_channels=(inbound_channel,),
            workspace_contact_policy=workspace_contact_policy,
            campaign_goal=campaign_goal,
            brokerage_name=workspace.name,
            cadence_step_id=cadence_step_id,
            scheduled_for=now,
            pre_send_policy=_pre_send_policy(workspace_contact_policy, workspace.default_timezone),
            journey_kind=OutboundJourneyKind.DORMANT,
            drafting_config=config.outbound_drafting_config,
            conversation_summary=(
                latest_summary.summary_text if latest_summary is not None else None
            ),
            latest_lead_request=inbound_body,
            extracted_preferences=(
                latest_summary.preferences if latest_summary is not None else {}
            ),
        ),
        lead_repository=lead_repository,
        message_repository=message_repository,
        llm_client=llm_client,
        now=now,
        workspace_llm_config_repository=workspace_llm_config_repository,
        workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
        default_openrouter_model=default_openrouter_model,
    )

    if plan_result.status == PlanOutboundMessageStatus.REJECTED or plan_result.message is None:
        return await _pause_after_block(
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=response_processing_workflow_id,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
            pause_reason="ai_continuation_planning_blocked",
            block_explanation=f"Planning blocked: {_reason_values(plan_result.reasons)}.",
            reasons=(ContinueAIReasonCode.PLANNING_BLOCKED,),
            now=now,
            transition_id_factory=transition_id_factory,
        )

    if plan_result.status == PlanOutboundMessageStatus.DUPLICATE:
        duplicate_message = plan_result.message
        return ContinueAIResult(
            status=ContinueAIStatus.ALREADY_SENT,
            workflow=response_processing_workflow,
            workflow_state=WorkflowState.RESPONSE_PROCESSING,
            workflow_id=response_processing_workflow_id,
            outbound_message_id=(
                duplicate_message.message_id if duplicate_message is not None else None
            ),
            lead_state_rerouted=reroute_result is not None,
        )

    message = plan_result.message
    assert message is not None

    if plan_result.status == PlanOutboundMessageStatus.PLANNED:
        resolved_subject = resolve_reply_email_subject(
            inbound_channel=inbound_channel,
            inbound_email_subject=inbound_email_subject,
            drafted_subject=message.subject,
        )
        if resolved_subject != message.subject:
            updated_message = await message_repository.save(
                replace(message, subject=resolved_subject, updated_at=now)
            )
            message = updated_message

    send_context = OutboundSendContext(
        campaign_status=config.campaign_status,
        workflow_state=WorkflowState.RESPONSE_PROCESSING,
        enabled_channels=(inbound_channel,),
        workspace_contact_policy=workspace_contact_policy,
        current_message_version=message.message_version,
        pre_send_policy=_pre_send_policy(workspace_contact_policy, workspace.default_timezone),
    )
    send_result = await send_outbound_message(
        workspace_id=workspace_id,
        idempotency_key=message.idempotency_key,
        context=send_context,
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        workspace_operational_control_repository=workspace_operational_control_repository,
        inbound_message_repository=inbound_message_repository,
        email_thread_anchor_inbound_message_id=inbound_message_id,
        now=now,
    )

    send_succeeded = send_result.status in {
        SendOutboundMessageStatus.SENT,
        SendOutboundMessageStatus.ALREADY_SENT,
    }
    if send_succeeded:
        waiting_outcome = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=WorkflowState.WAITING_FOR_RESPONSE,
            reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_SENT,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            external_event_id=external_event_id,
            metadata={
                "outbound_message_id": (
                    str(send_result.message.message_id) if send_result.message is not None else None
                ),
                "inbound_message_id": (
                    str(inbound_message_id) if inbound_message_id is not None else None
                ),
            },
            transition_id_factory=transition_id_factory,
        )
        if waiting_outcome.status != WorkflowStateTransitionStatus.UPDATED:
            return await _pause_after_block(
                workspace_id=workspace_id,
                lead_id=lead_id,
                workflow_id=response_processing_workflow_id,
                lead_workflow_repository=lead_workflow_repository,
                workflow_transition_repository=workflow_transition_repository,
                reason_code=WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED,
                pause_reason="ai_continuation_waiting_state_failed",
                block_explanation=waiting_outcome.skip_reason,
                reasons=(ContinueAIReasonCode.WORKFLOW_TRANSITION_FAILED,),
                now=now,
                transition_id_factory=transition_id_factory,
            )
        sent_message = send_result.message
        updated_conversation: Conversation | None = None
        if send_result.status == SendOutboundMessageStatus.SENT:
            updated_conversation = await conversation_repository.save(
                Conversation(
                    conversation_id=conversation.conversation_id,
                    workspace_id=conversation.workspace_id,
                    lead_id=conversation.lead_id,
                    created_at=conversation.created_at,
                    updated_at=now,
                    campaign_id=conversation.campaign_id,
                    workflow_id=conversation.workflow_id,
                    status=conversation.status,
                    ai_interaction_count=conversation.ai_interaction_count + 1,
                    last_message_at=conversation.last_message_at,
                )
            )
        if (
            sent_message is not None
            and crm_client is not None
            and outbound_message_crm_completion_repository is not None
        ):
            await complete_outbound_message_crm_sync(
                lead=lead,
                outbound_message=sent_message,
                crm_sync_completion_repository=outbound_message_crm_completion_repository,
                crm_client=crm_client,
                now=now,
                summary_text=(latest_summary.summary_text if latest_summary is not None else None),
                latest_inbound_text=inbound_body,
                workspace_handoff_config=workspace_handoff_config,
                snapshot_status="waiting_for_response",
            )
        waiting_workflow_id = (
            waiting_outcome.workflow.workflow_id if waiting_outcome.workflow is not None else None
        )
        return ContinueAIResult(
            status=ContinueAIStatus.SENT,
            workflow=waiting_outcome.workflow,
            conversation=updated_conversation,
            workflow_state=WorkflowState.WAITING_FOR_RESPONSE,
            ai_interaction_count_increment=(
                1 if send_result.status == SendOutboundMessageStatus.SENT else 0
            ),
            workflow_id=waiting_workflow_id,
            transition_id=waiting_outcome.transition_id,
            outbound_message_id=sent_message.message_id if sent_message is not None else None,
            provider_message_id=(
                sent_message.provider_message_id if sent_message is not None else None
            ),
            lead_state_rerouted=reroute_result is not None,
        )

    return await _pause_after_block(
        workspace_id=workspace_id,
        lead_id=lead_id,
        workflow_id=response_processing_workflow_id,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        reason_code=(
            WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_FAILED
            if send_result.status == SendOutboundMessageStatus.FAILED
            else WorkflowTransitionReasonCode.OUTBOUND_MESSAGE_BLOCKED
        ),
        pause_reason={
            SendOutboundMessageStatus.FAILED: "ai_continuation_send_failed",
            SendOutboundMessageStatus.REJECTED: "ai_continuation_send_rejected",
            SendOutboundMessageStatus.UNCERTAIN: "ai_continuation_send_uncertain",
        }.get(send_result.status, "ai_continuation_send_blocked"),
        block_explanation=f"Send blocked: {_reason_values(send_result.reasons)}.",
        reasons=(
            {
                SendOutboundMessageStatus.FAILED: ContinueAIReasonCode.SENDING_FAILED,
                SendOutboundMessageStatus.UNCERTAIN: ContinueAIReasonCode.SENDING_UNCERTAIN,
            }.get(send_result.status, ContinueAIReasonCode.SENDING_BLOCKED),
        ),
        now=now,
        transition_id_factory=transition_id_factory,
        lead_state_rerouted=reroute_result is not None,
    )


async def _pause_after_block(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow_id: UUID,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    reason_code: WorkflowTransitionReasonCode,
    pause_reason: str,
    block_explanation: str | None,
    reasons: tuple[ContinueAIReasonCode, ...],
    now: datetime,
    transition_id_factory: Callable[[], UUID] | None = None,
    lead_state_rerouted: bool = False,
) -> ContinueAIResult:
    pause_outcome = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=reason_code,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "workflow_id": str(workflow_id),
            "pause_reason": pause_reason,
            "block_explanation": block_explanation,
        },
        pause_reason=pause_reason,
        transition_id_factory=transition_id_factory,
    )
    return ContinueAIResult(
        status=ContinueAIStatus.BLOCKED,
        workflow=pause_outcome.workflow,
        workflow_state=WorkflowState.PAUSED,
        workflow_id=workflow_id,
        transition_id=pause_outcome.transition_id,
        reasons=reasons,
        block_explanation=block_explanation,
        pause_reason=pause_reason,
        lead_state_rerouted=lead_state_rerouted,
    )


async def _maybe_route_reply_before_continuation(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    inbound_body: str,
    latest_summary: ConversationSummary | None,
    lead_repository: LeadRepository,
    artifact_repository: LeadClassificationArtifactRepository | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    crm_conversation_event_repository: CrmConversationEventRepository | None,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    llm_client: LLMClient,
    now: datetime,
    default_openrouter_model: str,
    supplemental_crm_conversation_events: tuple[CrmConversationEvent, ...],
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackRepository | None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
) -> AiNurtureRouteResult | None:
    if (
        lead is None
        or artifact_repository is None
        or crm_conversation_event_repository is None
        or workspace_llm_config_repository is None
        or lead.do_not_contact
        or lead.sms_opted_out
        or lead.email_unsubscribed
    ):
        return None
    return await route_ai_nurture_lead(
        workspace_id=workspace_id,
        lead=lead,
        lead_repository=lead_repository,
        paused_search_history_repository=cast(LeadPausedSearchHistoryRepository, lead_repository),
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        now=now,
        default_openrouter_model=default_openrouter_model,
        conversation_summary=(
            latest_summary.summary_text if latest_summary is not None else inbound_body
        ),
        supplemental_crm_conversation_events=supplemental_crm_conversation_events,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        routing_review_repository=routing_review_repository,
    )


def _resolve_continuation_step(
    config: CampaignExecutionConfig,
    current_step_id: UUID | None,
) -> CampaignCadenceStep | None:
    if current_step_id is not None:
        for step in config.cadence_steps:
            if step.cadence_step_id == current_step_id:
                return step
    return config.cadence_steps[0] if config.cadence_steps else None


def _pre_send_policy(
    workspace_contact_policy: WorkspaceContactPolicy,
    timezone: str,
) -> PreSendPolicy:
    if not workspace_contact_policy.quiet_hours_enabled:
        return PreSendPolicy(
            allowed_send_start_hour=0,
            allowed_send_end_hour=24,
            timezone=timezone,
        )
    quiet_hours_start = workspace_contact_policy.quiet_hours_start
    quiet_hours_end = workspace_contact_policy.quiet_hours_end
    return PreSendPolicy(
        allowed_send_start_hour=quiet_hours_start.hour if quiet_hours_start else 10,
        allowed_send_end_hour=quiet_hours_end.hour if quiet_hours_end else 17,
        timezone=timezone,
    )


def _reason_values(reasons: tuple[StrEnum, ...]) -> str:
    return ", ".join(reason.value for reason in reasons)
