from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowOverrideAuditLogRepository,
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    WorkspaceRepository,
)
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.application.use_cases.lead_paused_search import update_lead_paused_search
from app.application.use_cases.schedule_next_paused_search_action import (
    schedule_next_paused_search_action,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.campaigns.paused_search_tracks import PausedSearchTrackStep
from app.domain.common.ids import LeadId, PausedSearchTrackVersionId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionDecision,
    evaluate_permission,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadPausedSearchProfile,
    lead_paused_search_profile,
)
from app.domain.workflows import (
    LeadWorkflow,
    LeadWorkflowOverrideAction,
    LeadWorkflowOverrideAuditLog,
    WorkflowState,
)


class PausedSearchWorkflowOverrideStatus(StrEnum):
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    INVALID = "invalid"


class PausedSearchWorkflowOverrideReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    WORKFLOW_NOT_FOUND = "workflow_not_found"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    PAUSED_SEARCH_NOT_ACTIVE = "paused_search_not_active"
    WORKFLOW_STATE_NOT_OVERRIDABLE = "workflow_state_not_overridable"
    TRACK_VERSION_NOT_FOUND = "track_version_not_found"
    TRACK_VERSION_NOT_PUBLISHED = "track_version_not_published"
    TRACK_VERSION_DISABLED = "track_version_disabled"
    TRACK_VERSION_UNCHANGED = "track_version_unchanged"
    NO_PINNED_TRACK = "no_pinned_track"
    NO_NEXT_TOUCH_TO_SKIP = "no_next_touch_to_skip"


@dataclass(frozen=True)
class PausedSearchWorkflowOverrideResult:
    status: PausedSearchWorkflowOverrideStatus
    lead_id: LeadId | None = None
    workflow: LeadWorkflow | None = None
    profile: LeadPausedSearchProfile | None = None
    audit_log: LeadWorkflowOverrideAuditLog | None = None
    skipped_step_id: UUID | None = None
    reasons: tuple[PausedSearchWorkflowOverrideReasonCode, ...] = ()


async def override_paused_search_timing(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reengagement_not_before: datetime | None,
    reengagement_window_label: str | None,
    reason: str,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    workspace_repository: WorkspaceRepository,
    now: datetime,
) -> PausedSearchWorkflowOverrideResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.NOT_FOUND,
            PausedSearchWorkflowOverrideReasonCode.LEAD_NOT_FOUND,
        )
    if not _can_edit_paused_search(actor, lead):
        return _result(
            PausedSearchWorkflowOverrideStatus.REJECTED,
            PausedSearchWorkflowOverrideReasonCode.PERMISSION_DENIED,
        )
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKFLOW_NOT_FOUND,
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKSPACE_NOT_FOUND,
        )
    previous_profile = lead_paused_search_profile(lead)
    if previous_profile is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.PAUSED_SEARCH_NOT_ACTIVE,
        )

    update_result = await update_lead_paused_search(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        active=True,
        reason_code=previous_profile.pause_reason_code,
        reason_note=previous_profile.pause_reason_note,
        reengagement_not_before=reengagement_not_before,
        reengagement_window_label=reengagement_window_label,
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )
    if update_result.status == "unchanged":
        return PausedSearchWorkflowOverrideResult(
            status=PausedSearchWorkflowOverrideStatus.UNCHANGED,
            lead_id=lead_id,
            workflow=workflow,
            profile=previous_profile,
        )

    saved_workflow = workflow
    if _workflow_allows_cursor_override(workflow):
        schedule_result = await schedule_next_paused_search_action(
            workspace_id=workspace_id,
            lead_id=lead_id,
            lead_repository=lead_repository,
            paused_search_track_repository=paused_search_track_repository,
            lead_workflow_repository=lead_workflow_repository,
            timezone=workspace.default_timezone,
            now=now,
        )
        if schedule_result.workflow is not None:
            saved_workflow = schedule_result.workflow
    audit_log = await lead_workflow_override_audit_repository.append(
        LeadWorkflowOverrideAuditLog(
            audit_log_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow.workflow_id,
            actor_user_id=actor.user_id,
            action=LeadWorkflowOverrideAction.TIMING_CHANGED,
            reason=reason,
            created_at=now,
            details={
                "previous_reengagement_not_before": _iso_or_none(
                    previous_profile.reengagement_not_before
                ),
                "new_reengagement_not_before": _iso_or_none(reengagement_not_before),
                "previous_reengagement_window_label": previous_profile.reengagement_window_label,
                "new_reengagement_window_label": _normalized_optional_text(
                    reengagement_window_label
                ),
            },
        )
    )
    return PausedSearchWorkflowOverrideResult(
        status=PausedSearchWorkflowOverrideStatus.UPDATED,
        lead_id=lead_id,
        workflow=saved_workflow,
        profile=update_result.profile,
        audit_log=audit_log,
    )


