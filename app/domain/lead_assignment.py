from dataclasses import dataclass
from enum import StrEnum

from app.domain.common.ids import UserId


class AssignmentResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNMAPPED_CRM_AGENT = "unmapped_crm_agent"
    AMBIGUOUS_CRM_AGENT = "ambiguous_crm_agent"
    CRM_AGENT_INACTIVE = "crm_agent_inactive"
    APP_USER_INACTIVE = "app_user_inactive"
    UNRESOLVED = "unresolved"
    FALLBACK_MANAGER_MISSING = "fallback_manager_missing"


class EffectiveOwnerSource(StrEnum):
    CRM_MAPPING = "crm_mapping"
    WORKSPACE_MANAGER_FALLBACK = "workspace_manager_fallback"


@dataclass(frozen=True)
class LeadAssignmentFacts:
    crm_owner_present: bool
    crm_agent_active: bool | None = None
    assigned_agent_user_id: UserId | None = None
    assigned_agent_user_active: bool | None = None
    ambiguous_assigned_agent: bool = False
    fallback_manager_user_id: UserId | None = None


@dataclass(frozen=True)
class LeadAssignmentDecision:
    status: AssignmentResolutionStatus
    assigned_agent_user_id: UserId | None = None
    effective_owner_user_id: UserId | None = None
    effective_owner_source: EffectiveOwnerSource | None = None


def resolve_lead_assignment(facts: LeadAssignmentFacts) -> LeadAssignmentDecision:
    base_status = _base_status(facts)
    if base_status == AssignmentResolutionStatus.RESOLVED:
        return LeadAssignmentDecision(
            status=AssignmentResolutionStatus.RESOLVED,
            assigned_agent_user_id=facts.assigned_agent_user_id,
            effective_owner_user_id=facts.assigned_agent_user_id,
            effective_owner_source=EffectiveOwnerSource.CRM_MAPPING,
        )

    if facts.fallback_manager_user_id is None:
        return LeadAssignmentDecision(
            status=AssignmentResolutionStatus.FALLBACK_MANAGER_MISSING,
            assigned_agent_user_id=facts.assigned_agent_user_id,
        )

    return LeadAssignmentDecision(
        status=base_status,
        assigned_agent_user_id=facts.assigned_agent_user_id,
        effective_owner_user_id=facts.fallback_manager_user_id,
        effective_owner_source=EffectiveOwnerSource.WORKSPACE_MANAGER_FALLBACK,
    )


def _base_status(facts: LeadAssignmentFacts) -> AssignmentResolutionStatus:
    if not facts.crm_owner_present:
        return AssignmentResolutionStatus.UNMAPPED_CRM_AGENT
    if facts.ambiguous_assigned_agent:
        return AssignmentResolutionStatus.AMBIGUOUS_CRM_AGENT
    if facts.crm_agent_active is False:
        return AssignmentResolutionStatus.CRM_AGENT_INACTIVE
    if facts.assigned_agent_user_id is None:
        return AssignmentResolutionStatus.UNMAPPED_CRM_AGENT
    if facts.assigned_agent_user_active is not True:
        return AssignmentResolutionStatus.APP_USER_INACTIVE
    return AssignmentResolutionStatus.RESOLVED
