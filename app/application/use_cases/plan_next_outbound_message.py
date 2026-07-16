from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityRepository
from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    CrmConversationEventRepository,
    LeadRepository,
    OutboundMessageRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.services.canonical_lead_inputs import (
    approved_outbound_context_from_canonical_lead,
)
from app.application.services.listing_context_enrichment import (
    maybe_enrich_outbound_lead_context,
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
from app.domain.conversations import CrmConversationEvent

OUTBOUND_CONTEXT_ACTIVITY_HISTORY_LIMIT = 24


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
    activity_items: tuple[LeadActivityItem, ...] = ()


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
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    lead_activity_repository: LeadActivityRepository | None = None,
    crm_conversation_event_repository: CrmConversationEventRepository | None = None,
    listing_source_repository: ListingSourceRepository | None = None,
    listing_snapshot_repository: ListingSnapshotRepository | None = None,
    listing_search_client: ListingSearchClient | None = None,
    listing_enrichment_enabled: bool = False,
    listing_cache_ttl: timedelta = timedelta(hours=6),
    listing_max_results: int = 3,
    message_id_factory: Callable[[], UUID] | None = None,
) -> PlanOutboundMessageResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PlanOutboundMessageResult(
            status=PlanOutboundMessageStatus.REJECTED,
            reasons=(PlanOutboundMessageReasonCode.LEAD_NOT_FOUND,),
        )

    activity_items = context.activity_items
    if not activity_items and lead_activity_repository is not None:
        activity_items = await lead_activity_repository.list_for_lead(
            workspace_id,
            lead_id,
            limit=OUTBOUND_CONTEXT_ACTIVITY_HISTORY_LIMIT,
        )

    crm_conversation_events: tuple[CrmConversationEvent, ...] = ()
    if not activity_items and crm_conversation_event_repository is not None:
        crm_conversation_events = await crm_conversation_event_repository.list_for_lead(
            workspace_id,
            lead_id,
            limit=OUTBOUND_CONTEXT_ACTIVITY_HISTORY_LIMIT,
        )

    lead_context = approved_outbound_context_from_canonical_lead(
        lead,
        now=now,
        conversation_summary=context.conversation_summary,
        latest_lead_request=context.latest_lead_request,
        extracted_preferences=context.extracted_preferences,
        allowed_mapped_custom_field_keys=context.allowed_mapped_custom_field_keys,
        activity_items=activity_items,
        crm_conversation_events=crm_conversation_events,
    )
    lead_context = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=lead_context,
        now=now,
        enrichment_enabled=listing_enrichment_enabled,
        cache_ttl=listing_cache_ttl,
        max_results=listing_max_results,
        source_repository=listing_source_repository,
        snapshot_repository=listing_snapshot_repository,
        listing_search_client=listing_search_client,
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
        lead_context=lead_context,
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
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
        message_id_factory=message_id_factory,
    )
