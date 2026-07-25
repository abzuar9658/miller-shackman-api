from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from secrets import token_hex
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    LeadRepository,
    OutboundMessageRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOutboundDraftingConfigRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    OutboundMessageDraftReasonCode,
    OutboundMessageDraftResult,
    OutboundMessageDraftStatus,
    draft_outbound_message,
)
from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_openrouter_model,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import (
    PreSendDecision,
    PreSendFacts,
    PreSendPolicy,
    PreSendReasonCode,
    ProviderSendStatus,
    ScheduledMessageStatus,
    WorkflowState,
    evaluate_pre_send_safety,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config


class PlanOutboundMessageStatus(StrEnum):
    PLANNED = "planned"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


class PlanOutboundMessageReasonCode(StrEnum):
    LEAD_NOT_FOUND = "lead_not_found"
    NO_ENABLED_CHANNELS = "no_enabled_channels"
    CHANNEL_DESTINATION_MISSING = "channel_destination_missing"
    CHANNEL_NOT_CONTACTABLE = "channel_not_contactable"
    PRE_SEND_BLOCKED = "pre_send_blocked"
    DRAFT_REJECTED = "draft_rejected"
    DUPLICATE_PLAN = "duplicate_plan"


class ChannelEvaluationOutcome(StrEnum):
    SELECTED = "selected"
    DUPLICATE = "duplicate"
    MISSING_DESTINATION = "missing_destination"
    NOT_CONTACTABLE = "not_contactable"
    PRE_SEND_BLOCKED = "pre_send_blocked"


@dataclass(frozen=True)
class ChannelEvaluation:
    channel: ContactChannel
    outcome: ChannelEvaluationOutcome
    reasons: tuple[PlanOutboundMessageReasonCode, ...] = ()
    pre_send_reasons: tuple[PreSendReasonCode, ...] = ()
    next_allowed_at: datetime | None = None


@dataclass(frozen=True)
class OutboundPlanningContext:
    campaign_status: CampaignStatus
    workflow_state: WorkflowState
    enabled_channels: tuple[ContactChannel, ...]
    workspace_contact_policy: WorkspaceContactPolicy
    campaign_goal: str
    brokerage_name: str
    cadence_step_id: str
    assigned_agent_name: str | None = None
    scheduled_for: datetime | None = None
    message_version: int = 1
    pre_send_policy: PreSendPolicy = field(default_factory=PreSendPolicy)
    lead_context: ApprovedOutboundLeadContext = field(default_factory=ApprovedOutboundLeadContext)
    preflight_vetoed: bool = False
    handoff_active: bool = False
    human_owned: bool = False
    lead_replied_since_scheduled: bool = False
    recent_human_activity: bool = False
    ownership_changed: bool = False
    last_global_outreach_at: datetime | None = None
    last_campaign_outreach_at: datetime | None = None
    last_channel_outreach_at: datetime | None = None
    other_channel_sent_at: datetime | None = None


@dataclass(frozen=True)
class PlanOutboundMessageResult:
    status: PlanOutboundMessageStatus
    message: OutboundMessage | None = None
    selected_channel: ContactChannel | None = None
    pre_send_decision: PreSendDecision | None = None
    draft_result: OutboundMessageDraftResult | None = None
    reasons: tuple[PlanOutboundMessageReasonCode, ...] = ()
    draft_reasons: tuple[OutboundMessageDraftReasonCode, ...] = ()
    channel_evaluations: tuple[ChannelEvaluation, ...] = ()


async def plan_outbound_message(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    context: OutboundPlanningContext,
    lead_repository: LeadRepository,
    message_repository: OutboundMessageRepository,
    llm_client: LLMClient,
    now: datetime,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    message_id_factory: Callable[[], UUID] | None = None,
) -> PlanOutboundMessageResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=(PlanOutboundMessageReasonCode.LEAD_NOT_FOUND,),
        )

    return await plan_outbound_message_for_lead_record(
        lead=lead,
        campaign_id=campaign_id,
        context=context,
        message_repository=message_repository,
        llm_client=llm_client,
        now=now,
        workspace_llm_config_repository=workspace_llm_config_repository,
        workspace_outbound_drafting_config_repository=workspace_outbound_drafting_config_repository,
        default_openrouter_model=default_openrouter_model,
        message_id_factory=message_id_factory,
    )


