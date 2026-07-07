from typing import cast

import pytest
from temporalio.client import Client

from app.core.config import Settings
from app.infrastructure.workflows.temporal.smoke import SmokePingWorkflow, smoke_ping_activity
from app.infrastructure.workflows.temporal.worker import (
    build_temporal_worker,
    connect_temporal_client,
    run_temporal_worker,
)


async def test_smoke_ping_activity_returns_pong() -> None:
    assert await smoke_ping_activity() == "pong"


async def test_connect_temporal_client_uses_configured_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class FakeClient:
        @classmethod
        async def connect(cls, target_host: str) -> str:
            captured["target_host"] = target_host
            return "fake-client"

    monkeypatch.setattr("app.infrastructure.workflows.temporal.worker.Client", FakeClient)

    client = await connect_temporal_client(Settings(temporal_address="temporal.example:7233"))

    assert cast(str, client) == "fake-client"
    assert captured == {"target_host": "temporal.example:7233"}


def test_build_temporal_worker_registers_smoke_components(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeWorker:
        def __init__(
            self,
            client: object,
            *,
            task_queue: str,
            workflows: list[type[object]],
            activities: list[object],
        ) -> None:
            captured["client"] = client
            captured["task_queue"] = task_queue
            captured["workflows"] = workflows
            captured["activities"] = activities

    monkeypatch.setattr("app.infrastructure.workflows.temporal.worker.Worker", FakeWorker)

    client = cast(Client, object())
    worker = build_temporal_worker(
        client,
        Settings(temporal_task_queue="custom-task-queue"),
    )

    assert isinstance(worker, FakeWorker)
    assert captured == {
        "client": client,
        "task_queue": "custom-task-queue",
        "workflows": [SmokePingWorkflow],
        "activities": [smoke_ping_activity],
    }


async def test_run_temporal_worker_connects_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        temporal_address="temporal.example:7233",
        temporal_task_queue="custom-task-queue",
    )
    captured: dict[str, object] = {}

    class FakeWorker:
        async def run(self) -> None:
            captured["ran"] = True

    async def fake_connect_temporal_client(received_settings: Settings) -> object:
        captured["connect_settings"] = received_settings
        return "fake-client"

    def fake_build_temporal_worker(client: object, received_settings: Settings) -> FakeWorker:
        captured["client"] = client
        captured["build_settings"] = received_settings
        return FakeWorker()

    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.worker.connect_temporal_client",
        fake_connect_temporal_client,
    )
    monkeypatch.setattr(
        "app.infrastructure.workflows.temporal.worker.build_temporal_worker",
        fake_build_temporal_worker,
    )

    await run_temporal_worker(settings)

    assert captured["connect_settings"] is settings
    assert captured["client"] == "fake-client"
    assert captured["build_settings"] is settings
    assert captured["ran"] is True
