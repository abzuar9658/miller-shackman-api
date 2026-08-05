from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceOperationalControlRepository,
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
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
    occurrence_idempotency_key,
)
from app.domain.campaigns.paused_search_timing import (
    PausedSearchNextActionPlan,
    PausedSearchOccurrencePlan,
    PausedSearchTimingReasonCode,
    plan_next_paused_search_occurrence,
    plan_paused_search_next_action,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTerminalBehavior,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import default_workspace_contact_policy
from app.domain.leads import LeadPausedSearchProfile, lead_paused_search_profile
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class PausedSearchScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    HOLD = "hold"
    NO_TRACK = "no_track"
    NO_PROFILE = "no_profile"
    NO_WORKFLOW = "no_workflow"
    WORKFLOW_NOT_SENDABLE = "workflow_not_sendable"
    TERMINAL = "terminal"
    REVIEW = "review"


@dataclass(frozen=True)
class PausedSearchNextActionScheduleResult:
    status: PausedSearchScheduleStatus
    workflow: LeadWorkflow | None = None
    next_action_at: datetime | None = None
    phase: PausedSearchTrackStepPhase | None = None
    step_id: UUID | None = None
    reason_code: PausedSearchTimingReasonCode | None = None
    reason_detail: str | None = None
    occurrence: RecurringOccurrence | None = None


async def schedule_next_paused_search_action(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    lead_repository: LeadRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    timezone: str,
    now: datetime,
    occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    recurring_paused_search_pilot_workspace_ids: Collection[WorkspaceId] | None = None,
) -> PausedSearchNextActionScheduleResult:
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is None:
        return PausedSearchNextActionScheduleResult(
            status=PausedSearchScheduleStatus.NO_WORKFLOW,
        )

    if occurrence_repository is not None and workspace_operational_control_repository is not None:
        operational_control = await resolve_workspace_operational_control(
            workspace_id=workspace_id,
            workspace_operational_control_repository=workspace_operational_control_repository,
        )
        if not recurring_paused_search_is_enabled(
            control=operational_control,
            workspace_id=workspace_id,
            pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
        ):
            return PausedSearchNextActionScheduleResult(
                status=PausedSearchScheduleStatus.HOLD,
                workflow=workflow,
                reason_code=PausedSearchTimingReasonCode.HOLD_FOR_REVIEW,
                reason_detail=recurring_paused_search_block_reason(
                    control=operational_control,
                    workspace_id=workspace_id,
                    pilot_workspace_ids=recurring_paused_search_pilot_workspace_ids,
                ),
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

    contact_policy = default_workspace_contact_policy(workspace_id)
    if workspace_contact_policy_repository is not None:
        contact_policy = (
            await workspace_contact_policy_repository.get_by_workspace_id(workspace_id)
            or contact_policy
        )

    plan = plan_paused_search_next_action(
        profile=profile,
        track_version=track_version,
        steps=steps,
        workflow=workflow,
        timezone=timezone,
        now=now,
        quiet_hours_enabled=contact_policy.quiet_hours_enabled,
        quiet_hours_start=contact_policy.quiet_hours_start,
        quiet_hours_end=contact_policy.quiet_hours_end,
    )

    if plan.reason_code != PausedSearchTimingReasonCode.SCHEDULED:
        workflow = await _save_terminal_or_hold(
            workflow=workflow,
            track_version=track_version,
            reason_code=plan.reason_code,
            reason_detail=plan.reason_detail,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            now=now,
        )
        return _hold_result(workflow, plan)

    occurrence_plan: PausedSearchOccurrencePlan | None = None
    occurrence: RecurringOccurrence | None = None
    if occurrence_repository is not None and plan.step_id is not None:
        step = next((candidate for candidate in steps if candidate.step_id == plan.step_id), None)
        if step is not None:
            assert workflow.paused_search_track_version_id is not None
            track_version_id = workflow.paused_search_track_version_id
            latest = await occurrence_repository.get_latest_for_step(
                workspace_id,
                workflow.workflow_id,
                track_version_id,
                step.step_id,
            )
            if latest is not None and latest.status in _OPEN_OCCURRENCE_STATUSES:
                workflow = await _save_schedule(
                    workflow,
                    lead_workflow_repository,
                    PausedSearchNextActionPlan(
                        next_action_at=latest.scheduled_for,
                        phase=latest.phase,
                        step_id=latest.step_id,
                        reason_code=PausedSearchTimingReasonCode.SCHEDULED,
                    ),
                    now,
                )
                return PausedSearchNextActionScheduleResult(
                    status=PausedSearchScheduleStatus.SCHEDULED,
                    workflow=workflow,
                    next_action_at=latest.scheduled_for,
                    phase=latest.phase,
                    step_id=latest.step_id,
                    reason_code=PausedSearchTimingReasonCode.SCHEDULED,
                    occurrence=latest,
                )

            occurrence_number = latest.occurrence_number + 1 if latest is not None else 1
            occurrence_plan = plan_next_paused_search_occurrence(
                profile=profile,
                track_version=track_version,
                step=step,
                steps=steps,
                workflow=workflow,
                timezone=timezone,
                now=now,
                occurrence_number=occurrence_number,
                previous_due_at=latest.due_at if latest is not None else None,
                quiet_hours_enabled=contact_policy.quiet_hours_enabled,
                quiet_hours_start=contact_policy.quiet_hours_start,
                quiet_hours_end=contact_policy.quiet_hours_end,
            )
            if occurrence_plan.reason_code != PausedSearchTimingReasonCode.SCHEDULED:
                workflow = await _save_terminal_or_hold(
                    workflow=workflow,
                    track_version=track_version,
                    reason_code=occurrence_plan.reason_code,
                    reason_detail=occurrence_plan.reason_detail,
                    lead_workflow_repository=lead_workflow_repository,
                    workflow_transition_repository=workflow_transition_repository,
                    now=now,
                )
                return _occurrence_hold_result(workflow, occurrence_plan)

            assert occurrence_plan.next_action_at is not None
            assert occurrence_plan.due_at is not None
            occurrence = await occurrence_repository.create_or_get(
                RecurringOccurrence(
                    occurrence_id=uuid4(),
                    workspace_id=workspace_id,
                    lead_id=lead_id,
                    workflow_id=workflow.workflow_id,
                    track_version_id=track_version_id,
                    step_id=step.step_id,
                    phase=step.phase,
                    occurrence_number=occurrence_plan.occurrence_number,
                    scheduled_for=occurrence_plan.next_action_at,
                    due_at=occurrence_plan.due_at,
                    status=RecurringOccurrenceStatus.PLANNED,
                    idempotency_key=occurrence_idempotency_key(
                        workflow_id=workflow.workflow_id,
                        track_version_id=track_version_id,
                        step_id=step.step_id,
                        occurrence_number=occurrence_plan.occurrence_number,
                        channel=step.channel.value,
                    ),
                    created_at=now,
                    timezone_snapshot=timezone,
                )
            )
            plan = PausedSearchNextActionPlan(
                next_action_at=occurrence_plan.next_action_at,
                phase=occurrence_plan.phase,
                step_id=occurrence_plan.step_id,
                reason_code=occurrence_plan.reason_code,
            )

    workflow = await _save_schedule(workflow, lead_workflow_repository, plan, now)
    return PausedSearchNextActionScheduleResult(
        status=PausedSearchScheduleStatus.SCHEDULED,
        workflow=workflow,
        next_action_at=plan.next_action_at,
        phase=plan.phase,
        step_id=plan.step_id,
        reason_code=plan.reason_code,
        occurrence=occurrence,
    )


_OPEN_OCCURRENCE_STATUSES = frozenset(
    {
        RecurringOccurrenceStatus.PLANNED,
        RecurringOccurrenceStatus.DEFERRED,
        RecurringOccurrenceStatus.REVIEW_REQUESTED,
        RecurringOccurrenceStatus.APPROVED,
        RecurringOccurrenceStatus.UNCERTAIN,
    }
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


async def _save_terminal_or_hold(
    *,
    workflow: LeadWorkflow,
    track_version: PausedSearchTrackVersion,
    reason_code: PausedSearchTimingReasonCode,
    reason_detail: str | None,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    now: datetime,
) -> LeadWorkflow:
    terminal_reason_codes = {
        PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED,
        PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED,
        PausedSearchTimingReasonCode.DURATION_EXPIRED,
    }
    if reason_code not in terminal_reason_codes or workflow_transition_repository is None:
        return await _save_hold(workflow, lead_workflow_repository, now)

    target_state = {
        PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED: WorkflowState.COMPLETED,
        PausedSearchTerminalBehavior.CLOSE_AUTOMATION: WorkflowState.CLOSED,
        PausedSearchTerminalBehavior.PAUSE_FOR_REVIEW: WorkflowState.PAUSED,
    }[track_version.terminal_behavior]
    outcome = await apply_workflow_state_transition(
        workspace_id=workflow.workspace_id,
        lead_id=workflow.lead_id,
        to_state=target_state,
        reason_code=WorkflowTransitionReasonCode.PAUSED_SEARCH_TERMINALIZED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        now=now,
        metadata={
            "reason_code": reason_code.value,
            "reason_detail": reason_detail,
            "terminal_behavior": track_version.terminal_behavior.value,
        },
        pause_reason=(
            "paused_search_terminal_review" if target_state == WorkflowState.PAUSED else None
        ),
    )
    if outcome.status == WorkflowStateTransitionStatus.UPDATED and outcome.workflow is not None:
        return outcome.workflow
    return workflow


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
    elif plan.reason_code == PausedSearchTimingReasonCode.TOUCH_LIMIT_REACHED:
        status = _terminal_schedule_status(workflow)
    else:
        status = PausedSearchScheduleStatus.HOLD
    return PausedSearchNextActionScheduleResult(
        status=status,
        workflow=workflow,
        reason_code=plan.reason_code,
        reason_detail=plan.reason_detail,
    )


def _occurrence_hold_result(
    workflow: LeadWorkflow,
    plan: PausedSearchOccurrencePlan,
) -> PausedSearchNextActionScheduleResult:
    return PausedSearchNextActionScheduleResult(
        status=(
            _terminal_schedule_status(workflow)
            if plan.reason_code
            in {
                PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED,
                PausedSearchTimingReasonCode.DURATION_EXPIRED,
            }
            else PausedSearchScheduleStatus.HOLD
        ),
        workflow=workflow,
        phase=plan.phase,
        step_id=plan.step_id,
        reason_code=plan.reason_code,
        reason_detail=plan.reason_detail,
    )


def _terminal_schedule_status(workflow: LeadWorkflow) -> PausedSearchScheduleStatus:
    if workflow.state == WorkflowState.PAUSED:
        return PausedSearchScheduleStatus.REVIEW
    return PausedSearchScheduleStatus.TERMINAL
