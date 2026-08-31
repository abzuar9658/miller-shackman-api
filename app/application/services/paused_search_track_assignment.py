from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.ports.temporal import (
    TemporalWorkflowExecutionMode,
    TemporalWorkflowStarter,
)
from app.application.services.campaign_enrollment_starter import start_single_campaign_enrollment
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
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
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
    is_terminal_workflow_state,
)


class PausedSearchTrackAssignmentSyncStatus(StrEnum):
    RESOLVED = "resolved"
    REASSIGNED = "reassigned"
    PRESERVED = "preserved"
    CLEARED = "cleared"


class PausedSearchProgressHandling(StrEnum):
    """Admin choice for what happens to a live workflow when a track is (re)selected.

    RESTART closes the current run and starts fresh from step one even when the
    selected track is unchanged. CONTINUE keeps the current run and re-pins it,
    resuming phase-based in the new track. When unspecified, a different track
    restarts and the same track is a no-op (the pre-existing default).
    """

    RESTART = "restart"
    CONTINUE = "continue"


@dataclass(frozen=True)
class PausedSearchTrackAssignmentSyncResult:
    status: PausedSearchTrackAssignmentSyncStatus
    assignment: PausedSearchTrackAssignment | None
    workflow: LeadWorkflow | None
    resolved_track_version_id: PausedSearchTrackVersionId | None = None
    error: str | None = None


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
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    progress_handling: PausedSearchProgressHandling | None = None,
) -> PausedSearchTrackAssignmentSyncResult:
    """Synchronize the durable assignment and latest workflow while both rows are locked.

    Assigning a track to a lead with a live workflow on any other journey —
    a different paused-search track or an unpinned dormant run — is a lifecycle
    event, not an edit: the old run is closed and a fresh enrollment, workflow,
    and Temporal execution are started so the step cursor, touch budget, AI
    budget, and occurrence idempotency keys all reset for the new track.
    Re-pinning the old row would resume mid-track with a spent budget. The
    close-and-create path requires the transition/enrollment repositories and
    the Temporal starter; callers that cannot supply them fall back to the
    legacy re-pin.

    Clearing the assignment never starts or restarts a run: ending the cleared
    track's live workflow is the caller's decision (see
    ``workflow_needs_terminalization_on_clear``), and any next journey — dormant
    or another track — is an explicit admin enrollment, not a side effect of
    the clear.

    ``progress_handling`` lets the admin override that default: RESTART forces
    close-and-create even when the track is unchanged; CONTINUE keeps the
    current run and re-pins it (clearing a now-stale step cursor so the timing
    planner resumes phase-based in the new track).
    """

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
        # A live track-pinned run whose track just disappeared keeps its pin so
        # the caller can terminalize it with the track still recorded;
        # un-pinning it here would leave a paused-search-recurring Temporal
        # execution with no track before the caller gets to end it.
        if not workflow_needs_terminalization_on_clear(workflow):
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
        assignment=assignment,
        target_track_version_id=target_track_version_id,
        track_repository=track_repository,
        pin_applies=_version_pin_applies(
            assignment=assignment,
            workflow=workflow,
            progress_handling=progress_handling,
        ),
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

    if _should_restart_workflow(workflow, version.track_version_id, progress_handling) and (
        workflow_transition_repository is not None
        and campaign_enrollment_repository is not None
        and temporal_workflow_starter is not None
    ):
        assert workflow is not None
        return await _close_and_restart_workflow_for_reassignment(
            workspace_id=workspace_id,
            lead_id=lead_id,
            old_workflow=workflow,
            assignment=assignment,
            new_track_version_id=version.track_version_id,
            actor_user_id=actor_user_id,
            progress_handling=progress_handling,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            commit=commit,
            now=now,
        )

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


# Human-pause states are excluded: reassignment must never silently restart
# automation on a lead a human paused or took over. Those workflows keep the
# legacy re-pin and resume only through the explicit, permission-checked paths.
_REASSIGNABLE_STATES = frozenset(
    {
        WorkflowState.QUEUED,
        WorkflowState.ACTIVE_NURTURE,
        WorkflowState.WAITING_FOR_RESPONSE,
        WorkflowState.RESPONSE_PROCESSING,
    }
)


def _should_restart_workflow(
    workflow: LeadWorkflow | None,
    new_track_version_id: PausedSearchTrackVersionId,
    progress_handling: PausedSearchProgressHandling | None,
) -> bool:
    """A workflow restarts whenever the run it represents is not the assigned track's run.

    That covers both a workflow pinned to a *different* track and an unpinned
    (dormant-journey) workflow being moved onto a track: in either case the old
    run ends and a fresh run starts so the step cursor, touch budget, and AI
    budget belong entirely to the newly assigned track. CONTINUE is the one
    explicit override that keeps the current run.
    """
    if workflow is None or workflow.state not in _REASSIGNABLE_STATES:
        return False
    if progress_handling is PausedSearchProgressHandling.CONTINUE:
        return False
    if progress_handling is PausedSearchProgressHandling.RESTART:
        return True
    return workflow.paused_search_track_version_id != new_track_version_id


