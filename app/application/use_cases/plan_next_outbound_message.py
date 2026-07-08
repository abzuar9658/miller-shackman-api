from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import LeadRepository, OutboundMessageRepository
from app.application.services.canonical_lead_inputs import (
    approved_outbound_context_from_canonical_lead,
)
from app.application.use_cases.plan_outbound_message import (
    OutboundPlanningContext,
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageResult,
    PlanOutboundMessageStatus,
    plan_outbound_message_for_lead_record,
)
from app.domain.campaigns.pre_send import PreSendPolicy, WorkflowState
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel, WorkspaceContactPolicy


def _empty_preferences() -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class PlanNextOutboundMessageContext:
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
    conversation_summary: str | None = None
    latest_lead_request: str | None = None
    extracted_preferences: Mapping[str, str] = field(default_factory=_empty_preferences)
    allowed_mapped_custom_field_keys: tuple[str, ...] = ()


async def plan_next_outbound_message_for_lead(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    context: PlanNextOutboundMessageContext,
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

    planning_context = OutboundPlanningContext(
        campaign_status=context.campaign_status,
        workflow_state=context.workflow_state,
        enabled_channels=context.enabled_channels,
        workspace_contact_policy=context.workspace_contact_policy,
        campaign_goal=context.campaign_goal,
        brokerage_name=context.brokerage_name,
        cadence_step_id=context.cadence_step_id,
        assigned_agent_name=context.assigned_agent_name,
        scheduled_for=context.scheduled_for,
        message_version=context.message_version,
        pre_send_policy=context.pre_send_policy,
        lead_context=approved_outbound_context_from_canonical_lead(
            lead,
            now=now,
            conversation_summary=context.conversation_summary,
            latest_lead_request=context.latest_lead_request,
            extracted_preferences=context.extracted_preferences,
            allowed_mapped_custom_field_keys=context.allowed_mapped_custom_field_keys,
        ),
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
    )

    return await plan_outbound_message_for_lead_record(
        lead=lead,
        campaign_id=campaign_id,
        context=planning_context,
        message_repository=message_repository,
        llm_client=llm_client,
        now=now,
        message_id_factory=message_id_factory,
    )