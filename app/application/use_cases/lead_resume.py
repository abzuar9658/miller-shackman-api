from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import (
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadWorkflowRepository,
)
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    ExternalEventRepository,
    LeadWorkflowRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import (
    LeadNurtureWorkflowSignaler,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowStarter,
)
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.internal_external_events import (
    create_internal_external_event,
    update_internal_external_event_status,
)
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.domain.campaigns.enrollment import CampaignEnrollmentSource, CampaignEnrollmentStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import (
    ContactChannel,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
    evaluate_contactability,
)
from app.domain.conversations import Handoff, HandoffStatus, InboundMessage
from app.domain.crm_sync import ExternalEventStatus
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionDecision,
    WorkspaceMembershipRole,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowState


class LeadResumeEligibilityStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadResumeEligibilityReasonCode(StrEnum):
    NO_WORKFLOW = "no_workflow"
    WORKFLOW_STATE_NOT_RESUMABLE = "workflow_state_not_resumable"
    NO_CONTACTABLE_CHANNELS = "no_contactable_channels"


class LeadResumeActionStatus(StrEnum):
    REQUESTED = "requested"
    RESTARTED = "restarted"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    NOT_RESUMABLE = "not_resumable"
    SIGNAL_FAILED = "signal_failed"


class LeadResumeActionReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    SIGNAL_FAILED = "signal_failed"
    HANDOFF_REQUIRED = "handoff_required"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    RESTART_FAILED = "restart_failed"


@dataclass(frozen=True)
class LeadResumeEligibility:
    can_resume: bool
    workflow_id: UUID | None = None
    workflow_state: WorkflowState | None = None
    contactable_channels: tuple[ContactChannel, ...] = ()
    reasons: tuple[LeadResumeEligibilityReasonCode, ...] = ()
    blocked_contactability_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LeadResumeEligibilityResult:
    status: LeadResumeEligibilityStatus
    eligibility: LeadResumeEligibility | None = None
    reasons: tuple[LeadResumeActionReasonCode, ...] = ()


@dataclass(frozen=True)
class ResumeLeadWorkflowResult:
    status: LeadResumeActionStatus
    eligibility: LeadResumeEligibility | None = None
    workflow_id: UUID | None = None
    workflow_state: WorkflowState | None = None
    reasons: tuple[LeadResumeActionReasonCode, ...] = ()
    signal_failure_reason: str | None = None


async def get_lead_resume_eligibility(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadReadLeadRepository,
    workflow_repository: LeadReadWorkflowRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
) -> LeadResumeEligibilityResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return LeadResumeEligibilityResult(
            status=LeadResumeEligibilityStatus.NOT_FOUND,
            reasons=(LeadResumeActionReasonCode.LEAD_NOT_FOUND,),
        )

    permission = _resume_permission(actor, lead, resume_reason_provided=True)
    if not permission.allowed:
        return LeadResumeEligibilityResult(
            status=LeadResumeEligibilityStatus.REJECTED,
            reasons=(LeadResumeActionReasonCode.PERMISSION_DENIED,),
        )

    workflow = await workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    policy = await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
    return LeadResumeEligibilityResult(
        status=LeadResumeEligibilityStatus.OK,
        eligibility=_build_resume_eligibility(
            lead,
            workflow,
            policy or default_workspace_contact_policy(workspace_id),
        ),
    )


