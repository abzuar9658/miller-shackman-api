from uuid import UUID

from app.domain.lead_assignment import (
    AssignmentResolutionStatus,
    EffectiveOwnerSource,
    LeadAssignmentFacts,
    resolve_lead_assignment,
)

ASSIGNED_AGENT_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
FALLBACK_MANAGER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_resolve_lead_assignment_returns_crm_mapping_when_assignment_is_valid() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=True,
            assigned_agent_user_id=ASSIGNED_AGENT_USER_ID,
            assigned_agent_user_active=True,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.RESOLVED
    assert decision.assigned_agent_user_id == ASSIGNED_AGENT_USER_ID
    assert decision.effective_owner_user_id == ASSIGNED_AGENT_USER_ID
    assert decision.effective_owner_source == EffectiveOwnerSource.CRM_MAPPING


def test_resolve_lead_assignment_routes_unmapped_agent_to_fallback_manager() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=True,
            fallback_manager_user_id=FALLBACK_MANAGER_USER_ID,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.UNMAPPED_CRM_AGENT
    assert decision.assigned_agent_user_id is None
    assert decision.effective_owner_user_id == FALLBACK_MANAGER_USER_ID
    assert decision.effective_owner_source == EffectiveOwnerSource.WORKSPACE_MANAGER_FALLBACK


def test_resolve_lead_assignment_routes_inactive_crm_agent_to_fallback_manager() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=False,
            fallback_manager_user_id=FALLBACK_MANAGER_USER_ID,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.CRM_AGENT_INACTIVE
    assert decision.effective_owner_user_id == FALLBACK_MANAGER_USER_ID


def test_resolve_lead_assignment_routes_inactive_app_user_to_fallback_manager() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=True,
            assigned_agent_user_id=ASSIGNED_AGENT_USER_ID,
            assigned_agent_user_active=False,
            fallback_manager_user_id=FALLBACK_MANAGER_USER_ID,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.APP_USER_INACTIVE
    assert decision.assigned_agent_user_id == ASSIGNED_AGENT_USER_ID
    assert decision.effective_owner_user_id == FALLBACK_MANAGER_USER_ID


def test_resolve_lead_assignment_routes_ambiguous_mapping_to_fallback_manager() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=True,
            assigned_agent_user_id=ASSIGNED_AGENT_USER_ID,
            assigned_agent_user_active=True,
            ambiguous_assigned_agent=True,
            fallback_manager_user_id=FALLBACK_MANAGER_USER_ID,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.AMBIGUOUS_CRM_AGENT
    assert decision.effective_owner_user_id == FALLBACK_MANAGER_USER_ID


def test_resolve_lead_assignment_reports_missing_fallback_manager_when_unresolved() -> None:
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=True,
            crm_agent_active=True,
        ),
    )

    assert decision.status == AssignmentResolutionStatus.FALLBACK_MANAGER_MISSING
    assert decision.effective_owner_user_id is None
    assert decision.effective_owner_source is None
