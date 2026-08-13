"""Claim queued inbound message events and run the full processing pipeline.

The inbound message worker calls this on every poll cycle. Events are claimed
with FOR UPDATE SKIP LOCKED (safe for concurrent workers); each event is
processed and committed individually so one failure never blocks the batch.
Failures are recorded as retryable with exponential backoff until the attempt
budget is exhausted.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import structlog

from app.application.ports.repositories import (
    ExternalEventRepository,
    InboundMessageEventQueueRepository,
)
from app.application.use_cases.enqueue_inbound_message_event import (
    inbound_message_event_from_external_event,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventResult,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus

logger = structlog.get_logger(__name__)

InboundMessageEventProcessor = Callable[
    [InboundMessageEvent, ExternalEvent, datetime],
    Awaitable[ProcessInboundMessageEventResult],
]

_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = timedelta(seconds=30)
_RETRY_MAX_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class ProcessQueuedInboundMessageEventsResult:
    claimed_count: int
    processed_count: int
    invalid_count: int
    failed_count: int
    exhausted_count: int


async def process_queued_inbound_message_events(
    *,
    queue_repository: InboundMessageEventQueueRepository,
    external_event_repository: ExternalEventRepository,
    processor: InboundMessageEventProcessor,
    commit: Callable[[], Awaitable[None]],
    rollback: Callable[[], Awaitable[None]],
    now: datetime,
    limit: int = 10,
) -> ProcessQueuedInboundMessageEventsResult:
    events = await queue_repository.claim_due_queued_inbound_events(now=now, limit=limit)
    processed_count = 0
    invalid_count = 0
    failed_count = 0
    exhausted_count = 0
    for event in events:
        inbound_event = inbound_message_event_from_external_event(event)
        if inbound_event is None:
            await external_event_repository.save(
                replace(
                    event,
                    status=ExternalEventStatus.PERMANENT_FAILURE,
                    processed_at=now,
                    failure_reason="queued_inbound_payload_invalid",
                    updated_at=now,
                ),
            )
            await commit()
            invalid_count += 1
            logger.warning(
                "queued_inbound_event_payload_invalid",
                workspace_id=str(event.workspace_id),
                external_event_id=str(event.external_event_id),
                provider=event.provider,
            )
            continue
        try:
            result = await processor(inbound_event, event, now)
            await commit()
            processed_count += 1
            logger.info(
                "queued_inbound_event_processed",
                workspace_id=str(event.workspace_id),
                external_event_id=str(event.external_event_id),
                provider=event.provider,
                status=result.status.value,
                attempt_count=event.attempt_count,
            )
        except Exception:
            await rollback()
            exhausted = event.attempt_count >= _MAX_ATTEMPTS
            status = (
                ExternalEventStatus.EXHAUSTED
                if exhausted
                else ExternalEventStatus.RETRYABLE_FAILURE
            )
            next_retry_at = None
            if status is ExternalEventStatus.RETRYABLE_FAILURE:
                delay = min(
                    _RETRY_BASE_DELAY * (2 ** max(event.attempt_count - 1, 0)),
                    _RETRY_MAX_DELAY,
                )
                next_retry_at = now + delay
            await external_event_repository.save(
                replace(
                    event,
                    status=status,
                    processed_at=now if exhausted else None,
                    failure_reason="queued_inbound_processing_failed",
                    next_retry_at=next_retry_at,
                    updated_at=now,
                ),
            )
            await commit()
            if exhausted:
                exhausted_count += 1
            else:
                failed_count += 1
            logger.exception(
                "queued_inbound_event_processing_failed",
                workspace_id=str(event.workspace_id),
                external_event_id=str(event.external_event_id),
                provider=event.provider,
                attempt_count=event.attempt_count,
                status=status.value,
                next_retry_at=next_retry_at.isoformat() if next_retry_at else None,
            )

    return ProcessQueuedInboundMessageEventsResult(
        claimed_count=len(events),
        processed_count=processed_count,
        invalid_count=invalid_count,
        failed_count=failed_count,
        exhausted_count=exhausted_count,
    )
