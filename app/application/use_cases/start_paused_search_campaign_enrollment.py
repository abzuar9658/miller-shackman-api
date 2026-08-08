from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    WorkflowTransitionRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import (
    TemporalWorkflowExecutionMode,
    TemporalWorkflowStarter,
)
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.services.paused_search_track_assignment import (
    synchronize_paused_search_track_assignment,
)
from app.application.services.workspace_automation_control import (
    recurring_paused_search_block_reason,
    recurring_paused_search_is_enabled,
    resolve_workspace_operational_control,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.campaign_enrollment_types import (
    LeadStartResult,
    LeadStartStatus,
)
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackAssignmentSource
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode


class PausedSearchCampaignEnrollmentStatus(StrEnum):
    STARTED = "started"
    ALREADY_ENROLLED = "already_enrolled"
    REVIEW_HOLD = "review_hold"
    FAILED = "failed"


@dataclass(frozen=True)
class PausedSearchCampaignEnrollmentResult:
    status: PausedSearchCampaignEnrollmentStatus
    lead_result: LeadStartResult | None = None
    reason_codes: tuple[str, ...] = ()
    error: str | None = None


async def start_paused_search_campaign_enrollment(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    lead_id: LeadId,
    lead: CanonicalLeadRecord,
    source: CampaignEnrollmentSource,
    reason_codes: tuple[str, ...],
    actor_user_id: UUID | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    commit: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> PausedSearchCampaignEnrollmentResult:
    if workspace_operational_control_repository is not None:
        operational_control = await resolve_workspace_operational_control(
            workspace_id=workspace_id,
            workspace_operational_control_repository=workspace_operational_control_repository,
        )
        if not recurring_paused_search_is_enabled(
            control=operational_control,
            workspace_id=workspace_id,
        ):
            return PausedSearchCampaignEnrollmentResult(
                status=PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD,
                reason_codes=reason_codes + ("recurring_paused_search_disabled",),
                error=recurring_paused_search_block_reason(
                    control=operational_control,
                    workspace_id=workspace_id,
                ),
            )

    active_assignment = (
        await paused_search_track_assignment_repository.get_active_for_lead_for_update(
            workspace_id, lead_id
        )
    )
    if active_assignment is None:
        return PausedSearchCampaignEnrollmentResult(
            status=PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD,
            reason_codes=reason_codes + ("paused_search_track_assignment_unavailable",),
        )
    if active_assignment.track_version_id is None:
        return PausedSearchCampaignEnrollmentResult(
            status=PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD,
            reason_codes=reason_codes + ("paused_search_track_assignment_unavailable",),
        )

    existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
        workspace_id,
        lead_id,
        campaign_id,
    )
    if existing is None:
        lead_result = await start_single_campaign_enrollment(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            campaign_version_id=campaign_version_id,
            lead_id=lead_id,
            source=source,
            reason_codes=reason_codes,
            actor_user_id=actor_user_id,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            now=now,
            metadata=_paused_search_enrollment_metadata(lead),
            initial_workflow_state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=active_assignment.track_version_id,
            execution_mode=TemporalWorkflowExecutionMode.PAUSED_SEARCH_RECURRING,
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            commit=commit,
        )
    else:
        lead_result = LeadStartResult(
            lead_id=lead_id,
            status=LeadStartStatus.ALREADY_ENROLLED,
            campaign_enrollment_id=existing.campaign_enrollment_id,
        )

    if lead_result.status not in {LeadStartStatus.STARTED, LeadStartStatus.ALREADY_ENROLLED}:
        return PausedSearchCampaignEnrollmentResult(
            status=PausedSearchCampaignEnrollmentStatus.FAILED,
            lead_result=lead_result,
            error=lead_result.error or "failed to start enrollment",
        )

    assignment_result = await synchronize_paused_search_track_assignment(
        workspace_id=workspace_id,
        lead_id=lead_id,
        clear=False,
        actor_user_id=actor_user_id,
        source=PausedSearchTrackAssignmentSource.CLASSIFICATION,
        assignment_repository=paused_search_track_assignment_repository,
        track_repository=paused_search_track_repository,
        lead_workflow_repository=lead_workflow_repository,
        now=now,
        target_track_version_id=active_assignment.track_version_id,
    )
    pinned_workflow = assignment_result.workflow
    if pinned_workflow is None:
        return PausedSearchCampaignEnrollmentResult(
            status=PausedSearchCampaignEnrollmentStatus.FAILED,
            lead_result=lead_result,
            error="failed to pin paused-search track on workflow",
        )

    if pinned_workflow.state == WorkflowState.QUEUED:
        transition_result = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=WorkflowState.ACTIVE_NURTURE,
            reason_code=WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
            metadata=_paused_search_enrollment_metadata(lead),
        )
        if transition_result.status not in {
            WorkflowStateTransitionStatus.UPDATED,
            WorkflowStateTransitionStatus.SKIPPED,
        }:
            return PausedSearchCampaignEnrollmentResult(
                status=PausedSearchCampaignEnrollmentStatus.FAILED,
                lead_result=lead_result,
                error="failed to activate paused-search workflow",
            )
        if transition_result.workflow is not None:
            pinned_workflow = transition_result.workflow

    if existing is not None and pinned_workflow.temporal_workflow_id is not None:
        if commit is not None:
            await commit()
        await temporal_workflow_starter.configure_paused_search_workflow(
            temporal_workflow_id=pinned_workflow.temporal_workflow_id,
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=pinned_workflow.workflow_id,
            paused_search_track_version_id=active_assignment.track_version_id,
            occurred_at=now,
            reason="operator_selected_paused_search_track",
        )

    lead_result = LeadStartResult(
        lead_id=lead_id,
        status=lead_result.status,
        campaign_enrollment_id=lead_result.campaign_enrollment_id,
        workflow_id=pinned_workflow.workflow_id,
        temporal_workflow_id=pinned_workflow.temporal_workflow_id,
        error=lead_result.error,
    )

    if commit is not None:
        await commit()
    return PausedSearchCampaignEnrollmentResult(
        status=(
            PausedSearchCampaignEnrollmentStatus.STARTED
            if lead_result.status == LeadStartStatus.STARTED
            else PausedSearchCampaignEnrollmentStatus.ALREADY_ENROLLED
        ),
        lead_result=lead_result,
        reason_codes=reason_codes,
    )


def _paused_search_enrollment_metadata(lead: CanonicalLeadRecord) -> dict[str, object]:
    metadata: dict[str, object] = {
        "route": "paused_search",
        "paused_search_active": lead.paused_search_active,
        "explanation": "Lead routed onto the paused-search nurture path.",
    }
    if lead.paused_search_track_key is not None:
        metadata["paused_search_track_key"] = lead.paused_search_track_key
    if lead.paused_search_track_version_id is not None:
        metadata["paused_search_track_version_id"] = str(lead.paused_search_track_version_id)
    if lead.reengagement_window_label:
        metadata["reengagement_window_label"] = lead.reengagement_window_label
    if lead.reengagement_not_before is not None:
        metadata["reengagement_not_before"] = lead.reengagement_not_before.isoformat()
    return metadata
