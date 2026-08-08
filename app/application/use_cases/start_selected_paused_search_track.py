from collections.abc import Awaitable, Callable
from datetime import datetime

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    WorkflowTransitionRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.use_cases.campaign_enrollment_types import LeadStartResult
from app.application.use_cases.lead_manual_enrollment import (
    LeadManualEnrollmentActionStatus,
    LeadManualEnrollmentReasonCode,
    StartLeadManualEnrollmentResult,
    active_published_campaign_version,
    manual_enrollment_permission_allowed,
    manual_enrollment_source,
)
from app.application.use_cases.route_ai_nurture_lead import AiNurtureRoute
from app.application.use_cases.start_paused_search_campaign_enrollment import (
    PausedSearchCampaignEnrollmentStatus,
    start_paused_search_campaign_enrollment,
)
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.identity import AuthenticatedActor
from app.domain.leads import PausedSearchSource, lead_paused_search_profile


async def start_selected_paused_search_track(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    lead_repository: LeadRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    event_bus: EventBus | None,
    commit: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> StartLeadManualEnrollmentResult:
    lead = await lead_repository.get_by_id_for_update(workspace_id, lead_id)
    if lead is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            campaign_id=campaign_id,
            reasons=(LeadManualEnrollmentReasonCode.LEAD_NOT_FOUND,),
        )

    profile = lead_paused_search_profile(lead)
    if (
        profile is None
        or profile.paused_search_source is not PausedSearchSource.OPERATOR
        or profile.paused_search_track_version_id is None
    ):
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
            campaign_id=campaign_id,
            reasons=("operator_paused_search_assignment_required",),
        )

    assignment = (
        await paused_search_track_assignment_repository.get_active_for_lead_for_update(
            workspace_id, lead_id
        )
    )
    if assignment is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
            campaign_id=campaign_id,
            reasons=("paused_search_track_assignment_unavailable",),
        )
    if assignment.track_version_id != profile.paused_search_track_version_id:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REVIEW_HOLD,
            campaign_id=campaign_id,
            reasons=("paused_search_track_assignment_mismatch",),
        )

    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    version = await active_published_campaign_version(
        campaign_admin_repository, workspace_id, campaign
    )
    if campaign is None or version is None:
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.NOT_FOUND,
            campaign_id=campaign_id,
            reasons=(LeadManualEnrollmentReasonCode.CAMPAIGN_NOT_FOUND,),
        )
    if not manual_enrollment_permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
    ):
        return StartLeadManualEnrollmentResult(
            status=LeadManualEnrollmentActionStatus.REJECTED,
            campaign_id=campaign_id,
            campaign_version_id=version.campaign_version_id,
            reasons=(LeadManualEnrollmentReasonCode.PERMISSION_DENIED,),
        )

    result = await start_paused_search_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        lead_id=lead_id,
        lead=lead,
        source=manual_enrollment_source(actor),
        reason_codes=("operator_selected_paused_search_track",),
        actor_user_id=actor.user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        now=now,
    )
    return _result_from_paused_search_enrollment(
        campaign_id=campaign_id,
        campaign_version_id=version.campaign_version_id,
        result_status=result.status,
        lead_result=result.lead_result,
        reason_codes=result.reason_codes,
        error=result.error,
    )


def _result_from_paused_search_enrollment(
    *,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    result_status: PausedSearchCampaignEnrollmentStatus,
    lead_result: LeadStartResult | None,
    reason_codes: tuple[str, ...],
    error: str | None,
) -> StartLeadManualEnrollmentResult:
    status_by_enrollment_status = {
        PausedSearchCampaignEnrollmentStatus.STARTED: LeadManualEnrollmentActionStatus.STARTED,
        PausedSearchCampaignEnrollmentStatus.ALREADY_ENROLLED: (
            LeadManualEnrollmentActionStatus.ALREADY_ENROLLED
        ),
        PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD: (
            LeadManualEnrollmentActionStatus.REVIEW_HOLD
        ),
        PausedSearchCampaignEnrollmentStatus.FAILED: LeadManualEnrollmentActionStatus.FAILED,
    }
    return StartLeadManualEnrollmentResult(
        status=status_by_enrollment_status[result_status],
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        campaign_enrollment_id=(lead_result.campaign_enrollment_id if lead_result else None),
        workflow_id=lead_result.workflow_id if lead_result else None,
        temporal_workflow_id=lead_result.temporal_workflow_id if lead_result else None,
        route=AiNurtureRoute.PAUSED_SEARCH,
        reasons=reason_codes,
        error=error,
    )