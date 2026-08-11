from datetime import datetime

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)


class OutboundSendDispatchMetrics:
    """Prometheus instruments for the durable outbound-send dispatcher."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.cycles = Counter(
            "miller_schackman_outbound_send_dispatch_cycles",
            "Completed outbound-send dispatch cycles.",
            registry=self.registry,
        )
        self.cycle_failures = Counter(
            "miller_schackman_outbound_send_dispatch_cycle_failures",
            "Outbound-send dispatch cycles that raised an exception.",
            registry=self.registry,
        )
        self.requests = Counter(
            "miller_schackman_outbound_send_dispatch_requests",
            "Outbound-send requests handled by outcome.",
            labelnames=("outcome",),
            registry=self.registry,
        )
        self.pending_requests = Gauge(
            "miller_schackman_outbound_send_dispatch_pending_requests",
            "Due pending outbound-send requests awaiting dispatch.",
            registry=self.registry,
        )
        self.oldest_pending_age = Gauge(
            "miller_schackman_outbound_send_dispatch_oldest_pending_age_seconds",
            "Age of the oldest due pending outbound-send request.",
            registry=self.registry,
        )
        self.last_cycle_timestamp = Gauge(
            "miller_schackman_outbound_send_dispatch_last_cycle_timestamp_seconds",
            "Unix timestamp of the last completed dispatch cycle.",
            registry=self.registry,
        )
        self.last_success_timestamp = Gauge(
            "miller_schackman_outbound_send_dispatch_last_success_timestamp_seconds",
            "Unix timestamp of the last dispatch cycle without an exception.",
            registry=self.registry,
        )
        self.cycle_duration = Histogram(
            "miller_schackman_outbound_send_dispatch_cycle_duration_seconds",
            "Duration of outbound-send dispatch cycles.",
            registry=self.registry,
        )

    def record_cycle(
        self,
        *,
        now: datetime,
        elapsed_seconds: float,
        recovered_uncertain_count: int,
        claimed_count: int,
        sent_count: int,
        retry_scheduled_count: int,
        policy_rejected_count: int,
        failed_count: int,
        uncertain_count: int,
        pending_count: int | None,
        oldest_pending_at: datetime | None,
    ) -> None:
        self.cycles.inc()
        self.cycle_duration.observe(elapsed_seconds)
        self.last_cycle_timestamp.set(now.timestamp())
        self.last_success_timestamp.set(now.timestamp())
        for outcome, count in (
            ("recovered_uncertain", recovered_uncertain_count),
            ("claimed", claimed_count),
            ("sent", sent_count),
            ("retry_scheduled", retry_scheduled_count),
            ("policy_rejected", policy_rejected_count),
            ("failed", failed_count),
            ("uncertain", uncertain_count),
        ):
            self.requests.labels(outcome=outcome).inc(count)
        if pending_count is not None:
            self.pending_requests.set(pending_count)
            age = 0.0
            if oldest_pending_at is not None:
                age = max(0.0, (now - oldest_pending_at).total_seconds())
            self.oldest_pending_age.set(age)

    def record_failure(self, *, now: datetime, elapsed_seconds: float) -> None:
        self.cycle_failures.inc()
        self.cycle_duration.observe(elapsed_seconds)
        self.last_cycle_timestamp.set(now.timestamp())


outbound_send_dispatch_metrics = OutboundSendDispatchMetrics()