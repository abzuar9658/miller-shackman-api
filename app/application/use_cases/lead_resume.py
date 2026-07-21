from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance import (
    ContactChannel,
    ContactSuppressionKind,
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
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class LeadResumeEligibilityStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadResumeEligibilityReasonCode(StrEnum):
    NO_WORKFLOW = "no_workflow"
    WORKFLOW_STATE_NOT_RESUMABLE = "workflow_state_not_resumable"
    WORKFLOW_ALREADY_ACTIVE = "workflow_already_active"
    HANDOFF_REQUIRES_MANAGER = "handoff_requires_manager"
    SUPPRESSION_REQUIRES_MANAGER = "suppression_requires_manager"
    SUPPRESSION_NOT_RESUMABLE = "suppression_not_resumable"
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
    signal_queued: bool = False


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
            actor,
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
    lead_workflow_repository: LeadWorkflowRepository,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    external_event_repository: ExternalEventRepository,
    commit: Callable[[], Awaitable[None]],
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

    resume_reason = reason.strip()
    workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
    policy = await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
    eligibility = _build_resume_eligibility(
        actor,
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
    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.ACTIVE_NURTURE,
        reason_code=WorkflowTransitionReasonCode.MANUAL_RESUME,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        actor_user_id=actor.user_id,
        external_event_id=external_event.external_event_id,
        metadata={"reason": resume_reason},
        resume_reason=resume_reason,
    )
    if transition.status != WorkflowStateTransitionStatus.UPDATED or transition.workflow is None:
        return ResumeLeadWorkflowResult(
            status=LeadResumeActionStatus.NOT_RESUMABLE,
            eligibility=eligibility,
            workflow_id=eligibility.workflow_id,
            workflow_state=eligibility.workflow_state,
            reasons=(LeadResumeActionReasonCode.MANUAL_REVIEW_REQUIRED,),
        )

    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=workspace_id,
            workflow_id=transition.workflow.workflow_id,
            temporal_workflow_id=transition.workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.RESUME_REQUESTED,
            payload={
                "lead_id": str(lead_id),
                "occurred_at": now.isoformat(),
                "reason": resume_reason,
                "actor_user_id": str(actor.user_id),
                "external_event_id": str(external_event.external_event_id),
            },
            idempotency_key=f"resume-requested:{external_event.external_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await commit()

    return ResumeLeadWorkflowResult(
        status=LeadResumeActionStatus.REQUESTED,
        eligibility=eligibility,
        workflow_id=transition.workflow.workflow_id,
        workflow_state=transition.workflow.state,
        signal_queued=True,
    )


def _build_resume_eligibility(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow | None,
    policy: WorkspaceContactPolicy,
) -> LeadResumeEligibility:
    reasons: list[LeadResumeEligibilityReasonCode] = []

    if workflow is None:
        reasons.append(LeadResumeEligibilityReasonCode.NO_WORKFLOW)
    else:
        reasons.extend(_workflow_resume_reasons(actor, lead, workflow))

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


def _workflow_resume_reasons(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow,
) -> tuple[LeadResumeEligibilityReasonCode, ...]:
    if workflow.state == WorkflowState.SUPPRESSED:
        return (LeadResumeEligibilityReasonCode.SUPPRESSION_NOT_RESUMABLE,)
    if workflow.state in _active_or_recovering_states():
        return (LeadResumeEligibilityReasonCode.WORKFLOW_ALREADY_ACTIVE,)
    if workflow.state in {WorkflowState.HUMAN_HANDOFF, WorkflowState.HUMAN_OWNED}:
        if _has_global_resume_permission(actor, lead):
            return ()
        return (LeadResumeEligibilityReasonCode.HANDOFF_REQUIRES_MANAGER,)
    if workflow.state == WorkflowState.PAUSED:
        restriction = _paused_resume_restriction_reason(workflow.pause_reason)
        if restriction is None:
            return ()
        if restriction == LeadResumeEligibilityReasonCode.SUPPRESSION_NOT_RESUMABLE:
            return (restriction,)
        if _has_global_resume_permission(actor, lead):
            return ()
        return (restriction,)
    if workflow.state not in _resumable_states():
        return (LeadResumeEligibilityReasonCode.WORKFLOW_STATE_NOT_RESUMABLE,)
    return ()


def _paused_resume_restriction_reason(
    pause_reason: str | None,
) -> LeadResumeEligibilityReasonCode | None:
    if pause_reason is None:
        return None
    if pause_reason == WorkflowTransitionReasonCode.HUMAN_HANDOFF_REQUIRED.value:
        return LeadResumeEligibilityReasonCode.HANDOFF_REQUIRES_MANAGER
    if pause_reason == WorkflowTransitionReasonCode.OPT_OUT_DETECTED.value:
        return LeadResumeEligibilityReasonCode.SUPPRESSION_REQUIRES_MANAGER
    if pause_reason in {
        ContactSuppressionKind.SMS_OPT_OUT.value,
        ContactSuppressionKind.EMAIL_UNSUBSCRIBED.value,
    }:
        return LeadResumeEligibilityReasonCode.SUPPRESSION_REQUIRES_MANAGER
    if pause_reason == ContactSuppressionKind.DO_NOT_CONTACT.value:
        return LeadResumeEligibilityReasonCode.SUPPRESSION_NOT_RESUMABLE
    return None


def _has_global_resume_permission(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
) -> bool:
    decision = evaluate_permission(
        actor,
        PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
        PermissionContext(
            acts_on_assigned_lead=_acts_on_assigned_lead(actor, lead),
            handoff_resume_reason_provided=True,
        ),
    )
    return decision.allowed


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


def _active_or_recovering_states() -> frozenset[WorkflowState]:
    return frozenset(
        {
            WorkflowState.ACTIVE_NURTURE,
            WorkflowState.WAITING_FOR_RESPONSE,
            WorkflowState.RESPONSE_PROCESSING,
        }
    )
