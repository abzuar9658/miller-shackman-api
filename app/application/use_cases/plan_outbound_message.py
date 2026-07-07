from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import LeadRepository, OutboundMessageRepository
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    OutboundMessageDraftReasonCode,
    OutboundMessageDraftResult,
    OutboundMessageDraftStatus,
    draft_outbound_message,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import (
    PreSendDecision,
    PreSendFacts,
    PreSendPolicy,
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
    message_id_factory: Callable[[], UUID] | None = None,
) -> PlanOutboundMessageResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=(PlanOutboundMessageReasonCode.LEAD_NOT_FOUND,),
        )

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
        )
    if selected.channel is None or selected.pre_send_decision is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=tuple(dict.fromkeys(selected.reasons)),
        )

    draft_result = await draft_outbound_message(
        lead=lead,
        channel=selected.channel,
        campaign_goal=context.campaign_goal,
        brokerage_name=context.brokerage_name,
        assigned_agent_name=context.assigned_agent_name,
        lead_context=context.lead_context,
        llm_client=llm_client,
    )
    if draft_result.status != OutboundMessageDraftStatus.DRAFTED or draft_result.body is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            selected_channel=selected.channel,
            pre_send_decision=selected.pre_send_decision,
            draft_result=draft_result,
            reasons=(PlanOutboundMessageReasonCode.DRAFT_REJECTED,),
            draft_reasons=draft_result.reasons,
        )

    idempotency_key = _outbound_idempotency_key(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        lead_id=lead_id,
        cadence_step_id=context.cadence_step_id,
        channel=selected.channel,
        message_version=context.message_version,
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
        message_version=context.message_version,
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
    )


@dataclass(frozen=True)
class _ChannelSelection:
    channel: ContactChannel | None
    pre_send_decision: PreSendDecision | None = None
    duplicate_message: OutboundMessage | None = None
    reasons: tuple[PlanOutboundMessageReasonCode, ...] = ()


async def _select_channel(
    *,
    workspace_id: WorkspaceId,
    lead: object,
    campaign_id: CampaignId,
    context: OutboundPlanningContext,
    message_repository: OutboundMessageRepository,
    now: datetime,
) -> _ChannelSelection:
    from app.domain.leads import CanonicalLeadRecord

    if not isinstance(lead, CanonicalLeadRecord):
        raise TypeError("lead must be CanonicalLeadRecord")

    rejection_reasons: list[PlanOutboundMessageReasonCode] = []
    contactability_facts = contactability_facts_from_canonical_lead(lead)
    for channel in context.enabled_channels:
        if not _has_destination_for_channel(lead, channel):
            rejection_reasons.append(PlanOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING)
            continue

        contactability_decision = evaluate_contactability(
            contactability_facts,
            context.workspace_contact_policy,
            channel,
        )
        pre_send_decision = evaluate_pre_send_safety(
            PreSendFacts(
                channel=channel,
                campaign_status=context.campaign_status,
                workflow_state=context.workflow_state,
                message_status=ScheduledMessageStatus.PENDING,
                provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
                scheduled_message_version=context.message_version,
                current_message_version=context.message_version,
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
            continue
        if not pre_send_decision.allowed:
            rejection_reasons.append(PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED)
            continue

        idempotency_key = _outbound_idempotency_key(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            lead_id=lead.lead_id,
            cadence_step_id=context.cadence_step_id,
            channel=channel,
            message_version=context.message_version,
        )
        existing = await message_repository.get_by_idempotency_key(workspace_id, idempotency_key)
        if existing is not None:
            return _ChannelSelection(
                channel=channel,
                pre_send_decision=pre_send_decision,
                duplicate_message=existing,
            )
        return _ChannelSelection(channel=channel, pre_send_decision=pre_send_decision)

    return _ChannelSelection(
        channel=None,
        reasons=tuple(rejection_reasons),
    )


def _has_destination_for_channel(lead: object, channel: ContactChannel) -> bool:
    from app.domain.leads import CanonicalLeadRecord

    if not isinstance(lead, CanonicalLeadRecord):
        raise TypeError("lead must be CanonicalLeadRecord")
    if channel == ContactChannel.SMS:
        return lead.has_sms_capable_phone and lead.primary_phone is not None
    return lead.has_email and lead.primary_email is not None


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
