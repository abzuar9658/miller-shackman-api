from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.llm import LLMClient
from app.application.ports.repositories import (
    CrmConversationEventRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    WorkspaceLLMConfigRepository,
)
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.services.lead_nurture_rescheduling import (
    enqueue_lead_nurture_reschedule_signal,
)
from app.application.services.llm.lead_state_classification import (
    LeadStateClassificationResult,
    LeadStateClassificationStatus,
    classify_lead_from_conversation,
)
from app.application.services.llm.workspace_model_resolution import (
    resolve_workspace_openrouter_model,
)
from app.application.services.paused_search_track_assignment import (
    synchronize_paused_search_track_assignment,
)
from app.application.services.paused_search_track_pinning import (
    pin_published_paused_search_track_on_latest_workflow,
)
from app.domain.campaigns import PausedSearchTrackAssignmentSource
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import CrmConversationEvent
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    evaluate_permission,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    LeadClassificationAppliedStatus,
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    LeadStateClassificationOutcome,
    PausedSearchAction,
    PausedSearchReasonCode,
    PausedSearchSource,
    lead_paused_search_profile,
)


class ApplyLeadStateClassificationStatus(StrEnum):
    APPLIED = "applied"
    REVIEW = "review"
    BLOCKED = "blocked"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ApplyLeadStateClassificationResult:
    status: ApplyLeadStateClassificationStatus
    lead_id: LeadId | None = None
    classification_result: LeadStateClassificationResult | None = None
    artifact: LeadClassificationArtifact | None = None
    profile: LeadPausedSearchProfile | None = None
    history_entry: LeadPausedSearchHistoryEntry | None = None
    reasons: tuple[str, ...] = ()


async def apply_lead_state_classification(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    actor: AuthenticatedActor | None,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    artifact_repository: LeadClassificationArtifactRepository,
    crm_conversation_event_repository: CrmConversationEventRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    now: datetime,
    default_openrouter_model: str = "openai/gpt-4o-mini",
    dormant_threshold_days: int | None = None,
    allow_overwrite_human_state: bool = False,
    conversation_summary: str | None = None,
    supplemental_crm_conversation_events: tuple[CrmConversationEvent, ...] = (),
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None = None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    precomputed_classification_result: LeadStateClassificationResult | None = None,
    artifact_source: str = "ai_conversation_classification",
    paused_search_source: PausedSearchSource = PausedSearchSource.AI_CONVERSATION_CLASSIFICATION,
    crm_conversation_events: tuple[CrmConversationEvent, ...] | None = None,
) -> ApplyLeadStateClassificationResult:
    lead = await lead_repository.get_by_id_for_update(workspace_id, lead_id)
    if lead is None:
        return ApplyLeadStateClassificationResult(
            status=ApplyLeadStateClassificationStatus.NOT_FOUND,
            lead_id=lead_id,
            reasons=("lead_not_found",),
        )

    if actor is not None and not _permission_allowed(actor, lead):
        return ApplyLeadStateClassificationResult(
            status=ApplyLeadStateClassificationStatus.REJECTED,
            lead_id=lead_id,
            reasons=("permission_denied",),
        )

    actor_user_id = actor.user_id if actor is not None else None

    if precomputed_classification_result is not None:
        classification_result = precomputed_classification_result
    else:
        openrouter_model = await resolve_workspace_openrouter_model(
            workspace_id=workspace_id,
            workspace_llm_config_repository=workspace_llm_config_repository,
            default_openrouter_model=default_openrouter_model,
        )

        if crm_conversation_events is not None:
            crm_events = crm_conversation_events
        else:
            crm_events = await crm_conversation_event_repository.list_for_lead(
                workspace_id, lead_id, limit=20
            )
        merged_crm_events = _merge_crm_conversation_events(
            crm_events=crm_events,
            supplemental_events=supplemental_crm_conversation_events,
        )

        classification_result = await classify_lead_from_conversation(
            lead=lead,
            now=now,
            crm_conversation_events=merged_crm_events,
            conversation_summary=conversation_summary,
            llm_client=llm_client,
            dormant_threshold_days=dormant_threshold_days,
            model=openrouter_model,
        )
    if classification_result.status != LeadStateClassificationStatus.CLASSIFIED:
        saved_artifact = await _save_artifact(
            artifact_repository=artifact_repository,
            workspace_id=workspace_id,
            lead_id=lead_id,
            classification_result=classification_result,
            artifact_source=artifact_source,
            applied_status=LeadClassificationAppliedStatus.REVIEW,
            applied_at=None,
            now=now,
        )
        return ApplyLeadStateClassificationResult(
            status=ApplyLeadStateClassificationStatus.REVIEW,
            lead_id=lead_id,
            classification_result=classification_result,
            artifact=saved_artifact,
            reasons=tuple(reason.value for reason in classification_result.reasons),
        )

    if classification_result.outcome == LeadStateClassificationOutcome.PAUSED_SEARCH:
        return await _apply_paused_search(
            workspace_id=workspace_id,
            lead=lead,
            classification_result=classification_result,
            artifact_repository=artifact_repository,
            artifact_source=artifact_source,
            actor_user_id=actor_user_id,
            lead_repository=lead_repository,
            paused_search_history_repository=paused_search_history_repository,
            now=now,
            allow_overwrite_human_state=allow_overwrite_human_state,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=paused_search_track_assignment_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            paused_search_source=paused_search_source,
        )

    saved_artifact = await _save_artifact(
        artifact_repository=artifact_repository,
        workspace_id=workspace_id,
        lead_id=lead_id,
        classification_result=classification_result,
        artifact_source=artifact_source,
        applied_status=_non_applied_artifact_status(classification_result),
        applied_at=None,
        now=now,
    )
    return ApplyLeadStateClassificationResult(
        status=ApplyLeadStateClassificationStatus.REVIEW,
        lead_id=lead_id,
        classification_result=classification_result,
        artifact=saved_artifact,
        reasons=("outcome_not_applied_in_this_slice",),
    )


