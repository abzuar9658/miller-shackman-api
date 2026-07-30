from dataclasses import dataclass
from typing import Any

import pytest

from app.application.use_cases.crm_sync import EnqueueDueCRMSyncsResult
from app.core.config import Settings
from app.interfaces.workers import crm_sync_scheduler_worker


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = (exc_type, exc, tb)

    async def commit(self) -> None:
        self.committed = True


class _FakeCRMSyncJobRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def fail_stale_active_jobs(
        self,
        *,
        now: object,
        pending_timeout_seconds: int,
        running_timeout_seconds: int,
    ) -> int:
        self.calls.append(
            {
                "now": now,
                "pending_timeout_seconds": pending_timeout_seconds,
                "running_timeout_seconds": running_timeout_seconds,
            }
        )
        return 2


@dataclass
class _FakeLogger:
    records: list[tuple[str, dict[str, Any]]]

    def info(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))


async def test_run_once_logs_scheduler_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    job_repository = _FakeCRMSyncJobRepository()
    fake_logger = _FakeLogger([])

    async def fake_enable_postgres_service_access(_: object) -> None:
        return None

    async def fake_enqueue_due_follow_up_boss_crm_syncs(**_: object) -> EnqueueDueCRMSyncsResult:
        return EnqueueDueCRMSyncsResult(
            scanned_count=3,
            requested_count=1,
            skipped_disabled_count=0,
            skipped_automation_blocked_count=1,
            skipped_active_count=1,
            skipped_not_due_count=0,
        )

    monkeypatch.setattr(crm_sync_scheduler_worker, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "enable_postgres_service_access",
        fake_enable_postgres_service_access,
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "PostgresCRMSyncJobRepository",
        lambda _: job_repository,
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "PostgresWorkspaceCRMSyncConfigRepository",
        lambda _: "config-repository",
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "PostgresCRMSyncWindowStateRepository",
        lambda _: "window-state-repository",
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "PostgresOutboxEventRepository",
        lambda _: "outbox-repository",
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "PostgresTransactionalEventBus",
        lambda _: "event-bus",
    )
    monkeypatch.setattr(
        crm_sync_scheduler_worker,
        "enqueue_due_follow_up_boss_crm_syncs",
        fake_enqueue_due_follow_up_boss_crm_syncs,
    )
    monkeypatch.setattr(crm_sync_scheduler_worker, "logger", fake_logger)

    await crm_sync_scheduler_worker.run_once(settings=Settings())

    assert session.committed is True
    assert job_repository.calls[0]["pending_timeout_seconds"] == 600
    assert fake_logger.records == [
        (
            "crm_sync_scheduler_tick",
            {
                "stale_jobs_recovered": 2,
                "scanned_count": 3,
                "requested_count": 1,
                "skipped_disabled_count": 0,
                "skipped_automation_blocked_count": 1,
                "skipped_active_count": 1,
                "skipped_not_due_count": 0,
            },
        )
    ]
