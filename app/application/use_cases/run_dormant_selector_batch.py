from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.dormant_candidates import DormantCandidateSelector
from app.application.ports.event_bus import EventBus
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.preflight_digest import PreflightDigestRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CrmConversationEventRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.canonical_lead_inputs import (
    contactability_facts_from_canonical_lead,
    enrollment_facts_from_canonical_lead,
    start_candidate_from_canonical_lead,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.preflight_digest import (
    PreflightDigestCandidate,
    PreflightDigestPreparationResult,
    PreflightDigestPreparationStatus,
    campaign_start_context_from_digest,
    prepare_preflight_digest,
)
from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    AiNurtureRouteResult,
    route_ai_nurture_lead,
)
from app.application.use_cases.start_paused_search_campaign_enrollment import (
    PausedSearchCampaignEnrollmentStatus,
    start_paused_search_campaign_enrollment,
)
from app.application.use_cases.start_selected_campaign_batch import (
    start_selected_campaign_batch,
)
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.start_queue import (
    CampaignStartCandidate,
    CampaignStartContext,
    CampaignStartPolicy,
    CampaignStatus,
    evaluate_campaign_start_batch,
)
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.compliance.enrollment import (
    CampaignEnrollmentPolicy,
    EnrollmentSource,
    evaluate_campaign_enrollment,
)
from app.domain.leads import CanonicalLeadRecord

DEFAULT_VETO_WINDOW_HOURS = 24
DEFAULT_CANDIDATE_BUFFER_FACTOR = 2


class DormantSelectorBatchStatus(StrEnum):
    COMPLETED = "completed"
    CAMPAIGN_INACTIVE = "campaign_inactive"
    MISSING_CONTACT_POLICY = "missing_contact_policy"
    NO_CANDIDATES = "no_candidates"


@dataclass(frozen=True)
class DormantSelectorBatchResult:
    status: DormantSelectorBatchStatus
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    batch_id: str
    digest_required: bool
    digest_id: str | None
    digest_status: str | None
    selected_count: int
    held_back_count: int
    started_count: int
    paused_search_started_count: int
    started_lead_ids: tuple[LeadId, ...]
    veto_window_expires_at: datetime | None
    reason: str | None = None


@dataclass(frozen=True)
class RoutedStartCandidate:
    lead: CanonicalLeadRecord
    route_result: AiNurtureRouteResult
    start_candidate: CampaignStartCandidate


@dataclass(frozen=True)
class _RouteSelectionResult:
    routed_candidates: list[RoutedStartCandidate]
    digest_candidates: list[PreflightDigestCandidate]