async def _apply_paused_search(
    *,
    workspace_id: WorkspaceId,
    lead: CanonicalLeadRecord,
    classification_result: LeadStateClassificationResult,
    artifact_repository: LeadClassificationArtifactRepository,
    artifact_source: str,
    actor_user_id: UUID | None,
    lead_repository: LeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    now: datetime,
    allow_overwrite_human_state: bool,
    lead_workflow_repository: LeadWorkflowRepository | None,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    paused_search_source: PausedSearchSource,
) -> ApplyLeadStateClassificationResult:
    previous_profile = lead_paused_search_profile(lead)
    if previous_profile is not None and not _may_overwrite_profile(
        previous_profile, allow_overwrite_human_state
    ):
        saved_artifact = await _save_artifact(
            artifact_repository=artifact_repository,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            classification_result=classification_result,
            artifact_source=artifact_source,
            applied_status=LeadClassificationAppliedStatus.REVIEW,
            applied_at=None,
            now=now,
        )
        return ApplyLeadStateClassificationResult(
            status=ApplyLeadStateClassificationStatus.REVIEW,
            lead_id=lead.lead_id,
            classification_result=classification_result,
            artifact=saved_artifact,
            reasons=("human_profile_blocks_ai_overwrite",),
        )

    current_profile = LeadPausedSearchProfile(
        paused_search_active=True,
        pause_reason_code=classification_result.pause_reason_code,
        pause_reason_note=None,
        reengagement_not_before=classification_result.reengagement_not_before,
        reengagement_window_label=classification_result.reengagement_window_label,
        paused_search_source=paused_search_source,
        paused_search_recorded_at=now,
        paused_search_recorded_by_user_id=None,
        paused_search_last_confirmed_at=now,
    )
    if previous_profile == current_profile:
        if lead_workflow_repository is not None and paused_search_track_repository is not None:
            await _synchronize_track_assignment(
                workspace_id=lead.workspace_id,
                lead_id=lead.lead_id,
                reason_code=current_profile.pause_reason_code,
                actor_user_id=actor_user_id,
                lead_workflow_repository=lead_workflow_repository,
                paused_search_track_repository=paused_search_track_repository,
                paused_search_track_assignment_repository=(
                    paused_search_track_assignment_repository
                ),
                now=now,
            )
        saved_artifact = await _save_artifact(
            artifact_repository=artifact_repository,
            workspace_id=workspace_id,
            lead_id=lead.lead_id,
            classification_result=classification_result,
            artifact_source=artifact_source,
            applied_status=LeadClassificationAppliedStatus.REVIEW,
            applied_at=None,
            now=now,
        )
        return ApplyLeadStateClassificationResult(
            status=ApplyLeadStateClassificationStatus.UNCHANGED,
            lead_id=lead.lead_id,
            classification_result=classification_result,
            artifact=saved_artifact,
            profile=previous_profile,
        )

    updated_lead = _lead_with_paused_search_profile(lead, current_profile)
    saved_lead = await lead_repository.upsert(updated_lead)
    saved_profile = lead_paused_search_profile(saved_lead)
    if lead_workflow_repository is not None and paused_search_track_repository is not None:
        await _synchronize_track_assignment(
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            reason_code=(
                saved_profile.pause_reason_code if saved_profile is not None else None
            ),
            actor_user_id=actor_user_id,
            lead_workflow_repository=lead_workflow_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=paused_search_track_assignment_repository,
            now=now,
        )
        if temporal_signal_outbox_repository is not None:
            await enqueue_lead_nurture_reschedule_signal(
                workspace_id=lead.workspace_id,
                lead_id=lead.lead_id,
                reason="paused_search_classification_applied",
                occurred_at=now,
                lead_workflow_repository=lead_workflow_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                actor_user_id=actor_user_id,
            )
    history_entry = await paused_search_history_repository.append(
        LeadPausedSearchHistoryEntry(
            history_id=uuid4(),
            workspace_id=lead.workspace_id,
            lead_id=lead.lead_id,
            action=_action_for_change(previous_profile, current_profile),
            previous_profile=previous_profile,
            current_profile=saved_profile,
            actor_user_id=actor_user_id,
            created_at=now,
        )
    )
    saved_artifact = await _save_artifact(
        artifact_repository=artifact_repository,
        workspace_id=workspace_id,
        lead_id=lead.lead_id,
        classification_result=classification_result,
        artifact_source=artifact_source,
        applied_status=LeadClassificationAppliedStatus.APPLIED,
        applied_at=now,
        now=now,
    )
    return ApplyLeadStateClassificationResult(
        status=ApplyLeadStateClassificationStatus.APPLIED,
        lead_id=lead.lead_id,
        classification_result=classification_result,
        artifact=saved_artifact,
        profile=saved_profile,
        history_entry=history_entry,
    )