async def plan_outbound_message_for_lead_record(
    *,
    lead: CanonicalLeadRecord,
    campaign_id: CampaignId,
    context: OutboundPlanningContext,
    message_repository: OutboundMessageRepository,
    llm_client: LLMClient,
    now: datetime,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository
    | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    message_id_factory: Callable[[], UUID] | None = None,
) -> PlanOutboundMessageResult:
    workspace_id = lead.workspace_id
    lead_id = lead.lead_id

    if not context.enabled_channels:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=(PlanOutboundMessageReasonCode.NO_ENABLED_CHANNELS,),
        )

    selected = await _select_channel(
        workspace_id=workspace_id,
        lead=lead,
        campaign_id=campaign_id,
        context=context,
        message_repository=message_repository,
        now=now,
    )
    if selected.duplicate_message is not None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.DUPLICATE,
            message=selected.duplicate_message,
            selected_channel=selected.channel,
            pre_send_decision=selected.pre_send_decision,
            reasons=(PlanOutboundMessageReasonCode.DUPLICATE_PLAN,),
            channel_evaluations=selected.evaluations,
        )
    if selected.channel is None or selected.pre_send_decision is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=tuple(dict.fromkeys(selected.reasons)),
            channel_evaluations=selected.evaluations,
        )

    openrouter_model = await resolve_workspace_openrouter_model(
        workspace_id=workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )
    drafting_config = default_workspace_outbound_drafting_config(workspace_id)
    if workspace_outbound_drafting_config_repository is not None:
        drafting_config = (
            await workspace_outbound_drafting_config_repository.get_by_workspace_id(workspace_id)
        ) or drafting_config

    draft_result = await draft_outbound_message(
        lead=lead,
        channel=selected.channel,
        campaign_goal=context.campaign_goal,
        brokerage_name=context.brokerage_name,
        assigned_agent_name=context.assigned_agent_name,
        lead_context=context.lead_context,
        llm_client=llm_client,
        drafting_config=drafting_config,
        model=openrouter_model,
    )
    if draft_result.status != OutboundMessageDraftStatus.DRAFTED or draft_result.body is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            selected_channel=selected.channel,
            pre_send_decision=selected.pre_send_decision,
            draft_result=draft_result,
            reasons=(PlanOutboundMessageReasonCode.DRAFT_REJECTED,),
            draft_reasons=draft_result.reasons,
            channel_evaluations=selected.evaluations,
        )

    idempotency_key = _outbound_idempotency_key(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        cadence_step_id=context.cadence_step_id,
        channel=selected.channel,
        message_version=selected.message_version,
    )
    message = OutboundMessage(
        message_id=(message_id_factory or uuid4)(),
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        cadence_step_id=context.cadence_step_id,
        channel=selected.channel,
        status=OutboundMessageStatus.PENDING,
        idempotency_key=idempotency_key,
        body=draft_result.body,
        subject=draft_result.subject,
        scheduled_for=context.scheduled_for,
        planned_at=now,
        created_at=now,
        updated_at=now,
        message_version=selected.message_version,
        reply_routing_token=(token_hex(16) if selected.channel == ContactChannel.EMAIL else None),
        draft_prompt_version=draft_result.prompt_version,
        draft_model=draft_result.model,
        draft_latency_ms=draft_result.latency_ms,
        draft_usage_tokens=draft_result.usage_tokens,
        draft_confidence=draft_result.confidence,
        draft_personalization_notes=draft_result.personalization_notes,
        draft_safety_flags=draft_result.safety_flags,
    )

    saved = await message_repository.save(message)
    return PlanOutboundMessageResult(
        status=PlanOutboundMessageStatus.PLANNED,
        message=saved,
        selected_channel=selected.channel,
        pre_send_decision=selected.pre_send_decision,
        draft_result=draft_result,
        channel_evaluations=selected.evaluations,
    )


@dataclass(frozen=True)
class _ChannelSelection:
    channel: ContactChannel | None
    message_version: int = 1
    pre_send_decision: PreSendDecision | None = None
    duplicate_message: OutboundMessage | None = None
    reasons: tuple[PlanOutboundMessageReasonCode, ...] = ()
    evaluations: tuple[ChannelEvaluation, ...] = ()