async def migrate_paused_search_track_version(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    target_track_version_id: PausedSearchTrackVersionId,
    reason: str,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    workspace_repository: WorkspaceRepository,
    now: datetime,
) -> PausedSearchWorkflowOverrideResult:
    if not evaluate_permission(
        actor,
        PermissionCapability.RESUME_OR_REASSIGN_ANY_LEAD,
        PermissionContext(),
    ).allowed:
        return _result(
            PausedSearchWorkflowOverrideStatus.REJECTED,
            PausedSearchWorkflowOverrideReasonCode.PERMISSION_DENIED,
        )
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.NOT_FOUND,
            PausedSearchWorkflowOverrideReasonCode.LEAD_NOT_FOUND,
        )
    if lead_paused_search_profile(lead) is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.PAUSED_SEARCH_NOT_ACTIVE,
        )
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKFLOW_NOT_FOUND,
        )
    if not _workflow_allows_cursor_override(workflow):
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKFLOW_STATE_NOT_OVERRIDABLE,
        )
    if workflow.paused_search_track_version_id is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.NO_PINNED_TRACK,
        )
    if workflow.paused_search_track_version_id == target_track_version_id:
        return _result(
            PausedSearchWorkflowOverrideStatus.UNCHANGED,
            PausedSearchWorkflowOverrideReasonCode.TRACK_VERSION_UNCHANGED,
        )
    target_track_version = await paused_search_track_repository.get_version(
        workspace_id,
        target_track_version_id,
    )
    if target_track_version is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.TRACK_VERSION_NOT_FOUND,
        )
    if target_track_version.status is not CampaignVersionStatus.PUBLISHED:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.TRACK_VERSION_NOT_PUBLISHED,
        )
    if not target_track_version.enabled:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.TRACK_VERSION_DISABLED,
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKSPACE_NOT_FOUND,
        )

    updated_workflow = await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_version_id=target_track_version_id,
            paused_search_track_step_id=None,
            next_action_at=None,
            updated_at=now,
        )
    )
    schedule_result = await schedule_next_paused_search_action(
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=lead_repository,
        paused_search_track_repository=paused_search_track_repository,
        lead_workflow_repository=lead_workflow_repository,
        timezone=workspace.default_timezone,
        now=now,
    )
    saved_workflow = schedule_result.workflow or updated_workflow
    await enqueue_lead_nurture_reschedule_signal(
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason="paused_search_track_version_migrated",
        occurred_at=now,
        lead_workflow_repository=lead_workflow_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        actor_user_id=actor.user_id,
    )
    audit_log = await lead_workflow_override_audit_repository.append(
        LeadWorkflowOverrideAuditLog(
            audit_log_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow.workflow_id,
            actor_user_id=actor.user_id,
            action=LeadWorkflowOverrideAction.TRACK_VERSION_MIGRATED,
            reason=reason,
            created_at=now,
            details={
                "previous_track_version_id": str(workflow.paused_search_track_version_id),
                "new_track_version_id": str(target_track_version_id),
            },
        )
    )
    return PausedSearchWorkflowOverrideResult(
        status=PausedSearchWorkflowOverrideStatus.UPDATED,
        lead_id=lead_id,
        workflow=saved_workflow,
        profile=lead_paused_search_profile(lead),
        audit_log=audit_log,
    )


