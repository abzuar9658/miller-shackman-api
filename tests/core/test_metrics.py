from datetime import UTC, datetime, timedelta

from prometheus_client import CollectorRegistry

from app.core.metrics import OutboundSendDispatchMetrics

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)


def test_dispatch_metrics_record_outcomes_and_queue_age() -> None:
    metrics = OutboundSendDispatchMetrics(CollectorRegistry())

    metrics.record_cycle(
        now=NOW,
        elapsed_seconds=0.25,
        recovered_uncertain_count=1,
        claimed_count=3,
        sent_count=1,
        retry_scheduled_count=1,
        policy_rejected_count=1,
        failed_count=0,
        uncertain_count=0,
        pending_count=4,
        oldest_pending_at=NOW - timedelta(seconds=90),
    )

    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_cycles_total"
    ) == 1.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_requests_total",
        {"outcome": "sent"},
    ) == 1.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_pending_requests"
    ) == 4.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_oldest_pending_age_seconds"
    ) == 90.0


def test_dispatch_metrics_record_cycle_failure_without_success_timestamp() -> None:
    metrics = OutboundSendDispatchMetrics(CollectorRegistry())

    metrics.record_failure(now=NOW, elapsed_seconds=0.5)

    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_cycle_failures_total"
    ) == 1.0
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_last_cycle_timestamp_seconds"
    ) == NOW.timestamp()
    assert metrics.registry.get_sample_value(
        "miller_schackman_outbound_send_dispatch_last_success_timestamp_seconds"
    ) == 0.0