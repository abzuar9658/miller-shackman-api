from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.canonical_lead_inputs import (
    contactability_facts_from_canonical_lead,
    enrollment_facts_from_canonical_lead,
    start_candidate_from_canonical_lead,
)
from app.application.use_cases.ai_nurture_routing_side_effects import (
    create_or_complete_ai_nurture_handoff,
    record_pending_ai_nurture_routing_review,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.complete_handoff import HandoffCompletionStatus
from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    AiNurtureRouteResult,
    route_ai_nurture_lead,
)
from app.application.use_cases.start_paused_search_campaign_enrollment import (
    PausedSearchCampaignEnrollmentStatus,
    start_paused_search_campaign_enrollment,
)
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignExecutionConfig
from app.domain.campaigns.start_queue import (
    CampaignStartContext,
    CampaignStartPolicy,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import evaluate_contactability
from app.domain.compliance.enrollment import (
    CampaignEnrollmentPolicy,
    EnrollmentSource,
    evaluate_campaign_enrollment,
)
from app.domain.leads import CanonicalLeadRecord

DEFAULT_VETO_WINDOW_HOURS = 24


class CRMTagCampaignEnrollmentStatus(StrEnum):
    NO_MATCHING_CAMPAIGN = "no_matching_campaign"
    MISSING_CONTACT_POLICY = "missing_contact_policy"
    NOT_ELIGIBLE = "not_eligible"
    HELD = "held"
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    ALREADY_ACTIVE_ELSEWHERE = "already_active_elsewhere"
    TERMINAL_REQUIRES_MANUAL_ENROLLMENT = "terminal_requires_manual_enrollment"
    PAUSED_SEARCH_TRACK_ASSIGNED = "paused_search_track_assigned"
    FAILED = "failed"
    PAUSED_SEARCH = "paused_search"
    HUMAN_HANDOFF = "human_handoff"
    REVIEW_HOLD = "review_hold"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CRMTagCampaignEnrollmentResult:
    status: CRMTagCampaignEnrollmentStatus
    workspace_id: WorkspaceId
    lead_id: LeadId
    campaign_id: CampaignId | None = None
    campaign_version_id: CampaignVersionId | None = None
    matched_tag: str | None = None
    reason_codes: tuple[str, ...] = ()
    route: AiNurtureRoute | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    handoff_id: UUID | None = None
    handoff_completion_status: HandoffCompletionStatus | None = None
    handoff_completion_failure_reason: str | None = None
    error: str | None = None


async def process_crm_tag_campaign_enrollment(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    observed_at: datetime,
    now: datetime,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    artifact_repository: LeadClassificationArtifactRepository,
    crm_conversation_event_repository: CrmConversationEventRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    rollback: Callable[[], Awaitable[None]] | None = None,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    routing_review_repository: LeadRoutingReviewRepository | None = None,
    handoff_repository: HandoffRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    crm_client: CRMClient | None = None,
    notification_provider: NotificationProvider | None = None,
    user_repository: UserRepository | None = None,
    handoff_id_factory: Callable[[], UUID] | None = None,
) -> CRMTagCampaignEnrollmentResult:
    configs = await campaign_execution_repository.list_active_for_workspace(workspace_id)
    matched_config = _matching_campaign_config(configs, lead.tags)
    if matched_config is None:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.NO_MATCHING_CAMPAIGN,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
        )

    if lead.do_not_contact or lead.suppression_types:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.BLOCKED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=("suppression",),
            route=AiNurtureRoute.BLOCKED,
        )

    contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
    if contact_policy is None:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.MISSING_CONTACT_POLICY,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
        )

    enabled_channels = frozenset(matched_config.enabled_channels)
    contactability_facts = contactability_facts_from_canonical_lead(lead)
    channel_contactability = {
        channel: evaluate_contactability(contactability_facts, contact_policy, channel)
        for channel in enabled_channels
    }
    enrollment_facts = enrollment_facts_from_canonical_lead(
        lead,
        enrollment_sources=frozenset({EnrollmentSource.CRM_TAG}),
        enabled_channels=enabled_channels,
        channel_contactability=channel_contactability,
        enrollment_tag_observed_at=observed_at,
    )
    enrollment_decision = evaluate_campaign_enrollment(
        enrollment_facts,
        CampaignEnrollmentPolicy(),
        now,
    )
    if not enrollment_decision.eligible:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.NOT_ELIGIBLE,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=tuple(reason.value for reason in enrollment_decision.reasons),
        )

    route_result = await route_ai_nurture_lead(
        workspace_id=workspace_id,
        lead=lead,
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        now=now,
        default_openrouter_model=default_openrouter_model,
        dormant_threshold_days=matched_config.dormant_threshold_days,
        routing_review_repository=routing_review_repository,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
    )
    if route_result.route == AiNurtureRoute.PAUSED_SEARCH:
        if paused_search_track_assignment_repository is None:
            review_reason_codes = route_result.reason_codes + (
                "paused_search_track_assignment_unavailable",
            )
            await record_pending_ai_nurture_routing_review(
                workspace_id=workspace_id,
                lead=lead,
                route_result=route_result,
                reason_codes=review_reason_codes,
                routing_review_repository=routing_review_repository,
                now=now,
            )
            return CRMTagCampaignEnrollmentResult(
                status=CRMTagCampaignEnrollmentStatus.REVIEW_HOLD,
                workspace_id=workspace_id,
                lead_id=lead.lead_id,
                campaign_id=matched_config.campaign_id,
                campaign_version_id=matched_config.campaign_version_id,
                matched_tag=matched_config.crm_enrollment_tag,
                reason_codes=review_reason_codes,
                route=AiNurtureRoute.REVIEW_HOLD,
            )
        current_lead = await lead_repository.get_by_id(workspace_id, lead.lead_id) or lead
        return await _start_paused_search_campaign(
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            lead=current_lead,
            matched_config=matched_config,
            route_result=route_result,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=(
                paused_search_track_assignment_repository
            ),
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            commit=commit,
            rollback=rollback,
            now=now,
        )

    if (
        route_result.route == AiNurtureRoute.REVIEW_HOLD
        and route_result.has_recent_crm_conversation_context
    ):
        review_reason_codes = route_result.reason_codes + ("review_hold_with_conversation_context",)
        await record_pending_ai_nurture_routing_review(
            workspace_id=workspace_id,
            lead=lead,
            route_result=route_result,
            reason_codes=review_reason_codes,
            routing_review_repository=routing_review_repository,
            now=now,
        )
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.REVIEW_HOLD,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=review_reason_codes,
            route=AiNurtureRoute.REVIEW_HOLD,
        )

    if route_result.route == AiNurtureRoute.HUMAN_HANDOFF:
        handoff_result = await create_or_complete_ai_nurture_handoff(
            workspace_id=workspace_id,
            lead=lead,
            campaign_id=matched_config.campaign_id,
            lead_repository=lead_repository,
            route_result=route_result,
            crm_conversation_event_repository=crm_conversation_event_repository,
            handoff_repository=handoff_repository,
            handoff_completion_repository=handoff_completion_repository,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
            crm_client=crm_client,
            notification_provider=notification_provider,
            user_repository=user_repository,
            event_bus=event_bus,
            now=now,
            fallback_summary="AI classification routed this tagged lead to human handoff.",
            handoff_id_factory=handoff_id_factory,
        )
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.HUMAN_HANDOFF,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=route_result.reason_codes,
            route=AiNurtureRoute.HUMAN_HANDOFF,
            handoff_id=handoff_result.handoff_id,
            handoff_completion_status=handoff_result.completion_status,
            handoff_completion_failure_reason=handoff_result.completion_failure_reason,
        )

    if route_result.route == AiNurtureRoute.REVIEW_HOLD:
        await record_pending_ai_nurture_routing_review(
            workspace_id=workspace_id,
            lead=lead,
            route_result=route_result,
            reason_codes=route_result.reason_codes,
            routing_review_repository=routing_review_repository,
            now=now,
        )
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.REVIEW_HOLD,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=route_result.reason_codes,
            route=AiNurtureRoute.REVIEW_HOLD,
        )

    if route_result.route == AiNurtureRoute.BLOCKED:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.BLOCKED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=route_result.reason_codes,
            route=AiNurtureRoute.BLOCKED,
        )

    assert route_result.route == AiNurtureRoute.DORMANT

    start_candidate = start_candidate_from_canonical_lead(
        lead,
        enrollment_decision=enrollment_decision,
        now=now,
    )
    start_policy = CampaignStartPolicy(
        daily_start_cap=matched_config.daily_start_cap,
        require_preflight_digest_for_first_batch=matched_config.preflight_digest_enabled,
        veto_window_hours=DEFAULT_VETO_WINDOW_HOURS,
        agentless_dormant_threshold_days=matched_config.dormant_threshold_days,
    )
    started_today_count = await campaign_enrollment_repository.count_started_today(
        workspace_id=workspace_id,
        campaign_id=matched_config.campaign_id,
        started_since=now,
    )
    start_decision = evaluate_campaign_start_batch(
        [start_candidate],
        start_policy,
        CampaignStartContext(
            campaign_status=matched_config.campaign_status,
            started_today_count=started_today_count,
            is_first_batch=True,
        ),
        now,
    )
    if not start_decision.selected:
        held = start_decision.held_back[0] if start_decision.held_back else None
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.HELD,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=tuple(reason.value for reason in held.reasons) if held else (),
        )

    start_result = await start_selected_campaign_batch(
        workspace_id=workspace_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        lead_ids=[lead.lead_id],
        source=CampaignEnrollmentSource.CRM_TAG,
        reason_codes=(),
        actor_user_id=None,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_assignment_repository=(
            paused_search_track_assignment_repository
        ),
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        rollback=rollback,
        now=now,
    )
    lead_result = start_result.lead_results[0] if start_result.lead_results else None
    if lead_result is not None and lead_result.status == LeadStartStatus.STARTED:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.STARTED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=route_result.reason_codes,
            route=AiNurtureRoute.DORMANT,
            campaign_enrollment_id=lead_result.campaign_enrollment_id,
            workflow_id=lead_result.workflow_id,
            temporal_workflow_id=lead_result.temporal_workflow_id,
        )
    if lead_result is not None and lead_result.status == LeadStartStatus.ALREADY_ENROLLED:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.ALREADY_ENROLLED,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            campaign_enrollment_id=lead_result.campaign_enrollment_id,
        )
    if lead_result is not None and lead_result.status in {
        LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE,
        LeadStartStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT,
        LeadStartStatus.PAUSED_SEARCH_TRACK_ASSIGNED,
    }:
        return CRMTagCampaignEnrollmentResult(
            status=(
                CRMTagCampaignEnrollmentStatus.ALREADY_ACTIVE_ELSEWHERE
                if lead_result.status == LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE
                else (
                    CRMTagCampaignEnrollmentStatus.PAUSED_SEARCH_TRACK_ASSIGNED
                    if lead_result.status == LeadStartStatus.PAUSED_SEARCH_TRACK_ASSIGNED
                    else CRMTagCampaignEnrollmentStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT
                )
            ),
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            workflow_id=lead_result.workflow_id,
            reason_codes=route_result.reason_codes,
            error=lead_result.error,
        )
    return CRMTagCampaignEnrollmentResult(
        status=CRMTagCampaignEnrollmentStatus.FAILED,
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        matched_tag=matched_config.crm_enrollment_tag,
        error=lead_result.error if lead_result is not None else "failed to start enrollment",
    )


