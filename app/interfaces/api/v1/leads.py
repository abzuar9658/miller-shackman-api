from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.lead_activity import LeadActivityItem
from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.lead_cadence_progress import LeadCadenceProgressView
from app.application.services.lead_decision_tree import LeadDecisionTreeView
from app.application.use_cases.apply_lead_state_classification import (
    ApplyLeadStateClassificationStatus,
    apply_lead_state_classification,
)
from app.application.use_cases.lead_draft_review import (
    ApproveRejectedDraftReviewStatus,
    approve_rejected_draft_review_and_send,
)
from app.application.use_cases.lead_manual_enrollment import (
    LeadManualEnrollmentActionStatus,
    LeadManualEnrollmentOptionsStatus,
    list_lead_manual_enrollment_options,
    start_lead_manual_enrollment,
)
from app.application.use_cases.lead_pause import (
    LeadPauseActionStatus,
    pause_lead_workflow,
)
from app.application.use_cases.lead_paused_search import (
    LeadPausedSearchActionStatus,
    update_lead_paused_search,
)
from app.application.use_cases.lead_read import (
    LeadDetailView,
    LeadOwnershipView,
    LeadPausedSearchHistoryView,
    LeadPausedSearchPlanView,
    LeadQualificationPlanView,
    LeadReadStatus,
    LeadReadView,
    LeadWorkflowOverrideAuditView,
    get_lead_detail_view,
    list_lead_views,
)
from app.application.use_cases.lead_resume import (
    LeadResumeActionStatus,
    LeadResumeEligibilityStatus,
    get_lead_resume_eligibility,
    resume_lead_workflow,
)
from app.application.use_cases.lead_review_hold_resolution import (
    LeadReviewHoldResolution,
    LeadReviewHoldResolutionStatus,
    resolve_lead_review_hold,
)
from app.application.use_cases.lead_workflow_overrides import (
    PausedSearchWorkflowOverrideStatus,
    override_paused_search_timing,
    skip_paused_search_next_touch,
)
from app.application.use_cases.review_queue_read import (
    PendingRoutingReviewView,
    ReviewQueueReadStatus,
    list_pending_routing_reviews,
)
from app.application.use_cases.start_selected_paused_search_track import (
    start_selected_paused_search_track,
)
from app.application.use_cases.terminalize_paused_search import (
    PausedSearchTerminalizationStatus,
    terminalize_paused_search,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.paused_search_tracks import PausedSearchTerminalBehavior
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.compliance import (
    ContactabilityDecision,
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.conversations import InboundMessage
from app.domain.crm_agent_mapping import CRMAgent
from app.domain.identity import AuthenticatedActor, User
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationArtifact,
    LeadPausedSearchProfile,
    LeadRoutingReview,
    lead_paused_search_profile,
)
from app.domain.workflows import LeadWorkflow, WorkflowTransition
from app.interfaces.api.dependencies.lead_classification import (
    LeadClassificationActionBundle,
    get_lead_classification_action_bundle,
)
from app.interfaces.api.dependencies.lead_draft_review import (
    LeadDraftReviewActionBundle,
    get_lead_draft_review_action_bundle,
)
from app.interfaces.api.dependencies.lead_manual_enrollment import (
    LeadManualEnrollmentBundle,
    get_lead_manual_enrollment_bundle,
)
from app.interfaces.api.dependencies.lead_paused_search import (
    LeadPausedSearchActionBundle,
    get_lead_paused_search_action_bundle,
)
from app.interfaces.api.dependencies.lead_read import LeadReadBundle, get_lead_read_bundle
from app.interfaces.api.dependencies.lead_resume import (
    LeadResumeActionBundle,
    LeadResumeReadBundle,
    get_lead_resume_action_bundle,
    get_lead_resume_read_bundle,
)
from app.interfaces.api.dependencies.lead_workflow_overrides import (
    LeadWorkflowOverrideActionBundle,
    get_lead_workflow_override_action_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.leads import (
    ApproveRejectedDraftReviewRequest,
    ApproveRejectedDraftReviewResponse,
    ClassifyLeadResponse,
    InboundMessageResponse,
    LeadActivityItemResponse,
    LeadAssignedCRMAgentResponse,
    LeadCadenceProgressResponse,
    LeadCadenceStepProgressResponse,
    LeadChannelContactabilityResponse,
    LeadChannelSendabilityResponse,
    LeadClassificationArtifactResponse,
    LeadClassificationTraceResponse,
    LeadContactabilityResponse,
    LeadDecisionTreeEdgeResponse,
    LeadDecisionTreeNodeResponse,
    LeadDecisionTreeResponse,
    LeadDetailResponse,
    LeadListItemResponse,
    LeadListResponse,
    LeadManualEnrollmentOptionResponse,
    LeadManualEnrollmentOptionsResponse,
    LeadMappedAppUserResponse,
    LeadOwnershipResponse,
    LeadPausedSearchHistoryEntryResponse,
    LeadPausedSearchProfileResponse,
    LeadPausedSearchTrackPlanResponse,
    LeadPausedSearchTrackStepPlanResponse,
    LeadQualificationPlanResponse,
    LeadResponse,
    LeadResumeEligibilityResponse,
    LeadRoutingReviewResponse,
    LeadSendabilityResponse,
    LeadWorkflowOverrideAuditLogResponse,
    LeadWorkflowResponse,
    OutboundMessageResponse,
    OverridePausedSearchTimingRequest,
    OverridePausedSearchTimingResponse,
    PauseLeadWorkflowRequest,
    PauseLeadWorkflowResponse,
    PendingRoutingReviewItemResponse,
    PendingRoutingReviewListResponse,
    RejectedDraftReviewResponse,
    ResolveLeadReviewHoldRequest,
    ResolveLeadReviewHoldResponse,
    ResumeLeadWorkflowRequest,
    ResumeLeadWorkflowResponse,
    SkipPausedSearchNextTouchRequest,
    SkipPausedSearchNextTouchResponse,
    StartLeadManualEnrollmentRequest,
    StartLeadManualEnrollmentResponse,
    StartSelectedPausedSearchTrackRequest,
    StartSelectedPausedSearchTrackResponse,
    TerminalizePausedSearchRequest,
    TerminalizePausedSearchResponse,
    UpdateLeadPausedSearchRequest,
    UpdateLeadPausedSearchResponse,
    WorkflowTransitionResponse,
)
from app.interfaces.api.serializers.handoffs import handoff_response

router = APIRouter(tags=["leads"])


@router.get("/{workspace_id}/leads", response_model=LeadListResponse)
async def list_leads_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadReadBundle, Depends(get_lead_read_bundle)],
) -> LeadListResponse:
    result = await list_lead_views(
        actor=actor,
        workspace_id=workspace_id,
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        activity_repository=bundle.activity_repository,
        rejected_draft_review_repository=bundle.rejected_draft_review_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        handoff_repository=bundle.handoff_repository,
        user_repository=bundle.user_repository,
        crm_agent_repository=bundle.crm_agent_repository,
    )
    if result.status == LeadReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=list(result.reasons),
        )
    contact_policy = await bundle.workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id
    )
    return LeadListResponse(
        status=result.status.value,
        leads=[
            _lead_list_item_response(
                view,
                contact_policy or WorkspaceContactPolicy(workspace_id=workspace_id),
            )
            for view in result.views
        ],
    )


