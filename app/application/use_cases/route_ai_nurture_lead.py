from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    CrmConversationEventRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.services.lead_routing_review import (
    create_or_refresh_pending_routing_review,
    supersede_pending_routing_reviews_for_lead,
)
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    LeadStateClassificationStatus,
)
from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationResult,
    _merge_crm_conversation_events,
    apply_lead_state_classification,
)
from app.domain.common.ids import WorkspaceId
from app.domain.conversations import CrmConversationEvent
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationArtifact,
    LeadStateClassificationOutcome,
)


class AiNurtureRoute(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"
    HUMAN_HANDOFF = "human_handoff"
    REVIEW_HOLD = "review_hold"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class AiNurtureRouteResult:
    route: AiNurtureRoute
    reason_codes: tuple[str, ...] = ()
    classification_result: LeadStateClassificationResult | None = None
    artifact: LeadClassificationArtifact | None = None
    has_recent_crm_conversation_context: bool = False


async def route_ai_nurture_lead(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    artifact_repository: LeadClassificationArtifactRepository,
    crm_conversation_event_repository: CrmConversationEventRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    dormant_threshold_days: int | None = None,
    conversation_summary: str | None = None,
    supplemental_crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    paused_search_track_repository: PausedSearchTrackRepository | None = None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    routing_review_repository: LeadRoutingReviewRepository | None = None,
) -> AiNurtureRouteResult:
    if _lead_is_hard_suppressed(lead):
        return AiNurtureRouteResult(
            route=AiNurtureRoute.BLOCKED,
            reason_codes=("suppression",),
        )

    stored_crm_events = await crm_conversation_event_repository.list_for_lead(
        workspace_id, lead.lead_id, limit=20
    )
    merged_crm_events = _merge_crm_conversation_events(
        crm_events=stored_crm_events,
        supplemental_events=supplemental_crm_conversation_events,
    )
    has_recent_crm_conversation_context = any(
        event.content is not None and event.content.strip() for event in merged_crm_events
    )

    apply_result = await apply_lead_state_classification(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        actor=None,
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        now=now,
        default_openrouter_model=default_openrouter_model,
        dormant_threshold_days=dormant_threshold_days,
        allow_overwrite_human_state=False,
        conversation_summary=conversation_summary,
        supplemental_crm_conversation_events=supplemental_crm_conversation_events,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        crm_conversation_events=stored_crm_events,
    )

    route_result = _route_from_apply_result(apply_result, has_recent_crm_conversation_context)
    await _sync_pending_routing_review(
        workspace_id=workspace_id,
        lead=lead,
        route_result=route_result,
        routing_review_repository=routing_review_repository,
        now=now,
    )
    return route_result


async def _sync_pending_routing_review(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    route_result: AiNurtureRouteResult,
    routing_review_repository: LeadRoutingReviewRepository | None,
    now: datetime,
) -> None:
    if routing_review_repository is None:
        return
    if route_result.route == AiNurtureRoute.REVIEW_HOLD and route_result.artifact is not None:
        await create_or_refresh_pending_routing_review(
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            artifact=route_result.artifact,
            reason_codes=route_result.reason_codes,
            routing_review_repository=routing_review_repository,
            now=now,
        )
        return
    await supersede_pending_routing_reviews_for_lead(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        routing_review_repository=routing_review_repository,
        now=now,
    )


def _lead_is_hard_suppressed(lead: CanonicalLeadRecord) -> bool:
    if lead.do_not_contact:
        return True
    return bool(lead.suppression_types)


def _route_from_apply_result(
    apply_result: ApplyLeadStateClassificationResult,
    has_recent_crm_conversation_context: bool,
) -> AiNurtureRouteResult:
    classification_result = apply_result.classification_result
    artifact = apply_result.artifact

    is_rejected = (
        classification_result is None
        or classification_result.status == LeadStateClassificationStatus.REJECTED
    )
    if is_rejected:
        return AiNurtureRouteResult(
            route=AiNurtureRoute.REVIEW_HOLD,
            reason_codes=("classification_rejected",),
            classification_result=classification_result,
            artifact=artifact,
            has_recent_crm_conversation_context=has_recent_crm_conversation_context,
        )

    assert classification_result is not None
    outcome = classification_result.outcome
    if outcome == LeadStateClassificationOutcome.HUMAN_HANDOFF:
        return AiNurtureRouteResult(
            route=AiNurtureRoute.HUMAN_HANDOFF,
            reason_codes=("ai_classified_human_handoff",),
            classification_result=classification_result,
            artifact=artifact,
            has_recent_crm_conversation_context=has_recent_crm_conversation_context,
        )
    if outcome == LeadStateClassificationOutcome.BLOCKED:
        return AiNurtureRouteResult(
            route=AiNurtureRoute.BLOCKED,
            reason_codes=("ai_classified_blocked",),
            classification_result=classification_result,
            artifact=artifact,
            has_recent_crm_conversation_context=has_recent_crm_conversation_context,
        )
    if outcome == LeadStateClassificationOutcome.PAUSED_SEARCH:
        return AiNurtureRouteResult(
            route=AiNurtureRoute.PAUSED_SEARCH,
            reason_codes=("ai_classified_paused_search",),
            classification_result=classification_result,
            artifact=artifact,
            has_recent_crm_conversation_context=has_recent_crm_conversation_context,
        )
    if outcome == LeadStateClassificationOutcome.DORMANT:
        return AiNurtureRouteResult(
            route=AiNurtureRoute.DORMANT,
            reason_codes=("ai_classified_dormant",),
            classification_result=classification_result,
            artifact=artifact,
            has_recent_crm_conversation_context=has_recent_crm_conversation_context,
        )

    return AiNurtureRouteResult(
        route=AiNurtureRoute.REVIEW_HOLD,
        reason_codes=("ai_classified_review_hold",),
        classification_result=classification_result,
        artifact=artifact,
        has_recent_crm_conversation_context=has_recent_crm_conversation_context,
    )
