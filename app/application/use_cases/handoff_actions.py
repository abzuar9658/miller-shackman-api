from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import (
    HandoffRepository,
    LeadRepository,
    WorkspaceMembershipRepository,
)
from app.application.services.lead_assignment import lead_effective_owner_user_id
from app.domain.common.ids import UserId, WorkspaceId
from app.domain.conversations import Handoff, HandoffStatus, is_open_handoff
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    WorkspaceMembershipStatus,
    evaluate_permission,
)


class HandoffActionStatus(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    ALREADY_ACKNOWLEDGED = "already_acknowledged"
    REASSIGNED = "reassigned"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class HandoffActionReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    HANDOFF_NOT_FOUND = "handoff_not_found"
    HANDOFF_NOT_OPEN = "handoff_not_open"
    ASSIGNEE_NOT_ACTIVE_MEMBER = "assignee_not_active_member"


@dataclass(frozen=True)
class HandoffActionResult:
    status: HandoffActionStatus
    handoff: Handoff | None = None
    reasons: tuple[HandoffActionReasonCode, ...] = ()


async def acknowledge_handoff(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    handoff_id: UUID,
    handoff_repository: HandoffRepository,
    lead_repository: LeadRepository,
    now: datetime,
) -> HandoffActionResult:
    handoff = await handoff_repository.get_by_id(workspace_id, handoff_id)
    if handoff is None:
        return HandoffActionResult(
            status=HandoffActionStatus.NOT_FOUND,
            reasons=(HandoffActionReasonCode.HANDOFF_NOT_FOUND,),
        )

    if not await _can_act_on_handoff(
        actor=actor,
        workspace_id=workspace_id,
        handoff=handoff,
        lead_repository=lead_repository,
    ):
        return HandoffActionResult(
            status=HandoffActionStatus.REJECTED,
            reasons=(HandoffActionReasonCode.PERMISSION_DENIED,),
        )

    if handoff.status == HandoffStatus.ACKNOWLEDGED:
        return HandoffActionResult(
            status=HandoffActionStatus.ALREADY_ACKNOWLEDGED,
            handoff=handoff,
        )
    if not is_open_handoff(handoff):
        return HandoffActionResult(
            status=HandoffActionStatus.REJECTED,
            reasons=(HandoffActionReasonCode.HANDOFF_NOT_OPEN,),
        )

    saved = await handoff_repository.save(
        replace(handoff, status=HandoffStatus.ACKNOWLEDGED, acknowledged_at=now),
    )
    return HandoffActionResult(status=HandoffActionStatus.ACKNOWLEDGED, handoff=saved)


async def reassign_handoff(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    handoff_id: UUID,
    assigned_agent_user_id: UserId,
    handoff_repository: HandoffRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> HandoffActionResult:
    handoff = await handoff_repository.get_by_id(workspace_id, handoff_id)
    if handoff is None:
        return HandoffActionResult(
            status=HandoffActionStatus.NOT_FOUND,
            reasons=(HandoffActionReasonCode.HANDOFF_NOT_FOUND,),
        )

    permission = evaluate_permission(
        actor,
        PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
    )
    if not permission.allowed or actor.active_workspace_id != workspace_id:
        return HandoffActionResult(
            status=HandoffActionStatus.REJECTED,
            reasons=(HandoffActionReasonCode.PERMISSION_DENIED,),
        )

    if not is_open_handoff(handoff):
        return HandoffActionResult(
            status=HandoffActionStatus.REJECTED,
            reasons=(HandoffActionReasonCode.HANDOFF_NOT_OPEN,),
        )

    membership = await membership_repository.get_by_user_and_workspace(
        assigned_agent_user_id,
        workspace_id,
    )
    if membership is None or membership.status != WorkspaceMembershipStatus.ACTIVE:
        return HandoffActionResult(
            status=HandoffActionStatus.REJECTED,
            reasons=(HandoffActionReasonCode.ASSIGNEE_NOT_ACTIVE_MEMBER,),
        )

    saved = await handoff_repository.save(
        replace(handoff, assigned_agent_user_id=assigned_agent_user_id),
    )
    return HandoffActionResult(status=HandoffActionStatus.REASSIGNED, handoff=saved)


async def _can_act_on_handoff(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    handoff: Handoff,
    lead_repository: LeadRepository,
) -> bool:
    if actor.active_workspace_id != workspace_id:
        return False
    if evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed:
        return True
    assigned_user_id = handoff.assigned_agent_user_id
    if assigned_user_id is None:
        lead = await lead_repository.get_by_id(workspace_id, handoff.lead_id)
        if lead is not None:
            assigned_user_id = lead_effective_owner_user_id(lead)
    permission = evaluate_permission(
        actor,
        PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
        PermissionContext(
            acts_on_assigned_lead=(
                assigned_user_id is not None and assigned_user_id == actor.user_id
            ),
        ),
    )
    return permission.allowed
