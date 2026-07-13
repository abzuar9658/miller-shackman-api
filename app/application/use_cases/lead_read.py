from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.application.ports.lead_read import (
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadUserRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.common.ids import LeadId, UserId, WorkspaceId
from app.domain.conversations import Handoff, InboundMessage
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    WorkspaceMembershipRole,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import LeadWorkflow, WorkflowTransition


class LeadReadStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"


@dataclass(frozen=True)
class LeadReadView:
    lead: CanonicalLeadRecord
    assigned_agent_name: str | None
    latest_workflow: LeadWorkflow | None
    latest_handoff: Handoff | None


@dataclass(frozen=True)
class LeadListResult:
    status: LeadReadStatus
    views: tuple[LeadReadView, ...] = ()
    reasons: tuple[LeadReadReasonCode, ...] = ()


@dataclass(frozen=True)
class LeadDetailView:
    lead: LeadReadView
    workflow_transitions: tuple[WorkflowTransition, ...]
    inbound_messages: tuple[InboundMessage, ...]
    outbound_messages: tuple[OutboundMessage, ...]
    handoffs: tuple[Handoff, ...]


@dataclass(frozen=True)
class LeadDetailResult:
    status: LeadReadStatus
    view: LeadDetailView | None = None
    reasons: tuple[LeadReadReasonCode, ...] = ()


async def list_lead_views(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_repository: LeadReadLeadRepository,
    workflow_repository: LeadReadWorkflowRepository,
    handoff_repository: LeadReadHandoffRepository,
    user_repository: LeadReadUserRepository,
    limit: int = 100,
) -> LeadListResult:
    scoped_actor: AuthenticatedActor | None
    if _can_view_workspace_leads(actor):
        scoped_actor = None
    elif actor.active_role == WorkspaceMembershipRole.ASSIGNED_AGENT:
        scoped_actor = actor
    else:
        return LeadListResult(
            status=LeadReadStatus.REJECTED,
            reasons=(LeadReadReasonCode.PERMISSION_DENIED,),
        )

    leads = await lead_repository.list_for_workspace(workspace_id, limit=limit)
    latest_workflows = {
        workflow.lead_id: workflow
        for workflow in await workflow_repository.list_latest_for_workspace(
            workspace_id, limit=limit
        )
    }
    latest_handoffs: dict[LeadId, Handoff] = {}
    for handoff in await handoff_repository.list_handoffs(workspace_id, limit=limit * 3):
        latest_handoffs.setdefault(handoff.lead_id, handoff)
    user_name_cache: dict[UserId, str | None] = {}
    views = [
        LeadReadView(
            lead=lead,
            assigned_agent_name=await _assigned_agent_name(lead, user_repository, user_name_cache),
            latest_workflow=latest_workflows.get(lead.lead_id),
            latest_handoff=latest_handoffs.get(lead.lead_id),
        )
        for lead in leads
        if scoped_actor is None or _can_view_assigned_lead(scoped_actor, lead)
    ]
    return LeadListResult(status=LeadReadStatus.OK, views=tuple(views))


async def get_lead_detail_view(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadReadLeadRepository,
    workflow_repository: LeadReadWorkflowRepository,
    workflow_transition_repository: LeadReadWorkflowTransitionRepository,
    inbound_message_repository: LeadReadInboundMessageRepository,
    outbound_message_repository: LeadReadOutboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    user_repository: LeadReadUserRepository,
) -> LeadDetailResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return LeadDetailResult(
            status=LeadReadStatus.NOT_FOUND,
            reasons=(LeadReadReasonCode.LEAD_NOT_FOUND,),
        )

    if not _can_view_workspace_leads(actor) and not _can_view_assigned_lead(actor, lead):
        return LeadDetailResult(
            status=LeadReadStatus.REJECTED,
            reasons=(LeadReadReasonCode.PERMISSION_DENIED,),
        )

    latest_workflow = await workflow_repository.get_latest_for_lead(workspace_id, lead_id)
    transitions = (
        await workflow_transition_repository.list_for_workflow(
            workspace_id, latest_workflow.workflow_id
        )
        if latest_workflow is not None
        else ()
    )
    handoffs = await handoff_repository.list_for_lead(workspace_id, lead_id)
    user_name_cache: dict[UserId, str | None] = {}
    lead_view = LeadReadView(
        lead=lead,
        assigned_agent_name=await _assigned_agent_name(lead, user_repository, user_name_cache),
        latest_workflow=latest_workflow,
        latest_handoff=handoffs[0] if handoffs else None,
    )
    return LeadDetailResult(
        status=LeadReadStatus.OK,
        view=LeadDetailView(
            lead=lead_view,
            workflow_transitions=transitions,
            inbound_messages=await inbound_message_repository.list_for_lead(workspace_id, lead_id),
            outbound_messages=await outbound_message_repository.list_for_lead(
                workspace_id, lead_id
            ),
            handoffs=handoffs,
        ),
    )


async def _assigned_agent_name(
    lead: CanonicalLeadRecord,
    user_repository: LeadReadUserRepository,
    user_name_cache: dict[UserId, str | None],
) -> str | None:
    user_id = _assigned_agent_user_id(lead)
    if user_id is None:
        return None
    if user_id not in user_name_cache:
        user = await user_repository.get_by_id(user_id)
        user_name_cache[user_id] = user.full_name if user is not None else None
    return user_name_cache[user_id]


def _assigned_agent_user_id(lead: CanonicalLeadRecord) -> UserId | None:
    value = lead.mapped_custom_fields.get("assigned_agent_user_id")
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _can_view_workspace_leads(actor: AuthenticatedActor) -> bool:
    return bool(evaluate_permission(actor, PermissionCapability.VIEW_WORKSPACE_REPORTING).allowed)


def _can_view_assigned_lead(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    return bool(
        evaluate_permission(
            actor,
            PermissionCapability.VIEW_OWN_ASSIGNED_LEAD,
            PermissionContext(acts_on_assigned_lead=_acts_on_assigned_lead(actor, lead)),
        ).allowed
    )


def _acts_on_assigned_lead(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    assigned_agent_user_id = _assigned_agent_user_id(lead)
    return assigned_agent_user_id is not None and assigned_agent_user_id == actor.user_id
