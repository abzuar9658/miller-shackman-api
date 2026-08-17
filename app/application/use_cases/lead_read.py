from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from typing import cast

from app.application.ports.lead_activity import (
    LeadActivityItem,
    LeadActivityRepository,
    LeadActivitySummary,
)
from app.application.ports.lead_read import (
    LeadReadClassificationArtifactRepository,
    LeadReadHandoffRepository,
    LeadReadInboundMessageRepository,
    LeadReadLeadRepository,
    LeadReadOutboundMessageRepository,
    LeadReadPausedSearchHistoryRepository,
    LeadReadPausedSearchTrackRepository,
    LeadReadUserRepository,
    LeadReadWorkflowOverrideAuditRepository,
    LeadReadWorkflowRepository,
    LeadReadWorkflowTransitionRepository,
)
from app.application.ports.rejected_draft_review import RejectedDraftReviewRepository
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    CampaignExecutionRepository,
    CRMAgentRepository,
    LeadRoutingReviewRepository,
    PausedSearchTrackAssignmentRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.application.services.lead_assignment import (
    is_actor_assigned_to_lead,
    lead_assigned_agent_user_id,
    lead_effective_owner_user_id,
)
from app.application.services.lead_cadence_progress import (
    LeadCadenceProgressView,
    build_dormant_cadence_progress,
    build_lead_status_narrative,
    build_paused_search_cadence_progress,
)
from app.application.services.lead_decision_tree import (
    LeadDecisionTreeView,
    PausedSearchTrackOptionSpec,
    build_lead_decision_tree,
)
from app.domain.campaigns.execution import CampaignExecutionConfig, CampaignVersionStatus
from app.domain.campaigns.outbound_message import OutboundMessage
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrack,
    PausedSearchTrackStatus,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
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
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadRoutingReview,
    lead_paused_search_profile,
)
from app.domain.workflows import LeadWorkflow, LeadWorkflowOverrideAuditLog, WorkflowTransition


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
    qualification_plan: LeadQualificationPlanView | None
    decision_tree: LeadDecisionTreeView
    workflow_transitions: tuple[WorkflowTransition, ...]
    workflow_override_audits: tuple[LeadWorkflowOverrideAuditView, ...]
    paused_search_history: tuple[LeadPausedSearchHistoryView, ...]
    routing_reviews: tuple[LeadRoutingReview, ...]
    rejected_draft_reviews: tuple[RejectedDraftReview, ...]
    activity_items: tuple[LeadActivityItem, ...]
    inbound_messages: tuple[InboundMessage, ...]
    outbound_messages: tuple[OutboundMessage, ...]
    handoffs: tuple[Handoff, ...]
    cadence_progress: tuple[LeadCadenceProgressView, ...] = ()
    status_narrative: str | None = None


@dataclass(frozen=True)
class LeadPausedSearchHistoryView:
    entry: LeadPausedSearchHistoryEntry
    actor_name: str | None = None


@dataclass(frozen=True)
class LeadWorkflowOverrideAuditView:
    entry: LeadWorkflowOverrideAuditLog
    actor_name: str | None = None


@dataclass(frozen=True)
class LeadPausedSearchPlanView:
    track: PausedSearchTrack
    version: PausedSearchTrackVersion
    steps: tuple[PausedSearchTrackStep, ...] = ()
    current_step: PausedSearchTrackStep | None = None
    next_action_at: datetime | None = None