def workflow_needs_terminalization_on_clear(workflow: LeadWorkflow | None) -> bool:
    """Whether clearing the paused-search profile must end this workflow.

    A live, automatable workflow that is still pinned to a track cannot outlive
    the track: its Temporal execution runs in paused-search-recurring mode, so
    without a track it would strand pending occurrences with no valid plan.
    Dormant (unpinned) runs are untouched by a clear, and human-pause states
    stay under explicit human control.
    """
    return (
        workflow is not None
        and workflow.state in _REASSIGNABLE_STATES
        and workflow.paused_search_track_version_id is not None
    )


async def _close_and_restart_workflow_for_reassignment(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    old_workflow: LeadWorkflow,
    assignment: PausedSearchTrackAssignment,
    new_track_version_id: PausedSearchTrackVersionId,
    actor_user_id: UserId | None,
    progress_handling: PausedSearchProgressHandling | None,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    commit: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> PausedSearchTrackAssignmentSyncResult:
    """Close the current run and start a fresh one on the newly assigned track."""
    old_enrollment = await campaign_enrollment_repository.get_latest_by_lead_and_campaign(
        workspace_id,
        lead_id,
        old_workflow.campaign_id,
    )
    if old_enrollment is None:
        # A workflow without its enrollment row is unexpected; re-pin rather
        # than guess a campaign version for the fresh run.
        pinned = await _pin_workflow(
            workflow=old_workflow,
            track_version_id=new_track_version_id,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
        return PausedSearchTrackAssignmentSyncResult(
            status=PausedSearchTrackAssignmentSyncStatus.RESOLVED,
            assignment=assignment,
            workflow=pinned,
            resolved_track_version_id=new_track_version_id,
            error="enrollment_missing_for_reassignment",
        )

    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=WorkflowState.CLOSED,
        reason_code=WorkflowTransitionReasonCode.TRACK_REASSIGNED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        now=now,
        actor_user_id=actor_user_id,
        metadata={
            "previous_track_version_id": (
                str(old_workflow.paused_search_track_version_id)
                if old_workflow.paused_search_track_version_id is not None
                else "dormant"
            ),
            "new_track_version_id": str(new_track_version_id),
            **(
                {"progress_handling": progress_handling.value}
                if progress_handling is not None
                else {}
            ),
        },
    )
    if transition.status is not WorkflowStateTransitionStatus.UPDATED:
        return PausedSearchTrackAssignmentSyncResult(
            status=PausedSearchTrackAssignmentSyncStatus.RESOLVED,
            assignment=assignment,
            workflow=old_workflow,
            resolved_track_version_id=new_track_version_id,
            error=transition.skip_reason or "failed to close workflow for track reassignment",
        )

    if temporal_signal_outbox_repository is not None:
        # Wake the old Temporal execution so it observes it has been superseded
        # and exits instead of sleeping until its next timer.
        await temporal_signal_outbox_repository.append(
            TemporalSignalOutboxEntry(
                temporal_signal_id=uuid4(),
                workspace_id=workspace_id,
                workflow_id=old_workflow.workflow_id,
                temporal_workflow_id=old_workflow.temporal_workflow_id,
                signal_name=TemporalSignalName.RESCHEDULE_REQUESTED,
                payload={
                    "lead_id": str(lead_id),
                    "occurred_at": now.isoformat(),
                    "reason": "track_reassigned",
                },
                idempotency_key=f"track-reassigned:{old_workflow.workflow_id}:{new_track_version_id}",
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    lead_result = await start_single_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=old_workflow.campaign_id,
        campaign_version_id=old_enrollment.campaign_version_id,
        lead_id=lead_id,
        source=old_enrollment.source,
        reason_codes=("track_reassigned",),
        actor_user_id=actor_user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        now=now,
        metadata={
            "route": "paused_search",
            "track_reassignment": True,
            "previous_workflow_id": str(old_workflow.workflow_id),
            "previous_track_version_id": (
                str(old_workflow.paused_search_track_version_id)
                if old_workflow.paused_search_track_version_id is not None
                else "dormant"
            ),
        },
        initial_workflow_state=WorkflowState.ACTIVE_NURTURE,
        paused_search_track_version_id=new_track_version_id,
        execution_mode=TemporalWorkflowExecutionMode.PAUSED_SEARCH_RECURRING,
        commit=commit,
        is_track_reassignment=True,
    )
    if lead_result.status is not LeadStartStatus.STARTED:
        return PausedSearchTrackAssignmentSyncResult(
            status=PausedSearchTrackAssignmentSyncStatus.REASSIGNED,
            assignment=assignment,
            workflow=transition.workflow,
            resolved_track_version_id=new_track_version_id,
            error=lead_result.error or "failed to start fresh workflow for reassigned track",
        )

    new_workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id, lead_id
    )
    return PausedSearchTrackAssignmentSyncResult(
        status=PausedSearchTrackAssignmentSyncStatus.REASSIGNED,
        assignment=assignment,
        workflow=new_workflow,
        resolved_track_version_id=new_track_version_id,
    )


async def resolve_effective_paused_search_track_version_id(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    catalog_track_version_id: PausedSearchTrackVersionId,
    assignment_repository: PausedSearchTrackAssignmentRepository,
    track_repository: PausedSearchTrackRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    progress_handling: PausedSearchProgressHandling | None = None,
) -> PausedSearchTrackVersionId:
    """The version a lead should be recorded against for a catalog selection.

    Callers that persist ``lead.paused_search_track_version_id`` must record the
    same version the assignment will hold, otherwise the start path rejects the
    lead on a pin mismatch. This applies the pinning rule described on
    ``_resolve_assignment_snapshot`` and falls back to the catalog version
    whenever no pin applies.
    """
    assignment = await assignment_repository.get_active_for_lead(workspace_id, lead_id)
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id, lead_id
    )
    if not _version_pin_applies(
        assignment=assignment,
        workflow=workflow,
        progress_handling=progress_handling,
    ):
        return catalog_track_version_id
    target_version = await track_repository.get_version(workspace_id, catalog_track_version_id)
    if target_version is None:
        return catalog_track_version_id
    pinned = await _pinned_version_for_same_track(
        workspace_id=workspace_id,
        assignment=assignment,
        target_version=target_version,
        track_repository=track_repository,
    )
    return pinned.track_version_id if pinned is not None else catalog_track_version_id