async def skip_paused_search_next_touch(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason: str,
    lead_repository: LeadRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    workspace_repository: WorkspaceRepository,
    now: datetime,
) -> PausedSearchWorkflowOverrideResult:
    lead = await lead_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.NOT_FOUND,
            PausedSearchWorkflowOverrideReasonCode.LEAD_NOT_FOUND,
        )
    if not _can_edit_paused_search(actor, lead):
        return _result(
            PausedSearchWorkflowOverrideStatus.REJECTED,
            PausedSearchWorkflowOverrideReasonCode.PERMISSION_DENIED,
        )
    if lead_paused_search_profile(lead) is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.PAUSED_SEARCH_NOT_ACTIVE,
        )
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(workspace_id, lead_id)
    if workflow is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKFLOW_NOT_FOUND,
        )
    if not _workflow_allows_cursor_override(workflow):
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKFLOW_STATE_NOT_OVERRIDABLE,
        )
    if (
        workflow.paused_search_track_version_id is None
        or workflow.paused_search_track_step_id is None
    ):
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.NO_NEXT_TOUCH_TO_SKIP,
        )
    steps = await paused_search_track_repository.get_steps(
        workspace_id,
        workflow.paused_search_track_version_id,
    )
    next_step_id = _next_step_id_after_current(workflow.paused_search_track_step_id, steps)
    if next_step_id is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.NO_NEXT_TOUCH_TO_SKIP,
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        return _result(
            PausedSearchWorkflowOverrideStatus.INVALID,
            PausedSearchWorkflowOverrideReasonCode.WORKSPACE_NOT_FOUND,
        )

    updated_workflow = await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_step_id=next_step_id,
            next_action_at=None,
            updated_at=now,
        )
    )
    schedule_result = await schedule_next_paused_search_action(
        workspace_id=workspace_id,
        lead_id=lead_id,
        lead_repository=lead_repository,
        paused_search_track_repository=paused_search_track_repository,
        lead_workflow_repository=lead_workflow_repository,
        timezone=workspace.default_timezone,
        now=now,
    )
    saved_workflow = schedule_result.workflow or updated_workflow
    await enqueue_lead_nurture_reschedule_signal(
        workspace_id=workspace_id,
        lead_id=lead_id,
        reason="paused_search_next_touch_skipped",
        occurred_at=now,
        lead_workflow_repository=lead_workflow_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        actor_user_id=actor.user_id,
    )
    audit_log = await lead_workflow_override_audit_repository.append(
        LeadWorkflowOverrideAuditLog(
            audit_log_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            workflow_id=workflow.workflow_id,
            actor_user_id=actor.user_id,
            action=LeadWorkflowOverrideAction.NEXT_TOUCH_SKIPPED,
            reason=reason,
            created_at=now,
            details={
                "skipped_step_id": str(workflow.paused_search_track_step_id),
                "new_target_step_id": str(next_step_id),
            },
        )
    )
    return PausedSearchWorkflowOverrideResult(
        status=PausedSearchWorkflowOverrideStatus.UPDATED,
        lead_id=lead_id,
        workflow=saved_workflow,
        profile=lead_paused_search_profile(lead),
        audit_log=audit_log,
        skipped_step_id=workflow.paused_search_track_step_id,
    )


def _can_edit_paused_search(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    any_lead_decision: PermissionDecision = evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_ANY_LEAD,
        PermissionContext(),
    )
    own_lead_decision: PermissionDecision = evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_OWN_LEAD,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )
    return any_lead_decision.allowed or own_lead_decision.allowed


def _workflow_allows_cursor_override(workflow: LeadWorkflow) -> bool:
    return workflow.state in {
        WorkflowState.QUEUED,
        WorkflowState.ACTIVE_NURTURE,
        WorkflowState.PAUSED,
    }


def _next_step_id_after_current(
    current_step_id: UUID,
    steps: tuple[PausedSearchTrackStep, ...],
) -> UUID | None:
    current_index: int | None = None
    current_phase: object | None = None
    ordered_steps = sorted(steps, key=lambda item: item.step_order)
    for index, step in enumerate(ordered_steps):
        if step.step_id == current_step_id:
            current_index = index
            current_phase = step.phase
            break
    if current_index is None:
        return None
    for step in ordered_steps[current_index + 1 :]:
        if step.phase == current_phase:
            return step.step_id
    return None


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _result(
    status: PausedSearchWorkflowOverrideStatus,
    reason: PausedSearchWorkflowOverrideReasonCode,
) -> PausedSearchWorkflowOverrideResult:
    return PausedSearchWorkflowOverrideResult(status=status, reasons=(reason,))