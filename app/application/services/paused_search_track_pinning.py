from dataclasses import replace
from datetime import datetime

from app.application.ports.repositories import (
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import LeadId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.leads import PausedSearchReasonCode
from app.domain.workflows import LeadWorkflow


async def resolve_published_paused_search_track_version_id(
    *,
    workspace_id: WorkspaceId,
    pause_reason_code: PausedSearchReasonCode | None,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
) -> PausedSearchTrackVersionId | None:
    if pause_reason_code is None:
        return None
    mapping = await paused_search_track_repository.get_reason_mapping(
        workspace_id,
        pause_reason_code,
    )
    if mapping is None:
        return None
    version = await paused_search_track_repository.get_version(
        workspace_id,
        mapping.track_version_id,
    )
    if version is None or version.status != CampaignVersionStatus.PUBLISHED:
        return None
    return version.track_version_id


async def pin_published_paused_search_track_on_latest_workflow(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    pause_reason_code: PausedSearchReasonCode | None,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    now: datetime,
) -> LeadWorkflow | None:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return None
    track_version_id = await resolve_published_paused_search_track_version_id(
        workspace_id=workspace_id,
        pause_reason_code=pause_reason_code,
        paused_search_track_repository=paused_search_track_repository,
    )
    if workflow.paused_search_track_version_id == track_version_id:
        return workflow
    return await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_version_id=track_version_id,
            updated_at=now,
        )
    )
