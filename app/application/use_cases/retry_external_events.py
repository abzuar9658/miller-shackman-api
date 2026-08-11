from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from app.application.ports.crm_webhook import FollowUpBossWebhookEventHandler
from app.application.ports.repositories import ExternalEventRetryRepository


@dataclass(frozen=True)
class RetryExternalEventsResult:
    claimed_count: int
    processed_count: int
    terminal_failure_count: int
    failed_count: int


async def retry_due_external_events(
    *,
    provider_name: str,
    external_event_repository: ExternalEventRetryRepository,
    webhook_handler: FollowUpBossWebhookEventHandler,
    commit: Callable[[], Awaitable[None]],
    rollback: Callable[[], Awaitable[None]],
    now: datetime,
    limit: int = 10,
) -> RetryExternalEventsResult:
    events = await external_event_repository.claim_due_retryable(
        provider_name=provider_name,
        now=now,
        limit=limit,
    )
    processed_count = 0
    terminal_failure_count = 0
    failed_count = 0
    for event in events:
        try:
            result = await webhook_handler.handle(
                event.workspace_id,
                event.payload_redacted,
                now,
                replay=True,
            )
            await commit()
        except Exception:
            await rollback()
            failed_count += 1
            continue

        if result.status == "processed":
            processed_count += 1
        elif result.status in {"permanent_failure", "exhausted"}:
            terminal_failure_count += 1

    return RetryExternalEventsResult(
        claimed_count=len(events),
        processed_count=processed_count,
        terminal_failure_count=terminal_failure_count,
        failed_count=failed_count,
    )