from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from secrets import token_hex
from uuid import UUID, uuid4

from app.application.ports.lead_read import LeadReadLeadRepository, LeadReadWorkflowRepository
from app.application.ports.repositories import (
    ExternalEventRepository,
    LeadPausedSearchHistoryRepository,
    LeadRepository,
    LeadWorkflowOverrideAuditLogRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    PausedSearchOccurrenceOperationsRepository,
    PausedSearchReviewRepository,
    PausedSearchTrackMappingRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceContactPolicyRepository,
    WorkspaceRepository,
)
from app.application.services.internal_external_events import create_internal_external_event
from app.application.services.lead_assignment import is_actor_assigned_to_lead
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.application.use_cases.lead_resume import (
    LeadResumeActionStatus,
    resume_lead_workflow,
)
from app.application.use_cases.lead_workflow_overrides import (
    PausedSearchWorkflowOverrideStatus,
    migrate_paused_search_track_version,
    skip_paused_search_next_touch,
)
from app.application.use_cases.plan_outbound_message import outbound_message_idempotency_key
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.paused_search_reviews import (
    PausedSearchReview,
    PausedSearchReviewAction,
    PausedSearchReviewKind,
    PausedSearchReviewStatus,
    apply_review_action,
)
from app.domain.campaigns.paused_search_tracks import PausedSearchTerminalBehavior
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    PermissionCapability,
    PermissionContext,
    PermissionReasonCode,
    evaluate_permission,
)
from app.domain.leads import CanonicalLeadRecord
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


class PausedSearchOperationsStatus(StrEnum):
    OK = "ok"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    ALREADY_RESOLVED = "already_resolved"


class PausedSearchOperationsReason(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    OCCURRENCE_NOT_FOUND = "occurrence_not_found"
    REVIEW_NOT_FOUND = "review_not_found"
    INVALID_ACTION = "invalid_action"
    POLICY_ACTION_NOT_ALLOWED = "policy_action_not_allowed"
    INVALID_TRANSITION = "invalid_transition"
    REASON_REQUIRED = "reason_required"
    MESSAGE_NOT_FOUND = "message_not_found"
    MESSAGE_CONTENT_REQUIRED = "message_content_required"


@dataclass(frozen=True)
class PausedSearchOccurrenceView:
    occurrence: RecurringOccurrence
    lead: CanonicalLeadRecord


@dataclass(frozen=True)
class PausedSearchReviewView:
    review: PausedSearchReview
    lead: CanonicalLeadRecord
    message: OutboundMessage | None = None


@dataclass(frozen=True)
class PausedSearchOperationsReadResult:
    status: PausedSearchOperationsStatus
    occurrences: tuple[PausedSearchOccurrenceView, ...] = ()
    reviews: tuple[PausedSearchReviewView, ...] = ()
    occurrence: PausedSearchOccurrenceView | None = None
    review: PausedSearchReviewView | None = None
    reasons: tuple[PausedSearchOperationsReason, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


@dataclass(frozen=True)
class PausedSearchReviewActionResult:
    status: PausedSearchOperationsStatus
    review: PausedSearchReview | None = None
    occurrence: RecurringOccurrence | None = None
    message: OutboundMessage | None = None
    reasons: tuple[PausedSearchOperationsReason, ...] = ()
    permission_reasons: tuple[PermissionReasonCode, ...] = ()


async def list_paused_search_occurrences(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    occurrence_repository: PausedSearchOccurrenceOperationsRepository,
    lead_repository: LeadReadLeadRepository,
    lead_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
) -> PausedSearchOperationsReadResult:
    permission = evaluate_permission(actor, PermissionCapability.VIEW_PAUSED_SEARCH_ANY)
    own_permission = evaluate_permission(
        actor,
        PermissionCapability.VIEW_PAUSED_SEARCH_OWN,
        PermissionContext(acts_on_assigned_lead=True),
    )
    if not permission.allowed and not own_permission.allowed:
        return _read_rejected(permission.reasons or own_permission.reasons)

    occurrences = await occurrence_repository.list_for_workspace(
        workspace_id,
        lead_id=lead_id,
        status=status,
        limit=limit,
    )
    views: list[PausedSearchOccurrenceView] = []
    for occurrence in occurrences:
        lead = await lead_repository.get_by_id(workspace_id, occurrence.lead_id)
        if lead is None or not _can_view_lead(actor, lead, permission.allowed):
            continue
        views.append(PausedSearchOccurrenceView(occurrence=occurrence, lead=lead))
    return PausedSearchOperationsReadResult(
        status=PausedSearchOperationsStatus.OK,
        occurrences=tuple(views),
    )


async def get_paused_search_occurrence(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    occurrence_id: UUID,
    occurrence_repository: PausedSearchOccurrenceOperationsRepository,
    lead_repository: LeadReadLeadRepository,
) -> PausedSearchOperationsReadResult:
    occurrence = await occurrence_repository.get_by_id(workspace_id, occurrence_id)
    if occurrence is None:
        return PausedSearchOperationsReadResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.OCCURRENCE_NOT_FOUND,),
        )
    lead = await lead_repository.get_by_id(workspace_id, occurrence.lead_id)
    if lead is None:
        return PausedSearchOperationsReadResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.OCCURRENCE_NOT_FOUND,),
        )
    permission = evaluate_permission(actor, PermissionCapability.VIEW_PAUSED_SEARCH_ANY)
    if not _can_view_lead(actor, lead, permission.allowed):
        return _read_rejected(permission.reasons)
    return PausedSearchOperationsReadResult(
        status=PausedSearchOperationsStatus.OK,
        occurrence=PausedSearchOccurrenceView(occurrence=occurrence, lead=lead),
    )


