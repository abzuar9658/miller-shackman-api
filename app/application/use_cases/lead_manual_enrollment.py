from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
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
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.ai_nurture_routing_side_effects import (
    create_or_complete_ai_nurture_handoff,
    record_pending_ai_nurture_routing_review,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.route_ai_nurture_lead import (
    AiNurtureRoute,
    route_ai_nurture_lead,
)
from app.application.use_cases.start_paused_search_campaign_enrollment import (
    PausedSearchCampaignEnrollmentStatus,
    start_paused_search_campaign_enrollment,
)
from app.domain.campaigns.admin import CampaignAdminCampaign, CampaignAdminVersion
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    WorkspaceMembershipRole,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord


class LeadManualEnrollmentOptionsStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadManualEnrollmentActionStatus(StrEnum):
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    REVIEW_HOLD = "review_hold"
    HUMAN_HANDOFF = "human_handoff"
    BLOCKED = "blocked"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadManualEnrollmentReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"
    NO_CAMPAIGNS_CONFIGURED = "no_campaigns_configured"
    NO_ACTIVE_CAMPAIGNS = "no_active_campaigns"
    NO_ACTIVE_PUBLISHED_CAMPAIGNS = "no_active_published_campaigns"
    LEAD_ALREADY_ENROLLED_IN_AVAILABLE_CAMPAIGNS = "lead_already_enrolled_in_available_campaigns"
    CAMPAIGNS_DISALLOW_AGENT_MANUAL_ENROLLMENT = "campaigns_disallow_agent_manual_enrollment"
    NO_STARTABLE_CAMPAIGNS = "no_startable_campaigns"


@dataclass(frozen=True)
class LeadManualEnrollmentOption:
    campaign_id: CampaignId
    campaign_version_id: CampaignVersionId
    campaign_name: str
    enabled_channels: tuple[str, ...]
    preflight_digest_enabled: bool


@dataclass(frozen=True)
class LeadManualEnrollmentOptionsResult:
    status: LeadManualEnrollmentOptionsStatus
    campaigns: tuple[LeadManualEnrollmentOption, ...] = ()
    reasons: tuple[LeadManualEnrollmentReasonCode, ...] = ()
    total_campaign_count: int = 0
    active_campaign_count: int = 0
    active_published_campaign_count: int = 0
    already_enrolled_campaign_count: int = 0


@dataclass(frozen=True)
class StartLeadManualEnrollmentResult:
    status: LeadManualEnrollmentActionStatus
    campaign_id: CampaignId | None = None
    campaign_version_id: CampaignVersionId | None = None
    campaign_enrollment_id: UUID | None = None
    workflow_id: UUID | None = None
    temporal_workflow_id: str | None = None
    route: AiNurtureRoute | None = None
    reasons: tuple[str, ...] = ()
    error: str | None = None


async def list_lead_manual_enrollment_options(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadReadLeadRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
) -> LeadManualEnrollmentOptionsResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return LeadManualEnrollmentOptionsResult(
            status=LeadManualEnrollmentOptionsStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.LEAD_NOT_FOUND,),
        )
    if not manual_enrollment_permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=True,
    ):
        return LeadManualEnrollmentOptionsResult(
            status=LeadManualEnrollmentOptionsStatus.REJECTED,
            reasons=(LeadManualEnrollmentReasonCode.PERMISSION_DENIED,),
        )

    options: list[LeadManualEnrollmentOption] = []
    total_campaign_count = 0
    active_campaign_count = 0
    active_published_campaign_count = 0
    already_enrolled_campaign_count = 0
    permission_blocked_campaign_count = 0

    for campaign in await campaign_admin_repository.list_campaigns(workspace_id):
        total_campaign_count += 1
        if campaign.status == CampaignStatus.ACTIVE:
            active_campaign_count += 1

        version = await active_published_campaign_version(
            campaign_admin_repository, workspace_id, campaign
        )
        if version is None:
            continue
        active_published_campaign_count += 1

        if not manual_enrollment_permission_allowed(
            actor,
            lead,
            campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
        ):
            permission_blocked_campaign_count += 1
            continue

        existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign.campaign_id,
        )
        if existing is not None:
            already_enrolled_campaign_count += 1
            continue
        options.append(
            LeadManualEnrollmentOption(
                campaign_id=campaign.campaign_id,
                campaign_version_id=version.campaign_version_id,
                campaign_name=campaign.name,
                enabled_channels=tuple(channel.value for channel in version.enabled_channels),
                preflight_digest_enabled=version.preflight_digest_enabled,
            )
        )
    reasons: tuple[LeadManualEnrollmentReasonCode, ...] = ()
    if len(options) == 0:
        if total_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_CAMPAIGNS_CONFIGURED,)
        elif active_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_ACTIVE_CAMPAIGNS,)
        elif active_published_campaign_count == 0:
            reasons = (LeadManualEnrollmentReasonCode.NO_ACTIVE_PUBLISHED_CAMPAIGNS,)
        elif permission_blocked_campaign_count == active_published_campaign_count:
            reasons = (LeadManualEnrollmentReasonCode.CAMPAIGNS_DISALLOW_AGENT_MANUAL_ENROLLMENT,)
        elif already_enrolled_campaign_count > 0 and (
            already_enrolled_campaign_count + permission_blocked_campaign_count
            >= active_published_campaign_count
        ):
            reasons = (LeadManualEnrollmentReasonCode.LEAD_ALREADY_ENROLLED_IN_AVAILABLE_CAMPAIGNS,)
        else:
            reasons = (LeadManualEnrollmentReasonCode.NO_STARTABLE_CAMPAIGNS,)

    return LeadManualEnrollmentOptionsResult(
        status=LeadManualEnrollmentOptionsStatus.OK,
        campaigns=tuple(options),
        reasons=reasons,
        total_campaign_count=total_campaign_count,
        active_campaign_count=active_campaign_count,
        active_published_campaign_count=active_published_campaign_count,
        already_enrolled_campaign_count=already_enrolled_campaign_count,
    )


