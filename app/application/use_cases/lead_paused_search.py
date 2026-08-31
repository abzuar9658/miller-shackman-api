from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    ExternalEventRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchOccurrenceRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.application.services.paused_search_track_assignment import (
    PausedSearchProgressHandling,
    resolve_effective_paused_search_track_version_id,
    synchronize_paused_search_track_assignment,
    workflow_needs_terminalization_on_clear,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.campaigns import (
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackCatalogEntry,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTerminalBehavior
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    evaluate_permission,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    PausedSearchAction,
    PausedSearchSource,
    lead_paused_search_profile,
)
from app.domain.workflows import (
    WorkflowState,
    WorkflowTransitionReasonCode,
    is_terminal_workflow_state,
)


class LeadPausedSearchActionStatus(StrEnum):
    UPDATED = "updated"
    CLEARED = "cleared"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadPausedSearchActionReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    LEAD_NOT_FOUND = "lead_not_found"
    TRACK_REQUIRED = "track_required"
    TRACK_UNAVAILABLE = "track_unavailable"
    TRACK_AMBIGUOUS = "track_ambiguous"
    TERMINAL_BEHAVIOR_INVALID = "terminal_behavior_invalid"


@dataclass(frozen=True)
class LeadPausedSearchActionResult:
    status: LeadPausedSearchActionStatus
    lead_id: LeadId | None = None
    profile: LeadPausedSearchProfile | None = None
    history_entry: LeadPausedSearchHistoryEntry | None = None
    reasons: tuple[LeadPausedSearchActionReasonCode, ...] = ()
    workflow_terminalized: bool = False
    workflow_state: WorkflowState | None = None


async def update_lead_paused_search(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    active: bool,
    selected_track_key: str | None,
    reason_note: str | None,
    reengagement_not_before: datetime | None,
    reengagement_window_label: str | None,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    terminal_behavior: PausedSearchTerminalBehavior | None = None,
    terminal_reason: str | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None = None,
    external_event_repository: ExternalEventRepository | None = None,
    temporal_workflow_starter: TemporalWorkflowStarter | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    progress_handling: PausedSearchProgressHandling | None = None,
    now: datetime,
) -> LeadPausedSearchActionResult:
    lead = await lead_repository.get_by_id_for_update(workspace_id, lead_id)
    if lead is None:
        return LeadPausedSearchActionResult(
            status=LeadPausedSearchActionStatus.NOT_FOUND,
            reasons=(LeadPausedSearchActionReasonCode.LEAD_NOT_FOUND,),
        )

    if not _can_edit_paused_search(actor, lead):
        return LeadPausedSearchActionResult(
            status=LeadPausedSearchActionStatus.REJECTED,
            reasons=(LeadPausedSearchActionReasonCode.PERMISSION_DENIED,),
        )

    if terminal_behavior is not None and (
        active
        or terminal_behavior
        not in {
            PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED,
            PausedSearchTerminalBehavior.CLOSE_AUTOMATION,
        }
        or workflow_transition_repository is None
        or external_event_repository is None
    ):
        return LeadPausedSearchActionResult(
            status=LeadPausedSearchActionStatus.REJECTED,
            lead_id=lead_id,
            reasons=(LeadPausedSearchActionReasonCode.TERMINAL_BEHAVIOR_INVALID,),
        )

    selected_track: PausedSearchTrackCatalogEntry | None = None
    if active:
        normalized_track_key = _normalized_optional_text(selected_track_key)
        if normalized_track_key is None:
            return LeadPausedSearchActionResult(
                status=LeadPausedSearchActionStatus.REJECTED,
                lead_id=lead_id,
                reasons=(LeadPausedSearchActionReasonCode.TRACK_REQUIRED,),
            )
        catalog = await paused_search_track_repository.list_active_catalog(workspace_id)
        matches = tuple(entry for entry in catalog if entry.track_key == normalized_track_key)
        if not matches:
            return LeadPausedSearchActionResult(
                status=LeadPausedSearchActionStatus.REJECTED,
                lead_id=lead_id,
                reasons=(LeadPausedSearchActionReasonCode.TRACK_UNAVAILABLE,),
            )
        if len(matches) != 1:
            return LeadPausedSearchActionResult(
                status=LeadPausedSearchActionStatus.REJECTED,
                lead_id=lead_id,
                reasons=(LeadPausedSearchActionReasonCode.TRACK_AMBIGUOUS,),
            )
        selected_track = matches[0]

    effective_track_version_id: UUID | None = None
    if active:
        assert selected_track is not None
        effective_track_version_id = await resolve_effective_paused_search_track_version_id(
            workspace_id=workspace_id,
            lead_id=lead_id,
            catalog_track_version_id=selected_track.track_version_id,
            assignment_repository=paused_search_track_assignment_repository,
            track_repository=paused_search_track_repository,
            lead_workflow_repository=lead_workflow_repository,
            progress_handling=progress_handling,
        )
    previous_profile = lead_paused_search_profile(lead)
    current_profile = (
        LeadPausedSearchProfile(
            paused_search_active=True,
            paused_search_track_key=selected_track.track_key if selected_track else None,
            paused_search_track_version_id=effective_track_version_id,
            pause_reason_note=_normalized_optional_text(reason_note),
            reengagement_not_before=reengagement_not_before,
            reengagement_window_label=_normalized_optional_text(reengagement_window_label),
            paused_search_source=PausedSearchSource.OPERATOR,
            paused_search_recorded_at=now,
            paused_search_recorded_by_user_id=actor.user_id,
            paused_search_last_confirmed_at=now,
        )
        if active
        else None
    )

    if previous_profile == current_profile:
        await _synchronize_track_assignment(
            workspace_id=workspace_id,
            lead_id=lead_id,
            clear=current_profile is None,
            target_track_version_id=(
                current_profile.paused_search_track_version_id if current_profile else None
            ),
            actor_user_id=actor.user_id,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=paused_search_track_assignment_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            commit=commit,
            progress_handling=progress_handling,
            now=now,
        )
        unchanged_terminalized = False
        unchanged_workflow_state: WorkflowState | None = None
        if (
            current_profile is None
            and workflow_transition_repository is not None
            and external_event_repository is not None
        ):
            unchanged_terminalized, unchanged_workflow_state = await _terminalize_active_workflow(
                workspace_id=workspace_id,
                lead_id=lead_id,
                actor=actor,
                terminal_behavior=terminal_behavior,
                terminal_reason=terminal_reason,
                lead_workflow_repository=lead_workflow_repository,
                workflow_transition_repository=workflow_transition_repository,
                paused_search_occurrence_repository=paused_search_occurrence_repository,
                campaign_enrollment_repository=campaign_enrollment_repository,
                external_event_repository=external_event_repository,
                now=now,
            )
        return LeadPausedSearchActionResult(
            status=LeadPausedSearchActionStatus.UNCHANGED,
            lead_id=lead_id,
            profile=current_profile,
            workflow_terminalized=unchanged_terminalized,
            workflow_state=unchanged_workflow_state,
        )

    updated_lead = replace(
        lead,
        paused_search_active=current_profile.paused_search_active if current_profile else False,
        paused_search_track_key=(
            current_profile.paused_search_track_key if current_profile else None
        ),
        paused_search_track_version_id=(
            current_profile.paused_search_track_version_id if current_profile else None
        ),
        pause_reason_note=current_profile.pause_reason_note if current_profile else None,
        reengagement_not_before=(
            current_profile.reengagement_not_before if current_profile else None
        ),
        reengagement_window_label=(
            current_profile.reengagement_window_label if current_profile else None
        ),
        paused_search_source=current_profile.paused_search_source if current_profile else None,
        paused_search_recorded_at=(
            current_profile.paused_search_recorded_at if current_profile else None
        ),
        paused_search_recorded_by_user_id=(
            current_profile.paused_search_recorded_by_user_id if current_profile else None
        ),
        paused_search_last_confirmed_at=(
            current_profile.paused_search_last_confirmed_at if current_profile else None
        ),
    )
    saved_lead = await lead_repository.upsert(updated_lead)
    saved_profile = lead_paused_search_profile(saved_lead)
    await _synchronize_track_assignment(
        workspace_id=workspace_id,
        lead_id=lead_id,
        clear=saved_profile is None,
        target_track_version_id=(
            saved_profile.paused_search_track_version_id if saved_profile else None
        ),
        actor_user_id=actor.user_id,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        commit=commit,
        progress_handling=progress_handling,
        now=now,
    )
    workflow_terminalized = False
    terminal_workflow_state: WorkflowState | None = None
    if (
        saved_profile is None
        and workflow_transition_repository is not None
        and external_event_repository is not None
    ):
        workflow_terminalized, terminal_workflow_state = await _terminalize_active_workflow(
            workspace_id=workspace_id,
            lead_id=lead_id,
            actor=actor,
            terminal_behavior=terminal_behavior,
            terminal_reason=terminal_reason,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            external_event_repository=external_event_repository,
            now=now,
        )
    if temporal_signal_outbox_repository is not None and not workflow_terminalized:
        await enqueue_lead_nurture_reschedule_signal(
            workspace_id=workspace_id,
            lead_id=lead_id,
            reason=(
                "paused_search_profile_cleared"
                if saved_profile is None
                else "paused_search_profile_updated"
            ),
            occurred_at=now,
            lead_workflow_repository=lead_workflow_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            actor_user_id=actor.user_id,
        )
    history_entry = await paused_search_history_repository.append(
        LeadPausedSearchHistoryEntry(
            history_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            action=_action_for_change(previous_profile, current_profile),
            previous_profile=previous_profile,
            current_profile=saved_profile,
            actor_user_id=actor.user_id,
            created_at=now,
        )
    )
    return LeadPausedSearchActionResult(
        status=(
            LeadPausedSearchActionStatus.UPDATED
            if saved_profile is not None
            else LeadPausedSearchActionStatus.CLEARED
        ),
        lead_id=lead_id,
        profile=saved_profile,
        history_entry=history_entry,
        workflow_terminalized=workflow_terminalized,
        workflow_state=terminal_workflow_state,
    )


async def _terminalize_active_workflow(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    actor: AuthenticatedActor,
    terminal_behavior: PausedSearchTerminalBehavior | None,
    terminal_reason: str | None,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    external_event_repository: ExternalEventRepository,
    now: datetime,
) -> tuple[bool, WorkflowState | None]:
    """End the active workflow as part of an atomic profile clear.

    Skips silently when there is no workflow or it is already terminal, so a
    plain profile clear on an idle lead never fails. The transition reuses the
    standard terminalization pathway (occurrence cancellation + enrollment
    sync), keeping DB state consistent for immediate re-enrollment.

    Clearing never starts a replacement run: what happens next — dormant
    nurture or another paused-search track — is a separate, explicit admin
    enrollment decision. When the admin gave no explicit terminal behavior, a
    live track-pinned run still must end (completed, re-enrollable) because its
    track no longer exists; any other live workflow is left untouched.
    """
    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id, lead_id
    )
    if workflow is None or is_terminal_workflow_state(workflow.state):
        return False, workflow.state if workflow is not None else None
    effective_behavior = terminal_behavior
    if effective_behavior is None:
        if not workflow_needs_terminalization_on_clear(workflow):
            return False, workflow.state
        effective_behavior = PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
    target_state = (
        WorkflowState.COMPLETED
        if effective_behavior is PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED
        else WorkflowState.CLOSED
    )
    event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        event_type="lead.paused_search_cleared_and_terminalized",
        now=now,
        payload_redacted={"actor_user_id": str(actor.user_id)},
    )
    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=lead_id,
        to_state=target_state,
        reason_code=WorkflowTransitionReasonCode.PAUSED_SEARCH_TERMINALIZED,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        now=now,
        actor_user_id=actor.user_id,
        external_event_id=event.external_event_id,
        metadata={
            "reason": _normalized_optional_text(terminal_reason) or "profile_cleared",
            "terminal_behavior": effective_behavior.value,
            "source": "paused_search_profile_clear",
        },
    )
    if (
        transition.status is WorkflowStateTransitionStatus.UPDATED
        and transition.workflow is not None
    ):
        return True, transition.workflow.state
    return False, transition.workflow.state if transition.workflow is not None else None