async def list_paused_search_reviews(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    review_repository: PausedSearchReviewRepository,
    lead_repository: LeadReadLeadRepository,
    status: str | None = None,
    lead_id: UUID | None = None,
    limit: int = 100,
    message_repository: OutboundMessageRepository | None = None,
) -> PausedSearchOperationsReadResult:
    permission = evaluate_permission(actor, PermissionCapability.VIEW_PAUSED_SEARCH_ANY)
    own_permission = evaluate_permission(
        actor,
        PermissionCapability.VIEW_PAUSED_SEARCH_OWN,
        PermissionContext(acts_on_assigned_lead=True),
    )
    if not permission.allowed and not own_permission.allowed:
        return _read_rejected(permission.reasons or own_permission.reasons)

    reviews = await review_repository.list_for_workspace(
        workspace_id,
        status=status,
        limit=limit,
    )
    views: list[PausedSearchReviewView] = []
    for review in reviews:
        if lead_id is not None and review.lead_id != lead_id:
            continue
        lead = await lead_repository.get_by_id(workspace_id, review.lead_id)
        if lead is None or not _can_view_lead(actor, lead, permission.allowed):
            continue
        message = await _review_message(review, message_repository)
        views.append(PausedSearchReviewView(review=review, lead=lead, message=message))
    return PausedSearchOperationsReadResult(
        status=PausedSearchOperationsStatus.OK,
        reviews=tuple(views),
    )


async def get_paused_search_review(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    review_id: UUID,
    review_repository: PausedSearchReviewRepository,
    lead_repository: LeadReadLeadRepository,
    message_repository: OutboundMessageRepository | None = None,
) -> PausedSearchOperationsReadResult:
    review = await review_repository.get_by_id(workspace_id, review_id)
    if review is None:
        return PausedSearchOperationsReadResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    lead = await lead_repository.get_by_id(workspace_id, review.lead_id)
    if lead is None:
        return PausedSearchOperationsReadResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    permission = evaluate_permission(actor, PermissionCapability.VIEW_PAUSED_SEARCH_ANY)
    if not _can_view_lead(actor, lead, permission.allowed):
        return _read_rejected(permission.reasons)
    return PausedSearchOperationsReadResult(
        status=PausedSearchOperationsStatus.OK,
        review=PausedSearchReviewView(
            review=review,
            lead=lead,
            message=await _review_message(review, message_repository),
        ),
    )


