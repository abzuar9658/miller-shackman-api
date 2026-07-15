from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import WorkspaceContactPolicyRepository
from app.application.ports.temporal import (
    LeadNurtureWorkflowSignaler,
    ResumeLeadNurtureWorkflowSignal,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import (
    ContactChannel,
    WorkspaceContactPolicy,
    default_workspace_contact_policy,
    evaluate_contactability,
)
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionDecision,
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
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    NOT_RESUMABLE = "not_resumable"
    SIGNAL_FAILED = "signal_failed"


class LeadResumeActionReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    SIGNAL_FAILED = "signal_failed"


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

    workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
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
    workflow_repository: LeadReadWorkflowRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
    now: datetime,
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

    try:
        await lead_nurture_workflow_signaler.signal_resume_lead_nurture_workflow(
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal=ResumeLeadNurtureWorkflowSignal(
                workspace_id=workspace_id,
                lead_id=lead_id,
                occurred_at=now,
                reason=reason.strip(),
                actor_user_id=actor.user_id,
                external_event_id=id_generator(),
            ),
        )
    except Exception as exc:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.SIGNAL_FAILED,
            eligibility=eligibility,
            workflow_id=workflow.workflow_id,
            workflow_state=workflow.state,
            reasons=(LeadResumeActionReasonCode.SIGNAL_FAILED,),
            signal_failure_reason=str(exc),
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
