from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.crm import CRMClient
from app.application.ports.notifications import NotificationProvider, ReviewNotification
from app.application.ports.repositories import (
    LeadRepository,
    LeadWorkflowRepository,
    PausedSearchNotificationRepository,
    PausedSearchOccurrenceRepository,
    TemporalSignalOutboxRepository,
    WorkflowTransitionRepository,
    WorkspaceHandoffConfigRepository,
)
from app.application.use_cases.apply_workflow_state_transition import (
    WorkflowStateTransitionStatus,
    apply_workflow_state_transition,
)
from app.domain.campaigns.paused_search_notifications import (
    PausedSearchNotification,
    PausedSearchNotificationChannel,
    PausedSearchNotificationEvent,
    PausedSearchNotificationStatus,
    default_paused_search_notification_policy,
)
from app.domain.campaigns.paused_search_occurrences import (
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.conversations import default_workspace_handoff_config
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    WorkflowState,
    WorkflowTransitionReasonCode,
)


@dataclass(frozen=True)
class UncertainOccurrenceTimeoutResult:
    occurrence: RecurringOccurrence | None
    workflow_state: WorkflowState | None
    timed_out: bool


async def timeout_uncertain_paused_search_occurrence(
    *,
    workspace_id: UUID,
    occurrence_id: UUID,
    now: datetime,
    occurrence_repository: PausedSearchOccurrenceRepository,
    lead_workflow_repository: LeadWorkflowRepository,
    workflow_transition_repository: WorkflowTransitionRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    lead_repository: LeadRepository | None = None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None = None,
    crm_client: CRMClient | None = None,
    notification_provider: NotificationProvider | None = None,
    notification_repository: PausedSearchNotificationRepository | None = None,
) -> UncertainOccurrenceTimeoutResult:
    # Probe unlocked to learn the lead, then lock workflow before occurrence —
    # the canonical lock order shared with cadence execution and the delivery
    # callback path (workflow row first, occurrence row after).
    probe = await occurrence_repository.get_by_id(workspace_id, occurrence_id)
    if probe is None or probe.status is not RecurringOccurrenceStatus.UNCERTAIN:
        return UncertainOccurrenceTimeoutResult(
            occurrence=probe,
            workflow_state=None,
            timed_out=False,
        )
    await lead_workflow_repository.get_latest_for_lead_for_update(
        workspace_id,
        probe.lead_id,
    )
    occurrence = await occurrence_repository.get_by_id_for_update(workspace_id, occurrence_id)
    if occurrence is None or occurrence.status is not RecurringOccurrenceStatus.UNCERTAIN:
        return UncertainOccurrenceTimeoutResult(
            occurrence=occurrence,
            workflow_state=None,
            timed_out=False,
        )

    resolved = await occurrence_repository.resolve_uncertain(
        workspace_id=workspace_id,
        occurrence_id=occurrence_id,
        status=RecurringOccurrenceStatus.FAILED.value,
        now=now,
        reason=WorkflowTransitionReasonCode.UNCERTAIN_SEND_TIMEOUT.value,
    )
    if resolved is None:
        return UncertainOccurrenceTimeoutResult(
            occurrence=occurrence,
            workflow_state=None,
            timed_out=False,
        )

    transition = await apply_workflow_state_transition(
        workspace_id=workspace_id,
        lead_id=resolved.lead_id,
        to_state=WorkflowState.PAUSED,
        reason_code=WorkflowTransitionReasonCode.UNCERTAIN_SEND_TIMEOUT,
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=workflow_transition_repository,
        paused_search_occurrence_repository=occurrence_repository,
        now=now,
        metadata={"occurrence_id": str(occurrence_id)},
        pause_reason="uncertain_send_timeout",
    )
    if (
        transition.status is WorkflowStateTransitionStatus.UPDATED
        and transition.workflow is not None
    ):
        await temporal_signal_outbox_repository.append(
            _timeout_signal(
                workspace_id=workspace_id,
                workflow_id=transition.workflow.workflow_id,
                lead_id=resolved.lead_id,
                temporal_workflow_id=transition.workflow.temporal_workflow_id,
                occurrence_id=occurrence_id,
                now=now,
            )
        )
        await _send_timeout_review_notification(
            workspace_id=workspace_id,
            occurrence=resolved,
            now=now,
            lead_repository=lead_repository,
            workspace_handoff_config_repository=workspace_handoff_config_repository,
            crm_client=crm_client,
            notification_provider=notification_provider,
            notification_repository=notification_repository,
        )
        return UncertainOccurrenceTimeoutResult(
            occurrence=resolved,
            workflow_state=transition.workflow.state,
            timed_out=True,
        )
    return UncertainOccurrenceTimeoutResult(
        occurrence=resolved,
        workflow_state=transition.workflow.state if transition.workflow else None,
        timed_out=True,
    )


