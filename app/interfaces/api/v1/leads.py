from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

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
from app.domain.conversations import InboundMessage
from app.domain.identity import AuthenticatedActor
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowTransition
from app.interfaces.api.dependencies.lead_read import LeadReadBundle, get_lead_read_bundle
from app.interfaces.api.dependencies.lead_resume import (
    LeadResumeActionBundle,
    LeadResumeReadBundle,
    get_lead_resume_action_bundle,
    get_lead_resume_read_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.schemas.leads import (
    InboundMessageResponse,
    LeadDetailResponse,
    LeadListItemResponse,
    LeadListResponse,
    LeadResponse,
    LeadResumeEligibilityResponse,
    LeadWorkflowResponse,
    OutboundMessageResponse,
    ResumeLeadWorkflowRequest,
    ResumeLeadWorkflowResponse,
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
        handoff_repository=bundle.handoff_repository,
        user_repository=bundle.user_repository,
    )
    if result.status == LeadReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in result.reasons],
        )
    return LeadListResponse(
        status=result.status.value,
        leads=[_lead_list_item_response(view) for view in result.views],
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
    return _lead_detail_response(result.view)


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
        lead_nurture_workflow_signaler=bundle.lead_nurture_workflow_signaler,
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
    return ResumeLeadWorkflowResponse(
        status=result.status.value,
        workflow_id=result.workflow_id,
        workflow_state=result.workflow_state.value if result.workflow_state is not None else None,
        reasons=[reason.value for reason in result.reasons],
        signal_failure_reason=result.signal_failure_reason,
    )


def _lead_list_item_response(view: LeadReadView) -> LeadListItemResponse:
    return LeadListItemResponse(
        lead=_lead_response(view.lead, view.assigned_agent_name),
        latest_workflow=_workflow_response(view.latest_workflow),
        latest_handoff=handoff_response(view.latest_handoff) if view.latest_handoff else None,
    )


def _lead_detail_response(view: LeadDetailView) -> LeadDetailResponse:
    return LeadDetailResponse(
        status=LeadReadStatus.OK.value,
        lead=_lead_response(view.lead.lead, view.lead.assigned_agent_name),
        latest_workflow=_workflow_response(view.lead.latest_workflow),
        latest_handoff=handoff_response(view.lead.latest_handoff)
        if view.lead.latest_handoff
        else None,
        workflow_transitions=[_transition_response(item) for item in view.workflow_transitions],
        inbound_messages=[_inbound_message_response(item) for item in view.inbound_messages],
        outbound_messages=[_outbound_message_response(item) for item in view.outbound_messages],
        handoffs=[handoff_response(item) for item in view.handoffs],
    )


def _lead_response(lead: CanonicalLeadRecord, assigned_agent_name: str | None) -> LeadResponse:
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
        facts_derived_at=lead.facts_derived_at,
        last_activity_at=lead.last_activity_at,
        last_meaningful_communication_at=lead.last_meaningful_communication_at,
        last_agent_activity_at=lead.last_agent_activity_at,
    )


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
