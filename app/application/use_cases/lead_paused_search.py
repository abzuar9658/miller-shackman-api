from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from app.application.ports.repositories import (
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
)
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.application.services.paused_search_track_pinning import (
    pin_published_paused_search_track_on_latest_workflow,
)
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
    PausedSearchReasonCode,
    PausedSearchSource,
    lead_paused_search_profile,
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


@dataclass(frozen=True)
class LeadPausedSearchActionResult:
    status: LeadPausedSearchActionStatus
    lead_id: LeadId | None = None
    profile: LeadPausedSearchProfile | None = None
    history_entry: LeadPausedSearchHistoryEntry | None = None
    reasons: tuple[LeadPausedSearchActionReasonCode, ...] = ()


async def update_lead_paused_search(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    active: bool,
    reason_code: PausedSearchReasonCode | None,
    reason_note: str | None,
    reengagement_not_before: datetime | None,
    reengagement_window_label: str | None,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
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

    previous_profile = lead_paused_search_profile(lead)
    current_profile = (
        LeadPausedSearchProfile(
            paused_search_active=True,
            pause_reason_code=reason_code,
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
        return LeadPausedSearchActionResult(
            status=LeadPausedSearchActionStatus.UNCHANGED,
            lead_id=lead_id,
            profile=current_profile,
        )

    updated_lead = replace(
        lead,
        paused_search_active=current_profile.paused_search_active if current_profile else False,
        pause_reason_code=current_profile.pause_reason_code if current_profile else None,
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
    await pin_published_paused_search_track_on_latest_workflow(
        workspace_id=workspace_id,
        lead_id=lead_id,
        pause_reason_code=(saved_profile.pause_reason_code if saved_profile is not None else None),
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        now=now,
    )
    if temporal_signal_outbox_repository is not None:
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
    )


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