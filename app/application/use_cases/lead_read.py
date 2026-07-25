from dataclasses import dataclass
from enum import StrEnum

from app.application.ports.lead_activity import (
    LeadActivityItem,
    LeadActivityRepository,
    LeadActivitySummary,
)
from app.application.ports.lead_read import (
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadUserRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import CRMAgentRepository
from app.application.services.lead_assignment import (
    is_actor_assigned_to_lead,
    lead_assigned_agent_user_id,
    lead_effective_owner_user_id,
)
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.rejected_draft_review import RejectedDraftReview
from app.domain.common.ids import LeadId, UserId, WorkspaceId
from app.domain.conversations import Handoff, InboundMessage
from app.domain.crm_agent_mapping import CRMAgent
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    User,
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
class LeadOwnershipView:
    crm_assigned_agent: CRMAgent | None = None
    mapped_app_user: User | None = None


@dataclass(frozen=True)
class LeadReadView:
    lead: CanonicalLeadRecord
    assigned_agent_name: str | None
    ownership: LeadOwnershipView
    latest_workflow: LeadWorkflow | None
    latest_handoff: Handoff | None
    activity_summary: LeadActivitySummary | None = None


@dataclass(frozen=True)
class LeadListResult:
    status: LeadReadStatus
    views: tuple[LeadReadView, ...] = ()
    reasons: tuple[LeadReadReasonCode, ...] = ()


@dataclass(frozen=True)
class LeadDetailView:
    lead: LeadReadView
    workflow_transitions: tuple[WorkflowTransition, ...]
    rejected_draft_reviews: tuple[RejectedDraftReview, ...]
    activity_items: tuple[LeadActivityItem, ...]
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
    activity_repository: LeadActivityRepository,
    rejected_draft_review_repository: RejectedDraftReviewRepository,
    inbound_message_repository: LeadReadInboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    user_repository: LeadReadUserRepository,
    crm_agent_repository: CRMAgentRepository,
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
    visible_leads = tuple(
        lead
        for lead in leads
        if scoped_actor is None or _can_view_assigned_lead(scoped_actor, lead)
    )
    activity_summaries = {
        summary.lead_id: summary
        for summary in await activity_repository.list_summaries(
            workspace_id,
            tuple(lead.lead_id for lead in visible_leads),
        )
    }
    user_name_cache: dict[UserId, str | None] = {}
    user_cache: dict[UserId, User | None] = {}
    crm_agent_cache: dict[tuple[str, str], CRMAgent | None] = {}
    views = [
        LeadReadView(
            lead=lead,
            assigned_agent_name=await _assigned_agent_name(lead, user_repository, user_name_cache),
            ownership=await _lead_ownership_view(
                lead,
                user_repository,
                crm_agent_repository,
                user_cache,
                crm_agent_cache,
            ),
            latest_workflow=latest_workflows.get(lead.lead_id),
            latest_handoff=latest_handoffs.get(lead.lead_id),
            activity_summary=activity_summaries.get(lead.lead_id),
        )
        for lead in visible_leads
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
    activity_repository: LeadActivityRepository,
    rejected_draft_review_repository: RejectedDraftReviewRepository,
    inbound_message_repository: LeadReadInboundMessageRepository,
    outbound_message_repository: LeadReadOutboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    user_repository: LeadReadUserRepository,
    crm_agent_repository: CRMAgentRepository,
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
    activity_summaries = await activity_repository.list_summaries(workspace_id, (lead_id,))
    user_name_cache: dict[UserId, str | None] = {}
    user_cache: dict[UserId, User | None] = {}
    crm_agent_cache: dict[tuple[str, str], CRMAgent | None] = {}
    lead_view = LeadReadView(
        lead=lead,
        assigned_agent_name=await _assigned_agent_name(lead, user_repository, user_name_cache),
        ownership=await _lead_ownership_view(
            lead,
            user_repository,
            crm_agent_repository,
            user_cache,
            crm_agent_cache,
        ),
        latest_workflow=latest_workflow,
        latest_handoff=handoffs[0] if handoffs else None,
        activity_summary=activity_summaries[0] if activity_summaries else None,
    )
    return LeadDetailResult(
        status=LeadReadStatus.OK,
        view=LeadDetailView(
            lead=lead_view,
            workflow_transitions=transitions,
            rejected_draft_reviews=await rejected_draft_review_repository.list_for_lead(
                workspace_id, lead_id
            ),
            activity_items=await activity_repository.list_for_lead(workspace_id, lead_id),
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
    user_id = lead_effective_owner_user_id(lead)
    if user_id is None:
        return None
    if user_id not in user_name_cache:
        user = await user_repository.get_by_id(user_id)
        user_name_cache[user_id] = user.full_name if user is not None else None
    return user_name_cache[user_id]


async def _mapped_app_user(
    lead: CanonicalLeadRecord,
    user_repository: LeadReadUserRepository,
    user_cache: dict[UserId, User | None],
) -> User | None:
    user_id = lead_assigned_agent_user_id(lead)
    if user_id is None:
        return None
    if user_id not in user_cache:
        user_cache[user_id] = await user_repository.get_by_id(user_id)
    return user_cache[user_id]


async def _crm_assigned_agent(
    lead: CanonicalLeadRecord,
    crm_agent_repository: CRMAgentRepository,
    crm_agent_cache: dict[tuple[str, str], CRMAgent | None],
) -> CRMAgent | None:
    if lead.assigned_agent_crm_id is None:
        return None
    cache_key = (lead.crm_provider.value, lead.assigned_agent_crm_id)
    if cache_key not in crm_agent_cache:
        crm_agent_cache[cache_key] = await crm_agent_repository.get_by_external_id(
            lead.workspace_id,
            lead.crm_provider,
            lead.assigned_agent_crm_id,
        )
    return crm_agent_cache[cache_key]


async def _lead_ownership_view(
    lead: CanonicalLeadRecord,
    user_repository: LeadReadUserRepository,
    crm_agent_repository: CRMAgentRepository,
    user_cache: dict[UserId, User | None],
    crm_agent_cache: dict[tuple[str, str], CRMAgent | None],
) -> LeadOwnershipView:
    return LeadOwnershipView(
        crm_assigned_agent=await _crm_assigned_agent(
            lead,
            crm_agent_repository,
            crm_agent_cache,
        ),
        mapped_app_user=await _mapped_app_user(lead, user_repository, user_cache),
    )


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
    return is_actor_assigned_to_lead(actor, lead)