async def _synchronize_track_assignment(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    reason_code: PausedSearchReasonCode | None,
    actor_user_id: UUID | None,
    lead_workflow_repository: LeadWorkflowRepository,
    paused_search_track_repository: PausedSearchTrackMappingRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    now: datetime,
) -> None:
    if paused_search_track_assignment_repository is not None:
        await synchronize_paused_search_track_assignment(
            workspace_id=workspace_id,
            lead_id=lead_id,
            reason_code=reason_code,
            clear=False,
            actor_user_id=actor_user_id,
            source=PausedSearchTrackAssignmentSource.REASON_MAPPING,
            assignment_repository=paused_search_track_assignment_repository,
            track_mapping_repository=paused_search_track_repository,
            lead_workflow_repository=lead_workflow_repository,
            now=now,
        )
        return
    await pin_published_paused_search_track_on_latest_workflow(
        workspace_id=workspace_id,
        lead_id=lead_id,
        pause_reason_code=reason_code,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        now=now,
    )


def _may_overwrite_profile(
    profile: LeadPausedSearchProfile, allow_overwrite_human_state: bool
) -> bool:
    if profile.paused_search_source in {
        PausedSearchSource.OPERATOR,
        PausedSearchSource.REVIEW_PROPOSAL,
    }:
        return allow_overwrite_human_state
    return True


