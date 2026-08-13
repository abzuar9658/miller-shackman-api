from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    WorkflowTransitionRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.use_cases.campaign_enrollment_types import LeadStartResult, LeadStartStatus
from app.domain.campaigns.enrollment import CampaignEnrollmentSource
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, UserId, WorkspaceId


@dataclass(frozen=True)
class StartSelectedCampaignBatchResult:
    workspace_id: WorkspaceId
    campaign_id: CampaignId
    started_count: int
    already_enrolled_count: int
    already_active_elsewhere_count: int
    terminal_requires_manual_enrollment_count: int
    failed_count: int
    lead_results: tuple[LeadStartResult, ...]
    paused_search_track_assigned_count: int = 0


async def start_selected_campaign_batch(
    *,
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    campaign_version_id: CampaignVersionId,
    lead_ids: Sequence[LeadId],
    source: CampaignEnrollmentSource,
    reason_codes: Sequence[str],
    actor_user_id: UserId | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    now: datetime,
    metadata: Mapping[str, object] | None = None,
    reentry_reason: str | None = None,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    paused_search_track_assignment_repository: (
        PausedSearchTrackAssignmentRepository | None
    ) = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    rollback: Callable[[], Awaitable[None]] | None = None,
) -> StartSelectedCampaignBatchResult:
    lead_results: list[LeadStartResult] = []
    started_count = 0
    already_enrolled_count = 0
    already_active_elsewhere_count = 0
    terminal_requires_manual_enrollment_count = 0
    paused_search_track_assigned_count = 0
    failed_count = 0

    for lead_id in lead_ids:
        existing = await campaign_enrollment_repository.get_by_lead_and_campaign(
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
        )
        if existing is not None:
            lead_results.append(
                LeadStartResult(
                    lead_id=lead_id,
                    status=LeadStartStatus.ALREADY_ENROLLED,
                    campaign_enrollment_id=existing.campaign_enrollment_id,
                ),
            )
            already_enrolled_count += 1
            continue

        result = await start_single_campaign_enrollment(
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
            workspace_operational_control_repository=workspace_operational_control_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            paused_search_track_assignment_repository=(
                paused_search_track_assignment_repository
            ),
            commit=commit,
            now=now,
            metadata=metadata,
            reentry_reason=reentry_reason,
            event_bus=event_bus,
            rollback=rollback,
        )
        lead_results.append(result)
        if result.status == LeadStartStatus.STARTED:
            started_count += 1
        elif result.status == LeadStartStatus.ALREADY_ENROLLED:
            already_enrolled_count += 1
        elif result.status == LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE:
            already_active_elsewhere_count += 1
        elif result.status == LeadStartStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT:
            terminal_requires_manual_enrollment_count += 1
        elif result.status == LeadStartStatus.PAUSED_SEARCH_TRACK_ASSIGNED:
            paused_search_track_assigned_count += 1
        else:
            failed_count += 1

    return StartSelectedCampaignBatchResult(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        started_count=started_count,
        already_enrolled_count=already_enrolled_count,
        already_active_elsewhere_count=already_active_elsewhere_count,
        terminal_requires_manual_enrollment_count=terminal_requires_manual_enrollment_count,
        failed_count=failed_count,
        lead_results=tuple(lead_results),
        paused_search_track_assigned_count=paused_search_track_assigned_count,
    )
