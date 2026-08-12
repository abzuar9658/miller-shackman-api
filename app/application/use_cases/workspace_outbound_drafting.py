import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.ports.listing_search import ListingSearchClient
from app.application.ports.listing_sources import ListingSnapshotRepository, ListingSourceRepository
from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    WorkspaceLLMConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOutboundDraftingConfigRepository,
    WorkspaceRepository,
)
from app.application.services.dormant_step_drafting import (
    apply_dormant_step_drafting_profile,
)
from app.application.services.listing_context_enrichment import (
    maybe_enrich_outbound_lead_context,
)
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    OutboundMessageDraftResult,
    build_listing_relevance_brief_payload,
    draft_outbound_message,
)
from app.application.services.llm.outbound_query_extraction import (
    OutboundQueryExtractionMethod,
    OutboundQueryExtractionReasonCode,
    build_outbound_context_with_query_extraction,
)
from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_llm_config,
    workspace_llm_selection_for_task,
)
from app.application.use_cases.authentication import AuthReasonCode
from app.application.use_cases.workspace import _actor_for_workspace
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.leads import CanonicalLeadRecord, CRMProvider, LeadType
from app.domain.llm import LLMTaskKind
from app.domain.outbound_drafting import (
    DormantStepTemplateProfile,
    OutboundJourneyKind,
    WorkspaceOutboundDraftingConfig,
    default_workspace_outbound_drafting_config,
)


class OutboundDraftingPreviewStatus(StrEnum):
    PREVIEWED = "previewed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class OutboundDraftPreview:
    status: str
    body: str | None
    subject: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class OutboundDraftingPreviewResult:
    status: OutboundDraftingPreviewStatus
    parsed_preferences: dict[str, str] | None = None
    lead_context: ApprovedOutboundLeadContext | None = None
    extraction_method: OutboundQueryExtractionMethod = OutboundQueryExtractionMethod.FALLBACK
    extraction_confidence: float | None = None
    extraction_reasons: tuple[OutboundQueryExtractionReasonCode, ...] = ()
    sms_preview: OutboundDraftPreview | None = None
    email_preview: OutboundDraftPreview | None = None
    listing_relevance_brief: dict[str, object] | None = None
    reasons: tuple[AuthReasonCode, ...] = ()