async def _send_timeout_review_notification(
    *,
    workspace_id: UUID,
    occurrence: RecurringOccurrence,
    now: datetime,
    lead_repository: LeadRepository | None,
    workspace_handoff_config_repository: WorkspaceHandoffConfigRepository | None,
    crm_client: CRMClient | None,
    notification_provider: NotificationProvider | None,
    notification_repository: PausedSearchNotificationRepository | None,
) -> None:
    if (
        lead_repository is None
        or workspace_handoff_config_repository is None
        or notification_provider is None
    ):
        return
    lead = await lead_repository.get_by_id(workspace_id, occurrence.lead_id)
    if lead is None:
        return
    config = await workspace_handoff_config_repository.get_by_workspace_id(workspace_id)
    handoff_config = config or default_workspace_handoff_config(workspace_id)
    assigned_agent = None
    if crm_client is not None:
        try:
            assigned_agent = await crm_client.get_assigned_agent(workspace_id, lead.crm_lead_id)
        except Exception:
            assigned_agent = None
    recipient_destination = (
        assigned_agent.email
        if assigned_agent is not None and assigned_agent.email
        else handoff_config.fallback_recipient_email
    )
    if recipient_destination is None:
        return
    recipient_id = (
        assigned_agent.crm_agent_id if assigned_agent is not None else recipient_destination
    )
    display_name = (
        lead.mapped_custom_fields.get("display_name")
        or lead.primary_email
        or lead.primary_phone
        or lead.crm_lead_id
    )
    policy = default_paused_search_notification_policy(workspace_id, now=now)
    idempotency_key = f"uncertain-timeout-review:{workspace_id}:{occurrence.occurrence_id}"
    notification = PausedSearchNotification(
        notification_id=uuid4(),
        workspace_id=workspace_id,
        event=PausedSearchNotificationEvent.PROVIDER_FAILURE,
        channel=PausedSearchNotificationChannel.EMAIL,
        status=PausedSearchNotificationStatus.PENDING,
        idempotency_key=idempotency_key,
        recipient_user_id=None,
        recipient_destination=recipient_destination,
        subject="Paused-search provider delivery needs review",
        body=(
            "An outbound paused-search message remained uncertain for 24 hours. "
            "Review the provider record before resuming AI outreach."
        ),
        policy_id=policy.notification_policy_id,
        policy_version=policy.version,
        correlation_id=occurrence.correlation_id,
    )
    if notification_repository is not None:
        existing = await notification_repository.get_by_idempotency_key(
            workspace_id,
            idempotency_key,
        )
        notification = existing or await notification_repository.save(notification)
        if existing is not None and existing.status is PausedSearchNotificationStatus.ACCEPTED:
            return
    try:
        await notification_provider.send_review_notification(
            ReviewNotification(
                workspace_id=workspace_id,
                inbound_message_id=occurrence.occurrence_id,
                lead_id=lead.lead_id,
                recipient_id=recipient_id,
                recipient_destination=recipient_destination,
                lead_display_name=display_name,
                lead_primary_email=lead.primary_email,
                lead_primary_phone=lead.primary_phone,
                latest_inbound_text="No provider delivery confirmation was received.",
                summary=(
                    "An outbound paused-search message remained uncertain for 24 hours. "
                    "Review the provider record before resuming AI outreach."
                ),
                review_reason=WorkflowTransitionReasonCode.UNCERTAIN_SEND_TIMEOUT.value,
                channel="paused_search",
                idempotency_key=idempotency_key,
            )
        )
        if notification_repository is not None:
            await notification_repository.save(
                replace(
                    notification,
                    status=PausedSearchNotificationStatus.ACCEPTED,
                    accepted_at=now,
                )
            )
    except Exception:
        if notification_repository is not None:
            await notification_repository.save(
                replace(
                    notification,
                    status=PausedSearchNotificationStatus.FAILED,
                    failed_at=now,
                    failure_reason="notification_provider_failed",
                )
            )
        return


def _timeout_signal(
    *,
    workspace_id: UUID,
    workflow_id: UUID,
    lead_id: UUID,
    temporal_workflow_id: str,
    occurrence_id: UUID,
    now: datetime,
) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=uuid4(),
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
        signal_name=TemporalSignalName.PAUSE_REQUESTED,
        payload={
            "lead_id": str(lead_id),
            "occurrence_id": str(occurrence_id),
            "occurred_at": now.isoformat(),
            "reason": WorkflowTransitionReasonCode.UNCERTAIN_SEND_TIMEOUT.value,
        },
        idempotency_key=f"uncertain-timeout:{workspace_id}:{occurrence_id}",
        available_at=now,
        created_at=now,
        updated_at=now,
    )