@dataclass(frozen=True)
class LeadQualificationPlanView:
    classification_artifact: LeadClassificationArtifact | None = None
    paused_search_plan: LeadPausedSearchPlanView | None = None


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
    paused_search_history_repository: LeadReadPausedSearchHistoryRepository,
    classification_artifact_repository: LeadReadClassificationArtifactRepository,
    workflow_repository: LeadReadWorkflowRepository,
    workflow_override_audit_repository: LeadReadWorkflowOverrideAuditRepository,
    workflow_transition_repository: LeadReadWorkflowTransitionRepository,
    paused_search_track_repository: LeadReadPausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    activity_repository: LeadActivityRepository,
    rejected_draft_review_repository: RejectedDraftReviewRepository,
    inbound_message_repository: LeadReadInboundMessageRepository,
    outbound_message_repository: LeadReadOutboundMessageRepository,
    handoff_repository: LeadReadHandoffRepository,
    user_repository: LeadReadUserRepository,
    crm_agent_repository: CRMAgentRepository,
    routing_review_repository: LeadRoutingReviewRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    campaign_execution_repository: CampaignExecutionRepository | None = None,
    workspace_repository: WorkspaceRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    now: datetime | None = None,
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
    classification_artifacts = await classification_artifact_repository.list_for_lead(
        workspace_id,
        lead_id,
        limit=1,
    )
    user_name_cache: dict[UserId, str | None] = {}
    user_cache: dict[UserId, User | None] = {}
    crm_agent_cache: dict[tuple[str, str], CRMAgent | None] = {}
    paused_search_history_entries = await paused_search_history_repository.list_for_lead(
        workspace_id,
        lead_id,
    )
    workflow_override_audit_entries = await workflow_override_audit_repository.list_for_lead(
        workspace_id,
        lead_id,
    )
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
    paused_search_history_views: list[LeadPausedSearchHistoryView] = []
    for history_entry in paused_search_history_entries:
        paused_search_history_views.append(
            LeadPausedSearchHistoryView(
                entry=history_entry,
                actor_name=await _user_name(
                    history_entry.actor_user_id,
                    user_repository,
                    user_name_cache,
                ),
            )
        )
    workflow_override_audit_views: list[LeadWorkflowOverrideAuditView] = []
    for audit_entry in workflow_override_audit_entries:
        workflow_override_audit_views.append(
            LeadWorkflowOverrideAuditView(
                entry=audit_entry,
                actor_name=await _user_name(
                    audit_entry.actor_user_id,
                    user_repository,
                    user_name_cache,
                ),
            )
        )
    paused_search_plan = await _paused_search_plan_view(
        workspace_id,
        lead_id,
        lead,
        latest_workflow,
        paused_search_track_assignment_repository,
        paused_search_track_repository,
    )
    paused_search_track_options = await _paused_search_track_options(
        workspace_id,
        paused_search_track_repository,
    )
    qualification_plan = LeadQualificationPlanView(
        classification_artifact=classification_artifacts[0] if classification_artifacts else None,
        paused_search_plan=paused_search_plan,
    )
    decision_tree = build_lead_decision_tree(
        lead=lead,
        classification_artifact=qualification_plan.classification_artifact,
        paused_search_track=(paused_search_plan.track if paused_search_plan is not None else None),
        paused_search_track_version=(
            paused_search_plan.version if paused_search_plan is not None else None
        ),
        paused_search_steps=(paused_search_plan.steps if paused_search_plan is not None else ()),
        paused_search_current_step=(
            paused_search_plan.current_step if paused_search_plan is not None else None
        ),
        paused_search_track_options=paused_search_track_options,
        latest_workflow=latest_workflow,
        latest_handoff=lead_view.latest_handoff,
    )
    outbound_messages = await outbound_message_repository.list_for_lead(workspace_id, lead_id)
    cadence_progress = await _cadence_progress_views(
        workspace_id=workspace_id,
        lead=lead,
        workflow=latest_workflow,
        paused_search_plan=paused_search_plan,
        outbound_messages=outbound_messages,
        campaign_enrollment_repository=campaign_enrollment_repository,
        campaign_execution_repository=campaign_execution_repository,
        workspace_repository=workspace_repository,
        workspace_contact_policy_repository=workspace_contact_policy_repository,
        now=now if now is not None else datetime.now(UTC),
    )
    status_narrative = build_lead_status_narrative(
        workflow=latest_workflow,
        progress_views=cadence_progress,
        now=now if now is not None else datetime.now(UTC),
    )
    return LeadDetailResult(
        status=LeadReadStatus.OK,
        view=LeadDetailView(
            lead=lead_view,
            qualification_plan=(
                qualification_plan
                if qualification_plan.classification_artifact is not None
                or qualification_plan.paused_search_plan is not None
                else None
            ),
            decision_tree=decision_tree,
            workflow_transitions=transitions,
            workflow_override_audits=tuple(workflow_override_audit_views),
            paused_search_history=tuple(paused_search_history_views),
            routing_reviews=await routing_review_repository.list_for_lead(workspace_id, lead_id),
            rejected_draft_reviews=await rejected_draft_review_repository.list_for_lead(
                workspace_id, lead_id
            ),
            activity_items=await activity_repository.list_for_lead(workspace_id, lead_id),
            inbound_messages=await inbound_message_repository.list_for_lead(workspace_id, lead_id),
            outbound_messages=outbound_messages,
            handoffs=handoffs,
            cadence_progress=cadence_progress,
            status_narrative=status_narrative,
        ),
    )


async def _cadence_progress_views(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow | None,
    paused_search_plan: LeadPausedSearchPlanView | None,
    outbound_messages: tuple[OutboundMessage, ...],
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
    workspace_repository: WorkspaceRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    now: datetime,
) -> tuple[LeadCadenceProgressView, ...]:
    views: list[LeadCadenceProgressView] = []
    # Tracks are mutually exclusive: an active paused-search plan owns the
    # journey, so the dormant cadence card is only rendered when no
    # paused-search plan is in effect.
    if paused_search_plan is not None:
        workspace = (
            await workspace_repository.get_by_id(workspace_id)
            if workspace_repository is not None
            else None
        )
        contact_policy = (
            await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
            if workspace_contact_policy_repository is not None
            else None
        )
        paused_progress = build_paused_search_cadence_progress(
            flow_name=paused_search_plan.track.display_name,
            track_steps=paused_search_plan.steps,
            outbound_messages=outbound_messages,
            workflow=workflow,
            profile=lead_paused_search_profile(lead),
            track_version=paused_search_plan.version,
            timezone=workspace.default_timezone if workspace is not None else None,
            now=now,
            quiet_hours_enabled=(
                contact_policy.quiet_hours_enabled if contact_policy is not None else True
            ),
            quiet_hours_start=(
                contact_policy.quiet_hours_start if contact_policy is not None else time(10, 0)
            ),
            quiet_hours_end=(
                contact_policy.quiet_hours_end if contact_policy is not None else time(17, 0)
            ),
        )
        if paused_progress is not None:
            views.append(paused_progress)
        return tuple(views)
    dormant_config = await _dormant_campaign_config(
        workspace_id=workspace_id,
        workflow=workflow,
        campaign_enrollment_repository=campaign_enrollment_repository,
        campaign_execution_repository=campaign_execution_repository,
    )
    if dormant_config is not None:
        dormant_progress = build_dormant_cadence_progress(
            flow_name=dormant_config.campaign_name,
            cadence_steps=dormant_config.cadence_steps,
            outbound_messages=outbound_messages,
            workflow=workflow,
        )
        if dormant_progress is not None:
            views.append(dormant_progress)
    return tuple(views)