async def start_lead_manual_enrollment(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    lead_repository: LeadRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    crm_conversation_event_repository: CrmConversationEventRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    event_bus: EventBus | None,
    now: datetime,
    default_openrouter_model: str,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    handoff_repository: HandoffRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    crm_client: CRMClient | None = None,
    notification_provider: NotificationProvider | None = None,
    user_repository: UserRepository | None = None,
    handoff_id_factory: Callable[[], UUID] | None = None,
) -> StartLeadManualEnrollmentResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.LEAD_NOT_FOUND,),
        )
    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    version = await active_published_campaign_version(
        campaign_admin_repository, workspace_id, campaign
    )
    if campaign is None or version is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            reasons=(LeadManualEnrollmentReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if not manual_enrollment_permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
    ):
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REJECTED,
            reasons=(LeadManualEnrollmentReasonCode.PERMISSION_DENIED,),
        )

    existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
    )
    if existing is not None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.ALREADY_ENROLLED,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            campaign_enrollment_id=existing.campaign_enrollment_id,
        )

    route_result = await route_ai_nurture_lead(
        workspace_id=workspace_id,
        lead=lead,
        lead_repository=lead_repository,
        artifact_repository=lead_classification_artifact_repository,
        paused_search_history_repository=paused_search_history_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        crm_conversation_event_repository=crm_conversation_event_repository,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        routing_review_repository=routing_review_repository,
        now=now,
        default_openrouter_model=default_openrouter_model,
        dormant_threshold_days=version.dormant_threshold_days,
    )

    if route_result.route == AiNurtureRoute.PAUSED_SEARCH:
        if paused_search_track_assignment_repository is None:
            review_reasons = route_result.reason_codes + (
                "paused_search_track_assignment_unavailable",
            )
            await record_pending_ai_nurture_routing_review(
                workspace_id=workspace_id,
                lead=lead,
                route_result=route_result,
                reason_codes=review_reasons,
                routing_review_repository=routing_review_repository,
                now=now,
            )
            return StartLeadManualEnrollmentResult(
                status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
                campaign_id=campaign_id,
                campaign_version_id=version.campaign_version_id,
                route=AiNurtureRoute.REVIEW_HOLD,
                reasons=review_reasons,
            )
        current_lead = await lead_repository.get_by_id(workspace_id, lead_id)
        paused_search_result = await start_paused_search_campaign_enrollment(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            lead_id=lead_id,
            lead=current_lead or lead,
            source=manual_enrollment_source(actor),
            reason_codes=route_result.reason_codes,
            actor_user_id=actor.user_id,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            workspace_operational_control_repository=workspace_operational_control_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=(
                paused_search_track_assignment_repository
            ),
            commit=commit,
            now=now,
            event_bus=event_bus,
        )
        if paused_search_result.status == PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD:
            await record_pending_ai_nurture_routing_review(
                workspace_id=workspace_id,
                lead=lead,
                route_result=route_result,
                reason_codes=paused_search_result.reason_codes,
                routing_review_repository=routing_review_repository,
                now=now,
            )
            return StartLeadManualEnrollmentResult(
                status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
                campaign_id=campaign_id,
                campaign_version_id=version.campaign_version_id,
                route=AiNurtureRoute.REVIEW_HOLD,
                reasons=paused_search_result.reason_codes,
            )
        if paused_search_result.status == PausedSearchCampaignEnrollmentStatus.ALREADY_ENROLLED:
            return StartLeadManualEnrollmentResult(
                status=LeadManualEnrollmentActionStatus.ALREADY_ENROLLED,
                campaign_id=campaign_id,
                campaign_version_id=version.campaign_version_id,
                campaign_enrollment_id=(
                    paused_search_result.lead_result.campaign_enrollment_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                workflow_id=(
                    paused_search_result.lead_result.workflow_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                temporal_workflow_id=(
                    paused_search_result.lead_result.temporal_workflow_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                route=AiNurtureRoute.PAUSED_SEARCH,
                reasons=route_result.reason_codes,
            )
        if paused_search_result.status == PausedSearchCampaignEnrollmentStatus.STARTED:
            return StartLeadManualEnrollmentResult(
                status=LeadManualEnrollmentActionStatus.STARTED,
                campaign_id=campaign_id,
                campaign_version_id=version.campaign_version_id,
                campaign_enrollment_id=(
                    paused_search_result.lead_result.campaign_enrollment_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                workflow_id=(
                    paused_search_result.lead_result.workflow_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                temporal_workflow_id=(
                    paused_search_result.lead_result.temporal_workflow_id
                    if paused_search_result.lead_result is not None
                    else None
                ),
                route=AiNurtureRoute.PAUSED_SEARCH,
                reasons=route_result.reason_codes,
            )
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.FAILED,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            route=AiNurtureRoute.PAUSED_SEARCH,
            reasons=route_result.reason_codes,
            error=paused_search_result.error,
        )

    if route_result.route == AiNurtureRoute.REVIEW_HOLD:
        review_reason_codes = route_result.reason_codes
        if route_result.has_recent_crm_conversation_context:
            review_reason_codes = review_reason_codes + ("review_hold_with_conversation_context",)
            await record_pending_ai_nurture_routing_review(
                workspace_id=workspace_id,
                lead=lead,
                route_result=route_result,
                reason_codes=review_reason_codes,
                routing_review_repository=routing_review_repository,
                now=now,
            )
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            route=AiNurtureRoute.REVIEW_HOLD,
            reasons=review_reason_codes,
        )

    if route_result.route == AiNurtureRoute.HUMAN_HANDOFF:
        await create_or_complete_ai_nurture_handoff(
            workspace_id=workspace_id,
            lead=lead,
            campaign_id=campaign_id,
            route_result=route_result,
            crm_conversation_event_repository=crm_conversation_event_repository,
            lead_repository=lead_repository,
            handoff_repository=handoff_repository,
            handoff_completion_repository=handoff_completion_repository,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
            crm_client=crm_client,
            notification_provider=notification_provider,
            user_repository=user_repository,
            event_bus=event_bus,
            now=now,
            fallback_summary=(
                "AI classification routed this manually started lead to human handoff."
            ),
            handoff_id_factory=handoff_id_factory or uuid4,
        )
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.HUMAN_HANDOFF,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            route=AiNurtureRoute.HUMAN_HANDOFF,
            reasons=route_result.reason_codes,
        )

    if route_result.route == AiNurtureRoute.BLOCKED:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.BLOCKED,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            route=AiNurtureRoute.BLOCKED,
            reasons=route_result.reason_codes,
        )

    result = await start_single_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        lead_id=lead_id,
        source=manual_enrollment_source(actor),
        reason_codes=(),
        actor_user_id=actor.user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        workspace_operational_control_repository=workspace_operational_control_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        commit=commit,
        now=now,
        event_bus=event_bus,
    )
    return StartLeadManualEnrollmentResult(
        status=(
            LeadManualEnrollmentActionStatus.STARTED
            if result.status == LeadStartStatus.STARTED
            else (
                LeadManualEnrollmentActionStatus.ALREADY_ENROLLED
                if result.status == LeadStartStatus.ALREADY_ENROLLED
                else LeadManualEnrollmentActionStatus.FAILED
            )
        ),
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        campaign_enrollment_id=result.campaign_enrollment_id,
        workflow_id=result.workflow_id,
        temporal_workflow_id=result.temporal_workflow_id,
        route=AiNurtureRoute.DORMANT,
        reasons=route_result.reason_codes,
        error=result.error,
    )