def _version_pin_applies(
    *,
    assignment: PausedSearchTrackAssignment | None,
    workflow: LeadWorkflow | None,
    progress_handling: PausedSearchProgressHandling | None,
) -> bool:
    """Whether the lead's assigned version should override the catalog's.

    The pin exists to protect a journey that is still running. An admin who
    chose how to handle progress (RESTART/CONTINUE) is deliberately asking for
    the named version, and a lead whose run already ended is starting a new
    journey — both must take the track's current version instead.
    """
    if progress_handling is not None:
        return False
    if assignment is None:
        return False
    return workflow is not None and not is_terminal_workflow_state(workflow.state)


async def _resolve_assignment_snapshot(
    *,
    workspace_id: WorkspaceId,
    assignment: PausedSearchTrackAssignment | None,
    target_track_version_id: PausedSearchTrackVersionId | None,
    track_repository: PausedSearchTrackRepository,
    pin_applies: bool,
) -> tuple[PausedSearchTrack, PausedSearchTrackVersion] | None:
    """Resolve the version this lead should be assigned to.

    Callers resolve a track from the catalog, which always names the track's
    *currently active* version. For a lead already assigned to that same track
    with a live run that is the wrong answer: republishing mints a new version
    id, and treating it as the target would re-point the assignment and restart
    the run, silently moving an in-flight lead onto a new script at step one. So
    when the target names the same track the lead is already on, its pinned
    version wins (see ``_version_pin_applies``). A target naming a *different*
    track is a genuine reassignment and always resolves normally.
    """
    if target_track_version_id is None:
        return None
    target_version = await track_repository.get_version(workspace_id, target_track_version_id)
    if target_version is None:
        return None
    pinned = (
        await _pinned_version_for_same_track(
            workspace_id=workspace_id,
            assignment=assignment,
            target_version=target_version,
            track_repository=track_repository,
        )
        if pin_applies
        else None
    )
    version = pinned or (target_version if _is_assignable_active_version(target_version) else None)
    if version is None:
        return None
    track = await track_repository.get_track(workspace_id, version.track_id)
    if track is None or track.status is PausedSearchTrackStatus.RETIRED:
        return None
    return track, version


async def _pinned_version_for_same_track(
    *,
    workspace_id: WorkspaceId,
    assignment: PausedSearchTrackAssignment | None,
    target_version: PausedSearchTrackVersion,
    track_repository: PausedSearchTrackRepository,
) -> PausedSearchTrackVersion | None:
    if assignment is None or assignment.track_version_id is None:
        return None
    if assignment.track_version_id == target_version.track_version_id:
        return None
    if assignment.track_id != target_version.track_id:
        return None
    pinned = await track_repository.get_version(workspace_id, assignment.track_version_id)
    # A pinned version is retired once a newer one is published, so RETIRED is
    # expected here; DRAFT never is, and a disabled version must not keep
    # driving sends.
    if (
        pinned is None
        or pinned.status is CampaignVersionStatus.DRAFT
        or not pinned.enabled
    ):
        return None
    return pinned


def _is_assignable_active_version(version: PausedSearchTrackVersion) -> bool:
    return version.status is CampaignVersionStatus.PUBLISHED and version.enabled


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
    # Terminal workflows are immutable history; re-pinning them would revive a
    # finished run instead of letting enrollment create a fresh workflow.
    if is_terminal_workflow_state(workflow.state):
        return workflow
    # The step cursor belongs to the previously pinned track; keeping it would
    # make the timing planner hold for review instead of resuming phase-based
    # in the newly pinned track.
    return await lead_workflow_repository.save(
        replace(
            workflow,
            paused_search_track_version_id=track_version_id,
            paused_search_track_step_id=None,
            updated_at=now,
        )
    )