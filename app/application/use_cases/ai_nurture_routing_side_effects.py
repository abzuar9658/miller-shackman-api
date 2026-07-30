from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CrmConversationEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    UserRepository,
    WorkspaceHandoffConfigRepository,
)
from app.application.services.handoff_support import (
    latest_open_handoff_for_lead,
    publish_handoff_created_event,
)
from app.application.services.lead_routing_review import (
    create_or_refresh_pending_routing_review,
)
from app.application.use_cases.complete_handoff import (
    HandoffCompletionStatus,
    complete_handoff,
)
from app.application.use_cases.route_ai_nurture_lead import AiNurtureRouteResult
from app.domain.common.ids import CampaignId, WorkspaceId
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    Handoff,
    HandoffReasonCode,
)
from app.domain.leads import CanonicalLeadRecord


@dataclass(frozen=True)
class AiNurtureHandoffResult:
    handoff_id: UUID | None = None
    completion_status: HandoffCompletionStatus | None = None
    completion_failure_reason: str | None = None


async def record_pending_ai_nurture_routing_review(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    route_result: AiNurtureRouteResult,
    reason_codes: tuple[str, ...],
    routing_review_repository: LeadRoutingReviewRepository | None,
    now: datetime,
) -> None:
    if routing_review_repository is None or route_result.artifact is None:
        return
    await create_or_refresh_pending_routing_review(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        artifact=route_result.artifact,
        reason_codes=reason_codes,
        routing_review_repository=routing_review_repository,
        now=now,
    )


async def create_or_complete_ai_nurture_handoff(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    campaign_id: CampaignId,
    route_result: AiNurtureRouteResult,
    crm_conversation_event_repository: CrmConversationEventRepository,
    lead_repository: LeadRepository,
    handoff_repository: HandoffRepository | None,
    handoff_completion_repository: HandoffCompletionRepository | None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
    crm_client: CRMClient | None,
    notification_provider: NotificationProvider | None,
    user_repository: UserRepository | None,
    event_bus: EventBus | None,
    now: datetime,
    fallback_summary: str,
    handoff_id_factory: Callable[[], UUID] | None = None,
) -> AiNurtureHandoffResult:
    _validate_handoff_dependency_bundle(
        handoff_repository=handoff_repository,
        handoff_completion_repository=handoff_completion_repository,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        crm_client=crm_client,
        notification_provider=notification_provider,
    )
    if handoff_repository is None:
        return AiNurtureHandoffResult()

    existing_handoff = await latest_open_handoff_for_lead(
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        handoff_repository=handoff_repository,
    )
    handoff = existing_handoff
    if handoff is None:
        crm_events = await crm_conversation_event_repository.list_for_lead(
            workspace_id,
            lead.lead_id,
            limit=20,
        )
        handoff = await handoff_repository.save(
            Handoff(
                handoff_id=(handoff_id_factory or uuid4)(),
                workspace_id=workspace_id,
                lead_id=lead.lead_id,
                campaign_id=campaign_id,
                assigned_agent_user_id=lead.assigned_agent_user_id,
                assigned_agent_crm_id=lead.assigned_agent_crm_id,
                reason_code=_handoff_reason_from_route_result(route_result),
                summary=_handoff_summary(route_result, crm_events, fallback_summary),
                latest_inbound_text=_latest_crm_inbound_text(crm_events),
                created_at=now,
            )
        )
        await publish_handoff_created_event(handoff=handoff, event_bus=event_bus)

    completion_result = None
    if (
        handoff_completion_repository is not None
        and workspace_handoff_config_repository is not None
        and crm_client is not None
        and notification_provider is not None
    ):
        completion_result = await complete_handoff(
            workspace_id=workspace_id,
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

    return AiNurtureHandoffResult(
        handoff_id=handoff.handoff_id,
        completion_status=(completion_result.status if completion_result else None),
        completion_failure_reason=(
            completion_result.failure_reason if completion_result else None
        ),
    )


def _validate_handoff_dependency_bundle(
    *,
    handoff_repository: HandoffRepository | None,
    handoff_completion_repository: HandoffCompletionRepository | None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
    crm_client: CRMClient | None,
    notification_provider: NotificationProvider | None,
) -> None:
    dependencies = (
        handoff_repository,
        handoff_completion_repository,
        workspace_handoff_config_repository,
        crm_client,
        notification_provider,
    )
    if any(dependency is not None for dependency in dependencies) and not all(
        dependency is not None for dependency in dependencies
    ):
        raise ValueError(
            "AI nurture human handoff requires a complete handoff dependency bundle when enabled"
        )


def _handoff_summary(
    route_result: AiNurtureRouteResult,
    crm_events: tuple[CrmConversationEvent, ...],
    fallback_summary: str,
) -> str:
    classification_summary = (
        route_result.classification_result.summary
        if route_result.classification_result
        else None
    )
    artifact_summary = route_result.artifact.summary if route_result.artifact is not None else None
    latest_inbound = _latest_crm_inbound_text(crm_events)
    latest_any = _latest_crm_event_text(crm_events)
    return (
        classification_summary
        or artifact_summary
        or latest_inbound
        or latest_any
        or fallback_summary
    )


def _latest_crm_inbound_text(crm_events: tuple[CrmConversationEvent, ...]) -> str | None:
    for event in reversed(crm_events):
        if event.direction != CrmConversationEventDirection.INBOUND:
            continue
        text = _normalized_crm_event_text(event)
        if text is not None:
            return text
    return None


def _latest_crm_event_text(crm_events: tuple[CrmConversationEvent, ...]) -> str | None:
    for event in reversed(crm_events):
        text = _normalized_crm_event_text(event)
        if text is not None:
            return text
    return None


def _normalized_crm_event_text(event: CrmConversationEvent) -> str | None:
    if event.content is None:
        return None
    normalized = event.content.strip()
    return normalized or None


def _handoff_reason_from_route_result(route_result: AiNurtureRouteResult) -> HandoffReasonCode:
    classification_result = route_result.classification_result
    if classification_result is not None and classification_result.handoff_reason_code is not None:
        return classification_result.handoff_reason_code
    fallback_text = " ".join(
        part.strip().lower()
        for part in (
            *(classification_result.evidence if classification_result is not None else ()),
            classification_result.summary if classification_result is not None else "",
            route_result.artifact.summary if route_result.artifact is not None else "",
        )
        if part and part.strip()
    )
    if "call" in fallback_text:
        return HandoffReasonCode.HUMAN_REQUESTED
    if "meeting" in fallback_text or "appointment" in fallback_text or "showing" in fallback_text:
        return HandoffReasonCode.HUMAN_REQUESTED
    if "seller" in fallback_text or "sell" in fallback_text:
        return HandoffReasonCode.SELLER_INTEREST
    return HandoffReasonCode.HUMAN_REQUESTED