async def preview_workspace_outbound_drafting(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    query: str,
    agent_name: str | None = None,
    brokerage_name: str | None = None,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    workspace_outbound_drafting_config_repository: WorkspaceOutboundDraftingConfigRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository | None,
    llm_client: LLMClient,
    listing_source_repository: ListingSourceRepository | None,
    listing_snapshot_repository: ListingSnapshotRepository | None,
    listing_search_client: ListingSearchClient | None,
    listing_cache_ttl: timedelta = timedelta(hours=1),
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    drafting_config: WorkspaceOutboundDraftingConfig | None = None,
    journey_kind: OutboundJourneyKind | None = None,
    template_profile: DormantStepTemplateProfile | None = None,
    template_channel: ContactChannel | None = None,
    campaign_goal: str = "Preview outbound response to a live user property query.",
) -> OutboundDraftingPreviewResult:
    effective_actor = await _actor_for_workspace(
        actor=actor,
        workspace_id=workspace_id,
        workspace_repository=workspace_repository,
        membership_repository=membership_repository,
    )
    if effective_actor is None:
        return OutboundDraftingPreviewResult(
            status=OutboundDraftingPreviewStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_MEMBERSHIP_NOT_FOUND,),
        )
    permission = evaluate_permission(
        effective_actor,
        PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
    )
    if not permission.allowed:
        return OutboundDraftingPreviewResult(
            status=OutboundDraftingPreviewStatus.REJECTED,
            reasons=(AuthReasonCode.PERMISSION_DENIED,),
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return OutboundDraftingPreviewResult(
            status=OutboundDraftingPreviewStatus.REJECTED,
            reasons=(AuthReasonCode.WORKSPACE_NOT_FOUND,),
        )
    resolved_agent_name = _normalized_preview_value(agent_name)
    resolved_brokerage_name = _normalized_preview_value(brokerage_name) or workspace.name

    if drafting_config is None:
        drafting_config = (
            await workspace_outbound_drafting_config_repository.get_by_workspace_id(workspace_id)
        ) or default_workspace_outbound_drafting_config(workspace_id)
    llm_config = await resolve_workspace_llm_config(
        workspace_id=workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )
    classification_selection = workspace_llm_selection_for_task(
        llm_config, LLMTaskKind.CLASSIFICATION
    )
    drafting_selection = workspace_llm_selection_for_task(llm_config, LLMTaskKind.DRAFTING)
    lead = _preview_lead(workspace_id=workspace_id, query=query, now=now)
    extraction = await build_outbound_context_with_query_extraction(
        lead=lead,
        now=now,
        activity_items=(
            LeadActivityItem(
                activity_id=uuid4(),
                lead_id=lead.lead_id,
                kind=LeadActivityKind.INBOUND_MESSAGE,
                occurred_at=now,
                title="Inbound message",
                preview=query,
                content=query,
                channel="email",
                direction="inbound",
                actor_name="lead",
            ),
        ),
        enabled_query_extraction_fields=drafting_config.enabled_extraction_fields,
        llm_client=llm_client,
        model=classification_selection.model,
        provider=classification_selection.provider,
    )
    lead_context = extraction.lead_context
    lead_context = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=lead_context,
        now=now,
        enrichment_enabled=True,
        cache_ttl=listing_cache_ttl,
        max_results=3,
        source_repository=listing_source_repository,
        snapshot_repository=listing_snapshot_repository,
        listing_search_client=listing_search_client,
    )
    if template_profile is not None and template_channel is not None:
        drafting_config, lead_context = apply_dormant_step_drafting_profile(
            drafting_config=drafting_config,
            lead_context=lead_context,
            template_profile=template_profile,
            channel=template_channel.value,
        )
    sms_result: OutboundMessageDraftResult | None = None
    email_result: OutboundMessageDraftResult | None = None
    if template_channel is None:
        sms_result, email_result = await asyncio.gather(
            draft_outbound_message(
                lead=lead,
                channel=ContactChannel.SMS,
                campaign_goal=campaign_goal,
                brokerage_name=resolved_brokerage_name,
                assigned_agent_name=resolved_agent_name,
                lead_context=lead_context,
                journey_kind=journey_kind,
                llm_client=llm_client,
                drafting_config=drafting_config,
                model=drafting_selection.model,
                provider=drafting_selection.provider,
            ),
            draft_outbound_message(
                lead=lead,
                channel=ContactChannel.EMAIL,
                campaign_goal=campaign_goal,
                brokerage_name=resolved_brokerage_name,
                assigned_agent_name=resolved_agent_name,
                lead_context=lead_context,
                journey_kind=journey_kind,
                llm_client=llm_client,
                drafting_config=drafting_config,
                model=drafting_selection.model,
                provider=drafting_selection.provider,
            ),
        )
    elif template_channel == ContactChannel.SMS:
        sms_result = await draft_outbound_message(
            lead=lead,
            channel=ContactChannel.SMS,
            campaign_goal=campaign_goal,
            brokerage_name=resolved_brokerage_name,
            assigned_agent_name=resolved_agent_name,
            lead_context=lead_context,
            journey_kind=journey_kind,
            llm_client=llm_client,
            drafting_config=drafting_config,
            model=drafting_selection.model,
            provider=drafting_selection.provider,
        )
    else:
        email_result = await draft_outbound_message(
            lead=lead,
            channel=ContactChannel.EMAIL,
            campaign_goal=campaign_goal,
            brokerage_name=resolved_brokerage_name,
            assigned_agent_name=resolved_agent_name,
            lead_context=lead_context,
            journey_kind=journey_kind,
            llm_client=llm_client,
            drafting_config=drafting_config,
            model=drafting_selection.model,
            provider=drafting_selection.provider,
        )
    listing_relevance_brief = build_listing_relevance_brief_payload(lead_context.listing_context)
    return OutboundDraftingPreviewResult(
        status=OutboundDraftingPreviewStatus.PREVIEWED,
        parsed_preferences=dict(lead_context.extracted_preferences),
        lead_context=lead_context,
        extraction_method=extraction.method,
        extraction_confidence=extraction.confidence,
        extraction_reasons=extraction.reasons,
        sms_preview=_preview_from_draft(sms_result),
        email_preview=_preview_from_draft(email_result),
        listing_relevance_brief=listing_relevance_brief,
    )


def _preview_from_draft(
    result: OutboundMessageDraftResult | None,
) -> OutboundDraftPreview | None:
    if result is None:
        return None
    return OutboundDraftPreview(
        status=result.status.value,
        body=result.body,
        subject=result.subject,
        prompt_version=result.prompt_version,
        model=result.model,
        reasons=tuple(reason.value for reason in result.reasons),
    )


def _normalized_preview_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _preview_lead(*, workspace_id: WorkspaceId, query: str, now: datetime) -> CanonicalLeadRecord:
    normalized = query.lower()
    lead_source = "Preview inquiry"
    if any(term in normalized for term in ("rent", "rental", "lease")):
        lead_source = "Preview rental inquiry"
    elif any(term in normalized for term in ("buy", "sale", "purchase")):
        lead_source = "Preview sale inquiry"
    return CanonicalLeadRecord(
        workspace_id=workspace_id,
        lead_id=uuid4(),
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="preview-query",
        facts_derived_at=now,
        source_payload_version="preview:v1",
        lead_type=LeadType.BUYER,
        lead_source=lead_source,
        lead_stage="preview",
        latest_property_context_present=True,
    )