@router.get("/{workspace_id}/review-queue", response_model=PendingRoutingReviewListResponse)
async def list_review_queue_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadReadBundle, Depends(get_lead_read_bundle)],
) -> PendingRoutingReviewListResponse:
    result = await list_pending_routing_reviews(
        actor=actor,
        workspace_id=workspace_id,
        lead_repository=bundle.lead_repository,
        artifact_repository=bundle.classification_artifact_repository,
        routing_review_repository=bundle.routing_review_repository,
    )
    if result.status == ReviewQueueReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=list(result.reasons),
        )
    contact_policy = await bundle.workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id
    )
    return PendingRoutingReviewListResponse(
        status=result.status.value,
        items=[
            _pending_routing_review_item_response(
                view,
                contact_policy or WorkspaceContactPolicy(workspace_id=workspace_id),
            )
            for view in result.views
        ],
    )


@router.get("/{workspace_id}/leads/{lead_id}", response_model=LeadDetailResponse)
async def get_lead_route(
    workspace_id: UUID,
    lead_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadReadBundle, Depends(get_lead_read_bundle)],
) -> LeadDetailResponse:
    result = await get_lead_detail_view(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=bundle.lead_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        classification_artifact_repository=bundle.classification_artifact_repository,
        workflow_repository=bundle.workflow_repository,
        workflow_override_audit_repository=bundle.workflow_override_audit_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=bundle.paused_search_track_assignment_repository,
        activity_repository=bundle.activity_repository,
        rejected_draft_review_repository=bundle.rejected_draft_review_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        outbound_message_repository=bundle.outbound_message_repository,
        handoff_repository=bundle.handoff_repository,
        user_repository=bundle.user_repository,
        crm_agent_repository=bundle.crm_agent_repository,
        routing_review_repository=bundle.routing_review_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        campaign_execution_repository=bundle.campaign_execution_repository,
    )
    if result.status == LeadReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=list(result.reasons),
        )
    if result.status == LeadReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.view is not None
    contact_policy = await bundle.workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id
    )
    return _lead_detail_response(
        result.view,
        contact_policy or WorkspaceContactPolicy(workspace_id=workspace_id),
    )


