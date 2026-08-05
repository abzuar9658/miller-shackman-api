from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.application.ports.crm import CRMClient
from app.application.ports.event_bus import EventBus
from app.application.ports.lead_read import LeadReadLeadRepository
from app.application.ports.llm import LLMClient
from app.application.ports.notifications import NotificationProvider
from app.application.ports.repositories import (
    CampaignAdminRepository,
    CampaignEnrollmentRepository,
    CrmConversationEventRepository,
    HandoffCompletionRepository,
    HandoffRepository,
    LeadClassificationArtifactRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadRoutingReviewRepository,
    LeadWorkflowRepository,
    PausedSearchTrackAssignmentRepository,
    PausedSearchTrackRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceHandoffConfigRepository,
    WorkspaceLLMConfigRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.ports.temporal import TemporalWorkflowStarter
from app.application.services.lead_routing_review import (
    resolve_pending_routing_reviews_for_lead,
)
from app.application.services.paused_search_track_assignment import (
    synchronize_paused_search_track_assignment,
)
from app.application.use_cases.lead_manual_enrollment import (
    LeadManualEnrollmentActionStatus,
    LeadManualEnrollmentReasonCode,
    active_published_campaign_version,
    manual_enrollment_permission_allowed,
    manual_enrollment_source,
    start_lead_manual_enrollment,
)
from app.application.use_cases.lead_paused_search import (
    LeadPausedSearchActionStatus,
    update_lead_paused_search,
)
from app.application.use_cases.start_paused_search_campaign_enrollment import (
    PausedSearchCampaignEnrollmentStatus,
    start_paused_search_campaign_enrollment,
)
from app.domain.campaigns import PausedSearchTrackAssignmentSource
from app.domain.common.ids import CampaignId, CampaignVersionId, LeadId, WorkspaceId
from app.domain.identity import AuthenticatedActor
from app.domain.leads import (
    LeadClassificationArtifact,
    LeadPausedSearchHistoryEntry,
    LeadPausedSearchProfile,
    LeadRoutingReviewResolution,
    LeadStateClassificationOutcome,
)


class LeadReviewHoldResolution(StrEnum):
    DORMANT = "dormant"
    PAUSED_SEARCH = "paused_search"


class LeadReviewHoldResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    ALREADY_ENROLLED = "already_enrolled"
    REVIEW_REQUIRED = "review_required"
    INVALID = "invalid"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"


class LeadReviewHoldResolutionReasonCode(StrEnum):
    LEAD_NOT_FOUND = "lead_not_found"
    CAMPAIGN_NOT_FOUND = "campaign_not_found"
    PERMISSION_DENIED = "permission_denied"
    REVIEW_HOLD_REQUIRED = "review_hold_required"
    WORKFLOW_ALREADY_EXISTS = "workflow_already_exists"
    PAUSED_SEARCH_TRACK_REQUIRED = "paused_search_track_required"
    PAUSED_SEARCH_TRACK_UNAVAILABLE = "paused_search_track_unavailable"
    PAUSED_SEARCH_UPDATE_FAILED = "paused_search_update_failed"
    START_FAILED = "start_failed"


@dataclass(frozen=True)
class LeadReviewHoldResolutionResult:
    status: LeadReviewHoldResolutionStatus
    resolution: LeadReviewHoldResolution | None = None
    lead_id: LeadId | None = None
    campaign_id: CampaignId | None = None
    artifact: LeadClassificationArtifact | None = None
    paused_search: LeadPausedSearchProfile | None = None
    history_entry: LeadPausedSearchHistoryEntry | None = None
    campaign_enrollment_id: str | None = None
    workflow_id: str | None = None
    temporal_workflow_id: str | None = None
    reasons: tuple[LeadReviewHoldResolutionReasonCode, ...] = ()
    error: str | None = None


async def resolve_lead_review_hold(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    resolution: LeadReviewHoldResolution,
    lead_repository: LeadRepository,
    lead_read_repository: LeadReadLeadRepository,
    artifact_repository: LeadClassificationArtifactRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    crm_conversation_event_repository: CrmConversationEventRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    now: datetime,
    default_openrouter_model: str,
    commit: Callable[[], Awaitable[None]] | None = None,
    routing_review_repository: LeadRoutingReviewRepository | None = None,
    handoff_repository: HandoffRepository | None = None,
    handoff_completion_repository: HandoffCompletionRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    crm_client: CRMClient | None = None,
    notification_provider: NotificationProvider | None = None,
    user_repository: UserRepository | None = None,
    selected_track_key: str | None = None,
    pause_reason_note: str | None = None,
    reengagement_not_before: datetime | None = None,
    reengagement_window_label: str | None = None,
) -> LeadReviewHoldResolutionResult:
    lead = await lead_read_repository.get_by_id(workspace_id, lead_id)
    if lead is None:
        return _result(
            LeadReviewHoldResolutionStatus.NOT_FOUND,
            resolution=resolution,
            lead_id=lead_id,
            campaign_id=campaign_id,
            reasons=(LeadReviewHoldResolutionReasonCode.LEAD_NOT_FOUND,),
        )

    workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        lead_id,
    )
    if workflow is not None:
        return _result(
            LeadReviewHoldResolutionStatus.INVALID,
            resolution=resolution,
            lead_id=lead_id,
            campaign_id=campaign_id,
            reasons=(LeadReviewHoldResolutionReasonCode.WORKFLOW_ALREADY_EXISTS,),
        )

    artifact = await _latest_review_hold_artifact(artifact_repository, workspace_id, lead_id)
    if artifact is None:
        return _result(
            LeadReviewHoldResolutionStatus.INVALID,
            resolution=resolution,
            lead_id=lead_id,
            campaign_id=campaign_id,
            reasons=(LeadReviewHoldResolutionReasonCode.REVIEW_HOLD_REQUIRED,),
        )

    campaign = await campaign_admin_repository.get_campaign(workspace_id, campaign_id)
    version = await active_published_campaign_version(
        campaign_admin_repository,
        workspace_id,
        campaign,
    )
    if campaign is None or version is None:
        return _result(
            LeadReviewHoldResolutionStatus.NOT_FOUND,
            resolution=resolution,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.CAMPAIGN_NOT_FOUND,),
        )

    if not manual_enrollment_permission_allowed(
        actor,
        lead,
        campaign_allows_assigned_agent_enrollment=version.allow_assigned_agent_manual_enrollment,
    ):
        return _result(
            LeadReviewHoldResolutionStatus.REJECTED,
            resolution=resolution,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PERMISSION_DENIED,),
        )

    if resolution == LeadReviewHoldResolution.DORMANT:
        return await _resolve_to_dormant(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            lead_repository=lead_repository,
            lead_read_repository=lead_read_repository,
            lead_classification_artifact_repository=artifact_repository,
            paused_search_history_repository=paused_search_history_repository,
            workspace_llm_config_repository=workspace_llm_config_repository,
            llm_client=llm_client,
            crm_conversation_event_repository=crm_conversation_event_repository,
            campaign_admin_repository=campaign_admin_repository,
            campaign_enrollment_repository=campaign_enrollment_repository,
            lead_workflow_repository=lead_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=paused_search_track_assignment_repository,
            temporal_workflow_starter=temporal_workflow_starter,
            event_bus=event_bus,
            workspace_operational_control_repository=workspace_operational_control_repository,
            now=now,
            default_openrouter_model=default_openrouter_model,
            commit=commit,
            routing_review_repository=routing_review_repository,
            handoff_repository=handoff_repository,
            handoff_completion_repository=handoff_completion_repository,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
            crm_client=crm_client,
            notification_provider=notification_provider,
            user_repository=user_repository,
        )

    return await _resolve_to_paused_search(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        artifact=artifact,
        lead_repository=lead_repository,
        lead_read_repository=lead_read_repository,
        paused_search_history_repository=paused_search_history_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        now=now,
        commit=commit,
        routing_review_repository=routing_review_repository,
        selected_track_key=selected_track_key,
        pause_reason_note=pause_reason_note,
        reengagement_not_before=reengagement_not_before,
        reengagement_window_label=reengagement_window_label,
        campaign_version_id=version.campaign_version_id,
    )


