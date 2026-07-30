from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import (
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
)
from app.domain.campaigns.paused_search_timing import (
    PausedSearchNextActionPlan,
    PausedSearchTimingReasonCode,
    plan_paused_search_next_action,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrackStepPhase,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.leads import LeadPausedSearchProfile, lead_paused_search_profile
from app.domain.workflows import LeadWorkflow


class PausedSearchScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    HOLD = "hold"
    NO_TRACK = "no_track"
    NO_PROFILE = "no_profile"
    NO_WORKFLOW = "no_workflow"
    WORKFLOW_NOT_SENDABLE = "workflow_not_sendable"


@dataclass(frozen=True)
class PausedSearchNextActionScheduleResult:
    status: PausedSearchScheduleStatus
    workflow: LeadWorkflow | None = None
    next_action_at: datetime | None = None
    phase: PausedSearchTrackStepPhase | None = None
    step_id: UUID | None = None
    reason_code: PausedSearchTimingReasonCode | None = None
    reason_detail: str | None = None


async def schedule_next_paused_search_action(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    timezone: str,
    now: datetime,
) -> PausedSearchNextActionScheduleResult:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is None:
        return PausedSearchNextActionScheduleResult(
            status=PausedSearchScheduleStatus.NO_WORKFLOW,
        )

    if workflow.paused_search_track_version_id is None:
        return PausedSearchNextActionScheduleResult(
            status=PausedSearchScheduleStatus.NO_TRACK,
            workflow=workflow,
            reason_code=PausedSearchTimingReasonCode.TRACK_UNAVAILABLE,
            reason_detail="workflow has no pinned paused-search track version",
        )

    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return PausedSearchNextActionScheduleResult(
            status=PausedSearchScheduleStatus.NO_PROFILE,
            workflow=workflow,
        )

    profile = lead_paused_search_profile(lead) or LeadPausedSearchProfile(
        paused_search_active=False,
    )

    track_version = await paused_search_track_repository.get_version(
        workspace_id,
        workflow.paused_search_track_version_id,
    )
    if track_version is None:
        return PausedSearchNextActionScheduleResult(
            status=PausedSearchScheduleStatus.NO_TRACK,
            workflow=workflow,
            reason_code=PausedSearchTimingReasonCode.TRACK_UNAVAILABLE,
            reason_detail="pinned track version no longer exists",
        )

    steps = await paused_search_track_repository.get_steps(
        workspace_id,
        workflow.paused_search_track_version_id,
    )

    plan = plan_paused_search_next_action(
        profile=profile,
        track_version=track_version,
        steps=steps,
        workflow=workflow,
        timezone=timezone,
        now=now,
    )

    if plan.reason_code != PausedSearchTimingReasonCode.SCHEDULED:
        workflow = await _save_hold(workflow, lead_workflow_repository, now)
        return _hold_result(workflow, plan)

    workflow = await _save_schedule(workflow, lead_workflow_repository, plan, now)
    return PausedSearchNextActionScheduleResult(
        status=PausedSearchScheduleStatus.SCHEDULED,
        workflow=workflow,
        next_action_at=plan.next_action_at,
        phase=plan.phase,
        step_id=plan.step_id,
        reason_code=plan.reason_code,
    )


async def _save_hold(
    workflow: LeadWorkflow,
    lead_workflow_repository: LeadWorkflowRepository,
    now: datetime,
) -> LeadWorkflow:
    return await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_step_id=None,
            next_action_at=None,
            updated_at=now,
        )
    )


async def _save_schedule(
    workflow: LeadWorkflow,
    lead_workflow_repository: LeadWorkflowRepository,
    plan: PausedSearchNextActionPlan,
    now: datetime,
) -> LeadWorkflow:
    if (
        workflow.paused_search_track_step_id == plan.step_id
        and workflow.next_action_at == plan.next_action_at
    ):
        return workflow
    return await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_step_id=plan.step_id,
            next_action_at=plan.next_action_at,
            updated_at=now,
        )
    )


def _hold_result(
    workflow: LeadWorkflow,
    plan: PausedSearchNextActionPlan,
) -> PausedSearchNextActionScheduleResult:
    if plan.reason_code == PausedSearchTimingReasonCode.WORKFLOW_NOT_SENDABLE:
        status = PausedSearchScheduleStatus.WORKFLOW_NOT_SENDABLE
    else:
        status = PausedSearchScheduleStatus.HOLD
    return PausedSearchNextActionScheduleResult(
        status=status,
        workflow=workflow,
        reason_code=plan.reason_code,
        reason_detail=plan.reason_detail,
    )
