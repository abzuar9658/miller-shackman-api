from uuid import UUID

from app.domain.identity import AuthenticatedActor
from app.domain.leads import CanonicalLeadRecord


def is_actor_assigned_to_lead(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
) -> bool:
    assigned_agent_user_id = lead.mapped_custom_fields.get("assigned_agent_user_id")
    if not assigned_agent_user_id:
        return False
    try:
        return UUID(assigned_agent_user_id) == actor.user_id
    except ValueError:
        return False