async def run_dormant_selector_batch(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str | None = None,
    campaign_execution_repository: CampaignExecutionRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    dormant_candidate_selector: DormantCandidateSelector,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    preflight_digest_repository: PreflightDigestRepository,
    notification_provider: NotificationProvider,
    crm_client: CRMClient,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    artifact_repository: LeadClassificationArtifactRepository,
    crm_conversation_event_repository: CrmConversationEventRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    paused_search_track_repository: PausedSearchTrackMappingRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    routing_review_repository: LeadRoutingReviewRepository | None = None,
) -> DormantSelectorBatchResult:
    batch_id = batch_id or str(uuid4())
    config = await campaign_execution_repository.get_active_for_campaign(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
    )
    if config is None or config.campaign_status != CampaignStatus.ACTIVE:
        return _result(
            status=DormantSelectorBatchStatus.CAMPAIGN_INACTIVE,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="campaign is not active or has no published version",
        )

    contact_policy = await workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id=workspace_id,
    )
    if contact_policy is None:
        return _result(
            status=DormantSelectorBatchStatus.MISSING_CONTACT_POLICY,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="workspace contact policy is missing",
        )

    candidates = await dormant_candidate_selector.select_candidates(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        threshold_days=config.dormant_threshold_days,
        limit=config.daily_start_cap * DEFAULT_CANDIDATE_BUFFER_FACTOR,
        now=now,
    )
    if not candidates:
        return _result(
            status=DormantSelectorBatchStatus.NO_CANDIDATES,
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            reason="no dormant candidates found",
        )

    start_policy = CampaignStartPolicy(
        daily_start_cap=config.daily_start_cap,
        require_preflight_digest_for_first_batch=config.preflight_digest_enabled,
        veto_window_hours=DEFAULT_VETO_WINDOW_HOURS,
        agentless_dormant_threshold_days=config.dormant_threshold_days,
    )
    started_today_count = await campaign_enrollment_repository.count_started_today(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        started_since=now,
    )
    initial_context = _initial_context(
        campaign_status=config.campaign_status,
        started_today_count=started_today_count,
    )

    candidate_evaluation = await _evaluate_candidates(
        candidates=candidates,
        enabled_channels=config.enabled_channels,
        contact_policy=contact_policy,
        crm_client=crm_client,
        workspace_id=workspace_id,
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        artifact_repository=artifact_repository,
        crm_conversation_event_repository=crm_conversation_event_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        default_openrouter_model=default_openrouter_model,
        dormant_threshold_days=config.dormant_threshold_days,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        routing_review_repository=routing_review_repository,
        now=now,
    )

    digest_result = await _prepare_digest_if_needed(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_candidates=candidate_evaluation.digest_candidates,
        start_policy=start_policy,
        initial_context=initial_context,
        preflight_digest_repository=preflight_digest_repository,
        notification_provider=notification_provider,
        now=now,
    )

    digest = await preflight_digest_repository.get_digest(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
    )
    final_context = campaign_start_context_from_digest(
        campaign_status=config.campaign_status,
        digest=digest,
        started_today_count=started_today_count,
        is_first_batch=True,
    )

    start_decision = evaluate_campaign_start_batch(
        tuple(candidate.start_candidate for candidate in candidate_evaluation.routed_candidates),
        start_policy,
        final_context,
        now,
    )

    selected_lead_ids = tuple(
        decision.lead_id for decision in start_decision.selected if decision.selected
    )
    candidate_by_lead_id = {
        candidate.start_candidate.lead_id: candidate
        for candidate in candidate_evaluation.routed_candidates
    }
    selected_candidates = tuple(
        candidate_by_lead_id[lead_id]
        for lead_id in selected_lead_ids
        if lead_id in candidate_by_lead_id
    )
    dormant_selected_lead_ids = tuple(
        candidate.lead.lead_id
        for candidate in selected_candidates
        if candidate.route_result.route == AiNurtureRoute.DORMANT
    )
    paused_search_selected_candidates = [
        candidate
        for candidate in selected_candidates
        if candidate.route_result.route == AiNurtureRoute.PAUSED_SEARCH
    ]

    dormant_started_or_enrolled_lead_ids: tuple[LeadId, ...] = ()
    if dormant_selected_lead_ids:
        start_result = await start_selected_campaign_batch(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=config.campaign_version_id,
            lead_ids=dormant_selected_lead_ids,
            source=CampaignEnrollmentSource.DORMANT_SELECTOR,
            reason_codes=(),
            actor_user_id=None,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            commit=commit,
            now=now,
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
        )
        started_count = start_result.started_count
        dormant_started_or_enrolled_lead_ids = tuple(
            result.lead_id
            for result in start_result.lead_results
            if result.status in {LeadStartStatus.STARTED, LeadStartStatus.ALREADY_ENROLLED}
        )
    else:
        started_count = 0

    (
        paused_search_started_count,
        paused_search_started_lead_ids,
    ) = await _start_paused_search_candidates(
        candidates=paused_search_selected_candidates,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=config.campaign_version_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_repository=lead_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=paused_search_track_repository,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        now=now,
    )
    started_lead_ids = tuple(
        lead_id
        for lead_id in selected_lead_ids
        if lead_id
        in {
            *dormant_started_or_enrolled_lead_ids,
            *paused_search_started_lead_ids,
        }
    )

    return _result(
        status=DormantSelectorBatchStatus.COMPLETED,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_required=start_decision.digest_required,
        digest_id=digest_result.digest_id if digest_result else None,
        digest_status=digest_result.status.value if digest_result else None,
        selected_count=len(selected_lead_ids),
        held_back_count=len(start_decision.held_back),
        started_count=started_count,
        paused_search_started_count=paused_search_started_count,
        started_lead_ids=started_lead_ids,
        veto_window_expires_at=start_decision.veto_window_expires_at,
    )


def _result(
    *,
    status: DormantSelectorBatchStatus,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    digest_required: bool = False,
    digest_id: str | None = None,
    digest_status: str | None = None,
    selected_count: int = 0,
    held_back_count: int = 0,
    started_count: int = 0,
    paused_search_started_count: int = 0,
    started_lead_ids: tuple[LeadId, ...] = (),
    veto_window_expires_at: datetime | None = None,
    reason: str | None = None,
) -> DormantSelectorBatchResult:
    return DormantSelectorBatchResult(
        status=status,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        digest_required=digest_required,
        digest_id=digest_id,
        digest_status=digest_status,
        selected_count=selected_count,
        held_back_count=held_back_count,
        started_count=started_count,
        paused_search_started_count=paused_search_started_count,
        started_lead_ids=started_lead_ids,
        veto_window_expires_at=veto_window_expires_at,
        reason=reason,
    )


