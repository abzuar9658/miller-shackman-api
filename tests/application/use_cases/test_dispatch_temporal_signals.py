from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.repositories import (
    CampaignEnrollmentRepository,
    LeadWorkflowRepository,
    TemporalSignalOutboxRepository,
)
from app.application.ports.temporal import (
    InboundProcessedLeadNurtureWorkflowSignal,
    LeadNurtureWorkflowSignaler,
    PauseLeadNurtureWorkflowSignal,
    RescheduleLeadNurtureWorkflowSignal,
    ResumeLeadNurtureWorkflowSignal,
    TemporalWorkflowExecutionMode,
    TemporalWorkflowNotFoundError,
    TemporalWorkflowStarter,
    UnblockLeadNurtureWorkflowSignal,
)
from app.application.use_cases.dispatch_temporal_signals import (
    DispatchTemporalSignalsResult,
    dispatch_temporal_signals,
)
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.workflows import (
    LeadWorkflow,
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
    WorkflowState,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadNurtureWorkflowSignaler,
    FakeLeadWorkflowRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW_ID = UUID("10000000-0000-0000-0000-000000000002")
LEAD_ID = UUID("10000000-0000-0000-0000-000000000003")
EXTERNAL_EVENT_ID = UUID("10000000-0000-0000-0000-000000000004")
USER_ID = UUID("10000000-0000-0000-0000-000000000005")
CAMPAIGN_ID = UUID("10000000-0000-0000-0000-000000000010")
CAMPAIGN_VERSION_ID = UUID("10000000-0000-0000-0000-000000000011")
CAMPAIGN_ENROLLMENT_ID = UUID("10000000-0000-0000-0000-000000000012")
TRACK_VERSION_ID = UUID("10000000-0000-0000-0000-000000000013")


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


async def test_dispatch_temporal_signals_preserves_paused_search_reply_decision() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(
        replace(
            _entry(),
            payload={
                **_entry().payload,
                "paused_search_reply_decision": "restart",
            },
        )
    )
    signaler = FakeLeadNurtureWorkflowSignaler()

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=repository,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
    )

    assert result.sent_count == 1
    inbound_signal = cast(
        InboundProcessedLeadNurtureWorkflowSignal,
        signaler.calls[0]["signal"],
    )
    assert inbound_signal.paused_search_reply_decision == "restart"


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


def _workflow(
    *,
    state: WorkflowState = WorkflowState.QUEUED,
    paused_search_track_version_id: UUID | None = TRACK_VERSION_ID,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=CAMPAIGN_ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )


def _enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=CAMPAIGN_ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.CRM_TAG,
        status=CampaignEnrollmentStatus.QUEUED,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=None,
        ended_at=None,
        created_by_user_id=None,
        reason_codes=(),
        created_at=NOW,
        updated_at=NOW,
    )


async def _run_dispatch_with_restart_dependencies(
    *,
    repository: FakeTemporalSignalOutboxRepository,
    workflow: LeadWorkflow | None,
    enrollment: CampaignEnrollment | None,
    starter: FakeTemporalWorkflowStarter,
) -> DispatchTemporalSignalsResult:
    lead_workflow_repository = FakeLeadWorkflowRepository()
    if workflow is not None:
        await lead_workflow_repository.save(workflow)
    campaign_enrollment_repository = FakeCampaignEnrollmentRepository()
    if enrollment is not None:
        await campaign_enrollment_repository.save(enrollment)
    return await dispatch_temporal_signals(
        temporal_signal_outbox_repository=cast(TemporalSignalOutboxRepository, repository),
        lead_nurture_workflow_signaler=cast(
            LeadNurtureWorkflowSignaler,
            MissingWorkflowSignaler(),
        ),
        lead_workflow_repository=cast(LeadWorkflowRepository, lead_workflow_repository),
        campaign_enrollment_repository=cast(
            CampaignEnrollmentRepository,
            campaign_enrollment_repository,
        ),
        temporal_workflow_starter=cast(TemporalWorkflowStarter, starter),
        now=NOW,
    )