async def resume_lead_workflow(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason: str,
    lead_repository: LeadReadLeadRepository,
    workflow_repository: LeadWorkflowRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    inbound_message_repository: LeadReadInboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
    external_event_repository: ExternalEventRepository,
    commit: Callable[[], Awaitable[None]],
    event_bus: EventBus | None,
    now: datetime,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    id_generator: Callable[[], UUID] = uuid4,
) -> ResumeLeadWorkflowResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.NOT_FOUND,
            reasons=(LeadResumeActionReasonCode.LEAD_NOT_FOUND,),
        )

    permission = _resume_permission(
        actor,
        lead,
        resume_reason_provided=bool(reason.strip()),
    )
    if not permission.allowed:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.REJECTED,
            reasons=(LeadResumeActionReasonCode.PERMISSION_DENIED,),
        )

    resume_reason = reason.strip()
    workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
    policy = await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
    eligibility = _build_resume_eligibility(
        lead,
        workflow,
        policy or default_workspace_contact_policy(workspace_id),
    )
    if not eligibility.can_resume or workflow is None:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.NOT_RESUMABLE,
            eligibility=eligibility,
            workflow_id=eligibility.workflow_id,
            workflow_state=eligibility.workflow_state,
        )

    external_event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.manual_resume_requested",
        now=now,
        payload_redacted={"actor_user_id": str(actor.user_id)},
        id_generator=id_generator,
    )
    await commit()
    try:
        await lead_nurture_workflow_signaler.signal_resume_lead_nurture_workflow(
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal=ResumeLeadNurtureWorkflowSignal(
                workspace_id=workspace_id,
                lead_id=lead_id,
                occurred_at=now,
                reason=resume_reason,
                actor_user_id=actor.user_id,
                external_event_id=external_event.external_event_id,
            ),
        )
    except Exception as exc:
        await update_internal_external_event_status(
            external_event_repository=external_event_repository,
            event=external_event,
            status=ExternalEventStatus.FAILED,
            now=now,
            failure_reason=str(exc),
        )
        return await _recover_failed_resume_signal(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow=workflow,
            eligibility=eligibility,
            inbound_message_repository=inbound_message_repository,
            handoff_repository=handoff_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            workspace_operational_control_repository=workspace_operational_control_repository,
            commit=commit,
            event_bus=event_bus,
            now=now,
            signal_failure_reason=str(exc),
        )

    await update_internal_external_event_status(
        external_event_repository=external_event_repository,
        event=external_event,
        status=ExternalEventStatus.PROCESSED,
        now=now,
    )

    return ResumeLeadWorkflowResult(
        status=LeadResumeActionStatus.REQUESTED,
        eligibility=eligibility,
        workflow_id=workflow.workflow_id,
        workflow_state=workflow.state,
    )


def _build_resume_eligibility(
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow | None,
    policy: WorkspaceContactPolicy,
) -> LeadResumeEligibility:
    reasons: list[LeadResumeEligibilityReasonCode] = []

    if workflow is None:
        reasons.append(LeadResumeEligibilityReasonCode.NO_WORKFLOW)
    elif workflow.state not in _resumable_states():
        reasons.append(LeadResumeEligibilityReasonCode.WORKFLOW_STATE_NOT_RESUMABLE)

    contactable_channels, blocked_reasons = _contactable_channels(lead, policy)
    if not contactable_channels:
        reasons.append(LeadResumeEligibilityReasonCode.NO_CONTACTABLE_CHANNELS)

    return LeadResumeEligibility(
        can_resume=not reasons,
        workflow_id=workflow.workflow_id if workflow is not None else None,
        workflow_state=workflow.state if workflow is not None else None,
        contactable_channels=contactable_channels,
        reasons=tuple(reasons),
        blocked_contactability_reasons=blocked_reasons,
    )


async def _recover_failed_resume_signal(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    workflow: LeadWorkflow,
    eligibility: LeadResumeEligibility,
    inbound_message_repository: LeadReadInboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    commit: Callable[[], Awaitable[None]],
    event_bus: EventBus | None,
    now: datetime,
    signal_failure_reason: str,
) -> ResumeLeadWorkflowResult:
    latest_handoff = await _latest_handoff(handoff_repository, workspace_id, lead_id)
    if latest_handoff is not None and latest_handoff.status not in _resolved_handoff_states():
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.NOT_RESUMABLE,
            eligibility=eligibility,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(LeadResumeActionReasonCode.HANDOFF_REQUIRED,),
            signal_failure_reason=signal_failure_reason,
        )

    latest_inbound = await _latest_inbound_message(
        inbound_message_repository,
        workspace_id,
        lead_id,
    )
    if latest_inbound is not None:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.NOT_RESUMABLE,
            eligibility=eligibility,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(LeadResumeActionReasonCode.MANUAL_REVIEW_REQUIRED,),
            signal_failure_reason=signal_failure_reason,
        )

    enrollment = await campaign_enrollment_repository.get_by_lead_and_campaign(
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=workflow.campaign_id,
    )
    if enrollment is None:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.SIGNAL_FAILED,
            eligibility=eligibility,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(
                LeadResumeActionReasonCode.SIGNAL_FAILED,
                LeadResumeActionReasonCode.RESTART_FAILED,
            ),
            signal_failure_reason=(
                f"{signal_failure_reason} Recovery could not restart the lead because the "
                "campaign enrollment context was missing."
            ),
        )

    if enrollment.status not in {
        CampaignEnrollmentStatus.COMPLETED,
        CampaignEnrollmentStatus.SUPPRESSED,
        CampaignEnrollmentStatus.CLOSED,
    }:
        await campaign_enrollment_repository.save(
            replace(
                enrollment,
                status=CampaignEnrollmentStatus.CLOSED,
                ended_at=now,
                updated_at=now,
            )
        )

    restart_result = await start_single_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=workflow.campaign_id,
        campaign_version_id=enrollment.campaign_version_id,
        lead_id=lead_id,
        source=_recovery_enrollment_source(actor),
        reason_codes=("resume_recovery_restart",),
        actor_user_id=actor.user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        commit=commit,
        now=now,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
    )
    if restart_result.status != LeadStartStatus.STARTED:
        restart_failure = restart_result.error or "Step-1 recovery restart failed."
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.SIGNAL_FAILED,
            eligibility=eligibility,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(
                LeadResumeActionReasonCode.SIGNAL_FAILED,
                LeadResumeActionReasonCode.RESTART_FAILED,
            ),
            signal_failure_reason=(
                f"{signal_failure_reason} Recovery restart failed: {restart_failure}"
            ),
        )

    return ResumeLeadWorkflowResult(
        status=LeadResumeActionStatus.RESTARTED,
        eligibility=eligibility,
        workflow_id=restart_result.workflow_id,
        workflow_state=WorkflowState.QUEUED,
    )