@router.get(
    "/{workspace_id}/leads/{lead_id}/manual-enrollment-options",
    response_model=LeadManualEnrollmentOptionsResponse,
)
async def list_lead_manual_enrollment_options_route(
    workspace_id: UUID,
    lead_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadManualEnrollmentBundle, Depends(get_lead_manual_enrollment_bundle)],
) -> LeadManualEnrollmentOptionsResponse:
    result = await list_lead_manual_enrollment_options(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=cast(LeadReadLeadRepository, bundle.lead_repository),
        campaign_admin_repository=bundle.campaign_admin_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
    )
    if result.status == LeadManualEnrollmentOptionsStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=["permission_denied"])
    if result.status == LeadManualEnrollmentOptionsStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["lead_not_found"])
    return LeadManualEnrollmentOptionsResponse(
        status=result.status.value,
        campaigns=[
            LeadManualEnrollmentOptionResponse(
                campaign_id=item.campaign_id,
                campaign_version_id=item.campaign_version_id,
                campaign_name=item.campaign_name,
                enabled_channels=list(item.enabled_channels),
                preflight_digest_enabled=item.preflight_digest_enabled,
            )
            for item in result.campaigns
        ],
        reasons=[reason.value for reason in result.reasons],
        total_campaign_count=result.total_campaign_count,
        active_campaign_count=result.active_campaign_count,
        active_published_campaign_count=result.active_published_campaign_count,
        already_enrolled_campaign_count=result.already_enrolled_campaign_count,
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/manual-enrollments",
    response_model=StartLeadManualEnrollmentResponse,
)
async def start_lead_manual_enrollment_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: StartLeadManualEnrollmentRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadManualEnrollmentBundle, Depends(get_lead_manual_enrollment_bundle)],
) -> StartLeadManualEnrollmentResponse:
    result = await start_lead_manual_enrollment(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=request.campaign_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        campaign_admin_repository=bundle.campaign_admin_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        temporal_workflow_starter=bundle.temporal_workflow_starter,
        lead_classification_artifact_repository=bundle.lead_classification_artifact_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        llm_client=bundle.llm_client,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        routing_review_repository=bundle.routing_review_repository,
        commit=bundle.session.commit,
        rollback=bundle.rollback,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
        default_openrouter_model=bundle.default_openrouter_model,
        handoff_repository=bundle.handoff_repository,
        handoff_completion_repository=bundle.handoff_completion_repository,
        workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
        crm_client=bundle.crm_client,
        notification_provider=bundle.notification_provider,
        user_repository=bundle.user_repository,
    )
    if result.status == LeadManualEnrollmentActionStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=["permission_denied"])
    if result.status == LeadManualEnrollmentActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=list(result.reasons),
        )
    if result.status == LeadManualEnrollmentActionStatus.REENTRY_REASON_REQUIRED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[result.error])
    await bundle.session.commit()
    return StartLeadManualEnrollmentResponse(
        status=result.status.value,
        campaign_id=result.campaign_id,
        campaign_version_id=result.campaign_version_id,
        campaign_enrollment_id=result.campaign_enrollment_id,
        workflow_id=result.workflow_id,
        temporal_workflow_id=result.temporal_workflow_id,
        route=result.route.value if result.route is not None else None,
        reasons=list(result.reasons),
        error=result.error,
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/paused-search/start",
    response_model=StartSelectedPausedSearchTrackResponse,
)
async def start_selected_paused_search_track_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: StartSelectedPausedSearchTrackRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadManualEnrollmentBundle, Depends(get_lead_manual_enrollment_bundle)],
) -> StartSelectedPausedSearchTrackResponse:
    if bundle.paused_search_track_assignment_repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=["paused_search_track_assignment_unavailable"],
        )
    result = await start_selected_paused_search_track(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=request.campaign_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        campaign_admin_repository=bundle.campaign_admin_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_workflow_starter=bundle.temporal_workflow_starter,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        event_bus=bundle.event_bus,
        commit=bundle.session.commit,
        rollback=bundle.rollback,
        now=datetime.now(UTC),
    )
    if result.status == LeadManualEnrollmentActionStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=["permission_denied"])
    if result.status == LeadManualEnrollmentActionStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=list(result.reasons))
    if result.status == LeadManualEnrollmentActionStatus.REENTRY_REASON_REQUIRED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[result.error])
    await bundle.session.commit()
    return StartSelectedPausedSearchTrackResponse(
        status=result.status.value,
        campaign_id=result.campaign_id,
        campaign_version_id=result.campaign_version_id,
        campaign_enrollment_id=result.campaign_enrollment_id,
        workflow_id=result.workflow_id,
        temporal_workflow_id=result.temporal_workflow_id,
        route=result.route.value if result.route is not None else None,
        reasons=list(result.reasons),
        error=result.error,
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/review-hold-resolutions",
    response_model=ResolveLeadReviewHoldResponse,
)
async def resolve_lead_review_hold_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: ResolveLeadReviewHoldRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    manual_bundle: Annotated[
        LeadManualEnrollmentBundle,
        Depends(get_lead_manual_enrollment_bundle),
    ],
    paused_bundle: Annotated[
        LeadPausedSearchActionBundle,
        Depends(get_lead_paused_search_action_bundle),
    ],
    classification_bundle: Annotated[
        LeadClassificationActionBundle,
        Depends(get_lead_classification_action_bundle),
    ],
) -> ResolveLeadReviewHoldResponse:
    result = await resolve_lead_review_hold(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=request.campaign_id,
        resolution=LeadReviewHoldResolution(request.resolution),
        lead_repository=paused_bundle.lead_repository,
        lead_read_repository=cast(LeadReadLeadRepository, manual_bundle.lead_repository),
        artifact_repository=classification_bundle.artifact_repository,
        paused_search_history_repository=paused_bundle.paused_search_history_repository,
        workspace_llm_config_repository=classification_bundle.workspace_llm_config_repository,
        llm_client=classification_bundle.llm_client,
        crm_conversation_event_repository=classification_bundle.crm_conversation_event_repository,
        campaign_admin_repository=manual_bundle.campaign_admin_repository,
        campaign_enrollment_repository=manual_bundle.campaign_enrollment_repository,
        lead_workflow_repository=manual_bundle.lead_workflow_repository,
        workflow_transition_repository=manual_bundle.workflow_transition_repository,
        paused_search_track_repository=paused_bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            paused_bundle.paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=paused_bundle.temporal_signal_outbox_repository,
        temporal_workflow_starter=manual_bundle.temporal_workflow_starter,
        event_bus=manual_bundle.event_bus,
        workspace_operational_control_repository=(
            manual_bundle.workspace_operational_control_repository
        ),
        now=datetime.now(UTC),
        default_openrouter_model=classification_bundle.default_openrouter_model,
        commit=manual_bundle.session.commit,
        rollback=manual_bundle.rollback,
        routing_review_repository=classification_bundle.routing_review_repository,
        handoff_repository=manual_bundle.handoff_repository,
        handoff_completion_repository=manual_bundle.handoff_completion_repository,
        workspace_handoff_config_repository=manual_bundle.workspace_handoff_config_repository,
        crm_client=manual_bundle.crm_client,
        notification_provider=manual_bundle.notification_provider,
        user_repository=manual_bundle.user_repository,
        selected_track_key=request.selected_track_key,
        pause_reason_note=request.pause_reason_note,
        reengagement_not_before=request.reengagement_not_before,
        reengagement_window_label=request.reengagement_window_label,
    )
    if result.status == LeadReviewHoldResolutionStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == LeadReviewHoldResolutionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status in {
        LeadReviewHoldResolutionStatus.INVALID,
        LeadReviewHoldResolutionStatus.REVIEW_REQUIRED,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[reason.value for reason in result.reasons],
        )
    return ResolveLeadReviewHoldResponse(
        status=result.status.value,
        resolution=result.resolution.value if result.resolution is not None else None,
        lead_id=result.lead_id,
        campaign_id=result.campaign_id,
        artifact=(
            _classification_artifact_response(result.artifact)
            if result.artifact is not None
            else None
        ),
        paused_search=_paused_search_profile_response(result.paused_search),
        history_entry=(
            _paused_search_history_response(LeadPausedSearchHistoryView(entry=result.history_entry))
            if result.history_entry is not None
            else None
        ),
        campaign_enrollment_id=result.campaign_enrollment_id,
        workflow_id=result.workflow_id,
        temporal_workflow_id=result.temporal_workflow_id,
        reasons=[reason.value for reason in result.reasons],
        error=result.error,
    )


@router.get(
    "/{workspace_id}/leads/{lead_id}/resume-eligibility",
    response_model=LeadResumeEligibilityResponse,
)
async def get_lead_resume_eligibility_route(
    workspace_id: UUID,
    lead_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadResumeReadBundle, Depends(get_lead_resume_read_bundle)],
) -> LeadResumeEligibilityResponse:
    result = await get_lead_resume_eligibility(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
    )
    if result.status == LeadResumeEligibilityStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == LeadResumeEligibilityStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    assert result.eligibility is not None
    return LeadResumeEligibilityResponse(
        status=result.status.value,
        can_resume=result.eligibility.can_resume,
        workflow_id=result.eligibility.workflow_id,
        workflow_state=(
            result.eligibility.workflow_state.value
            if result.eligibility.workflow_state is not None
            else None
        ),
        contactable_channels=[channel.value for channel in result.eligibility.contactable_channels],
        reasons=[reason.value for reason in result.eligibility.reasons],
        blocked_contactability_reasons=list(result.eligibility.blocked_contactability_reasons),
    )


