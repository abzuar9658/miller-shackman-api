from dataclasses import dataclass
from enum import StrEnum

from app.domain.identity.models import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)


class PermissionCapability(StrEnum):
    CREATE_WORKSPACE = "create_workspace"
    INVITE_WORKSPACE_USER = "invite_workspace_user"
    VIEW_OWN_ASSIGNED_LEAD = "view_own_assigned_lead"
    ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS = "enroll_own_lead_when_campaign_allows"
    ENROLL_ANY_ELIGIBLE_LEAD = "enroll_any_eligible_lead"
    VETO_OWN_PREFLIGHT_LEAD = "veto_own_preflight_lead"
    PAUSE_CAMPAIGN = "pause_campaign"
    LAUNCH_OR_PUBLISH_CAMPAIGN = "launch_or_publish_campaign"
    RESUME_AI_AFTER_HANDOFF_OWN_LEAD = "resume_ai_after_handoff_own_lead"
    RESUME_OR_REASSIGN_ANY_LEAD = "resume_or_reassign_any_lead"
    CHANGE_CONSENT_SUPPRESSION_POLICY = "change_consent_suppression_policy"


class PermissionReasonCode(StrEnum):
    USER_NOT_ACTIVE = "user_not_active"
    WORKSPACE_NOT_ACTIVE = "workspace_not_active"
    MEMBERSHIP_NOT_ACTIVE = "membership_not_active"
    ROLE_NOT_ALLOWED = "role_not_allowed"
    PLATFORM_SUPER_ADMIN_RESTRICTED = "platform_super_admin_restricted"
    OWNERSHIP_REQUIRED = "ownership_required"
    CAMPAIGN_DISALLOWS_ASSIGNED_AGENT_ENROLLMENT = (
        "campaign_disallows_assigned_agent_enrollment"
    )
    RESUME_REASON_REQUIRED = "resume_reason_required"


@dataclass(frozen=True)
class PermissionContext:
    acts_on_assigned_lead: bool = False
    campaign_allows_assigned_agent_enrollment: bool = True
    handoff_resume_reason_provided: bool = True


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    capability: PermissionCapability
    reasons: tuple[PermissionReasonCode, ...] = ()


def evaluate_permission(
    actor: AuthenticatedActor,
    capability: PermissionCapability,
    context: PermissionContext | None = None,
) -> PermissionDecision:
    evaluation_context = context or PermissionContext()
    reasons: list[PermissionReasonCode] = []

    if actor.user_status != UserStatus.ACTIVE:
        reasons.append(PermissionReasonCode.USER_NOT_ACTIVE)

    if capability == PermissionCapability.CREATE_WORKSPACE:
        if reasons:
            return PermissionDecision(False, capability, tuple(reasons))
        return _evaluate_create_workspace_permission(actor, capability)

    _append_active_workspace_context_reasons(actor, reasons)
    if reasons:
        return PermissionDecision(False, capability, tuple(reasons))

    if actor.active_role == WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN:
        return PermissionDecision(
            allowed=False,
            capability=capability,
            reasons=(PermissionReasonCode.PLATFORM_SUPER_ADMIN_RESTRICTED,),
        )

    if actor.active_role is None or not _role_allows(capability, actor.active_role):
        return PermissionDecision(
            allowed=False,
            capability=capability,
            reasons=(PermissionReasonCode.ROLE_NOT_ALLOWED,),
        )

    reasons.extend(_context_reasons(actor, capability, evaluation_context))
    return PermissionDecision(
        allowed=not reasons,
        capability=capability,
        reasons=tuple(reasons),
    )


def _evaluate_create_workspace_permission(
    actor: AuthenticatedActor,
    capability: PermissionCapability,
) -> PermissionDecision:
    if actor.active_role == WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN:
        return PermissionDecision(allowed=True, capability=capability)

    reasons: list[PermissionReasonCode] = []
    _append_active_workspace_context_reasons(actor, reasons)
    if reasons:
        return PermissionDecision(False, capability, tuple(reasons))

    if actor.active_role != WorkspaceMembershipRole.BROKERAGE_ADMIN:
        reasons.append(PermissionReasonCode.ROLE_NOT_ALLOWED)

    return PermissionDecision(
        allowed=not reasons,
        capability=capability,
        reasons=tuple(reasons),
    )


def _append_active_workspace_context_reasons(
    actor: AuthenticatedActor,
    reasons: list[PermissionReasonCode],
) -> None:
    if actor.active_workspace_status != WorkspaceStatus.ACTIVE:
        reasons.append(PermissionReasonCode.WORKSPACE_NOT_ACTIVE)

    if actor.active_membership_status != WorkspaceMembershipStatus.ACTIVE:
        reasons.append(PermissionReasonCode.MEMBERSHIP_NOT_ACTIVE)


def _role_allows(
    capability: PermissionCapability,
    role: WorkspaceMembershipRole,
) -> bool:
    if role == WorkspaceMembershipRole.ASSIGNED_AGENT:
        return capability in {
            PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
            PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
            PermissionCapability.VETO_OWN_PREFLIGHT_LEAD,
            PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
        }

    if role == WorkspaceMembershipRole.MANAGER:
        return capability in {
            PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
            PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
            PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD,
            PermissionCapability.VETO_OWN_PREFLIGHT_LEAD,
            PermissionCapability.PAUSE_CAMPAIGN,
            PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
            PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
        }

    if role == WorkspaceMembershipRole.BROKERAGE_ADMIN:
        return capability in {
            PermissionCapability.CREATE_WORKSPACE,
            PermissionCapability.INVITE_WORKSPACE_USER,
            PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
            PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
            PermissionCapability.ENROLL_ANY_ELIGIBLE_LEAD,
            PermissionCapability.VETO_OWN_PREFLIGHT_LEAD,
            PermissionCapability.PAUSE_CAMPAIGN,
            PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN,
            PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
            PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
            PermissionCapability.CHANGE_CONSENT_SUPPRESSION_POLICY,
        }

    return capability == PermissionCapability.CREATE_WORKSPACE


def _context_reasons(
    actor: AuthenticatedActor,
    capability: PermissionCapability,
    context: PermissionContext,
) -> list[PermissionReasonCode]:
    if actor.active_role != WorkspaceMembershipRole.ASSIGNED_AGENT:
        return []

    reasons: list[PermissionReasonCode] = []

    if capability in {
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
        PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS,
        PermissionCapability.VETO_OWN_PREFLIGHT_LEAD,
        PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD,
    } and not context.acts_on_assigned_lead:
        reasons.append(PermissionReasonCode.OWNERSHIP_REQUIRED)

    if (
        capability == PermissionCapability.ENROLL_OWN_LEAD_WHEN_CAMPAIGN_ALLOWS
        and not context.campaign_allows_assigned_agent_enrollment
    ):
        reasons.append(PermissionReasonCode.CAMPAIGN_DISALLOWS_ASSIGNED_AGENT_ENROLLMENT)

    if (
        capability == PermissionCapability.RESUME_AI_AFTER_HANDOFF_OWN_LEAD
        and not context.handoff_resume_reason_provided
    ):
        reasons.append(PermissionReasonCode.RESUME_REASON_REQUIRED)

    return reasons