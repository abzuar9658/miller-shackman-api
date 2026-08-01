from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import HandoffRepository, LeadRepository, UserRepository
from app.application.services.lead_assignment import lead_effective_owner_user_id
from app.domain.common.ids import UserId, WorkspaceId
from app.domain.conversations import Handoff, is_open_handoff
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    WorkspaceMembershipRole,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord

_RECOMMENDED_NEXT_ACTION = (
    "Review the latest reply, contact the lead directly, and decide whether to resume "
    "or keep AI paused."
)


class HandoffReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class HandoffReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    HANDOFF_NOT_FOUND = "handoff_not_found"
    LEAD_NOT_FOUND = "lead_not_found"


@dataclass(frozen=True)
class HandoffLeadSummary:
    lead_id: UUID
    display_name: str
    primary_email: str | None
    primary_phone: str | None


@dataclass(frozen=True)
class HandoffReadView:
    handoff: Handoff
    lead: HandoffLeadSummary
    assigned_agent_name: str | None
    recommended_next_action: str


@dataclass(frozen=True)
class HandoffListResult:
    status: HandoffReadStatus
    views: tuple[HandoffReadView, ...] = ()
    reasons: tuple[HandoffReadReasonCode, ...] = ()


@dataclass(frozen=True)
class HandoffDetailResult:
    status: HandoffReadStatus
    view: HandoffReadView | None = None
    reasons: tuple[HandoffReadReasonCode, ...] = ()


async def list_handoff_views(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    handoff_repository: HandoffRepository,
    lead_repository: LeadRepository,
    user_repository: UserRepository,
    limit: int = 100,
) -> HandoffListResult:
    handoffs = await handoff_repository.list_handoffs(workspace_id, limit=limit)
    user_name_cache: dict[UserId, str | None] = {}

    if _can_view_workspace_handoffs(actor):
        views = await _build_views(
            handoffs=handoffs,
            workspace_id=workspace_id,
            lead_repository=lead_repository,
            user_repository=user_repository,
            user_name_cache=user_name_cache,
            actor=None,
        )
        return HandoffListResult(status=HandoffReadStatus.OK, views=views)

    if actor.active_role != WorkspaceMembershipRole.ASSIGNED_AGENT:
        return HandoffListResult(
            status=HandoffReadStatus.REJECTED,
            reasons=(HandoffReadReasonCode.PERMISSION_DENIED,),
        )

    views = await _build_views(
        handoffs=handoffs,
        workspace_id=workspace_id,
        lead_repository=lead_repository,
        user_repository=user_repository,
        user_name_cache=user_name_cache,
        actor=actor,
    )
    return HandoffListResult(status=HandoffReadStatus.OK, views=views)


async def get_handoff_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    handoff_id: UUID,
    handoff_repository: HandoffRepository,
    lead_repository: LeadRepository,
    user_repository: UserRepository,
) -> HandoffDetailResult:
    handoff = await handoff_repository.get_by_id(workspace_id, handoff_id)
    if handoff is None:
        return HandoffDetailResult(
            status=HandoffReadStatus.NOT_FOUND,
            reasons=(HandoffReadReasonCode.HANDOFF_NOT_FOUND,),
        )

    lead = await lead_repository.get_by_id(workspace_id, handoff.lead_id)
    if lead is None:
        return HandoffDetailResult(
            status=HandoffReadStatus.NOT_FOUND,
            reasons=(HandoffReadReasonCode.LEAD_NOT_FOUND,),
        )

    if not _can_view_workspace_handoffs(actor):
        permission = evaluate_permission(
            actor,
            PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
            PermissionContext(acts_on_assigned_lead=_acts_on_assigned_lead(actor, handoff, lead)),
        )
        if not permission.allowed:
            return HandoffDetailResult(
                status=HandoffReadStatus.REJECTED,
                reasons=(HandoffReadReasonCode.PERMISSION_DENIED,),
            )

    user_name_cache: dict[UserId, str | None] = {}
    view = await _build_handoff_view(
        handoff=handoff,
        lead=lead,
        user_repository=user_repository,
        user_name_cache=user_name_cache,
    )
    return HandoffDetailResult(status=HandoffReadStatus.OK, view=view)


async def _build_views(
    *,
    handoffs: tuple[Handoff, ...],
    workspace_id: WorkspaceId,
    lead_repository: LeadRepository,
    user_repository: UserRepository,
    user_name_cache: dict[UserId, str | None],
    actor: AuthenticatedActor | None,
) -> tuple[HandoffReadView, ...]:
    views: list[HandoffReadView] = []
    for handoff in handoffs:
        if not is_open_handoff(handoff):
            continue
        lead = await lead_repository.get_by_id(workspace_id, handoff.lead_id)
        if lead is None:
            continue
        if actor is not None:
            permission = evaluate_permission(
                actor,
                PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
                PermissionContext(
                    acts_on_assigned_lead=_acts_on_assigned_lead(actor, handoff, lead)
                ),
            )
            if not permission.allowed:
                continue
        views.append(
            await _build_handoff_view(
                handoff=handoff,
                lead=lead,
                user_repository=user_repository,
                user_name_cache=user_name_cache,
            )
        )
    return tuple(views)


async def _build_handoff_view(
    *,
    handoff: Handoff,
    lead: CanonicalLeadRecord,
    user_repository: UserRepository,
    user_name_cache: dict[UserId, str | None],
) -> HandoffReadView:
    return HandoffReadView(
        handoff=handoff,
        lead=HandoffLeadSummary(
            lead_id=lead.lead_id,
            display_name=_lead_display_name(lead),
            primary_email=lead.primary_email,
            primary_phone=lead.primary_phone,
        ),
        assigned_agent_name=await _assigned_agent_name(
            handoff=handoff,
            lead=lead,
            user_repository=user_repository,
            user_name_cache=user_name_cache,
        ),
        recommended_next_action=_RECOMMENDED_NEXT_ACTION,
    )


async def _assigned_agent_name(
    *,
    handoff: Handoff,
    lead: CanonicalLeadRecord,
    user_repository: UserRepository,
    user_name_cache: dict[UserId, str | None],
) -> str | None:
    user_id = _assigned_agent_user_id(handoff, lead)
    if user_id is None:
        return None
    if user_id not in user_name_cache:
        user = await user_repository.get_by_id(user_id)
        user_name_cache[user_id] = user.full_name if user is not None else None
    return user_name_cache[user_id]


def _assigned_agent_user_id(handoff: Handoff, lead: CanonicalLeadRecord) -> UserId | None:
    if handoff.assigned_agent_user_id is not None:
        return handoff.assigned_agent_user_id
    return lead_effective_owner_user_id(lead)


def _acts_on_assigned_lead(
    actor: AuthenticatedActor,
    handoff: Handoff,
    lead: CanonicalLeadRecord,
) -> bool:
    user_id = _assigned_agent_user_id(handoff, lead)
    return user_id is not None and user_id == actor.user_id


def _can_view_workspace_handoffs(actor: AuthenticatedActor) -> bool:
    return bool(evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed)


def _lead_display_name(lead: CanonicalLeadRecord) -> str:
    return str(
        lead.mapped_custom_fields.get("display_name")
        or lead.primary_email
        or lead.primary_phone
        or lead.crm_lead_id
    )