@router.post("/{workspace_id}/leads/{lead_id}/resume", response_model=ResumeLeadWorkflowResponse)
async def resume_lead_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: ResumeLeadWorkflowRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadResumeActionBundle, Depends(get_lead_resume_action_bundle)],
) -> ResumeLeadWorkflowResponse:
    result = await resume_lead_workflow(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        external_event_repository=bundle.external_event_repository,
        commit=bundle.session.commit,
        now=datetime.now(UTC),
    )
    if result.status == LeadResumeActionStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == LeadResumeActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return ResumeLeadWorkflowResponse(
        status=result.status.value,
        workflow_id=result.workflow_id,
        workflow_state=result.workflow_state.value if result.workflow_state is not None else None,
        reasons=[reason.value for reason in result.reasons],
        signal_queued=result.signal_queued,
    )


@router.post("/{workspace_id}/leads/{lead_id}/pause", response_model=PauseLeadWorkflowResponse)
async def pause_lead_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: PauseLeadWorkflowRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadResumeActionBundle, Depends(get_lead_resume_action_bundle)],
) -> PauseLeadWorkflowResponse:
    result = await pause_lead_workflow(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        workflow_repository=bundle.workflow_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        external_event_repository=bundle.external_event_repository,
        commit=bundle.session.commit,
        now=datetime.now(UTC),
    )
    if result.status == LeadPauseActionStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == LeadPauseActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return PauseLeadWorkflowResponse(
        status=result.status.value,
        workflow_id=result.workflow_id,
        workflow_state=result.workflow_state.value if result.workflow_state is not None else None,
        reasons=[reason.value for reason in result.reasons],
        signal_queued=result.signal_queued,
    )


@router.patch(
    "/{workspace_id}/leads/{lead_id}/paused-search",
    response_model=UpdateLeadPausedSearchResponse,
)
async def update_lead_paused_search_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: UpdateLeadPausedSearchRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadPausedSearchActionBundle,
        Depends(get_lead_paused_search_action_bundle),
    ],
) -> UpdateLeadPausedSearchResponse:
    result = await update_lead_paused_search(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        active=request.active,
        selected_track_key=request.selected_track_key,
        reason_note=request.reason_note,
        reengagement_not_before=request.reengagement_not_before,
        reengagement_window_label=request.reengagement_window_label,
        lead_repository=bundle.lead_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        now=datetime.now(UTC),
    )
    if result.status == LeadPausedSearchActionStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status == LeadPausedSearchActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return UpdateLeadPausedSearchResponse(
        status=result.status.value,
        lead_id=result.lead_id,
        paused_search=_paused_search_profile_response(result.profile),
        history_entry=(
            _paused_search_history_response(
                LeadPausedSearchHistoryView(entry=result.history_entry),
            )
            if result.history_entry is not None
            else None
        ),
        reasons=[reason.value for reason in result.reasons],
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/paused-search/timing-override",
    response_model=OverridePausedSearchTimingResponse,
)
async def override_paused_search_timing_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: OverridePausedSearchTimingRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadWorkflowOverrideActionBundle,
        Depends(get_lead_workflow_override_action_bundle),
    ],
) -> OverridePausedSearchTimingResponse:
    result = await override_paused_search_timing(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        reengagement_not_before=request.reengagement_not_before,
        reengagement_window_label=request.reengagement_window_label,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        lead_workflow_override_audit_repository=bundle.lead_workflow_override_audit_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        workspace_repository=bundle.workspace_repository,
        now=datetime.now(UTC),
    )
    _raise_for_override_error(result.status, [reason.value for reason in result.reasons])
    await bundle.session.commit()
    return OverridePausedSearchTimingResponse(
        status=result.status.value,
        lead_id=result.lead_id,
        workflow_id=result.workflow.workflow_id if result.workflow is not None else None,
        paused_search=_paused_search_profile_response(result.profile),
        next_action_at=result.workflow.next_action_at if result.workflow is not None else None,
        reasons=[reason.value for reason in result.reasons],
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/paused-search/skip-next-touch",
    response_model=SkipPausedSearchNextTouchResponse,
)
async def skip_paused_search_next_touch_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: SkipPausedSearchNextTouchRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadWorkflowOverrideActionBundle,
        Depends(get_lead_workflow_override_action_bundle),
    ],
) -> SkipPausedSearchNextTouchResponse:
    result = await skip_paused_search_next_touch(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        lead_workflow_override_audit_repository=bundle.lead_workflow_override_audit_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        workspace_repository=bundle.workspace_repository,
        paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
        now=datetime.now(UTC),
    )
    _raise_for_override_error(result.status, [reason.value for reason in result.reasons])
    await bundle.session.commit()
    return SkipPausedSearchNextTouchResponse(
        status=result.status.value,
        lead_id=result.lead_id,
        workflow_id=result.workflow.workflow_id if result.workflow is not None else None,
        skipped_step_id=result.skipped_step_id,
        next_action_at=result.workflow.next_action_at if result.workflow is not None else None,
        reasons=[reason.value for reason in result.reasons],
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/paused-search/terminalize",
    response_model=TerminalizePausedSearchResponse,
)
async def terminalize_paused_search_route(
    workspace_id: UUID,
    lead_id: UUID,
    request: TerminalizePausedSearchRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[LeadResumeActionBundle, Depends(get_lead_resume_action_bundle)],
) -> TerminalizePausedSearchResponse:
    try:
        terminal_behavior = PausedSearchTerminalBehavior(request.terminal_behavior)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=["invalid_target"],
        ) from exc
    assert bundle.paused_search_occurrence_repository is not None
    result = await terminalize_paused_search(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        terminal_behavior=terminal_behavior,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        external_event_repository=bundle.external_event_repository,
        commit=bundle.session.commit,
        now=datetime.now(UTC),
    )
    if result.status is PausedSearchTerminalizationStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status is PausedSearchTerminalizationStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    if result.status is PausedSearchTerminalizationStatus.INVALID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=[reason.value for reason in result.reasons],
        )
    return TerminalizePausedSearchResponse(
        status=result.status.value,
        lead_id=result.lead_id,
        workflow_id=result.workflow_id,
        workflow_state=result.workflow_state.value if result.workflow_state else None,
        reasons=[reason.value for reason in result.reasons],
        signal_queued=result.signal_queued,
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/classify",
    response_model=ClassifyLeadResponse,
)
async def classify_lead_route(
    workspace_id: UUID,
    lead_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadClassificationActionBundle,
        Depends(get_lead_classification_action_bundle),
    ],
) -> ClassifyLeadResponse:
    result = await apply_lead_state_classification(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=bundle.lead_repository,
        paused_search_history_repository=bundle.paused_search_history_repository,
        artifact_repository=bundle.artifact_repository,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        llm_client=bundle.llm_client,
        now=datetime.now(UTC),
        default_openrouter_model=bundle.default_openrouter_model,
    )
    if result.status == ApplyLeadStateClassificationStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason for reason in result.reasons],
        )
    if result.status == ApplyLeadStateClassificationStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason for reason in result.reasons],
        )
    await bundle.session.commit()
    outcome_value = None
    confidence_value = None
    if result.classification_result is not None:
        confidence_value = result.classification_result.confidence
        if result.classification_result.outcome is not None:
            outcome_value = result.classification_result.outcome.value
    return ClassifyLeadResponse(
        status=result.status.value,
        lead_id=lead_id,
        outcome=outcome_value,
        confidence=confidence_value,
        applied_status=result.artifact.applied_status.value if result.artifact else None,
        artifact=_classification_artifact_response(result.artifact) if result.artifact else None,
        paused_search=_paused_search_profile_response(result.profile),
        history_entry=(
            _paused_search_history_response(
                LeadPausedSearchHistoryView(entry=result.history_entry),
            )
            if result.history_entry is not None
            else None
        ),
        reasons=[reason for reason in result.reasons],
    )