async def apply_paused_search_review_action(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    review_id: UUID,
    action: PausedSearchReviewAction,
    reason: str,
    review_repository: PausedSearchReviewRepository,
    occurrence_repository: PausedSearchOccurrenceOperationsRepository,
    lead_repository: LeadReadLeadRepository,
    idempotency_key: str,
    now: datetime,
    resolution_action: str | None = None,
    target_track_version_id: UUID | None = None,
    terminal_behavior: PausedSearchTerminalBehavior | None = None,
    workflow_repository: LeadReadWorkflowRepository | None = None,
    action_workflow_repository: LeadWorkflowRepository | None = None,
    workflow_transition_repository: WorkflowTransitionRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    external_event_repository: ExternalEventRepository | None = None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None = None,
    paused_search_history_repository: LeadPausedSearchHistoryRepository | None = None,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None = None,
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository | None = None,
    workspace_repository: WorkspaceRepository | None = None,
    paused_search_occurrence_repository: PausedSearchOccurrenceOperationsRepository | None = None,
    commit: Callable[[], Awaitable[None]] | None = None,
    action_lead_repository: LeadRepository | None = None,
    message_repository: OutboundMessageRepository | None = None,
) -> PausedSearchReviewActionResult:
    if not reason.strip():
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(PausedSearchOperationsReason.REASON_REQUIRED,),
        )
    command_reason = f"{reason.strip()} (command:{idempotency_key.strip()})"
    review = await review_repository.get_by_id_for_update(workspace_id, review_id)
    if review is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    lead = await lead_repository.get_by_id(workspace_id, review.lead_id)
    if lead is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    permission = evaluate_permission(actor, PermissionCapability.ACT_ON_PAUSED_SEARCH_ANY)
    own_permission = evaluate_permission(
        actor,
        PermissionCapability.ACT_ON_PAUSED_SEARCH_OWN,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )
    if not permission.allowed and not own_permission.allowed:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.REJECTED,
            reasons=(PausedSearchOperationsReason.PERMISSION_DENIED,),
            permission_reasons=own_permission.reasons or permission.reasons,
        )
    if review.status is not PausedSearchReviewStatus.PENDING:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.ALREADY_RESOLVED,
            review=review,
        )
    if review.kind is PausedSearchReviewKind.POLICY:
        if action is not PausedSearchReviewAction.RESOLVE or resolution_action not in {
            "skip",
            "resume_after_revalidation",
            "migrate",
            "terminalize",
        }:
            return PausedSearchReviewActionResult(
                status=PausedSearchOperationsStatus.INVALID,
                reasons=(PausedSearchOperationsReason.POLICY_ACTION_NOT_ALLOWED,),
            )
        if resolution_action == "migrate" and target_track_version_id is None:
            return PausedSearchReviewActionResult(
                status=PausedSearchOperationsStatus.INVALID,
                reasons=(PausedSearchOperationsReason.INVALID_ACTION,),
            )
        if resolution_action == "terminalize" and terminal_behavior is None:
            return PausedSearchReviewActionResult(
                status=PausedSearchOperationsStatus.INVALID,
                reasons=(PausedSearchOperationsReason.INVALID_ACTION,),
            )
        if not await _execute_policy_resolution(
            resolution_action=resolution_action,
            actor=actor,
            workspace_id=workspace_id,
            lead_id=review.lead_id,
            reason=reason,
            now=now,
            lead_repository=lead_repository,
            action_lead_repository=action_lead_repository,
            workflow_repository=workflow_repository,
            action_workflow_repository=action_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            external_event_repository=external_event_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            paused_search_history_repository=paused_search_history_repository,
            paused_search_track_repository=paused_search_track_repository,
            lead_workflow_override_audit_repository=lead_workflow_override_audit_repository,
            workspace_repository=workspace_repository,
            paused_search_occurrence_repository=paused_search_occurrence_repository,
            target_track_version_id=target_track_version_id,
            terminal_behavior=terminal_behavior,
            commit=commit,
        ):
            return PausedSearchReviewActionResult(
                status=PausedSearchOperationsStatus.INVALID,
                reasons=(PausedSearchOperationsReason.INVALID_ACTION,),
            )
    elif action is PausedSearchReviewAction.RESOLVE:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(PausedSearchOperationsReason.INVALID_ACTION,),
        )
    message = await _review_message(review, message_repository)
    if review.kind is PausedSearchReviewKind.MESSAGE and message is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            review=review,
            reasons=(PausedSearchOperationsReason.MESSAGE_NOT_FOUND,),
        )
    updated_review, error = apply_review_action(
        review,
        action=action,
        reviewer_user_id=actor.user_id,
        reason=(
            f"{resolution_action}: {command_reason}"
            if resolution_action is not None
            else command_reason
        ),
        now=now,
    )
    if error is not None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(
                PausedSearchOperationsReason.POLICY_ACTION_NOT_ALLOWED
                if error.value == "policy_action_not_allowed"
                else PausedSearchOperationsReason.INVALID_TRANSITION,
            ),
        )
    if updated_review is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(PausedSearchOperationsReason.INVALID_TRANSITION,),
        )
    occurrence = None
    if review.occurrence_id is not None:
        occurrence_status = _occurrence_status_for_action(
            review=review,
            action=action,
            resolution_action=resolution_action,
        )
        if occurrence_status is not None:
            occurrence = await occurrence_repository.update_status(
                workspace_id=workspace_id,
                occurrence_id=review.occurrence_id,
                status=occurrence_status.value,
                now=now,
                failure_reason=updated_review.action_reason,
            )
    saved_review = await review_repository.save(updated_review)
    if (
        review.kind is PausedSearchReviewKind.MESSAGE
        and action is PausedSearchReviewAction.REJECT
        and message is not None
        and message_repository is not None
    ):
        message = await message_repository.save(
            replace(
                message,
                status=OutboundMessageStatus.CANCELLED,
                updated_at=now,
                failure_reason=updated_review.action_reason,
            )
        )
    if review.kind is PausedSearchReviewKind.MESSAGE:
        await _queue_message_review_completion(
            actor=actor,
            review=saved_review,
            action=action,
            idempotency_key=idempotency_key,
            reason=reason,
            workflow_repository=workflow_repository,
            external_event_repository=external_event_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            now=now,
        )
    return PausedSearchReviewActionResult(
        status=PausedSearchOperationsStatus.OK,
        review=saved_review,
        occurrence=occurrence,
        message=message,
    )


