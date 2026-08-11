from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from prometheus_client import CollectorRegistry

from app.application.ports.messaging import EmailProvider, SMSProvider
from app.application.use_cases.dispatch_outbound_send_requests import (
    DispatchOutboundSendRequestsResult,
)
from app.core.config import Settings
from app.core.metrics import OutboundSendDispatchMetrics, outbound_send_dispatch_metrics
from app.interfaces.workers import outbound_send_dispatch_worker as worker

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)


def _result() -> DispatchOutboundSendRequestsResult:
    return DispatchOutboundSendRequestsResult(
        recovered_uncertain_count=1,
        claimed_count=2,
        sent_count=1,
        retry_scheduled_count=1,
        policy_rejected_count=0,
        failed_count=0,
        uncertain_count=0,
    )


def test_start_metrics_http_server_exposes_dispatcher_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, str, object]] = []

    def fake_start_http_server(
        port: int,
        addr: str,
        registry: object,
    ) -> tuple[object, object]:
        calls.append((port, addr, registry))
        return object(), object()

    monkeypatch.setattr(worker, "start_http_server", fake_start_http_server)
    settings = Settings(
        metrics_enabled=True,
        outbound_send_dispatch_metrics_host="0.0.0.0",
        outbound_send_dispatch_metrics_port=9101,
    )

    worker.start_metrics_http_server(settings)

    assert calls == [(9101, "0.0.0.0", outbound_send_dispatch_metrics.registry)]


def test_start_metrics_http_server_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*_: object, **__: object) -> None:
        raise AssertionError("metrics server should not start")

    monkeypatch.setattr(worker, "start_http_server", fail_if_called)

    worker.start_metrics_http_server(Settings(metrics_enabled=False))


async def test_run_once_records_successful_cycle_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = OutboundSendDispatchMetrics(CollectorRegistry())
    monkeypatch.setattr(worker, "outbound_send_dispatch_metrics", metrics)

    async def fake_run_once(
        **kwargs: object,
    ) -> tuple[DispatchOutboundSendRequestsResult, int, datetime]:
        _ = kwargs
        return _result(), 3, NOW - timedelta(seconds=45)

    monkeypatch.setattr(worker, "_run_once", fake_run_once)

    await worker.run_once(
        sms_provider=cast(SMSProvider, object()),
        email_provider=cast(EmailProvider, object()),
        settings=Settings(metrics_enabled=True),
    )

    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_cycles_total"
    ) == 1.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_requests_total",
        {"outcome": "recovered_uncertain"},
    ) == 1.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_pending_requests"
    ) == 3.0


async def test_run_once_records_failure_metrics_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = OutboundSendDispatchMetrics(CollectorRegistry())
    monkeypatch.setattr(worker, "outbound_send_dispatch_metrics", metrics)

    async def failing_run_once(
        **kwargs: object,
    ) -> tuple[DispatchOutboundSendRequestsResult, int, datetime]:
        _ = kwargs
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(worker, "_run_once", failing_run_once)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await worker.run_once(
            sms_provider=cast(SMSProvider, object()),
            email_provider=cast(EmailProvider, object()),
            settings=Settings(metrics_enabled=True),
        )

    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_cycle_failures_total"
    ) == 1.0