def _classification_artifact_response(
    artifact: LeadClassificationArtifact,
) -> LeadClassificationArtifactResponse:
    llm_trace = _classification_trace_response(artifact)
    return LeadClassificationArtifactResponse(
        artifact_id=artifact.artifact_id,
        source=artifact.source,
        outcome=artifact.outcome.value,
        selected_track_key=artifact.selected_track_key,
        track_selection_status=(
            artifact.track_selection_status.value if artifact.track_selection_status else None
        ),
        track_version_id=artifact.track_version_id,
        reengagement_not_before=artifact.reengagement_not_before,
        reengagement_window_label=artifact.reengagement_window_label,
        confidence=artifact.confidence,
        evidence=list(artifact.evidence),
        summary=artifact.summary,
        model=artifact.model,
        prompt_version=artifact.prompt_version,
        latency_ms=artifact.latency_ms,
        usage_tokens=artifact.usage_tokens,
        applied_status=artifact.applied_status.value,
        applied_at=artifact.applied_at,
        created_at=artifact.created_at,
        llm_trace=llm_trace,
    )


def _classification_trace_response(
    artifact: LeadClassificationArtifact,
) -> LeadClassificationTraceResponse | None:
    if (
        artifact.prompt_text is None
        and artifact.raw_llm_response_text is None
        and not artifact.input_context
        and not artifact.parsed_llm_response
    ):
        return None
    return LeadClassificationTraceResponse(
        prompt_text=artifact.prompt_text,
        input_context=dict(artifact.input_context),
        raw_response_text=artifact.raw_llm_response_text,
        parsed_response=dict(artifact.parsed_llm_response),
    )


def _routing_review_response(review: LeadRoutingReview) -> LeadRoutingReviewResponse:
    return LeadRoutingReviewResponse(
        review_id=review.review_id,
        artifact_id=review.artifact_id,
        status=review.status.value,
        reason_codes=list(review.reason_codes),
        resolution=review.resolution.value if review.resolution is not None else None,
        reviewed_by_user_id=review.reviewed_by_user_id,
        reviewed_at=review.reviewed_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def _pending_routing_review_item_response(
    view: PendingRoutingReviewView,
    contact_policy: WorkspaceContactPolicy,
) -> PendingRoutingReviewItemResponse:
    return PendingRoutingReviewItemResponse(
        review=_routing_review_response(view.review),
        lead=_lead_response(view.lead, None, contact_policy),
        artifact=_classification_artifact_response(view.artifact),
    )


@router.post(
    "/{workspace_id}/leads/{lead_id}/rejected-draft-reviews/{review_id}/approve-send",
    response_model=ApproveRejectedDraftReviewResponse,
)
async def approve_rejected_draft_review_route(
    workspace_id: UUID,
    lead_id: UUID,
    review_id: UUID,
    request: ApproveRejectedDraftReviewRequest,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        LeadDraftReviewActionBundle,
        Depends(get_lead_draft_review_action_bundle),
    ],
) -> ApproveRejectedDraftReviewResponse:
    result = await approve_rejected_draft_review_and_send(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        review_id=review_id,
        reason=request.reason,
        lead_repository=bundle.lead_repository,
        review_repository=bundle.review_repository,
        workflow_repository=bundle.workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        campaign_execution_repository=bundle.campaign_execution_repository,
        workspace_repository=bundle.workspace_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        message_repository=bundle.message_repository,
        external_event_repository=bundle.external_event_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        crm_client=bundle.crm_client,
        crm_agent_repository=bundle.crm_agent_repository,
        workspace_agent_crm_mapping_repository=bundle.workspace_agent_crm_mapping_repository,
        workspace_agent_mapping_config_repository=bundle.workspace_agent_mapping_config_repository,
        workspace_membership_repository=bundle.workspace_membership_repository,
        user_repository=bundle.user_repository,
        outbound_message_crm_completion_repository=bundle.outbound_message_crm_completion_repository,
        workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
        commit=bundle.session.commit,
        sms_provider=bundle.sms_provider,
        email_provider=bundle.email_provider,
        now=datetime.now(UTC),
    )
    if result.status == ApproveRejectedDraftReviewStatus.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=["not_found"])
    if result.status == ApproveRejectedDraftReviewStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=list(result.reasons))
    await bundle.session.commit()
    return ApproveRejectedDraftReviewResponse(
        status=result.status.value,
        review_id=result.review_id,
        outbound_message_id=result.outbound_message_id,
        workflow_id=result.workflow_id,
        reasons=list(result.reasons),
        signal_queued=result.signal_queued,
    )


