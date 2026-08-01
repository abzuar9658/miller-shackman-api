from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.temporal import (
    LeadNurtureWorkflowSignaler,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowNotFoundError,
    UnblockLeadNurtureWorkflowSignal,
)
from app.application.use_cases.dispatch_temporal_signals import dispatch_temporal_signals
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadNurtureWorkflowSignaler,
    FakeTemporalSignalOutboxRepository,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW_ID = UUID("10000000-0000-0000-0000-000000000002")
LEAD_ID = UUID("10000000-0000-0000-0000-000000000003")
EXTERNAL_EVENT_ID = UUID("10000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000005")


class MissingWorkflowSignaler:
    async def _raise(self, *, temporal_workflow_id: str, signal: object) -> None:  # noqa: ARG002
        raise TemporalWorkflowNotFoundError("workflow not found")

    async def signal_inbound_processed_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_pause_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_resume_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_unblock_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_reschedule_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)


class UnavailableWorkflowSignaler:
    async def _raise(self, *, temporal_workflow_id: str, signal: object) -> None:  # noqa: ARG002
        raise RuntimeError("temporal unavailable")

    async def signal_inbound_processed_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_pause_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_resume_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_unblock_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)

    async def signal_reschedule_lead_nurture_workflow(
        self, *, temporal_workflow_id: str, signal: object
    ) -> None:
        await self._raise(temporal_workflow_id=temporal_workflow_id, signal=signal)


def _entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return _inbound_processed_entry(available_at=available_at)


def _inbound_processed_entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=UUID("10000000-0000-0000-0000-000000000005"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.INBOUND_PROCESSED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "external_event_id": str(EXTERNAL_EVENT_ID),
            "conversation_id": None,
            "inbound_message_id": None,
            "workflow_transition_id": None,
            "inbound_action": "human_handoff",
            "reason": "human_requested",
        },
        idempotency_key=f"inbound-processed:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _pause_requested_entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=UUID("10000000-0000-0000-0000-000000000006"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.PAUSE_REQUESTED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "reason": "crm_note_added",
            "external_event_id": str(EXTERNAL_EVENT_ID),
        },
        idempotency_key=f"pause-requested:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _resume_requested_entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=UUID("10000000-0000-0000-0000-000000000007"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.RESUME_REQUESTED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "reason": "agent approved follow-up",
            "actor_user_id": str(USER_ID),
            "external_event_id": str(EXTERNAL_EVENT_ID),
        },
        idempotency_key=f"resume-requested:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _blocked_review_completed_entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=UUID("10000000-0000-0000-0000-000000000008"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "reason": "approved after review",
            "actor_user_id": str(USER_ID),
            "external_event_id": str(EXTERNAL_EVENT_ID),
        },
        idempotency_key=f"blocked-review-completed:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _reschedule_requested_entry(*, available_at: datetime = NOW) -> TemporalSignalOutboxEntry:
    return TemporalSignalOutboxEntry(
        temporal_signal_id=UUID("10000000-0000-0000-0000-000000000009"),
        workspace_id=WORKSPACE_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        signal_name=TemporalSignalName.RESCHEDULE_REQUESTED,
        payload={
            "lead_id": str(LEAD_ID),
            "occurred_at": NOW.isoformat(),
            "reason": "paused_search_profile_updated",
            "actor_user_id": str(USER_ID),
            "external_event_id": str(EXTERNAL_EVENT_ID),
        },
        idempotency_key=f"reschedule-requested:{EXTERNAL_EVENT_ID}",
        status=TemporalSignalOutboxStatus.PENDING,
        attempt_count=0,
        available_at=available_at,
        created_at=NOW,
        updated_at=NOW,
    )


async def test_dispatch_temporal_signals_marks_entry_sent() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_entry())
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert result.failed_count == 0
    assert result.terminal_failure_count == 0
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.SENT
    assert len(signaler.calls) == 1
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"


async def test_dispatch_temporal_signals_retries_transient_failure() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_entry())

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=cast(
            LeadNurtureWorkflowSignaler,
            UnavailableWorkflowSignaler(),
        ),
        now=NOW,
        retry_base_delay=timedelta(seconds=30),
        retry_max_delay=timedelta(minutes=15),
    )

    assert result.claimed_count == 1
    assert result.sent_count == 0
    assert result.failed_count == 1
    assert result.terminal_failure_count == 0
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.FAILED
    assert entry.available_at == NOW + timedelta(seconds=30)
    assert entry.last_error == "temporal unavailable"


async def test_dispatch_temporal_signals_marks_not_found_as_terminal_failure() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_entry())

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=cast(
            LeadNurtureWorkflowSignaler,
            MissingWorkflowSignaler(),
        ),
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 0
    assert result.failed_count == 0
    assert result.terminal_failure_count == 1
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.TERMINAL_FAILURE
    assert entry.last_error == "workflow not found"


async def test_dispatch_temporal_signals_sends_pause_requested_signal() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_pause_requested_entry())
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"
    pause_signal = cast(PauseLeadNurtureWorkflowSignal, signaler.calls[0]["signal"])
    assert pause_signal.reason == "crm_note_added"


async def test_dispatch_temporal_signals_sends_resume_requested_signal() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_resume_requested_entry())
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"
    resume_signal = cast(ResumeLeadNurtureWorkflowSignal, signaler.calls[0]["signal"])
    assert resume_signal.reason == "agent approved follow-up"


async def test_dispatch_temporal_signals_sends_blocked_review_completed_signal() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_blocked_review_completed_entry())
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"
    unblock_signal = cast(UnblockLeadNurtureWorkflowSignal, signaler.calls[0]["signal"])
    assert unblock_signal.reason == "approved after review"


async def test_dispatch_temporal_signals_sends_reschedule_requested_signal() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"
    reschedule_signal = cast(RescheduleLeadNurtureWorkflowSignal, signaler.calls[0]["signal"])
    assert reschedule_signal.reason == "paused_search_profile_updated"


async def test_dispatch_temporal_signals_preserves_reschedule_then_pause_order() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(
        replace(
            _pause_requested_entry(),
            created_at=NOW + timedelta(seconds=1),
            updated_at=NOW + timedelta(seconds=1),
        )
    )
    await repository.append(
        replace(
            _reschedule_requested_entry(),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
        batch_size=2,
    )

    assert result.claimed_count == 2
    assert result.sent_count == 2
    first_signal = cast(RescheduleLeadNurtureWorkflowSignal, signaler.calls[0]["signal"])
    second_signal = cast(PauseLeadNurtureWorkflowSignal, signaler.calls[1]["signal"])
    assert first_signal.reason == "paused_search_profile_updated"
    assert second_signal.reason == "crm_note_added"
