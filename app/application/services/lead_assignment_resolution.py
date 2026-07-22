from dataclasses import dataclass, replace
from datetime import datetime

from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
)
from app.domain.common.ids import CRMAgentRecordId, UserId, WorkspaceId
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import User, UserStatus, WorkspaceMembershipRole, WorkspaceMembershipStatus
from app.domain.lead_assignment import LeadAssignmentFacts, resolve_lead_assignment
from app.domain.leads import CanonicalLeadRecord, CRMProvider

_OWNER_ELIGIBLE_ROLES = frozenset(
    {
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        WorkspaceMembershipRole.MANAGER,
        WorkspaceMembershipRole.ASSIGNED_AGENT,
    }
)
_TRUSTED_MAPPING_STATUSES = frozenset(
    {
        CRMAgentMappingStatus.VERIFIED,
        CRMAgentMappingStatus.OVERRIDDEN,
    }
)


@dataclass(frozen=True)
class WorkspaceLeadAssignmentContext:
    crm_agents_by_external_id: dict[str, CRMAgent]
    trusted_mappings_by_agent_record_id: dict[CRMAgentRecordId, WorkspaceAgentCRMMapping]
    active_owner_user_ids: frozenset[UserId]
    ambiguous_user_ids: frozenset[UserId]
    fallback_manager_user_id: UserId | None


async def load_workspace_lead_assignment_context(
    *,
    workspace_id: WorkspaceId,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository,
    workspace_membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
    crm_provider: CRMProvider = CRMProvider.FOLLOW_UP_BOSS,
) -> WorkspaceLeadAssignmentContext:
    crm_agents = await crm_agent_repository.list_for_workspace(workspace_id)
    mappings = await workspace_agent_crm_mapping_repository.list_for_workspace(workspace_id)
    config = await workspace_agent_mapping_config_repository.get_by_workspace_id(workspace_id)
    memberships = await workspace_membership_repository.list_by_workspace_id(workspace_id)

    relevant_user_ids = {
        membership.user_id
        for membership in memberships
        if membership.role in _OWNER_ELIGIBLE_ROLES
    }
    relevant_user_ids.update(
        mapping.app_user_id
        for mapping in mappings
        if mapping.app_user_id is not None and mapping.mapping_status in _TRUSTED_MAPPING_STATUSES
    )
    if config is not None and config.unmapped_assignment_fallback_user_id is not None:
        relevant_user_ids.add(config.unmapped_assignment_fallback_user_id)

    users_by_id: dict[UserId, User | None] = {}
    for user_id in relevant_user_ids:
        users_by_id[user_id] = await user_repository.get_by_id(user_id)

    active_owner_user_ids = frozenset(
        membership.user_id
        for membership in memberships
        if membership.role in _OWNER_ELIGIBLE_ROLES
        and membership.status == WorkspaceMembershipStatus.ACTIVE
        and _is_active_user(users_by_id.get(membership.user_id))
    )
    active_manager_memberships = sorted(
        (
            membership
            for membership in memberships
            if membership.role == WorkspaceMembershipRole.MANAGER
            and membership.status == WorkspaceMembershipStatus.ACTIVE
            and _is_active_user(users_by_id.get(membership.user_id))
        ),
        key=lambda membership: (membership.created_at, str(membership.user_id)),
    )
    active_manager_user_ids = {membership.user_id for membership in active_manager_memberships}
    configured_fallback_user_id = (
        config.unmapped_assignment_fallback_user_id if config is not None else None
    )
    fallback_manager_user_id = (
        configured_fallback_user_id
        if configured_fallback_user_id in active_manager_user_ids
        else (active_manager_memberships[0].user_id if active_manager_memberships else None)
    )

    trusted_mappings = tuple(
        mapping
        for mapping in mappings
        if mapping.app_user_id is not None and mapping.mapping_status in _TRUSTED_MAPPING_STATUSES
    )
    mapping_count_by_user_id: dict[UserId, int] = {}
    for mapping in trusted_mappings:
        assert mapping.app_user_id is not None
        mapping_count_by_user_id[mapping.app_user_id] = (
            mapping_count_by_user_id.get(mapping.app_user_id, 0) + 1
        )

    return WorkspaceLeadAssignmentContext(
        crm_agents_by_external_id={
            agent.external_agent_id: agent
            for agent in crm_agents
            if agent.crm_provider == crm_provider
        },
        trusted_mappings_by_agent_record_id={
            mapping.crm_agent_record_id: mapping for mapping in trusted_mappings
        },
        active_owner_user_ids=active_owner_user_ids,
        ambiguous_user_ids=frozenset(
            user_id for user_id, count in mapping_count_by_user_id.items() if count > 1
        ),
        fallback_manager_user_id=fallback_manager_user_id,
    )


def apply_lead_assignment_resolution(
    lead: CanonicalLeadRecord,
    *,
    context: WorkspaceLeadAssignmentContext,
    now: datetime,
) -> CanonicalLeadRecord:
    crm_agent = (
        context.crm_agents_by_external_id.get(lead.assigned_agent_crm_id)
        if lead.assigned_agent_crm_id is not None
        else None
    )
    mapping = (
        context.trusted_mappings_by_agent_record_id.get(crm_agent.agent_record_id)
        if crm_agent is not None
        else None
    )
    assigned_agent_user_id = mapping.app_user_id if mapping is not None else None
    decision = resolve_lead_assignment(
        LeadAssignmentFacts(
            crm_owner_present=lead.assigned_agent_crm_id is not None,
            crm_agent_active=crm_agent.is_active if crm_agent is not None else None,
            assigned_agent_user_id=assigned_agent_user_id,
            assigned_agent_user_active=(
                assigned_agent_user_id in context.active_owner_user_ids
                if assigned_agent_user_id is not None
                else None
            ),
            ambiguous_assigned_agent=(
                assigned_agent_user_id in context.ambiguous_user_ids
                if assigned_agent_user_id is not None
                else False
            ),
            fallback_manager_user_id=context.fallback_manager_user_id,
        ),
    )
    return replace(
        lead,
        assigned_agent_user_id=decision.assigned_agent_user_id,
        effective_owner_user_id=decision.effective_owner_user_id,
        effective_owner_source=decision.effective_owner_source,
        assignment_resolution_status=decision.status,
        assignment_last_resolved_at=now,
        mapped_custom_fields={
            key: value
            for key, value in lead.mapped_custom_fields.items()
            if key != "assigned_agent_user_id"
        },
    )


def _is_active_user(user: User | None) -> bool:
    return user is not None and user.status == UserStatus.ACTIVE