def _lead_list_item_response(
    view: LeadReadView,
    contact_policy: WorkspaceContactPolicy,
) -> LeadListItemResponse:
    activity_summary = view.activity_summary
    return LeadListItemResponse(
        lead=_lead_response(view.lead, view.assigned_agent_name, contact_policy),
        ownership=_lead_ownership_response(view.ownership),
        latest_workflow=_workflow_response(view.latest_workflow),
        latest_handoff=handoff_response(view.latest_handoff) if view.latest_handoff else None,
        has_activity=activity_summary is not None and activity_summary.activity_count > 0,
        activity_count=activity_summary.activity_count if activity_summary is not None else 0,
        inbound_message_count=(
            activity_summary.inbound_message_count if activity_summary is not None else 0
        ),
        outbound_message_count=(
            activity_summary.outbound_message_count if activity_summary is not None else 0
        ),
        crm_event_count=activity_summary.crm_event_count if activity_summary is not None else 0,
        handoff_count=activity_summary.handoff_count if activity_summary is not None else 0,
        latest_activity_at=(
            activity_summary.latest_activity_at if activity_summary is not None else None
        ),
        latest_activity_preview=(
            activity_summary.latest_activity_preview if activity_summary is not None else None
        ),
        latest_activity_kind=(
            activity_summary.latest_activity_kind.value
            if activity_summary is not None and activity_summary.latest_activity_kind is not None
            else None
        ),
        has_conversation=activity_summary is not None
        and activity_summary.inbound_message_count > 0,
    )


def _lead_detail_response(
    view: LeadDetailView,
    contact_policy: WorkspaceContactPolicy,
) -> LeadDetailResponse:
    return LeadDetailResponse(
        status=LeadReadStatus.OK.value,
        lead=_lead_response(
            view.lead.lead,
            view.lead.assigned_agent_name,
            contact_policy,
        ),
        ownership=_lead_ownership_response(view.lead.ownership),
        latest_workflow=_workflow_response(view.lead.latest_workflow),
        latest_handoff=handoff_response(view.lead.latest_handoff)
        if view.lead.latest_handoff
        else None,
        qualification_plan=_qualification_plan_response(view.qualification_plan),
        decision_tree=_decision_tree_response(view.decision_tree),
        status_narrative=view.status_narrative,
        cadence_progress=[
            _cadence_progress_response(item) for item in view.cadence_progress
        ],
        workflow_transitions=[_transition_response(item) for item in view.workflow_transitions],
        workflow_override_audits=[
            _workflow_override_audit_response(item) for item in view.workflow_override_audits
        ],
        paused_search_history=[
            _paused_search_history_response(item) for item in view.paused_search_history
        ],
        routing_reviews=[_routing_review_response(item) for item in view.routing_reviews],
        rejected_draft_reviews=[
            _rejected_draft_review_response(item) for item in view.rejected_draft_reviews
        ],
        activity_log=[_activity_item_response(item) for item in view.activity_items],
        inbound_messages=[_inbound_message_response(item) for item in view.inbound_messages],
        outbound_messages=[_outbound_message_response(item) for item in view.outbound_messages],
        handoffs=[handoff_response(item) for item in view.handoffs],
    )


def _cadence_progress_response(view: LeadCadenceProgressView) -> LeadCadenceProgressResponse:
    return LeadCadenceProgressResponse(
        journey=view.journey.value,
        flow_name=view.flow_name,
        steps=[
            LeadCadenceStepProgressResponse(
                step_id=step.step_id,
                step_order=step.step_order,
                channel=step.channel.value,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                status=step.status.value,
                attempt_count=step.attempt_count,
                sent_at=step.sent_at,
                scheduled_for=step.scheduled_for,
                last_failure_reason=step.last_failure_reason,
                phase=step.phase,
            )
            for step in view.steps
        ],
        total_steps=view.total_steps,
        completed_steps=view.completed_steps,
        current_step_order=view.current_step_order,
        next_action_at=view.next_action_at,
    )


def _qualification_plan_response(
    view: LeadQualificationPlanView | None,
) -> LeadQualificationPlanResponse | None:
    if view is None:
        return None
    return LeadQualificationPlanResponse(
        classification_artifact=(
            _classification_artifact_response(view.classification_artifact)
            if view.classification_artifact is not None
            else None
        ),
        paused_search_plan=(
            _paused_search_plan_response(view.paused_search_plan)
            if view.paused_search_plan is not None
            else None
        ),
    )


def _decision_tree_response(view: LeadDecisionTreeView) -> LeadDecisionTreeResponse:
    nodes = view.nodes
    edges = view.edges
    return LeadDecisionTreeResponse(
        title=view.title,
        subtitle=view.subtitle,
        nodes=[
            LeadDecisionTreeNodeResponse(
                node_id=node.node_id,
                kind=node.kind.value,
                label=node.label,
                row=node.row,
                column=node.column,
                status=node.status.value,
                description=node.description,
                chips=list(node.chips),
            )
            for node in nodes
        ],
        edges=[
            LeadDecisionTreeEdgeResponse(
                edge_id=edge.edge_id,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                status=edge.status.value,
                label=edge.label,
                description=edge.description,
                detail_lines=list(edge.detail_lines),
            )
            for edge in edges
        ],
    )