async def _resolve_to_dormant(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    artifact: LeadClassificationArtifact,
    lead_repository: LeadRepository,
    lead_read_repository: LeadReadLeadRepository,
    lead_classification_artifact_repository: LeadClassificationArtifactRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    workspace_llm_config_repository: WorkspaceLLMConfigRepository,
    llm_client: LLMClient,
    crm_conversation_event_repository: CrmConversationEventRepository,
    campaign_admin_repository: CampaignAdminRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    temporal_workflow_starter: TemporalWorkflowStarter,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    now: datetime,
    default_openrouter_model: str,
    commit: Callable[[], Awaitable[None]] | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    handoff_repository: HandoffRepository | None,
    handoff_completion_repository: HandoffCompletionRepository | None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
    crm_client: CRMClient | None,
    notification_provider: NotificationProvider | None,
    user_repository: UserRepository | None,
) -> LeadReviewHoldResolutionResult:
    start_result = await start_lead_manual_enrollment(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        lead_repository=lead_repository,
        campaign_admin_repository=campaign_admin_repository,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        lead_classification_artifact_repository=lead_classification_artifact_repository,
        paused_search_history_repository=paused_search_history_repository,
        workspace_llm_config_repository=workspace_llm_config_repository,
        llm_client=llm_client,
        crm_conversation_event_repository=crm_conversation_event_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        routing_review_repository=routing_review_repository,
        event_bus=event_bus,
        now=now,
        default_openrouter_model=default_openrouter_model,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        handoff_repository=handoff_repository,
        handoff_completion_repository=handoff_completion_repository,
        workspace_handoff_config_repository=workspace_handoff_config_repository,
        crm_client=crm_client,
        notification_provider=notification_provider,
        user_repository=user_repository,
    )
    if start_result.status == LeadManualEnrollmentActionStatus.REJECTED:
        return _result(
            LeadReviewHoldResolutionStatus.REJECTED,
            resolution=LeadReviewHoldResolution.DORMANT,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PERMISSION_DENIED,),
        )
    if start_result.status == LeadManualEnrollmentActionStatus.NOT_FOUND:
        reason = (
            LeadReviewHoldResolutionReasonCode.CAMPAIGN_NOT_FOUND
            if LeadManualEnrollmentReasonCode.CAMPAIGN_NOT_FOUND.value in start_result.reasons
            else LeadReviewHoldResolutionReasonCode.LEAD_NOT_FOUND
        )
        return _result(
            LeadReviewHoldResolutionStatus.NOT_FOUND,
            resolution=LeadReviewHoldResolution.DORMANT,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(reason,),
        )
    if start_result.status == LeadManualEnrollmentActionStatus.ALREADY_ENROLLED:
        await _resolve_routing_reviews_if_needed(
            workspace_id=workspace_id,
            lead_id=lead_id,
            resolution=LeadRoutingReviewResolution.DORMANT,
            actor=actor,
            routing_review_repository=routing_review_repository,
            now=now,
        )
        return _result(
            LeadReviewHoldResolutionStatus.ALREADY_ENROLLED,
            resolution=LeadReviewHoldResolution.DORMANT,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            campaign_enrollment_id=(
                str(start_result.campaign_enrollment_id)
                if start_result.campaign_enrollment_id is not None
                else None
            ),
        )
    if start_result.status != LeadManualEnrollmentActionStatus.STARTED:
        return _result(
            LeadReviewHoldResolutionStatus.FAILED,
            resolution=LeadReviewHoldResolution.DORMANT,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.START_FAILED,),
            error=start_result.error,
        )

    await _resolve_routing_reviews_if_needed(
        workspace_id=workspace_id,
        lead_id=lead_id,
        resolution=LeadRoutingReviewResolution.DORMANT,
        actor=actor,
        routing_review_repository=routing_review_repository,
        now=now,
    )
    return _result(
        LeadReviewHoldResolutionStatus.RESOLVED,
        resolution=LeadReviewHoldResolution.DORMANT,
        lead_id=lead_id,
        campaign_id=campaign_id,
        artifact=artifact,
        campaign_enrollment_id=(
            str(start_result.campaign_enrollment_id)
            if start_result.campaign_enrollment_id is not None
            else None
        ),
        workflow_id=str(start_result.workflow_id) if start_result.workflow_id is not None else None,
        temporal_workflow_id=start_result.temporal_workflow_id,
    )