async def test_dispatch_temporal_signals_restarts_missing_workflow_in_sendable_state() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())
    starter = FakeTemporalWorkflowStarter()

    result = await _run_dispatch_with_restart_dependencies(
        repository=repository,
        workflow=_workflow(),
        enrollment=_enrollment(),
        starter=starter,
    )

    assert result.claimed_count == 1
    assert result.sent_count == 1
    assert result.terminal_failure_count == 0
    assert result.restarted_count == 1
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.SENT
    assert len(starter.calls) == 1
    start_call = starter.calls[0]
    assert start_call["temporal_workflow_id"] == "workflow-123"
    assert start_call["workflow_id"] == WORKFLOW_ID
    assert start_call["campaign_version_id"] == CAMPAIGN_VERSION_ID
    assert start_call["execution_mode"] == TemporalWorkflowExecutionMode.PAUSED_SEARCH_RECURRING
    assert start_call["paused_search_track_version_id"] == TRACK_VERSION_ID


async def test_dispatch_temporal_signals_restarts_standard_cadence_workflow() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_entry())
    starter = FakeTemporalWorkflowStarter()

    result = await _run_dispatch_with_restart_dependencies(
        repository=repository,
        workflow=_workflow(paused_search_track_version_id=None),
        enrollment=_enrollment(),
        starter=starter,
    )

    assert result.restarted_count == 1
    start_call = starter.calls[0]
    assert start_call["execution_mode"] == TemporalWorkflowExecutionMode.STANDARD_CADENCE
    assert start_call["paused_search_track_version_id"] is None


async def test_dispatch_temporal_signals_does_not_restart_non_sendable_workflow() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())
    starter = FakeTemporalWorkflowStarter()

    result = await _run_dispatch_with_restart_dependencies(
        repository=repository,
        workflow=_workflow(state=WorkflowState.COMPLETED),
        enrollment=_enrollment(),
        starter=starter,
    )

    assert result.restarted_count == 0
    assert result.terminal_failure_count == 1
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.TERMINAL_FAILURE
    assert starter.calls == []


async def test_dispatch_temporal_signals_does_not_restart_superseded_workflow() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())
    starter = FakeTemporalWorkflowStarter()
    newer_workflow = replace(
        _workflow(),
        workflow_id=UUID("10000000-0000-0000-0000-000000000099"),
    )

    result = await _run_dispatch_with_restart_dependencies(
        repository=repository,
        workflow=newer_workflow,
        enrollment=_enrollment(),
        starter=starter,
    )

    assert result.restarted_count == 0
    assert result.terminal_failure_count == 1
    assert starter.calls == []


async def test_dispatch_temporal_signals_retries_when_restart_fails() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())
    starter = FakeTemporalWorkflowStarter(always_fail=True)

    result = await _run_dispatch_with_restart_dependencies(
        repository=repository,
        workflow=_workflow(),
        enrollment=_enrollment(),
        starter=starter,
    )

    assert result.restarted_count == 0
    assert result.failed_count == 1
    assert result.terminal_failure_count == 0
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.FAILED
    assert entry.last_error is not None
    assert "workflow restart failed" in entry.last_error


async def test_dispatch_temporal_signals_without_restart_dependencies_dead_letters() -> None:
    repository = FakeTemporalSignalOutboxRepository()
    await repository.append(_reschedule_requested_entry())

    result = await dispatch_temporal_signals(
        temporal_signal_outbox_repository=cast(TemporalSignalOutboxRepository, repository),
        lead_nurture_workflow_signaler=cast(
            LeadNurtureWorkflowSignaler,
            MissingWorkflowSignaler(),
        ),
        now=NOW,
    )

    assert result.restarted_count == 0
    assert result.terminal_failure_count == 1
    entry = next(iter(repository.entries.values()))
    assert entry.status == TemporalSignalOutboxStatus.TERMINAL_FAILURE
