from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.application.ports.crm_webhook import FollowUpBossWebhookEventResult
from app.application.use_cases.retry_external_events import retry_due_external_events
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
EVENT_ID = UUID("22222222-2222-2222-2222-222222222222")


def _event() -> ExternalEvent:
    return ExternalEvent(
        external_event_id=EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider="follow_up_boss",
        event_type="textMessagesCreated",
        provider_event_id="evt-1",
        crm_lead_id=None,
        lead_id=None,
        received_at=NOW,
        processed_at=None,
        status=ExternalEventStatus.RETRYABLE_FAILURE,
        payload_redacted={
            "eventId": "evt-1",
            "eventCreated": NOW.isoformat(),
            "event": "textMessagesCreated",
            "resourceIds": [1],
            "uri": "https://api.followupboss.com/v1/textMessages?id=1",
        },
        failure_reason="temporary",
        created_at=NOW,
        updated_at=NOW,
        attempt_count=1,
    )


class _Repository:
    async def claim_due_retryable(
        self,
        *,
        provider_name: str,
        now: datetime,
        limit: int = 10,
    ) -> tuple[ExternalEvent, ...]:
        assert provider_name == "follow_up_boss"
        assert now == NOW
        assert limit == 10
        return (_event(),)


class _Handler:
    def __init__(self, result: FollowUpBossWebhookEventResult | None = None) -> None:
        self.result = result or FollowUpBossWebhookEventResult(status="processed")
        self.calls: list[tuple[UUID, dict[str, Any], bool]] = []

    async def handle(
        self,
        workspace_id: UUID,
        payload: dict[str, Any],
        now: datetime,
        replay: bool = False,
    ) -> FollowUpBossWebhookEventResult:
        assert now == NOW
        self.calls.append((workspace_id, payload, replay))
        return self.result


@pytest.mark.asyncio
async def test_retry_worker_replays_and_commits_processed_event() -> None:
    handler = _Handler()
    commits: list[str] = []
    rollbacks: list[str] = []

    result = await retry_due_external_events(
        provider_name="follow_up_boss",
        external_event_repository=_Repository(),
        webhook_handler=handler,  # type: ignore[arg-type]
        commit=lambda: _record(commits),
        rollback=lambda: _record(rollbacks),
        now=NOW,
    )

    assert result.claimed_count == 1
    assert result.processed_count == 1
    assert handler.calls[0][2] is True
    assert commits == ["commit"]
    assert rollbacks == []


@pytest.mark.asyncio
async def test_retry_worker_surfaces_terminal_failure_without_retrying_again() -> None:
    handler = _Handler(FollowUpBossWebhookEventResult(status="exhausted"))
    commits: list[str] = []

    result = await retry_due_external_events(
        provider_name="follow_up_boss",
        external_event_repository=_Repository(),
        webhook_handler=handler,  # type: ignore[arg-type]
        commit=lambda: _record(commits),
        rollback=lambda: _record([]),
        now=NOW,
    )

    assert result.terminal_failure_count == 1
    assert commits == ["commit"]


async def _record(values: list[str]) -> None:
    values.append("commit")