def _can_edit_paused_search(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    any_permission = evaluate_permission(
        actor, PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_ANY_LEAD
    )
    if any_permission.allowed:
        return True
    own_permission = evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_OWN_LEAD,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )
    return own_permission.allowed


async def _synchronize_track_assignment(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    clear: bool,
    target_track_version_id: UUID | None,
    actor_user_id: UUID,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    paused_search_occurrence_repository: PausedSearchOccurrenceRepository | None,
    campaign_enrollment_repository: CampaignEnrollmentRepository | None,
    temporal_workflow_starter: TemporalWorkflowStarter | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    commit: Callable[[], Awaitable[None]] | None,
    progress_handling: PausedSearchProgressHandling | None = None,
    now: datetime,
) -> None:
    await synchronize_paused_search_track_assignment(
        workspace_id=workspace_id,
        lead_id=lead_id,
        clear=clear,
        actor_user_id=actor_user_id,
        source=PausedSearchTrackAssignmentSource.OPERATOR,
        assignment_repository=paused_search_track_assignment_repository,
        track_repository=paused_search_track_repository,
        lead_workflow_repository=lead_workflow_repository,
        now=now,
        target_track_version_id=target_track_version_id,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=paused_search_occurrence_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        commit=commit,
        progress_handling=progress_handling,
    )


def _action_for_change(
    previous_profile: LeadPausedSearchProfile | None,
    current_profile: LeadPausedSearchProfile | None,
) -> PausedSearchAction:
    if current_profile is None:
        return PausedSearchAction.CLEARED
    if previous_profile is None:
        return PausedSearchAction.SET
    return PausedSearchAction.UPDATED


def _normalized_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
