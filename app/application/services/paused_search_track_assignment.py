from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
)
from app.domain.campaigns import (
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackStatus,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import (
    LeadId,
    PausedSearchTrackVersionId,
    UserId,
    WorkspaceId,
)
from app.domain.workflows import LeadWorkflow


class PausedSearchTrackAssignmentSyncStatus(StrEnum):
    RESOLVED = "resolved"
    PRESERVED = "preserved"
    CLEARED = "cleared"


@dataclass(frozen=True)
class PausedSearchTrackAssignmentSyncResult:
    status: PausedSearchTrackAssignmentSyncStatus
    assignment: PausedSearchTrackAssignment | None
    workflow: LeadWorkflow | None
    resolved_track_version_id: PausedSearchTrackVersionId | None = None


async def synchronize_paused_search_track_assignment(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    clear: bool,
    actor_user_id: UserId | None,
    source: PausedSearchTrackAssignmentSource,
    assignment_repository: PausedSearchTrackAssignmentRepository,
    track_repository: PausedSearchTrackRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
    target_track_version_id: PausedSearchTrackVersionId | None = None,
) -> PausedSearchTrackAssignmentSyncResult:
    """Synchronize the durable assignment and latest workflow while both rows are locked."""
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id, lead_id
    )
    assignment = await assignment_repository.get_active_for_lead_for_update(
        workspace_id, lead_id
    )

    if clear:
        if assignment is not None:
            await assignment_repository.release_active(
                workspace_id=workspace_id,
                lead_id=lead_id,
                released_at=now,
                released_by=actor_user_id,
                release_reason="paused_search_profile_cleared",
            )
        workflow = await _pin_workflow(
            workflow=workflow,
            track_version_id=None,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
        return PausedSearchTrackAssignmentSyncResult(
            status=PausedSearchTrackAssignmentSyncStatus.CLEARED,
            assignment=None,
            workflow=workflow,
        )

    resolved = await _resolve_assignment_snapshot(
        workspace_id=workspace_id,
        target_track_version_id=target_track_version_id,
        track_repository=track_repository,
    )
    if resolved is None:
        return PausedSearchTrackAssignmentSyncResult(
            status=PausedSearchTrackAssignmentSyncStatus.PRESERVED,
            assignment=assignment,
            workflow=workflow,
        )
    track, version = resolved

    if not _assignment_matches(assignment, version.track_version_id):
        if assignment is not None:
            await assignment_repository.release_active(
                workspace_id=workspace_id,
                lead_id=lead_id,
                released_at=now,
                released_by=actor_user_id,
                release_reason="paused_search_track_assignment_replaced",
            )
        assignment = await assignment_repository.create(
            PausedSearchTrackAssignment(
                assignment_id=uuid4(),
                workspace_id=workspace_id,
                lead_id=lead_id,
                track_id=track.track_id,
                track_version_id=version.track_version_id,
                track_key_snapshot=track.track_key,
                track_name_snapshot=track.display_name,
                track_version_snapshot=version.version_number,
                source=source,
                assigned_by_user_id=actor_user_id,
                assigned_at=now,
            )
        )
    assert assignment is not None

    workflow = await _pin_workflow(
        workflow=workflow,
        track_version_id=assignment.track_version_id,
        lead_workflow_repository=lead_workflow_repository,
        now=now,
    )
    return PausedSearchTrackAssignmentSyncResult(
        status=PausedSearchTrackAssignmentSyncStatus.RESOLVED,
        assignment=assignment,
        workflow=workflow,
        resolved_track_version_id=version.track_version_id,
    )


async def _resolve_assignment_snapshot(
    *,
    workspace_id: WorkspaceId,
    target_track_version_id: PausedSearchTrackVersionId | None,
    track_repository: PausedSearchTrackRepository,
) -> tuple[PausedSearchTrack, PausedSearchTrackVersion] | None:
    track_version_id = target_track_version_id
    if track_version_id is None:
        return None
    version = await track_repository.get_version(workspace_id, track_version_id)
    if (
        version is None
        or version.status is not CampaignVersionStatus.PUBLISHED
        or not version.enabled
    ):
        return None
    track = await track_repository.get_track(workspace_id, version.track_id)
    if track is None or track.status is PausedSearchTrackStatus.RETIRED:
        return None
    return track, version


def _assignment_matches(
    assignment: PausedSearchTrackAssignment | None,
    track_version_id: PausedSearchTrackVersionId,
) -> bool:
    return (
        assignment is not None
        and assignment.track_version_id == track_version_id
    )


async def _pin_workflow(
    *,
    workflow: LeadWorkflow | None,
    track_version_id: PausedSearchTrackVersionId | None,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow | None:
    if workflow is None or workflow.paused_search_track_version_id == track_version_id:
        return workflow
    return await lead_workflow_repository.save(
        replace(workflow, paused_search_track_version_id=track_version_id, updated_at=now)
    )