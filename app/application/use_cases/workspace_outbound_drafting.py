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
from app.application.services.canonical_lead_inputs import (
    approved_outbound_context_from_canonical_lead,
)
from app.application.services.listing_context_enrichment import (
    maybe_enrich_outbound_lead_context,
)
from app.application.services.llm.outbound_message_drafting import (
    ApprovedOutboundLeadContext,
    OutboundMessageDraftResult,
    build_listing_relevance_brief,
    draft_outbound_message,
)
from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_openrouter_model,
)
from app.application.use_cases.authentication import AuthReasonCode
from app.application.use_cases.workspace import _actor_for_workspace
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.leads import CanonicalLeadRecord, CRMProvider, LeadType
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config


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


@dataclass(frozen=True)
class OutboundDraftingPreviewResult:
    status: OutboundDraftingPreviewStatus
    parsed_preferences: dict[str, str] | None = None
    lead_context: ApprovedOutboundLeadContext | None = None
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
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
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

    drafting_config = (
        await workspace_outbound_drafting_config_repository.get_by_workspace_id(workspace_id)
    ) or default_workspace_outbound_drafting_config(workspace_id)
    lead = _preview_lead(workspace_id=workspace_id, query=query, now=now)
    lead_context = approved_outbound_context_from_canonical_lead(
        lead,
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
    )
    lead_context = await maybe_enrich_outbound_lead_context(
        lead=lead,
        lead_context=lead_context,
        now=now,
        enrichment_enabled=True,
        cache_ttl=timedelta(0),
        max_results=3,
        source_repository=listing_source_repository,
        snapshot_repository=listing_snapshot_repository,
        listing_search_client=listing_search_client,
        bypass_cache=True,
    )
    model = await resolve_workspace_openrouter_model(
        workspace_id=workspace_id,
        workspace_llm_config_repository=workspace_llm_config_repository,
        default_openrouter_model=default_openrouter_model,
    )
    sms_result, email_result = await asyncio.gather(
        draft_outbound_message(
            lead=lead,
            channel=ContactChannel.SMS,
            campaign_goal="Preview outbound response to a live user property query.",
            brokerage_name=resolved_brokerage_name,
            assigned_agent_name=resolved_agent_name,
            lead_context=lead_context,
            llm_client=llm_client,
            drafting_config=drafting_config,
            model=model,
        ),
        draft_outbound_message(
            lead=lead,
            channel=ContactChannel.EMAIL,
            campaign_goal="Preview outbound response to a live user property query.",
            brokerage_name=resolved_brokerage_name,
            assigned_agent_name=resolved_agent_name,
            lead_context=lead_context,
            llm_client=llm_client,
            drafting_config=drafting_config,
            model=model,
        ),
    )
    listing_relevance_brief = None
    if lead_context.listing_context is not None:
        brief = build_listing_relevance_brief(lead_context.listing_context)
        listing_relevance_brief = {
            "search_basis": brief.search_basis,
            "match_count": brief.match_count,
            "matching_areas": list(brief.matching_areas),
            "matching_property_types": list(brief.matching_property_types),
            "budget_alignment_note": brief.budget_alignment_note,
            "safe_talking_point": brief.safe_talking_point,
            "safe_cta": brief.safe_cta,
        }
    return OutboundDraftingPreviewResult(
        status=OutboundDraftingPreviewStatus.PREVIEWED,
        parsed_preferences=dict(lead_context.extracted_preferences),
        lead_context=lead_context,
        sms_preview=_preview_from_draft(sms_result),
        email_preview=_preview_from_draft(email_result),
        listing_relevance_brief=listing_relevance_brief,
    )


def _preview_from_draft(result: OutboundMessageDraftResult) -> OutboundDraftPreview:
    return OutboundDraftPreview(
        status=result.status.value,
        body=result.body,
        subject=result.subject,
        prompt_version=result.prompt_version,
        model=result.model,
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
