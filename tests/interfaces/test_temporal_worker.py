from pytest import MonkeyPatch

from app.core.config import Settings
from app.interfaces.workers.temporal_worker import main


async def test_temporal_worker_main_configures_logging_and_runs(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = Settings(log_level="DEBUG")
    captured: dict[str, object] = {}

    def fake_configure_logging(log_level: str) -> None:
        captured["log_level"] = log_level

    async def fake_run_temporal_worker(received_settings: Settings) -> None:
        captured["settings"] = received_settings

    monkeypatch.setattr("app.interfaces.workers.temporal_worker.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.interfaces.workers.temporal_worker.configure_logging",
        fake_configure_logging,
    )
    monkeypatch.setattr(
        "app.interfaces.workers.temporal_worker.run_temporal_worker",
        fake_run_temporal_worker,
    )

    await main()

    assert captured == {
        "log_level": "DEBUG",
        "settings": settings,
    }