def _paused_search_plan_response(
    plan: LeadPausedSearchPlanView,
) -> LeadPausedSearchTrackPlanResponse:
    return LeadPausedSearchTrackPlanResponse(
        track_id=plan.track.track_id,
        track_key=plan.track.track_key,
        display_name=plan.track.display_name,
        track_status=plan.track.status.value,
        track_version_id=plan.version.track_version_id,
        version_number=plan.version.version_number,
        version_status=plan.version.status.value,
        selection_guidance=plan.version.selection_guidance,
        enabled=plan.version.enabled,
        allowed_channels=[channel.value for channel in plan.version.allowed_channels],
        fallback_timing_policy=plan.version.fallback_timing_policy.value,
        maintenance_interval_days=plan.version.maintenance_interval_days,
        reactivation_window_days=plan.version.reactivation_window_days,
        max_total_touches=plan.version.max_total_touches,
        default_pause_duration_days=plan.version.default_pause_duration_days,
        max_duration_days=plan.version.max_duration_days,
        terminal_behavior=plan.version.terminal_behavior.value,
        steps=[
            LeadPausedSearchTrackStepPlanResponse(
                step_id=step.step_id,
                track_version_id=step.track_version_id,
                step_order=step.step_order,
                phase=step.phase.value,
                channel=step.channel.value,
                delay_hours=step.delay_hours,
                message_goal=step.message_goal,
                template_key=step.template_key,
                max_attempts=step.max_attempts,
                review_required=step.review_required,
                timing_basis=step.timing_basis.value,
                fallback_channel=step.fallback_channel.value if step.fallback_channel else None,
                interval_days=step.interval_days,
                max_occurrences=step.max_occurrences,
                template_version_id=step.template_version_id,
            )
            for step in plan.steps
        ],
        current_step_id=(plan.current_step.step_id if plan.current_step is not None else None),
        current_step_order=(
            plan.current_step.step_order if plan.current_step is not None else None
        ),
        current_phase=(plan.current_step.phase.value if plan.current_step is not None else None),
        current_channel=(
            plan.current_step.channel.value if plan.current_step is not None else None
        ),
        current_message_goal=(
            plan.current_step.message_goal if plan.current_step is not None else None
        ),
        next_action_at=plan.next_action_at,
    )


def _lead_ownership_response(ownership: LeadOwnershipView) -> LeadOwnershipResponse:
    return LeadOwnershipResponse(
        crm_assigned_agent=_crm_assigned_agent_response(ownership.crm_assigned_agent),
        mapped_app_user=_mapped_app_user_response(ownership.mapped_app_user),
    )


def _crm_assigned_agent_response(agent: CRMAgent | None) -> LeadAssignedCRMAgentResponse | None:
    if agent is None:
        return None
    return LeadAssignedCRMAgentResponse(
        external_agent_id=agent.external_agent_id,
        name=agent.name,
        email=agent.email,
    )


def _mapped_app_user_response(user: User | None) -> LeadMappedAppUserResponse | None:
    if user is None:
        return None
    return LeadMappedAppUserResponse(
        user_id=user.user_id,
        full_name=user.full_name,
        email=user.email,
    )


def _activity_item_response(item: LeadActivityItem) -> LeadActivityItemResponse:
    return LeadActivityItemResponse(
        activity_id=item.activity_id,
        lead_id=item.lead_id,
        kind=item.kind.value,
        occurred_at=item.occurred_at,
        title=item.title,
        preview=item.preview,
        content=item.content,
        channel=item.channel,
        direction=item.direction,
        status=item.status,
        actor_name=item.actor_name,
        details=item.details,
        transcript_segments=[
            {
                "text": segment.text,
                "speaker_name": segment.speaker_name,
                "speaker_role": segment.speaker_role,
                "started_at": segment.started_at.isoformat() if segment.started_at else None,
            }
            for segment in item.transcript_segments
        ],
    )


def _rejected_draft_review_response(review: RejectedDraftReview) -> RejectedDraftReviewResponse:
    return RejectedDraftReviewResponse(
        review_id=review.review_id,
        workflow_id=review.workflow_id,
        workflow_transition_id=review.workflow_transition_id,
        campaign_id=review.campaign_id,
        campaign_version_id=review.campaign_version_id,
        cadence_step_id=review.cadence_step_id,
        channel=review.channel.value,
        status=review.status.value,
        reason_codes=list(review.reason_codes),
        draft_reason_codes=list(review.draft_reason_codes),
        review_blockers=list(review.review_blockers),
        draft_safety_flags=list(review.draft_safety_flags),
        draft_personalization_notes=list(review.draft_personalization_notes),
        draft_body=review.draft_body,
        draft_subject=review.draft_subject,
        raw_llm_response_text=review.raw_llm_response_text,
        validation_error=review.validation_error,
        explanation=review.explanation,
        draft_confidence=review.draft_confidence,
        draft_model=review.draft_model,
        draft_prompt_version=review.draft_prompt_version,
        can_approve_send=review.can_approve_send,
        reviewed_by_user_id=review.reviewed_by_user_id,
        reviewed_at=review.reviewed_at,
        review_note=review.review_note,
        outbound_message_id=review.outbound_message_id,
        created_at=review.created_at,
    )


def _lead_response(
    lead: CanonicalLeadRecord,
    assigned_agent_name: str | None,
    contact_policy: WorkspaceContactPolicy,
) -> LeadResponse:
    return LeadResponse(
        lead_id=lead.lead_id,
        crm_provider=lead.crm_provider.value,
        crm_lead_id=lead.crm_lead_id,
        display_name=lead.mapped_custom_fields.get("display_name") or lead.crm_lead_id,
        primary_email=lead.primary_email,
        primary_phone=lead.primary_phone,
        lead_source=lead.lead_source,
        lead_stage=lead.lead_stage,
        lead_type=lead.lead_type.value,
        tags=list(lead.tags),
        has_accountable_owner=lead.has_accountable_owner,
        assigned_agent_crm_id=lead.assigned_agent_crm_id,
        assigned_agent_name=assigned_agent_name,
        sms_permission_status=lead.sms_permission_status.value,
        email_permission_status=lead.email_permission_status.value,
        sms_opted_out=lead.sms_opted_out,
        email_unsubscribed=lead.email_unsubscribed,
        do_not_contact=lead.do_not_contact,
        suppression_types=sorted(item.value for item in lead.suppression_types),
        contactability=_lead_contactability_response(lead),
        sendability=_lead_sendability_response(lead, contact_policy),
        paused_search=_paused_search_profile_response(lead_paused_search_profile(lead)),
        facts_derived_at=lead.facts_derived_at,
        last_activity_at=lead.last_activity_at,
        last_meaningful_communication_at=lead.last_meaningful_communication_at,
        last_agent_activity_at=lead.last_agent_activity_at,
    )


def _paused_search_history_response(
    item: LeadPausedSearchHistoryView,
) -> LeadPausedSearchHistoryEntryResponse:
    return LeadPausedSearchHistoryEntryResponse(
        history_id=item.entry.history_id,
        action=item.entry.action.value,
        actor_user_id=item.entry.actor_user_id,
        actor_name=item.actor_name,
        created_at=item.entry.created_at,
        previous_profile=_paused_search_profile_response(item.entry.previous_profile),
        current_profile=_paused_search_profile_response(item.entry.current_profile),
    )


