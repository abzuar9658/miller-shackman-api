from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from app.application.ports.crm import (
    CRMResourceFetchError,
    CRMResourceFetchFailureKind,
)
from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.infrastructure.crm.follow_up_boss import webhook_event_handler
from app.infrastructure.crm.follow_up_boss.webhook_event_handler import (
    FollowUpBossWebhookEventHandlerImpl,
)

NOW = datetime(2026, 7, 27, 18, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
EXTERNAL_EVENT_ID = UUID("22222222-2222-2222-2222-222222222222")


@dataclass
class _FakeLogger:
    records: list[tuple[str, str, dict[str, Any]]]

    def info(self, event: str, **kwargs: Any) -> None:
        self.records.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.records.append(("warning", event, kwargs))


class _FakeExternalEventRepository:
    def __init__(self, existing: ExternalEvent | None = None) -> None:
        self.existing = existing
        self.saved: list[ExternalEvent] = []

    async def get_by_provider_event_id(
        self,
        workspace_id: UUID,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        _ = (workspace_id, provider, provider_event_id)
        return self.existing

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.saved.append(event)
        self.existing = event
        return event


class _FailingCRMClient:
    def __init__(self, kind: CRMResourceFetchFailureKind) -> None:
        self.kind = kind

    async def fetch_resource_by_uri(self, workspace_id: UUID, uri: str) -> dict[str, Any]:
        _ = (workspace_id, uri)
        raise CRMResourceFetchError(self.kind, "fetch_failed")


def _existing_event() -> ExternalEvent:
    return ExternalEvent(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider="follow_up_boss",
        event_type="peopleUpdated",
        provider_event_id="evt-1",
        crm_lead_id=None,
        lead_id=None,
        received_at=NOW,
        processed_at=NOW,
        status=ExternalEventStatus.PROCESSED,
        payload_redacted={},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _payload(event: str) -> dict[str, object]:
    return {
        "eventId": "evt-1",
        "eventCreated": NOW.isoformat(),
        "event": event,
        "resourceIds": [1],
        "uri": "https://api.followupboss.com/v1/people?id=crm-123",
    }


async def test_logs_duplicate_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = _FakeLogger([])
    monkeypatch.setattr(webhook_event_handler, "logger", fake_logger)
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(
                external_event_repository=_FakeExternalEventRepository(_existing_event())
            ),
        )
    )

    result = await handler.handle(WORKSPACE_ID, _payload("peopleUpdated"), NOW)

    assert result.status == "duplicate"
    assert fake_logger.records == [
        (
            "info",
            "follow_up_boss_webhook_duplicate",
            {
                "workspace_id": str(WORKSPACE_ID),
                "provider_event_id": "evt-1",
                "event_type": "peopleUpdated",
            },
        )
    ]


async def test_logs_ignored_unknown_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = _FakeLogger([])
    monkeypatch.setattr(webhook_event_handler, "logger", fake_logger)
    repository = _FakeExternalEventRepository()
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(external_event_repository=repository),
        )
    )

    result = await handler.handle(WORKSPACE_ID, _payload("customEvent"), NOW)

    assert result.status == "ignored"
    assert fake_logger.records[0][1] == "follow_up_boss_webhook_ignored"
    assert fake_logger.records[0][2]["reasons"] == ["unsupported_event_type"]


async def test_logs_processed_people_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_logger = _FakeLogger([])
    monkeypatch.setattr(webhook_event_handler, "logger", fake_logger)

    async def fake_handle_people_event(*args: object) -> tuple[int, int]:
        _ = args
        return (1, 0)

    monkeypatch.setattr(webhook_event_handler, "handle_people_event", fake_handle_people_event)
    repository = _FakeExternalEventRepository()
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(external_event_repository=repository),
        )
    )

    result = await handler.handle(WORKSPACE_ID, _payload("peopleUpdated"), NOW)

    assert result.status == "processed"
    assert fake_logger.records[0][1] == "follow_up_boss_webhook_processed"
    assert fake_logger.records[0][2]["processed_count"] == 1


@pytest.mark.asyncio
async def test_transient_resource_fetch_failure_is_retryable_and_scheduled() -> None:
    repository = _FakeExternalEventRepository()
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(
                external_event_repository=repository,
                crm_client=_FailingCRMClient(CRMResourceFetchFailureKind.TRANSIENT),
            ),
        )
    )

    result = await handler.handle(WORKSPACE_ID, _payload("textMessagesCreated"), NOW)

    assert result.status == "retryable_failure"
    assert repository.saved[0].failure_kind is not None
    assert repository.saved[0].failure_kind.value == "transient"
    assert repository.saved[0].attempt_count == 1
    assert repository.saved[0].next_retry_at == NOW.replace(second=1)


@pytest.mark.asyncio
async def test_permanent_resource_fetch_failure_is_terminal() -> None:
    repository = _FakeExternalEventRepository()
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(
                external_event_repository=repository,
                crm_client=_FailingCRMClient(CRMResourceFetchFailureKind.PERMANENT),
            ),
        )
    )

    result = await handler.handle(WORKSPACE_ID, _payload("textMessagesCreated"), NOW)

    assert result.status == "permanent_failure"
    assert repository.saved[0].processed_at == NOW
    assert repository.saved[0].next_retry_at is None


@pytest.mark.asyncio
async def test_replay_updates_retryable_event_without_returning_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _FakeExternalEventRepository(
        replace(
            _existing_event(),
            status=ExternalEventStatus.RETRYABLE_FAILURE,
            attempt_count=2,
            next_retry_at=NOW,
        )
    )

    async def fake_handle_text_messages_created(*args: object) -> tuple[int, int]:
        _ = args
        return 1, 0

    monkeypatch.setattr(
        webhook_event_handler,
        "handle_text_messages_created",
        fake_handle_text_messages_created,
    )
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(external_event_repository=repository),
        )
    )

    result = await handler.handle(
        WORKSPACE_ID,
        _payload("textMessagesCreated"),
        NOW,
        replay=True,
    )

    assert result.status == "processed"
    assert repository.saved[-1].external_event_id == EXTERNAL_EVENT_ID
    assert repository.saved[-1].status is ExternalEventStatus.PROCESSED


@pytest.mark.asyncio
async def test_third_transient_failure_becomes_exhausted() -> None:
    repository = _FakeExternalEventRepository(
        replace(
            _existing_event(),
            status=ExternalEventStatus.RETRYABLE_FAILURE,
            attempt_count=3,
            next_retry_at=NOW,
        )
    )
    handler = FollowUpBossWebhookEventHandlerImpl(
        bundle=cast(
            FollowUpBossWebhookEventBundle,
            SimpleNamespace(
                external_event_repository=repository,
                crm_client=_FailingCRMClient(CRMResourceFetchFailureKind.TRANSIENT),
            ),
        )
    )

    result = await handler.handle(
        WORKSPACE_ID,
        _payload("textMessagesCreated"),
        NOW,
        replay=True,
    )

    assert result.status == "exhausted"
    assert repository.saved[-1].next_retry_at is None