async def edit_paused_search_message_review(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    review_id: UUID,
    body: str,
    subject: str | None,
    reason: str,
    idempotency_key: str,
    review_repository: PausedSearchReviewRepository,
    message_repository: OutboundMessageRepository,
    lead_repository: LeadReadLeadRepository,
    external_event_repository: ExternalEventRepository,
    now: datetime,
) -> PausedSearchReviewActionResult:
    if not body.strip():
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(PausedSearchOperationsReason.MESSAGE_CONTENT_REQUIRED,),
        )
    if not reason.strip():
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            reasons=(PausedSearchOperationsReason.REASON_REQUIRED,),
        )
    review = await review_repository.get_by_id_for_update(workspace_id, review_id)
    if review is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    lead = await lead_repository.get_by_id(workspace_id, review.lead_id)
    if lead is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.NOT_FOUND,
            reasons=(PausedSearchOperationsReason.REVIEW_NOT_FOUND,),
        )
    permission = evaluate_permission(actor, PermissionCapability.ACT_ON_PAUSED_SEARCH_ANY)
    own_permission = evaluate_permission(
        actor,
        PermissionCapability.ACT_ON_PAUSED_SEARCH_OWN,
        PermissionContext(acts_on_assigned_lead=is_actor_assigned_to_lead(actor, lead)),
    )
    if not permission.allowed and not own_permission.allowed:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.REJECTED,
            reasons=(PausedSearchOperationsReason.PERMISSION_DENIED,),
            permission_reasons=own_permission.reasons or permission.reasons,
        )
    if (
        review.kind is not PausedSearchReviewKind.MESSAGE
        or review.status is not PausedSearchReviewStatus.PENDING
    ):
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            review=review,
            reasons=(PausedSearchOperationsReason.INVALID_ACTION,),
        )
    current = await _review_message(review, message_repository)
    if current is None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.INVALID,
            review=review,
            reasons=(PausedSearchOperationsReason.MESSAGE_NOT_FOUND,),
        )
    event_key = f"paused-search-review-edit:{review_id}:{idempotency_key.strip()}"
    existing_event = await external_event_repository.get_by_provider_event_id(
        workspace_id,
        "internal",
        event_key,
    )
    if existing_event is not None:
        return PausedSearchReviewActionResult(
            status=PausedSearchOperationsStatus.OK,
            review=review,
            message=current,
        )

    next_version = current.message_version + 1
    edited = await message_repository.save(
        OutboundMessage(
            message_id=uuid4(),
            workspace_id=current.workspace_id,
            lead_id=current.lead_id,
            campaign_id=current.campaign_id,
            cadence_step_id=current.cadence_step_id,
            channel=current.channel,
            status=OutboundMessageStatus.PENDING,
            idempotency_key=outbound_message_idempotency_key(
                workspace_id=current.workspace_id,
                campaign_id=current.campaign_id,
                lead_id=current.lead_id,
                cadence_step_id=current.cadence_step_id,
                channel=current.channel,
                message_version=next_version,
            ),
            body=body.strip(),
            subject=subject.strip() if subject and subject.strip() else None,
            scheduled_for=current.scheduled_for,
            planned_at=now,
            created_at=now,
            updated_at=now,
            message_version=next_version,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
            reply_routing_token=(
                token_hex(16) if current.channel is ContactChannel.EMAIL else None
            ),
            draft_prompt_version=current.draft_prompt_version,
            draft_model=current.draft_model,
            draft_latency_ms=current.draft_latency_ms,
            draft_usage_tokens=current.draft_usage_tokens,
            draft_confidence=current.draft_confidence,
            draft_personalization_notes=current.draft_personalization_notes,
            draft_safety_flags=current.draft_safety_flags,
        )
    )
    await message_repository.save(
        replace(
            current,
            status=OutboundMessageStatus.CANCELLED,
            updated_at=now,
            failure_reason=f"Superseded by operator-edited version {next_version}.",
        )
    )
    saved_review = await review_repository.save(
        replace(
            review,
            outbound_message_id=edited.message_id,
            outbound_message_version=edited.message_version,
            action_reason=f"edit: {reason.strip()} (command:{idempotency_key.strip()})",
        )
    )
    await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=workspace_id,
        lead_id=review.lead_id,
        event_type="paused_search.message_review_edited",
        provider_event_id=event_key,
        now=now,
        payload_redacted={
            "actor_user_id": str(actor.user_id),
            "review_id": str(review.review_id),
            "previous_message_id": str(current.message_id),
            "outbound_message_id": str(edited.message_id),
            "message_version": edited.message_version,
            "reason": reason.strip(),
        },
    )
    return PausedSearchReviewActionResult(
        status=PausedSearchOperationsStatus.OK,
        review=saved_review,
        message=edited,
    )