async def _select_channel(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    campaign_id: CampaignId,
    context: OutboundPlanningContext,
    message_repository: OutboundMessageRepository,
    now: datetime,
) -> _ChannelSelection:
    rejection_reasons: list[PlanOutboundMessageReasonCode] = []
    evaluations: list[ChannelEvaluation] = []
    contactability_facts = contactability_facts_from_canonical_lead(lead)
    existing_messages = await message_repository.list_for_lead(workspace_id, lead.lead_id)
    for channel in context.enabled_channels:
        if not _has_destination_for_channel(lead, channel):
            rejection_reasons.append(PlanOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING)
            evaluations.append(
                ChannelEvaluation(
                    channel=channel,
                    outcome=ChannelEvaluationOutcome.MISSING_DESTINATION,
                    reasons=(PlanOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING,),
                )
            )
            continue

        contactability_decision = evaluate_contactability(
            contactability_facts,
            context.workspace_contact_policy,
            channel,
        )
        message_version = _message_version_for_channel(
            campaign_id=campaign_id,
            cadence_step_id=context.cadence_step_id,
            channel=channel,
            requested_message_version=context.message_version,
            existing_messages=existing_messages,
        )
        pre_send_decision = evaluate_pre_send_safety(
            PreSendFacts(
                channel=channel,
                campaign_status=context.campaign_status,
                workflow_state=context.workflow_state,
                message_status=ScheduledMessageStatus.PENDING,
                provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
                scheduled_message_version=message_version,
                current_message_version=message_version,
                channel_enabled=True,
                contactability_decision=contactability_decision,
                preflight_vetoed=context.preflight_vetoed,
                handoff_active=context.handoff_active,
                human_owned=context.human_owned,
                lead_replied_since_scheduled=context.lead_replied_since_scheduled,
                recent_human_activity=context.recent_human_activity,
                ownership_changed=context.ownership_changed,
                last_global_outreach_at=context.last_global_outreach_at,
                last_campaign_outreach_at=context.last_campaign_outreach_at,
                last_channel_outreach_at=context.last_channel_outreach_at,
                other_channel_sent_at=context.other_channel_sent_at,
            ),
            context.pre_send_policy,
            now,
        )
        if not contactability_decision.allowed:
            rejection_reasons.append(PlanOutboundMessageReasonCode.CHANNEL_NOT_CONTACTABLE)
            evaluations.append(
                ChannelEvaluation(
                    channel=channel,
                    outcome=ChannelEvaluationOutcome.NOT_CONTACTABLE,
                    reasons=(PlanOutboundMessageReasonCode.CHANNEL_NOT_CONTACTABLE,),
                )
            )
            continue
        if not pre_send_decision.allowed:
            rejection_reasons.append(PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED)
            evaluations.append(
                ChannelEvaluation(
                    channel=channel,
                    outcome=ChannelEvaluationOutcome.PRE_SEND_BLOCKED,
                    reasons=(PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED,),
                    pre_send_reasons=pre_send_decision.reasons,
                    next_allowed_at=pre_send_decision.next_allowed_at,
                )
            )
            continue

        idempotency_key = _outbound_idempotency_key(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            lead_id=lead.lead_id,
            cadence_step_id=context.cadence_step_id,
            channel=channel,
            message_version=message_version,
        )
        existing = await message_repository.get_by_idempotency_key(workspace_id, idempotency_key)
        if existing is not None:
            return _ChannelSelection(
                channel=channel,
                message_version=message_version,
                pre_send_decision=pre_send_decision,
                duplicate_message=existing,
                evaluations=tuple(
                    [
                        *evaluations,
                        ChannelEvaluation(
                            channel=channel,
                            outcome=ChannelEvaluationOutcome.DUPLICATE,
                            reasons=(PlanOutboundMessageReasonCode.DUPLICATE_PLAN,),
                        ),
                    ]
                ),
            )
        return _ChannelSelection(
            channel=channel,
            message_version=message_version,
            pre_send_decision=pre_send_decision,
            evaluations=tuple(
                [
                    *evaluations,
                    ChannelEvaluation(
                        channel=channel,
                        outcome=ChannelEvaluationOutcome.SELECTED,
                    ),
                ]
            ),
        )

    return _ChannelSelection(
        channel=None,
        reasons=tuple(rejection_reasons),
        evaluations=tuple(evaluations),
    )


def _has_destination_for_channel(
    lead: CanonicalLeadRecord,
    channel: ContactChannel,
) -> bool:
    if channel == ContactChannel.SMS:
        return lead.has_sms_capable_phone and lead.primary_phone is not None
    return lead.has_email and lead.primary_email is not None


def _message_version_for_channel(
    *,
    campaign_id: CampaignId,
    cadence_step_id: str,
    channel: ContactChannel,
    requested_message_version: int,
    existing_messages: tuple[OutboundMessage, ...],
) -> int:
    relevant_messages = tuple(
        message
        for message in existing_messages
        if message.campaign_id == campaign_id
        and message.cadence_step_id == cadence_step_id
        and message.channel == channel
    )
    if not relevant_messages:
        return requested_message_version

    latest_message = max(
        relevant_messages,
        key=lambda message: (message.message_version, message.updated_at, message.created_at),
    )
    if latest_message.status == OutboundMessageStatus.FAILED:
        return max(requested_message_version, latest_message.message_version + 1)
    return max(requested_message_version, latest_message.message_version)


def _outbound_idempotency_key(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    lead_id: LeadId,
    cadence_step_id: str,
    channel: ContactChannel,
    message_version: int,
) -> str:
    return (
        "outbound:"
        f"{workspace_id}:{campaign_id}:{lead_id}:{cadence_step_id}:{channel.value}:v{message_version}"
    )
