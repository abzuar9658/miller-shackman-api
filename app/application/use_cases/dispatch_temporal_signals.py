from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

from app.application.ports.repositories import TemporalSignalOutboxRepository
from app.application.ports.temporal import (
    InboundProcessedLeadNurtureWorkflowSignal,
    LeadNurtureWorkflowSignaler,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowNotFoundError,
    UnblockLeadNurtureWorkflowSignal,
)
from app.application.services.retry_backoff import exponential_retry_delay
from app.domain.workflows import TemporalSignalName, TemporalSignalOutboxEntry


class DispatchTemporalSignalsResult:
    def __init__(
        self,
        *,
        claimed_count: int,
        sent_count: int,
        failed_count: int,
        terminal_failure_count: int,
    ) -> None:
        self.claimed_count = claimed_count
        self.sent_count = sent_count
        self.failed_count = failed_count
        self.terminal_failure_count = terminal_failure_count


async def dispatch_temporal_signals(
    *,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
    now: datetime,
    batch_size: int = 100,
    lease_duration: timedelta = timedelta(minutes=5),
    retry_base_delay: timedelta = timedelta(seconds=30),
    retry_max_delay: timedelta = timedelta(minutes=15),
    max_attempts: int = 10,
) -> DispatchTemporalSignalsResult:
    claimed = await temporal_signal_outbox_repository.claim_available_batch(
        now=now,
        limit=batch_size,
        lease_duration=lease_duration,
        max_attempts=max_attempts,
    )
    sent_count = 0
    failed_count = 0
    terminal_failure_count = 0

    for entry in claimed:
        try:
            await _dispatch_entry(
                entry=entry,
                lead_nurture_workflow_signaler=lead_nurture_workflow_signaler,
            )
        except TemporalWorkflowNotFoundError as exc:
            terminal_failure_count += 1
            await temporal_signal_outbox_repository.mark_terminal_failure(
                entry.temporal_signal_id,
                error=str(exc) or exc.__class__.__name__,
                now=now,
            )
            continue
        except (KeyError, TypeError, ValueError) as exc:
            terminal_failure_count += 1
            await temporal_signal_outbox_repository.mark_terminal_failure(
                entry.temporal_signal_id,
                error=f"invalid temporal signal payload: {exc}",
                now=now,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            await temporal_signal_outbox_repository.mark_failed(
                entry.temporal_signal_id,
                error=str(exc) or exc.__class__.__name__,
                available_at=now
                + exponential_retry_delay(
                    entry.attempt_count,
                    base_delay=retry_base_delay,
                    max_delay=retry_max_delay,
                ),
                now=now,
            )
            continue

        sent_count += 1
        await temporal_signal_outbox_repository.mark_sent(entry.temporal_signal_id, now=now)

    return DispatchTemporalSignalsResult(
        claimed_count=len(claimed),
        sent_count=sent_count,
        failed_count=failed_count,
        terminal_failure_count=terminal_failure_count,
    )


async def _dispatch_entry(
    *,
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    dispatchers: dict[TemporalSignalName, _SignalDispatcher] = {
        TemporalSignalName.INBOUND_PROCESSED: _dispatch_inbound_processed,
        TemporalSignalName.PAUSE_REQUESTED: _dispatch_pause_requested,
        TemporalSignalName.RESUME_REQUESTED: _dispatch_resume_requested,
        TemporalSignalName.BLOCKED_REVIEW_COMPLETED: _dispatch_blocked_review_completed,
        TemporalSignalName.RESCHEDULE_REQUESTED: _dispatch_reschedule_requested,
    }
    dispatcher = dispatchers.get(entry.signal_name)
    if dispatcher is None:
        raise ValueError(f"unsupported temporal signal name: {entry.signal_name.value}")
    await dispatcher(entry, lead_nurture_workflow_signaler)


type _SignalDispatcher = Callable[
    [TemporalSignalOutboxEntry, LeadNurtureWorkflowSignaler],
    Awaitable[None],
]


async def _dispatch_inbound_processed(
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    await lead_nurture_workflow_signaler.signal_inbound_processed_lead_nurture_workflow(
        temporal_workflow_id=entry.temporal_workflow_id,
        signal=_inbound_processed_signal(entry),
    )


async def _dispatch_pause_requested(
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    await lead_nurture_workflow_signaler.signal_pause_lead_nurture_workflow(
        temporal_workflow_id=entry.temporal_workflow_id,
        signal=_pause_requested_signal(entry),
    )


async def _dispatch_resume_requested(
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    await lead_nurture_workflow_signaler.signal_resume_lead_nurture_workflow(
        temporal_workflow_id=entry.temporal_workflow_id,
        signal=_resume_requested_signal(entry),
    )


async def _dispatch_blocked_review_completed(
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    await lead_nurture_workflow_signaler.signal_unblock_lead_nurture_workflow(
        temporal_workflow_id=entry.temporal_workflow_id,
        signal=_blocked_review_completed_signal(entry),
    )


async def _dispatch_reschedule_requested(
    entry: TemporalSignalOutboxEntry,
    lead_nurture_workflow_signaler: LeadNurtureWorkflowSignaler,
) -> None:
    await lead_nurture_workflow_signaler.signal_reschedule_lead_nurture_workflow(
        temporal_workflow_id=entry.temporal_workflow_id,
        signal=_reschedule_requested_signal(entry),
    )


def _inbound_processed_signal(
    entry: TemporalSignalOutboxEntry,
) -> InboundProcessedLeadNurtureWorkflowSignal:
    payload = entry.payload
    return InboundProcessedLeadNurtureWorkflowSignal(
        workspace_id=entry.workspace_id,
        lead_id=_uuid_from_payload(payload, "lead_id"),
        occurred_at=datetime.fromisoformat(_string_from_payload(payload, "occurred_at")),
        external_event_id=_optional_uuid_from_payload(payload, "external_event_id"),
        conversation_id=_optional_uuid_from_payload(payload, "conversation_id"),
        inbound_message_id=_optional_uuid_from_payload(payload, "inbound_message_id"),
        workflow_transition_id=_optional_uuid_from_payload(payload, "workflow_transition_id"),
        inbound_action=_optional_string_from_payload(payload, "inbound_action"),
        reason=_optional_string_from_payload(payload, "reason"),
    )


def _pause_requested_signal(
    entry: TemporalSignalOutboxEntry,
) -> PauseLeadNurtureWorkflowSignal:
    payload = entry.payload
    return PauseLeadNurtureWorkflowSignal(
        workspace_id=entry.workspace_id,
        lead_id=_uuid_from_payload(payload, "lead_id"),
        occurred_at=datetime.fromisoformat(_string_from_payload(payload, "occurred_at")),
        reason=_string_from_payload(payload, "reason"),
        actor_user_id=_optional_uuid_from_payload(payload, "actor_user_id"),
        external_event_id=_optional_uuid_from_payload(payload, "external_event_id"),
    )


def _resume_requested_signal(
    entry: TemporalSignalOutboxEntry,
) -> ResumeLeadNurtureWorkflowSignal:
    payload = entry.payload
    return ResumeLeadNurtureWorkflowSignal(
        workspace_id=entry.workspace_id,
        lead_id=_uuid_from_payload(payload, "lead_id"),
        occurred_at=datetime.fromisoformat(_string_from_payload(payload, "occurred_at")),
        reason=_string_from_payload(payload, "reason"),
        actor_user_id=_uuid_from_payload(payload, "actor_user_id"),
        external_event_id=_optional_uuid_from_payload(payload, "external_event_id"),
    )


def _blocked_review_completed_signal(
    entry: TemporalSignalOutboxEntry,
) -> UnblockLeadNurtureWorkflowSignal:
    payload = entry.payload
    return UnblockLeadNurtureWorkflowSignal(
        workspace_id=entry.workspace_id,
        lead_id=_uuid_from_payload(payload, "lead_id"),
        occurred_at=datetime.fromisoformat(_string_from_payload(payload, "occurred_at")),
        reason=_string_from_payload(payload, "reason"),
        actor_user_id=_uuid_from_payload(payload, "actor_user_id"),
        external_event_id=_optional_uuid_from_payload(payload, "external_event_id"),
    )


def _reschedule_requested_signal(
    entry: TemporalSignalOutboxEntry,
) -> RescheduleLeadNurtureWorkflowSignal:
    payload = entry.payload
    return RescheduleLeadNurtureWorkflowSignal(
        workspace_id=entry.workspace_id,
        lead_id=_uuid_from_payload(payload, "lead_id"),
        occurred_at=datetime.fromisoformat(_string_from_payload(payload, "occurred_at")),
        reason=_string_from_payload(payload, "reason"),
        actor_user_id=_optional_uuid_from_payload(payload, "actor_user_id"),
        external_event_id=_optional_uuid_from_payload(payload, "external_event_id"),
    )


def _uuid_from_payload(payload: dict[str, object], key: str) -> UUID:
    return UUID(_string_from_payload(payload, key))


def _optional_uuid_from_payload(payload: dict[str, object], key: str) -> UUID | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string when present")
    return UUID(value)


def _string_from_payload(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string_from_payload(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when present")
    return value or None