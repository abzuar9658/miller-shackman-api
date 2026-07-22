from uuid import UUID

from app.domain.identity import AuthenticatedActor
from app.domain.leads import CanonicalLeadRecord


def is_actor_assigned_to_lead(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
) -> bool:
    effective_owner_user_id = lead_effective_owner_user_id(lead)
    if effective_owner_user_id is None:
        return False
    return effective_owner_user_id == actor.user_id


def lead_assigned_agent_user_id(lead: CanonicalLeadRecord) -> UUID | None:
    if lead.assigned_agent_user_id is not None:
        return lead.assigned_agent_user_id
    return _legacy_assigned_agent_user_id(lead)


def lead_effective_owner_user_id(lead: CanonicalLeadRecord) -> UUID | None:
    if lead.effective_owner_user_id is not None:
        return lead.effective_owner_user_id
    if lead.assigned_agent_user_id is not None:
        return lead.assigned_agent_user_id
    return _legacy_assigned_agent_user_id(lead)


def _legacy_assigned_agent_user_id(lead: CanonicalLeadRecord) -> UUID | None:
    assigned_agent_user_id = lead.mapped_custom_fields.get("assigned_agent_user_id")
    if not assigned_agent_user_id:
        return None
    try:
        return UUID(assigned_agent_user_id)
    except ValueError:
        return None