async def _resolve_to_paused_search(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    campaign_id: CampaignId,
    artifact: LeadClassificationArtifact,
    lead_repository: LeadRepository,
    lead_read_repository: LeadReadLeadRepository,
    paused_search_history_repository: LeadPausedSearchHistoryRepository,
    campaign_enrollment_repository: CampaignEnrollmentRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    paused_search_track_repository: PausedSearchTrackRepository,
    paused_search_track_assignment_repository: PausedSearchTrackAssignmentRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    temporal_workflow_starter: TemporalWorkflowStarter,
    event_bus: EventBus | None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None,
    now: datetime,
    commit: Callable[[], Awaitable[None]] | None,
    routing_review_repository: LeadRoutingReviewRepository | None,
    selected_track_key: str | None,
    pause_reason_note: str | None,
    reengagement_not_before: datetime | None,
    reengagement_window_label: str | None,
    campaign_version_id: CampaignVersionId,
) -> LeadReviewHoldResolutionResult:
    if selected_track_key is None:
        return _result(
            LeadReviewHoldResolutionStatus.INVALID,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PAUSED_SEARCH_TRACK_REQUIRED,),
        )

    catalog = await paused_search_track_repository.list_active_catalog(workspace_id)
    selected_tracks = tuple(
        entry for entry in catalog if entry.track_key == selected_track_key
    )
    if len(selected_tracks) != 1:
        return _result(
            LeadReviewHoldResolutionStatus.REVIEW_REQUIRED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PAUSED_SEARCH_TRACK_UNAVAILABLE,),
        )
    selected_track = selected_tracks[0]
    if paused_search_track_assignment_repository is None:
        return _result(
            LeadReviewHoldResolutionStatus.REVIEW_REQUIRED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PAUSED_SEARCH_TRACK_UNAVAILABLE,),
        )

    await synchronize_paused_search_track_assignment(
        workspace_id=workspace_id,
        lead_id=lead_id,
        clear=False,
        actor_user_id=actor.user_id,
        source=PausedSearchTrackAssignmentSource.OPERATOR,
        assignment_repository=paused_search_track_assignment_repository,
        track_repository=paused_search_track_repository,
        lead_workflow_repository=lead_workflow_repository,
        now=now,
        target_track_version_id=selected_track.track_version_id,
    )

    paused_result = await update_lead_paused_search(
        actor=actor,
        workspace_id=workspace_id,
        lead_id=lead_id,
        active=True,
        selected_track_key=selected_track_key,
        reason_note=pause_reason_note,
        reengagement_not_before=reengagement_not_before,
        reengagement_window_label=reengagement_window_label,
        lead_repository=lead_repository,
        paused_search_history_repository=paused_search_history_repository,
        lead_workflow_repository=lead_workflow_repository,
        paused_search_track_repository=paused_search_track_repository,
        paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )
    if paused_result.status == LeadPausedSearchActionStatus.REJECTED:
        return _result(
            LeadReviewHoldResolutionStatus.REJECTED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PERMISSION_DENIED,),
        )
    if paused_result.status == LeadPausedSearchActionStatus.NOT_FOUND:
        return _result(
            LeadReviewHoldResolutionStatus.NOT_FOUND,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.LEAD_NOT_FOUND,),
        )

    updated_lead = await lead_read_repository.get_by_id(workspace_id, lead_id)
    if updated_lead is None or paused_result.profile is None:
        return _result(
            LeadReviewHoldResolutionStatus.FAILED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            reasons=(LeadReviewHoldResolutionReasonCode.PAUSED_SEARCH_UPDATE_FAILED,),
        )

    start_result = await start_paused_search_campaign_enrollment(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        campaign_version_id=campaign_version_id,
        lead_id=lead_id,
        lead=updated_lead,
        source=manual_enrollment_source(actor),
        reason_codes=("review_hold_resolved",),
        actor_user_id=actor.user_id,
        campaign_enrollment_repository=campaign_enrollment_repository,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        temporal_workflow_starter=temporal_workflow_starter,
        paused_search_track_repository=paused_search_track_repository,
            paused_search_track_assignment_repository=paused_search_track_assignment_repository,
        event_bus=event_bus,
        workspace_operational_control_repository=workspace_operational_control_repository,
        commit=commit,
        now=now,
    )
    if start_result.status == PausedSearchCampaignEnrollmentStatus.REVIEW_HOLD:
        return _result(
            LeadReviewHoldResolutionStatus.REVIEW_REQUIRED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            paused_search=paused_result.profile,
            history_entry=paused_result.history_entry,
            reasons=(LeadReviewHoldResolutionReasonCode.PAUSED_SEARCH_TRACK_UNAVAILABLE,),
        )
    if start_result.status == PausedSearchCampaignEnrollmentStatus.FAILED:
        return _result(
            LeadReviewHoldResolutionStatus.FAILED,
            resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
            lead_id=lead_id,
            campaign_id=campaign_id,
            artifact=artifact,
            paused_search=paused_result.profile,
            history_entry=paused_result.history_entry,
            reasons=(LeadReviewHoldResolutionReasonCode.START_FAILED,),
            error=start_result.error,
        )

    lead_result = start_result.lead_result
    await _resolve_routing_reviews_if_needed(
        workspace_id=workspace_id,
        lead_id=lead_id,
        resolution=LeadRoutingReviewResolution.PAUSED_SEARCH,
        actor=actor,
        routing_review_repository=routing_review_repository,
        now=now,
    )
    return _result(
        LeadReviewHoldResolutionStatus.RESOLVED
        if start_result.status == PausedSearchCampaignEnrollmentStatus.STARTED
        else LeadReviewHoldResolutionStatus.ALREADY_ENROLLED,
        resolution=LeadReviewHoldResolution.PAUSED_SEARCH,
        lead_id=lead_id,
        campaign_id=campaign_id,
        artifact=artifact,
        paused_search=paused_result.profile,
        history_entry=paused_result.history_entry,
        campaign_enrollment_id=(
            str(lead_result.campaign_enrollment_id)
            if lead_result is not None and lead_result.campaign_enrollment_id is not None
            else None
        ),
        workflow_id=(
            str(lead_result.workflow_id)
            if lead_result is not None and lead_result.workflow_id is not None
            else None
        ),
        temporal_workflow_id=(
            lead_result.temporal_workflow_id if lead_result is not None else None
        ),
    )


