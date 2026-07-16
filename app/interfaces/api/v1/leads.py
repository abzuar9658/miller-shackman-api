from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.application.ports.lead_activity import LeadActivityItem
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
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
from app.application.use_cases.lead_read import (
    LeadDetailView,
    LeadReadStatus,
    LeadReadView,
    get_lead_detail_view,
    list_lead_views,
)
from app.application.use_cases.lead_resume import (
    LeadResumeActionStatus,
    LeadResumeEligibilityStatus,
    get_lead_resume_eligibility,
    resume_lead_workflow,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.compliance import (
    ContactabilityDecision,
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.conversations import InboundMessage
from app.domain.identity import AuthenticatedActor
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowTransition
from app.interfaces.api.dependencies.lead_draft_review import (
    LeadDraftReviewActionBundle,
    get_lead_draft_review_action_bundle,
)
from app.interfaces.api.dependencies.lead_manual_enrollment import (
    LeadManualEnrollmentBundle,
    get_lead_manual_enrollment_bundle,
)
from app.interfaces.api.dependencies.lead_read import LeadReadBundle, get_lead_read_bundle
from app.interfaces.api.dependencies.lead_resume import (
    LeadResumeActionBundle,
    LeadResumeReadBundle,
    get_lead_resume_action_bundle,
    get_lead_resume_read_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.leads import (
    ApproveRejectedDraftReviewRequest,
    ApproveRejectedDraftReviewResponse,
    InboundMessageResponse,
    LeadActivityItemResponse,
    LeadChannelContactabilityResponse,
    LeadChannelSendabilityResponse,
    LeadContactabilityResponse,
    LeadDetailResponse,
    LeadListItemResponse,
    LeadListResponse,
    LeadManualEnrollmentOptionResponse,
    LeadManualEnrollmentOptionsResponse,
    LeadResponse,
    LeadResumeEligibilityResponse,
    LeadSendabilityResponse,
    LeadWorkflowResponse,
    OutboundMessageResponse,
    RejectedDraftReviewResponse,
    ResumeLeadWorkflowRequest,
    ResumeLeadWorkflowResponse,
    StartLeadManualEnrollmentRequest,
    StartLeadManualEnrollmentResponse,
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
    )
    if result.status == LeadReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
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
        workflow_repository=bundle.workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        activity_repository=bundle.activity_repository,
        rejected_draft_review_repository=bundle.rejected_draft_review_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        outbound_message_repository=bundle.outbound_message_repository,
        handoff_repository=bundle.handoff_repository,
        user_repository=bundle.user_repository,
    )
    if result.status == LeadReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
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
        lead_repository=bundle.lead_repository,
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
        lead_repository=bundle.lead_repository,
        campaign_admin_repository=bundle.campaign_admin_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        temporal_workflow_starter=bundle.temporal_workflow_starter,
        commit=bundle.session.commit,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    if result.status == LeadManualEnrollmentActionStatus.REJECTED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=["permission_denied"])
    if result.status == LeadManualEnrollmentActionStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in result.reasons],
        )
    await bundle.session.commit()
    return StartLeadManualEnrollmentResponse(
        status=result.status.value,
        campaign_id=result.campaign_id,
        campaign_version_id=result.campaign_version_id,
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
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        handoff_repository=bundle.handoff_repository,
        campaign_enrollment_repository=bundle.campaign_enrollment_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_workflow_starter=bundle.temporal_workflow_starter,
        lead_nurture_workflow_signaler=bundle.lead_nurture_workflow_signaler,
        external_event_repository=bundle.external_event_repository,
        commit=bundle.session.commit,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
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
        signal_failure_reason=result.signal_failure_reason,
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
        commit=bundle.session.commit,
        sms_provider=bundle.sms_provider,
        email_provider=bundle.email_provider,
        lead_nurture_workflow_signaler=bundle.lead_nurture_workflow_signaler,
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
        signal_failure_reason=result.signal_failure_reason,
    )


def _lead_list_item_response(
    view: LeadReadView,
    contact_policy: WorkspaceContactPolicy,
) -> LeadListItemResponse:
    activity_summary = view.activity_summary
    return LeadListItemResponse(
        lead=_lead_response(view.lead, view.assigned_agent_name, contact_policy),
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
        latest_workflow=_workflow_response(view.lead.latest_workflow),
        latest_handoff=handoff_response(view.lead.latest_handoff)
        if view.lead.latest_handoff
        else None,
        workflow_transitions=[_transition_response(item) for item in view.workflow_transitions],
        rejected_draft_reviews=[
            _rejected_draft_review_response(item) for item in view.rejected_draft_reviews
        ],
        activity_log=[_activity_item_response(item) for item in view.activity_items],
        inbound_messages=[_inbound_message_response(item) for item in view.inbound_messages],
        outbound_messages=[_outbound_message_response(item) for item in view.outbound_messages],
        handoffs=[handoff_response(item) for item in view.handoffs],
    )


def _activity_item_response(item: LeadActivityItem) -> LeadActivityItemResponse:
    return LeadActivityItemResponse(
        activity_id=item.activity_id,
        lead_id=item.lead_id,
        kind=item.kind.value,
        occurred_at=item.occurred_at,
        title=item.title,
        preview=item.preview,
        channel=item.channel,
        direction=item.direction,
        status=item.status,
        actor_name=item.actor_name,
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
        facts_derived_at=lead.facts_derived_at,
        last_activity_at=lead.last_activity_at,
        last_meaningful_communication_at=lead.last_meaningful_communication_at,
        last_agent_activity_at=lead.last_agent_activity_at,
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
        sendable_channels=[
            decision.channel.value for decision in decisions if decision.allowed
        ],
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
        last_transition_at=workflow.last_transition_at,
        pause_reason=workflow.pause_reason,
        resume_reason=workflow.resume_reason,
    )


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