def _workflow_override_audit_response(
    item: LeadWorkflowOverrideAuditView,
) -> LeadWorkflowOverrideAuditLogResponse:
    return LeadWorkflowOverrideAuditLogResponse(
        audit_log_id=item.entry.audit_log_id,
        workflow_id=item.entry.workflow_id,
        action=item.entry.action.value,
        reason=item.entry.reason,
        actor_user_id=item.entry.actor_user_id,
        actor_name=item.actor_name,
        details=dict(item.entry.details),
        created_at=item.entry.created_at,
    )


def _paused_search_profile_response(
    profile: LeadPausedSearchProfile | None,
) -> LeadPausedSearchProfileResponse | None:
    if profile is None:
        return None
    return LeadPausedSearchProfileResponse(
        paused_search_active=profile.paused_search_active,
        paused_search_track_key=profile.paused_search_track_key,
        paused_search_track_version_id=profile.paused_search_track_version_id,
        pause_reason_note=profile.pause_reason_note,
        reengagement_not_before=profile.reengagement_not_before,
        reengagement_window_label=profile.reengagement_window_label,
        paused_search_source=(
            profile.paused_search_source.value if profile.paused_search_source else None
        ),
        paused_search_recorded_at=profile.paused_search_recorded_at,
        paused_search_recorded_by_user_id=profile.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=profile.paused_search_last_confirmed_at,
    )


def _lead_contactability_response(
    lead: CanonicalLeadRecord,
) -> LeadContactabilityResponse:
    sms_contactable = lead.has_sms_capable_phone and lead.primary_phone is not None
    email_contactable = lead.has_email and lead.primary_email is not None
    return LeadContactabilityResponse(
        sms=LeadChannelContactabilityResponse(
            channel=ContactChannel.SMS.value,
            contactable=sms_contactable,
        ),
        email=LeadChannelContactabilityResponse(
            channel=ContactChannel.EMAIL.value,
            contactable=email_contactable,
        ),
        contactable_channels=[
            channel
            for channel, contactable in (
                (ContactChannel.SMS.value, sms_contactable),
                (ContactChannel.EMAIL.value, email_contactable),
            )
            if contactable
        ],
    )


def _lead_sendability_response(
    lead: CanonicalLeadRecord,
    contact_policy: WorkspaceContactPolicy,
) -> LeadSendabilityResponse:
    facts = contactability_facts_from_canonical_lead(lead)
    sms_decision = evaluate_contactability(facts, contact_policy, ContactChannel.SMS)
    email_decision = evaluate_contactability(facts, contact_policy, ContactChannel.EMAIL)
    decisions = (sms_decision, email_decision)
    return LeadSendabilityResponse(
        sms=_channel_sendability_response(sms_decision),
        email=_channel_sendability_response(email_decision),
        sendable_channels=[decision.channel.value for decision in decisions if decision.allowed],
        blocked_reasons=_blocked_reason_values(decisions),
    )


def _channel_sendability_response(
    decision: ContactabilityDecision,
) -> LeadChannelSendabilityResponse:
    return LeadChannelSendabilityResponse(
        channel=decision.channel.value,
        sendable=decision.allowed,
        reasons=[reason.value for reason in decision.reasons],
    )


def _blocked_reason_values(
    decisions: tuple[ContactabilityDecision, ContactabilityDecision],
) -> list[str]:
    reason_values: list[str] = []
    for decision in decisions:
        if decision.allowed:
            continue
        for reason in decision.reasons:
            if reason.value not in reason_values:
                reason_values.append(reason.value)
    return reason_values


def _workflow_response(workflow: LeadWorkflow | None) -> LeadWorkflowResponse | None:
    if workflow is None:
        return None
    return LeadWorkflowResponse(
        workflow_id=workflow.workflow_id,
        campaign_id=workflow.campaign_id,
        state=workflow.state.value,
        current_step_id=str(workflow.current_step_id) if workflow.current_step_id else None,
        next_action_at=workflow.next_action_at,
        paused_search_track_version_id=workflow.paused_search_track_version_id,
        paused_search_track_step_id=workflow.paused_search_track_step_id,
        last_transition_at=workflow.last_transition_at,
        pause_reason=workflow.pause_reason,
        resume_reason=workflow.resume_reason,
    )


def _raise_for_override_error(status_value: str, reasons: list[str]) -> None:
    if status_value == PausedSearchWorkflowOverrideStatus.REJECTED.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reasons)
    if status_value == PausedSearchWorkflowOverrideStatus.NOT_FOUND.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=reasons)
    if status_value == PausedSearchWorkflowOverrideStatus.INVALID.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reasons)


def _transition_response(transition: WorkflowTransition) -> WorkflowTransitionResponse:
    return WorkflowTransitionResponse(
        transition_id=transition.transition_id,
        workflow_id=transition.workflow_id,
        lead_id=transition.lead_id,
        campaign_id=transition.campaign_id,
        from_state=transition.from_state.value if transition.from_state else None,
        to_state=transition.to_state.value,
        reason_code=transition.reason_code.value,
        actor_user_id=transition.actor_user_id,
        created_at=transition.created_at,
        metadata=dict(transition.metadata),
    )


def _inbound_message_response(message: InboundMessage) -> InboundMessageResponse:
    return InboundMessageResponse(
        inbound_message_id=message.inbound_message_id,
        conversation_id=message.conversation_id,
        channel=message.channel.value,
        provider=message.provider,
        provider_message_id=message.provider_message_id,
        from_address_redacted=message.from_address_redacted,
        to_address_redacted=message.to_address_redacted,
        body=message.body,
        received_at=message.received_at,
        processed_at=message.processed_at,
        classification_status=message.classification_status.value,
    )


def _outbound_message_response(message: OutboundMessage) -> OutboundMessageResponse:
    return OutboundMessageResponse(
        message_id=message.message_id,
        campaign_id=message.campaign_id,
        cadence_step_id=message.cadence_step_id,
        channel=message.channel.value,
        status=message.status.value,
        body=message.body,
        subject=message.subject,
        scheduled_for=message.scheduled_for,
        planned_at=message.planned_at,
        sent_at=message.sent_at,
        provider_send_status=message.provider_send_status.value,
        provider_name=message.provider_name,
        provider_delivery_status=(
            message.provider_delivery_status.value if message.provider_delivery_status else None
        ),
        delivered_at=message.delivered_at,
        failure_reason=message.failure_reason,
    )