async def _start_paused_search_campaign(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead: CanonicalLeadRecord,
    matched_config: CampaignExecutionConfig,
    route_result: AiNurtureRouteResult,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    commit: Callable[[], Awaitable[None]] | None,
    rollback: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> CRMTagCampaignEnrollmentResult:
    result = await start_paused_search_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        lead_id=lead_id,
        lead=lead,
        source=CampaignEnrollmentSource.CRM_TAG,
        reason_codes=route_result.reason_codes,
        actor_user_id=None,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        rollback=rollback,
        now=now,
    )
    lead_result = result.lead_result
    if result.status in {
        PausedSearchCampaignEnrollmentStatus.STARTED,
        PausedSearchCampaignEnrollmentStatus.ALREADY_ENROLLED,
    }:
        assert lead_result is not None
        return CRMTagCampaignEnrollmentResult(
            status=(
                CRMTagCampaignEnrollmentStatus.STARTED
                if result.status == PausedSearchCampaignEnrollmentStatus.STARTED
                else CRMTagCampaignEnrollmentStatus.ALREADY_ENROLLED
            ),
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=route_result.reason_codes,
            route=AiNurtureRoute.PAUSED_SEARCH,
            campaign_enrollment_id=lead_result.campaign_enrollment_id,
            workflow_id=lead_result.workflow_id,
            temporal_workflow_id=lead_result.temporal_workflow_id,
        )
    if result.status == PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD:
        return CRMTagCampaignEnrollmentResult(
            status=CRMTagCampaignEnrollmentStatus.REVIEW_HOLD,
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=matched_config.campaign_id,
            campaign_version_id=matched_config.campaign_version_id,
            matched_tag=matched_config.crm_enrollment_tag,
            reason_codes=result.reason_codes,
            route=AiNurtureRoute.REVIEW_HOLD,
        )
    return CRMTagCampaignEnrollmentResult(
        status=(
            CRMTagCampaignEnrollmentStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT
            if result.status
            == PausedSearchCampaignEnrollmentStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT
            else CRMTagCampaignEnrollmentStatus.FAILED
        ),
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=matched_config.campaign_id,
        campaign_version_id=matched_config.campaign_version_id,
        matched_tag=matched_config.crm_enrollment_tag,
        route=AiNurtureRoute.PAUSED_SEARCH,
        error=result.error or "failed to start enrollment",
    )


def _matching_campaign_config(
    configs: tuple[CampaignExecutionConfig, ...],
    lead_tags: tuple[str, ...],
) -> CampaignExecutionConfig | None:
    normalized_tags = {_normalized_tag(tag) for tag in lead_tags}
    normalized_tags.discard(None)
    for config in configs:
        configured_tag = _normalized_tag(config.crm_enrollment_tag)
        if configured_tag is None:
            continue
        if configured_tag in normalized_tags:
            return config
    return None


def _normalized_tag(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