async def _dormant_campaign_config(
    *,
    workspace_id: WorkspaceId,
    workflow: LeadWorkflow | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    campaign_execution_repository: CampaignExecutionRepository | None,
) -> CampaignExecutionConfig | None:
    if (
        workflow is None
        or campaign_enrollment_repository is None
        or campaign_execution_repository is None
    ):
        return None
    enrollment = await campaign_enrollment_repository.get_latest_by_lead_and_campaign(
        workspace_id,
        workflow.lead_id,
        workflow.campaign_id,
    )
    if enrollment is not None and enrollment.campaign_version_id is not None:
        config = await campaign_execution_repository.get_by_version_id(
            workspace_id,
            enrollment.campaign_version_id,
        )
        if config is not None:
            return cast(CampaignExecutionConfig, config)
    fallback = await campaign_execution_repository.get_active_for_campaign(
        workspace_id,
        workflow.campaign_id,
    )
    return cast("CampaignExecutionConfig | None", fallback)


async def _paused_search_plan_view(
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead: CanonicalLeadRecord,
    workflow: LeadWorkflow | None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    paused_search_track_repository: LeadReadPausedSearchTrackRepository,
) -> LeadPausedSearchPlanView | None:
    assignment = await paused_search_track_assignment_repository.get_active_for_lead(
        workspace_id,
        lead_id,
    )
    if assignment is None or assignment.track_version_id is None:
        return None

    # A stale, never-released assignment must not render as an active track:
    # the lead profile (or a workflow pinned to the same track) is the source
    # of truth for whether paused-search is currently in effect.
    workflow_pinned_to_assignment = (
        workflow is not None
        and workflow.paused_search_track_version_id == assignment.track_version_id
    )
    if not lead.paused_search_active and not workflow_pinned_to_assignment:
        return None

    version = await paused_search_track_repository.get_version(
        workspace_id,
        assignment.track_version_id,
    )
    if version is None:
        return None

    if assignment.track_id is not None and version.track_id != assignment.track_id:
        return None

    track = await paused_search_track_repository.get_track(workspace_id, version.track_id)
    if track is None:
        return None

    steps = await paused_search_track_repository.get_steps(
        workspace_id,
        version.track_version_id,
    )
    current_step = next(
        (
            step
            for step in steps
            if workflow is not None and step.step_id == workflow.paused_search_track_step_id
        ),
        None,
    )
    return LeadPausedSearchPlanView(
        track=track,
        version=version,
        steps=steps,
        current_step=current_step,
        next_action_at=workflow.next_action_at if workflow is not None else None,
    )


async def _paused_search_track_options(
    workspace_id: WorkspaceId,
    paused_search_track_repository: LeadReadPausedSearchTrackRepository,
) -> tuple[PausedSearchTrackOptionSpec, ...]:
    options: list[PausedSearchTrackOptionSpec] = []
    for track in await paused_search_track_repository.list_tracks(workspace_id):
        if track.status != PausedSearchTrackStatus.ACTIVE or track.active_version_id is None:
            continue
        version = await paused_search_track_repository.get_version(
            workspace_id,
            track.active_version_id,
        )
        if (
            version is None
            or not version.enabled
            or version.status != CampaignVersionStatus.PUBLISHED
        ):
            continue
        steps = await paused_search_track_repository.get_steps(
            workspace_id,
            version.track_version_id,
        )
        options.append(PausedSearchTrackOptionSpec(track=track, version=version, steps=steps))
    return tuple(options)


async def _assigned_agent_name(
    lead: CanonicalLeadRecord,
    user_repository: LeadReadUserRepository,
    user_name_cache: dict[UserId, str | None],
) -> str | None:
    user_id = lead_effective_owner_user_id(lead)
    return await _user_name(user_id, user_repository, user_name_cache)


async def _user_name(
    user_id: UserId | None,
    user_repository: LeadReadUserRepository,
    user_name_cache: dict[UserId, str | None],
) -> str | None:
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