def _initial_context(
    *,
    campaign_status: CampaignStatus,
    started_today_count: int,
) -> CampaignStartContext:
    return CampaignStartContext(
        campaign_status=campaign_status,
        started_today_count=started_today_count,
        is_first_batch=True,
    )


async def _evaluate_candidates(
    *,
    candidates: tuple[CanonicalLeadRecord, ...],
    enabled_channels: tuple[ContactChannel, ...],
    contact_policy: WorkspaceContactPolicy,
    crm_client: CRMClient,
    workspace_id: WorkspaceId,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    artifact_repository: LeadClassificationArtifactRepository,
    crm_conversation_event_repository: CrmConversationEventRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    default_openrouter_model: str,
    dormant_threshold_days: int,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    now: datetime,
) -> _RouteSelectionResult:
    routed_candidates: list[RoutedStartCandidate] = []
    digest_candidates: list[PreflightDigestCandidate] = []
    for lead in candidates:
        contactability_facts = contactability_facts_from_canonical_lead(lead)
        channel_contactability = {
            channel: evaluate_contactability(contactability_facts, contact_policy, channel)
            for channel in enabled_channels
        }
        enrollment_facts = enrollment_facts_from_canonical_lead(
            lead,
            enrollment_sources=frozenset({EnrollmentSource.DORMANT_SELECTOR}),
            enabled_channels=frozenset(enabled_channels),
            channel_contactability=channel_contactability,
        )
        enrollment_policy = CampaignEnrollmentPolicy()
        enrollment_decision = evaluate_campaign_enrollment(
            enrollment_facts,
            enrollment_policy,
            now,
        )
        if not enrollment_decision.eligible:
            continue

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
            dormant_threshold_days=dormant_threshold_days,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            routing_review_repository=routing_review_repository,
        )
        if route_result.route not in {
            AiNurtureRoute.DORMANT,
            AiNurtureRoute.PAUSED_SEARCH,
        }:
            continue

        start_candidate = start_candidate_from_canonical_lead(
            lead,
            enrollment_decision=enrollment_decision,
            now=now,
        )
        routed_candidates.append(
            RoutedStartCandidate(
                lead=lead,
                route_result=route_result,
                start_candidate=start_candidate,
            )
        )

        if start_candidate.has_assigned_agent:
            agent = await crm_client.get_assigned_agent(workspace_id, lead.crm_lead_id)
            if agent is not None and agent.email:
                digest_candidates.append(
                    PreflightDigestCandidate(
                        start_candidate=start_candidate,
                        recipient_id=agent.crm_agent_id,
                        recipient_destination=agent.email,
                        lead_display_name=lead.primary_email or lead.crm_lead_id,
                    )
                )

    return _RouteSelectionResult(
        routed_candidates=routed_candidates,
        digest_candidates=digest_candidates,
    )


async def _start_paused_search_candidates(
    *,
    candidates: list[RoutedStartCandidate],
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    commit: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> tuple[int, tuple[LeadId, ...]]:
    if paused_search_track_repository is None:
        return 0, ()
    started_count = 0
    started_lead_ids: list[LeadId] = []
    for candidate in candidates:
        lead = await lead_repository.get_by_id(workspace_id, candidate.lead.lead_id)
        lead = lead or candidate.lead
        result = await start_paused_search_campaign_enrollment(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=campaign_version_id,
            lead_id=lead.lead_id,
            lead=lead,
            source=CampaignEnrollmentSource.DORMANT_SELECTOR,
            reason_codes=candidate.route_result.reason_codes,
            actor_user_id=None,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            paused_search_track_repository=paused_search_track_repository,
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            commit=commit,
            now=now,
        )
        if result.status in {
            PausedSearchCampaignEnrollmentStatus.STARTED,
            PausedSearchCampaignEnrollmentStatus.ALREADY_ENROLLED,
        }:
            started_count += 1
            started_lead_ids.append(candidate.lead.lead_id)
    return started_count, tuple(started_lead_ids)


async def _prepare_digest_if_needed(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
    digest_candidates: list[PreflightDigestCandidate],
    start_policy: CampaignStartPolicy,
    initial_context: CampaignStartContext,
    preflight_digest_repository: PreflightDigestRepository,
    notification_provider: NotificationProvider,
    now: datetime,
) -> PreflightDigestPreparationResult:

    if not digest_candidates or not start_policy.require_preflight_digest_for_first_batch:
        return PreflightDigestPreparationResult(
            status=PreflightDigestPreparationStatus.NOT_REQUIRED,
        )

    return await prepare_preflight_digest(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        batch_id=batch_id,
        candidates=tuple(digest_candidates),
        start_policy=start_policy,
        start_context=initial_context,
        repository=preflight_digest_repository,
        notification_provider=notification_provider,
        now=now,
    )
