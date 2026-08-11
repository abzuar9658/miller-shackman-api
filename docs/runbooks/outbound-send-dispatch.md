# Outbound Send Dispatch Operations

The outbound-send dispatcher is the only process that calls the SMS and email
providers for standard cadence and fallback sends. Temporal activities enqueue
durable requests; the dispatcher claims and revalidates them before provider
dispatch.

## Metrics

When `METRICS_ENABLED=true`, the API exposes Prometheus text format at:

`GET /api/v1/metrics`

The standalone dispatcher exposes its own process registry at `GET /metrics`
on `OUTBOUND_SEND_DISPATCH_METRICS_HOST` and
`OUTBOUND_SEND_DISPATCH_METRICS_PORT`. The local Compose stack publishes this
as `http://localhost:9101/metrics`. Prometheus must scrape the dispatcher
endpoint to observe worker counters; the API and worker do not share memory.

The endpoint is intentionally not part of the public API schema. Keep it on a
private network or protect it at the ingress/reverse-proxy layer. It contains
aggregate operational counts and timestamps, not lead IDs, contact details,
message bodies, provider payloads, or workspace identifiers.

Important metrics include:

- `miller_schackman_outbound_send_dispatch_cycles_total`
- `miller_schackman_outbound_send_dispatch_cycle_failures_total`
- `miller_schackman_outbound_send_dispatch_requests_total{outcome="..."}`
- `miller_schackman_outbound_send_dispatch_pending_requests`
- `miller_schackman_outbound_send_dispatch_oldest_pending_age_seconds`
- `miller_schackman_outbound_send_dispatch_last_cycle_timestamp_seconds`
- `miller_schackman_outbound_send_dispatch_last_success_timestamp_seconds`
- `miller_schackman_outbound_send_dispatch_cycle_duration_seconds`

The `outcome` label is a fixed, low-cardinality set: `recovered_uncertain`,
`claimed`, `sent`, `retry_scheduled`, `policy_rejected`, `failed`, and
`uncertain`. Do not add lead, workflow, workspace, provider-error, or request
IDs as metric labels.

## Suggested alerts

Tune thresholds to the deployment's normal traffic, but start with:

1. **Worker stopped:** no increase in `..._cycles_total` for three polling
   intervals, or the last successful cycle timestamp is older than five minutes.
2. **Cycle failures:** `..._cycle_failures_total` increases over a five-minute
   window.
3. **Queue aging:** `..._oldest_pending_age_seconds` is above the agreed send
   SLO for five minutes.
4. **Uncertain sends:** the rate of `outcome="uncertain"` is non-zero and
   requires reconciliation review; never resolve these by blindly replaying the
   request.
5. **Provider failures:** `outcome="failed"` or `outcome="retry_scheduled"`
   increases materially above the deployment baseline.

## Triage procedure

1. Check API and dispatcher logs for `outbound_send_dispatch_cycle_failed`,
   `outbound_send_dispatch_worker_stopped`, and
   `outbound_send_dispatch_queue_metrics_failed`.
2. Check the last successful cycle timestamp and due queue age.
3. If the worker process stopped, restart the dispatcher using
   `make outbound-send-dispatcher` or the deployment's process supervisor.
4. If provider calls are failing, verify provider configuration and external
   provider status before changing retry settings.
5. Treat `uncertain` requests as send-once records. Resolve them through the
   existing provider callback/reconciliation process; do not manually reset a
   request to `pending`.
6. If policy rejections increase, investigate current CRM activity, consent,
   suppression, ownership, campaign, and quiet-hours data. Policy rejections
   are safety outcomes, not provider retry failures.

## Admin exception queue

Managers, brokerage admins, and platform operations admins can review durable
send exceptions in the authenticated workspace Attention queue. The backend
read contract is:

- `GET /api/v1/workspaces/{workspace_id}/outbound-send-exceptions`
- `GET /api/v1/workspaces/{workspace_id}/outbound-send-exceptions/{request_id}`

The list includes terminal `failed` and `uncertain` requests plus
`dispatching` requests older than 15 minutes. Operators can filter by status,
channel, provider, age, and bounded page size. Responses include request,
lead, workflow, reconciliation, provider, attempt, timestamp, and failure
metadata, but never message bodies, destinations, or provider payloads.

The Attention item is intentionally read-only. Acknowledging it records that
the exception was reviewed; it does not resolve the provider failure and does
not authorize a retry. For `uncertain` requests, follow the provider callback
or reconciliation process above and never reset the durable request to
`pending` or manually replay it.

## Local verification

1. Copy `.env.example` to `.env` and keep `METRICS_ENABLED=true`.
2. Run `make infra-up`. Compose applies migrations and starts the API,
   dispatcher, Prometheus, and Grafana with the supporting infrastructure.
3. Open the provisioned Grafana dashboard at
   `http://localhost:3000/d/outbound-send-dispatch/outbound-send-dispatch-operations`.
4. Check Prometheus targets at `http://localhost:9090/targets`; both
   `miller-schackman-api` and `outbound-send-dispatcher` should be up.
5. Verify raw worker metrics at `http://localhost:9101/metrics` and API metrics
   at `http://localhost:8000/api/v1/metrics`.
6. Use `make infra-logs` for API, dispatcher, Prometheus, and Grafana logs, and
   `make infra-down` to stop the stack.

The Compose dispatcher forces sink SMS and email providers, so routine local
monitoring does not call real messaging providers. Grafana uses anonymous
viewer access for local development only. Do not expose ports 3000, 9090, or
9101 publicly; production deployments must use authenticated, private
monitoring infrastructure.