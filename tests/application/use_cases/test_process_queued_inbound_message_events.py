from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.application.use_cases.enqueue_inbound_message_event import (
    EnqueueInboundMessageEventStatus,
    enqueue_inbound_message_event,
    inbound_message_event_from_external_event,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventResult,
    ProcessInboundMessageEventStatus,
)
from app.application.use_cases.process_queued_inbound_message_events import (
    process_queued_inbound_message_events,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CRMProvider
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeExternalEventRepository,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


def _inbound_event(provider_event_id: str = "evt-q-1") -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider="twilio",
        provider_event_id=provider_event_id,
        provider_message_id="SM-1",
        crm_lead_id="crm-123",
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        channel=ContactChannel.SMS,
        body="Can someone call me today?",
        received_at=NOW,
        from_address_redacted="***0123",
        to_address_redacted="***4567",
        payload_redacted={"event": "redacted"},
    )


class _QueueRepository:
    def __init__(self, repository: FakeExternalEventRepository) -> None:
        self._repository = repository

    async def claim_due_queued_inbound_events(
        self,
        *,
        now: datetime,
        limit: int = 10,
    ) -> tuple[ExternalEvent, ...]:
        due = [
            event
            for event in self._repository.events.values()
            if event.event_type == "inbound_message.received"
            and event.status
            in (ExternalEventStatus.PENDING, ExternalEventStatus.RETRYABLE_FAILURE)
            and (event.next_retry_at is None or event.next_retry_at <= now)
        ]
        claimed = []
        for event in due[:limit]:
            claimed.append(
                await self._repository.save(
                    ExternalEvent(
                        **{
                            **event.__dict__,
                            "attempt_count": event.attempt_count + 1,
                            "next_retry_at": None,
                            "updated_at": now,
                        }
                    )
                )
            )
        return tuple(claimed)


class _Processor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[InboundMessageEvent, ExternalEvent]] = []

    async def __call__(
        self,
        event: InboundMessageEvent,
        claimed_external_event: ExternalEvent,
        now: datetime,
    ) -> ProcessInboundMessageEventResult:
        self.calls.append((event, claimed_external_event))
        if self.fail:
            raise RuntimeError("llm unavailable")
        return ProcessInboundMessageEventResult(
            status=ProcessInboundMessageEventStatus.PROCESSED,
            external_event_id=claimed_external_event.external_event_id,
        )


async def _record(values: list[str], value: str) -> None:
    values.append(value)


@pytest.mark.asyncio
async def test_enqueued_event_roundtrips_through_payload() -> None:
    repository = FakeExternalEventRepository()
    original = _inbound_event()

    result = await enqueue_inbound_message_event(
        event=original,
        external_event_repository=repository,
        now=NOW,
        lead_id=uuid4(),
    )

    assert result.status is EnqueueInboundMessageEventStatus.ACCEPTED
    saved = repository.events[(WORKSPACE_ID, "twilio", "evt-q-1")]
    assert saved.status is ExternalEventStatus.PENDING
    rebuilt = inbound_message_event_from_external_event(saved)
    assert rebuilt is not None
    assert rebuilt.body == original.body
    assert rebuilt.channel is original.channel
    assert rebuilt.crm_provider is original.crm_provider
    assert rebuilt.provider_message_id == original.provider_message_id
    assert rebuilt.payload_redacted == {"event": "redacted"}


@pytest.mark.asyncio
async def test_enqueue_returns_duplicate_for_replayed_event() -> None:
    repository = FakeExternalEventRepository()
    await enqueue_inbound_message_event(
        event=_inbound_event(),
        external_event_repository=repository,
        now=NOW,
    )

    replay = await enqueue_inbound_message_event(
        event=_inbound_event(),
        external_event_repository=repository,
        now=NOW,
    )

    assert replay.status is EnqueueInboundMessageEventStatus.DUPLICATE
    assert replay.reasons == ("duplicate_event",)