def _resume_permission(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    *,
    resume_reason_provided: bool,
) -> PermissionDecision:
    context = PermissionContext(
        acts_on_assigned_lead=_acts_on_assigned_lead(actor, lead),
        handoff_resume_reason_provided=resume_reason_provided,
    )
    any_lead_decision = evaluate_permission(
        actor,
        PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
        context,
    )
    if any_lead_decision.allowed:
        return any_lead_decision
    return evaluate_permission(
        actor,
        PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
        context,
    )


def _acts_on_assigned_lead(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    return is_actor_assigned_to_lead(actor, lead)


async def _latest_handoff(
    handoff_repository: LeadReadHandoffRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
) -> Handoff | None:
    handoffs = await handoff_repository.list_for_lead(workspace_id, lead_id, limit=1)
    return handoffs[0] if handoffs else None


async def _latest_inbound_message(
    inbound_message_repository: LeadReadInboundMessageRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
) -> InboundMessage | None:
    messages = await inbound_message_repository.list_for_lead(workspace_id, lead_id, limit=1)
    return messages[0] if messages else None


def _contactable_channels(
    lead: CanonicalLeadRecord,
    policy: WorkspaceContactPolicy,
) -> tuple[tuple[ContactChannel, ...], tuple[str, ...]]:
    facts = contactability_facts_from_canonical_lead(lead)
    allowed: list[ContactChannel] = []
    blocked_reasons: list[str] = []

    for channel in (ContactChannel.SMS, ContactChannel.EMAIL):
        if not _has_destination_for_channel(lead, channel):
            continue
        decision = evaluate_contactability(facts, policy, channel)
        if decision.allowed:
            allowed.append(channel)
            continue
        blocked_reasons.extend(reason.value for reason in decision.reasons)

    return tuple(allowed), tuple(dict.fromkeys(blocked_reasons))


def _has_destination_for_channel(lead: CanonicalLeadRecord, channel: ContactChannel) -> bool:
    if channel == ContactChannel.SMS:
        return lead.has_sms_capable_phone and lead.primary_phone is not None
    return lead.has_email and lead.primary_email is not None


def _resumable_states() -> frozenset[WorkflowState]:
    return frozenset({WorkflowState.PAUSED, WorkflowState.HUMAN_HANDOFF, WorkflowState.HUMAN_OWNED})


def _resolved_handoff_states() -> frozenset[HandoffStatus]:
    return frozenset({HandoffStatus.RESOLVED, HandoffStatus.CANCELLED})


def _recovery_enrollment_source(actor: AuthenticatedActor) -> CampaignEnrollmentSource:
    return (
        CampaignEnrollmentSource.MANUAL_AGENT
        if actor.active_role == WorkspaceMembershipRole.ASSIGNED_AGENT
        else CampaignEnrollmentSource.MANUAL_ADMIN
    )