async def _review_message(
    review: PausedSearchReview,
    message_repository: OutboundMessageRepository | None,
) -> OutboundMessage | None:
    if message_repository is None or review.outbound_message_id is None:
        return None
    return await message_repository.get_by_id(
        review.workspace_id,
        review.outbound_message_id,
    )


async def _queue_message_review_completion(
    *,
    actor: AuthenticatedActor,
    review: PausedSearchReview,
    action: PausedSearchReviewAction,
    idempotency_key: str,
    reason: str,
    workflow_repository: LeadReadWorkflowRepository | None,
    external_event_repository: ExternalEventRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    now: datetime,
) -> None:
    if (
        workflow_repository is None
        or external_event_repository is None
        or temporal_signal_outbox_repository is None
    ):
        return
    workflow = await workflow_repository.get_latest_for_lead(
        review.workspace_id,
        review.lead_id,
    )
    if (
        workflow is None
        or workflow.workflow_id != review.workflow_id
        or workflow.temporal_workflow_id is None
    ):
        return
    event_key = (
        f"paused-search-review-{action.value}:{review.review_id}:{idempotency_key.strip()}"
    )
    event = await create_internal_external_event(
        external_event_repository=external_event_repository,
        workspace_id=review.workspace_id,
        lead_id=review.lead_id,
        event_type=f"paused_search.message_review_{action.value}",
        provider_event_id=event_key,
        now=now,
        payload_redacted={
            "actor_user_id": str(actor.user_id),
            "review_id": str(review.review_id),
            "occurrence_id": str(review.occurrence_id),
            "outbound_message_id": str(review.outbound_message_id),
            "outbound_message_version": review.outbound_message_version,
            "reason": reason.strip(),
        },
    )
    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=review.workspace_id,
            workflow_id=review.workflow_id,
            temporal_workflow_id=workflow.temporal_workflow_id,
            signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
            payload={
                "lead_id": str(review.lead_id),
                "review_id": str(review.review_id),
                "occurrence_id": str(review.occurrence_id),
                "occurred_at": now.isoformat(),
                "reason": reason.strip(),
                "actor_user_id": str(actor.user_id),
                "external_event_id": str(event.external_event_id),
            },
            idempotency_key=f"blocked-review-completed:{event.provider_event_id}",
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )


async def _execute_policy_resolution(
    *,
    resolution_action: str | None,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    lead_id: UUID,
    reason: str,
    now: datetime,
    lead_repository: LeadReadLeadRepository,
    action_lead_repository: LeadRepository | None,
    workflow_repository: LeadReadWorkflowRepository | None,
    action_workflow_repository: LeadWorkflowRepository | None,
    workflow_transition_repository: WorkflowTransitionRepository | None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None,
    external_event_repository: ExternalEventRepository | None,
    workspace_contact_policy_repository: WorkspaceContactPolicyRepository | None,
    paused_search_history_repository: LeadPausedSearchHistoryRepository | None,
    paused_search_track_repository: PausedSearchTrackMappingRepository | None,
    lead_workflow_override_audit_repository: LeadWorkflowOverrideAuditLogRepository | None,
    workspace_repository: WorkspaceRepository | None,
    paused_search_occurrence_repository: PausedSearchOccurrenceOperationsRepository | None,
    target_track_version_id: UUID | None,
    terminal_behavior: PausedSearchTerminalBehavior | None,
    commit: Callable[[], Awaitable[None]] | None,
) -> bool:
    if (
        action_workflow_repository is None
        or workflow_repository is None
        or workflow_transition_repository is None
        or temporal_signal_outbox_repository is None
        or paused_search_track_repository is None
        or lead_workflow_override_audit_repository is None
        or workspace_repository is None
    ):
        return False
    if resolution_action == "skip":
        skip_result = await skip_paused_search_next_touch(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead_id,
            reason=reason,
            lead_repository=action_lead_repository or lead_repository,  # type: ignore[arg-type]
            lead_workflow_repository=action_workflow_repository,
            lead_workflow_override_audit_repository=lead_workflow_override_audit_repository,
            paused_search_track_repository=paused_search_track_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            workspace_repository=workspace_repository,
            now=now,
        )
        return skip_result.status in {
            PausedSearchWorkflowOverrideStatus.UPDATED,
            PausedSearchWorkflowOverrideStatus.UNCHANGED,
        }
    if resolution_action == "migrate" and target_track_version_id is not None:
        migrate_result = await migrate_paused_search_track_version(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead_id,
            target_track_version_id=target_track_version_id,
            reason=reason,
            lead_repository=action_lead_repository or lead_repository,  # type: ignore[arg-type]
            lead_workflow_repository=action_workflow_repository,
            lead_workflow_override_audit_repository=lead_workflow_override_audit_repository,
            paused_search_track_repository=paused_search_track_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            workspace_repository=workspace_repository,
            now=now,
        )
        return migrate_result.status in {
            PausedSearchWorkflowOverrideStatus.UPDATED,
            PausedSearchWorkflowOverrideStatus.UNCHANGED,
        }
    if resolution_action == "resume_after_revalidation":
        if (
            external_event_repository is None
            or workspace_contact_policy_repository is None
            or commit is None
        ):
            return False
        resume_result = await resume_lead_workflow(
            actor=actor,
            workspace_id=workspace_id,
            lead_id=lead_id,
            reason=reason,
            lead_repository=lead_repository,
            workflow_repository=workflow_repository,
            lead_workflow_repository=action_workflow_repository,
            workspace_contact_policy_repository=workspace_contact_policy_repository,
            workflow_transition_repository=workflow_transition_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            external_event_repository=external_event_repository,
            commit=commit,
            now=now,
        )
        return resume_result.status in {
            LeadResumeActionStatus.REQUESTED,
            LeadResumeActionStatus.RESTARTED,
        }
    if resolution_action == "terminalize" and terminal_behavior is not None:
        target_state = {
            PausedSearchTerminalBehavior.COMPLETE_KEEP_PAUSED: WorkflowState.COMPLETED,
            PausedSearchTerminalBehavior.PAUSE_FOR_REVIEW: WorkflowState.PAUSED,
            PausedSearchTerminalBehavior.CLOSE_AUTOMATION: WorkflowState.CLOSED,
        }[terminal_behavior]
        terminal_result = await apply_workflow_state_transition(
            workspace_id=workspace_id,
            lead_id=lead_id,
            to_state=target_state,
            reason_code=WorkflowTransitionReasonCode.PAUSED_SEARCH_TERMINALIZED,
            lead_workflow_repository=action_workflow_repository,
            workflow_transition_repository=workflow_transition_repository,
            paused_search_occurrence_repository=None,
            now=now,
            actor_user_id=actor.user_id,
            metadata={"reason": reason, "terminal_behavior": terminal_behavior.value},
            pause_reason="paused_search_terminal_review"
            if target_state is WorkflowState.PAUSED
            else None,
        )
        return terminal_result.status is WorkflowStateTransitionStatus.UPDATED
    return False


def _occurrence_status_for_action(
    *,
    review: PausedSearchReview,
    action: PausedSearchReviewAction,
    resolution_action: str | None,
) -> RecurringOccurrenceStatus | None:
    if action is PausedSearchReviewAction.APPROVE:
        return RecurringOccurrenceStatus.APPROVED
    if action is PausedSearchReviewAction.REJECT:
        return RecurringOccurrenceStatus.SKIPPED
    if resolution_action in {"skip", "terminalize", "migrate"}:
        return RecurringOccurrenceStatus.SKIPPED
    if resolution_action == "resume_after_revalidation":
        return RecurringOccurrenceStatus.APPROVED
    return None


def _can_view_lead(
    actor: AuthenticatedActor,
    lead: CanonicalLeadRecord,
    has_workspace_permission: bool,
) -> bool:
    return has_workspace_permission or is_actor_assigned_to_lead(actor, lead)


def _read_rejected(
    permission_reasons: tuple[PermissionReasonCode, ...],
) -> PausedSearchOperationsReadResult:
    return PausedSearchOperationsReadResult(
        status=PausedSearchOperationsStatus.REJECTED,
        reasons=(PausedSearchOperationsReason.PERMISSION_DENIED,),
        permission_reasons=permission_reasons,
    )