@pytest.mark.asyncio
async def test_worker_processes_queued_event_and_commits() -> None:
    repository = FakeExternalEventRepository()
    await enqueue_inbound_message_event(
        event=_inbound_event(),
        external_event_repository=repository,
        now=NOW,
    )
    processor = _Processor()
    commits: list[str] = []
    rollbacks: list[str] = []

    result = await process_queued_inbound_message_events(
        queue_repository=_QueueRepository(repository),
        external_event_repository=repository,
        processor=processor,
        commit=lambda: _record(commits, "commit"),
        rollback=lambda: _record(rollbacks, "rollback"),
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.processed_count == 1
    assert result.failed_count == 0
    assert len(processor.calls) == 1
    assert commits == ["commit"]
    assert rollbacks == []


@pytest.mark.asyncio
async def test_worker_marks_failed_event_retryable_with_backoff() -> None:
    repository = FakeExternalEventRepository()
    await enqueue_inbound_message_event(
        event=_inbound_event(),
        external_event_repository=repository,
        now=NOW,
    )
    commits: list[str] = []
    rollbacks: list[str] = []

    result = await process_queued_inbound_message_events(
        queue_repository=_QueueRepository(repository),
        external_event_repository=repository,
        processor=_Processor(fail=True),
        commit=lambda: _record(commits, "commit"),
        rollback=lambda: _record(rollbacks, "rollback"),
        now=NOW,
    )

    assert result.failed_count == 1
    assert result.exhausted_count == 0
    assert rollbacks == ["rollback"]
    assert commits == ["commit"]
    saved = repository.events[(WORKSPACE_ID, "twilio", "evt-q-1")]
    assert saved.status is ExternalEventStatus.RETRYABLE_FAILURE
    assert saved.failure_reason == "queued_inbound_processing_failed"
    assert saved.next_retry_at == NOW + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_worker_exhausts_event_after_max_attempts() -> None:
    repository = FakeExternalEventRepository()
    await enqueue_inbound_message_event(
        event=_inbound_event(),
        external_event_repository=repository,
        now=NOW,
    )
    saved = repository.events[(WORKSPACE_ID, "twilio", "evt-q-1")]
    repository.events[(WORKSPACE_ID, "twilio", "evt-q-1")] = ExternalEvent(
        **{**saved.__dict__, "attempt_count": 2},
    )
    commits: list[str] = []

    result = await process_queued_inbound_message_events(
        queue_repository=_QueueRepository(repository),
        external_event_repository=repository,
        processor=_Processor(fail=True),
        commit=lambda: _record(commits, "commit"),
        rollback=lambda: _record([], "rollback"),
        now=NOW,
    )

    assert result.exhausted_count == 1
    assert result.failed_count == 0
    final = repository.events[(WORKSPACE_ID, "twilio", "evt-q-1")]
    assert final.status is ExternalEventStatus.EXHAUSTED
    assert final.processed_at == NOW
    assert final.next_retry_at is None


@pytest.mark.asyncio
async def test_worker_marks_invalid_payload_as_permanent_failure() -> None:
    repository = FakeExternalEventRepository()
    await repository.save(
        ExternalEvent(
            external_event_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            event_type="inbound_message.received",
            provider_event_id="evt-bad",
            crm_lead_id="crm-123",
            lead_id=None,
            received_at=NOW,
            processed_at=None,
            status=ExternalEventStatus.PENDING,
            payload_redacted={"event": "redacted"},
            failure_reason=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    processor = _Processor()
    commits: list[str] = []

    result = await process_queued_inbound_message_events(
        queue_repository=_QueueRepository(repository),
        external_event_repository=repository,
        processor=processor,
        commit=lambda: _record(commits, "commit"),
        rollback=lambda: _record([], "rollback"),
        now=NOW,
    )

    assert result.invalid_count == 1
    assert processor.calls == []
    saved = repository.events[(WORKSPACE_ID, "twilio", "evt-bad")]
    assert saved.status is ExternalEventStatus.PERMANENT_FAILURE
    assert saved.failure_reason == "queued_inbound_payload_invalid"