async def active_published_campaign_version(
    campaign_admin_repository: CampaignAdminRepository,
    workspace_id: WorkspaceId,
    campaign: CampaignAdminCampaign | None,
) -> CampaignAdminVersion | None:
    if (
        campaign is None
        or campaign.status != CampaignStatus.ACTIVE
        or campaign.active_version_id is None
    ):
        return None
    version = cast(
        CampaignAdminVersion | None,
        await campaign_admin_repository.get_version(workspace_id, campaign.active_version_id),
    )
    if version is None or version.status != CampaignVersionStatus.PUBLISHED:
        return None
    return version


def manual_enrollment_permission_allowed(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    *,
    campaign_allows_assigned_agent_enrollment: bool,
) -> bool:
    context = PermissionContext(
        acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead),
        campaign_allows_assigned_agent_enrollment=campaign_allows_assigned_agent_enrollment,
    )
    if evaluate_permission(actor, PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD, context).allowed:
        return True
    return evaluate_permission(
        actor,
        PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
        context,
    ).allowed


def manual_enrollment_source(actor: AuthenticatedActor) -> CampaignEnrollmentSource:
    return (
        CampaignEnrollmentSource.MANUAL_AGENT
        if actor.active_role == WorkspaceMembershipRole.ASSIGNED_AGENT
        else CampaignEnrollmentSource.MANUAL_ADMIN
    )