async def _latest_review_hold_artifact(
    artifact_repository: LeadClassificationArtifactRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
) -> LeadClassificationArtifact | None:
    artifacts = await artifact_repository.list_for_lead(workspace_id, lead_id)
    latest = artifacts[0] if artifacts else None
    if latest is None or latest.outcome != LeadStateClassificationOutcome.REVIEW_HOLD:
        return None
    return latest


async def _resolve_routing_reviews_if_needed(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    resolution: LeadRoutingReviewResolution,
    actor: AuthenticatedActor,
    routing_review_repository: LeadRoutingReviewRepository | None,
    now: datetime,
) -> None:
    if routing_review_repository is None:
        return
    await resolve_pending_routing_reviews_for_lead(
        workspace_id=workspace_id,
        lead_id=lead_id,
        resolution=resolution,
        reviewed_by_user_id=actor.user_id,
        routing_review_repository=routing_review_repository,
        now=now,
    )


def _result(
    status: LeadReviewHoldResolutionStatus,
    *,
    resolution: LeadReviewHoldResolution | None = None,
    lead_id: LeadId | None = None,
    campaign_id: CampaignId | None = None,
    artifact: LeadClassificationArtifact | None = None,
    paused_search: LeadPausedSearchProfile | None = None,
    history_entry: LeadPausedSearchHistoryEntry | None = None,
    campaign_enrollment_id: str | None = None,
    workflow_id: str | None = None,
    temporal_workflow_id: str | None = None,
    reasons: tuple[LeadReviewHoldResolutionReasonCode, ...] = (),
    error: str | None = None,
) -> LeadReviewHoldResolutionResult:
    return LeadReviewHoldResolutionResult(
        status=status,
        resolution=resolution,
        lead_id=lead_id,
        campaign_id=campaign_id,
        artifact=artifact,
        paused_search=paused_search,
        history_entry=history_entry,
        campaign_enrollment_id=campaign_enrollment_id,
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
        reasons=reasons,
        error=error,
    )