def _action_for_change(
    previous_profile: LeadPausedSearchProfile | None,
    current_profile: LeadPausedSearchProfile,
) -> PausedSearchAction:
    if previous_profile is None:
        return PausedSearchAction.SET
    return PausedSearchAction.UPDATED


def _lead_with_paused_search_profile(
    lead: CanonicalLeadRecord,
    profile: LeadPausedSearchProfile,
) -> CanonicalLeadRecord:
    return replace(
        lead,
        paused_search_active=profile.paused_search_active,
        pause_reason_code=profile.pause_reason_code,
        pause_reason_note=profile.pause_reason_note,
        reengagement_not_before=profile.reengagement_not_before,
        reengagement_window_label=profile.reengagement_window_label,
        paused_search_source=profile.paused_search_source,
        paused_search_recorded_at=profile.paused_search_recorded_at,
        paused_search_recorded_by_user_id=profile.paused_search_recorded_by_user_id,
        paused_search_last_confirmed_at=profile.paused_search_last_confirmed_at,
    )


def _non_applied_artifact_status(
    classification_result: LeadStateClassificationResult,
) -> LeadClassificationAppliedStatus:
    if classification_result.status != LeadStateClassificationStatus.CLASSIFIED:
        return LeadClassificationAppliedStatus.REVIEW
    if classification_result.outcome == LeadStateClassificationOutcome.BLOCKED:
        return LeadClassificationAppliedStatus.BLOCKED
    return LeadClassificationAppliedStatus.REVIEW


async def _save_artifact(
    *,
    artifact_repository: LeadClassificationArtifactRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    classification_result: LeadStateClassificationResult,
    artifact_source: str,
    applied_status: LeadClassificationAppliedStatus,
    applied_at: datetime | None,
    now: datetime,
) -> LeadClassificationArtifact:
    return await artifact_repository.save(
        LeadClassificationArtifact(
            artifact_id=uuid4(),
            workspace_id=workspace_id,
            lead_id=lead_id,
            source=artifact_source,
            outcome=(classification_result.outcome or LeadStateClassificationOutcome.REVIEW_HOLD),
            pause_reason_code=classification_result.pause_reason_code,
            reengagement_not_before=classification_result.reengagement_not_before,
            reengagement_window_label=classification_result.reengagement_window_label,
            confidence=classification_result.confidence or 0.0,
            evidence=classification_result.evidence,
            summary=classification_result.summary,
            model=classification_result.model or "unknown",
            prompt_version=classification_result.prompt_version,
            latency_ms=classification_result.latency_ms or 0,
            usage_tokens=classification_result.usage_tokens,
            applied_status=applied_status,
            applied_at=applied_at,
            created_at=now,
            prompt_text=classification_result.prompt_text,
            input_context=classification_result.input_context,
            raw_llm_response_text=classification_result.raw_llm_response_text,
            parsed_llm_response=classification_result.parsed_llm_response,
        )
    )


def _merge_crm_conversation_events(
    *,
    crm_events: tuple[CrmConversationEvent, ...],
    supplemental_events: tuple[CrmConversationEvent, ...],
) -> tuple[CrmConversationEvent, ...]:
    if not supplemental_events:
        return crm_events
    by_activity_id: dict[str, CrmConversationEvent] = {}
    for event in (*supplemental_events, *crm_events):
        by_activity_id.setdefault(event.crm_activity_id, event)
    merged = sorted(
        by_activity_id.values(),
        key=lambda event: (event.occurred_at, event.created_at),
        reverse=True,
    )
    return tuple(merged[:20])


def _permission_allowed(actor: AuthenticatedActor, lead: CanonicalLeadRecord) -> bool:
    context = PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead))
    any_lead_permission = evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_ANY_LEAD,
        context,
    )
    if any_lead_permission.allowed:
        return True
    return evaluate_permission(
        actor,
        PermissionCapability.EDIT_PAUSED_SEARCH_PROFILE_OWN_LEAD,
        context,
    ).allowed
