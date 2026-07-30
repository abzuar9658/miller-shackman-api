from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.domain.common.ids import WorkspaceId
from app.domain.crm_agent_mapping import CRMAgentMappingStatus
from app.domain.identity import AuthenticatedActor, WorkspaceMembershipRole

_TRUSTED_PREFLIGHT_MAPPING_STATUSES = frozenset(
    {
        CRMAgentMappingStatus.VERIFIED,
        CRMAgentMappingStatus.OVERRIDDEN,
    }
)


async def actor_preflight_recipient_ids(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    crm_agent_repository: CRMAgentRepository,
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository,
) -> frozenset[str]:
    """Return all recipient identifiers that may refer to this actor in preflight digests.

    Preflight digest entries store a ``recipient_id`` that was originally set to the
    CRM agent external id when the digest was prepared from the dormant selector.  The
    in-app product surface, however, deals with app user ids.  This helper lets the
    read and veto paths match either form, so assigned agents can see and act on the
    digests that belong to them even when the stored id is the CRM agent id.
    """
    recipient_ids: set[str] = {str(actor.user_id)}

    if actor.active_role != WorkspaceMembershipRole.ASSIGNED_AGENT:
        return frozenset(recipient_ids)

    mappings = await workspace_agent_crm_mapping_repository.list_for_workspace(workspace_id)
    for mapping in mappings:
        if mapping.app_user_id != actor.user_id:
            continue
        if mapping.mapping_status not in _TRUSTED_PREFLIGHT_MAPPING_STATUSES:
            continue
        agent = await crm_agent_repository.get_by_record_id(
            workspace_id,
            mapping.crm_agent_record_id,
        )
        if agent is not None:
            recipient_ids.add(agent.external_agent_id)

    return frozenset(recipient_ids)
