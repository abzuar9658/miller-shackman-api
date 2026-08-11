# Gap Remediation Progress

This ledger tracks delivery against
[`gap-remediation-implementation-plan.md`](./gap-remediation-implementation-plan.md) and
[`lead-lifecycle-feature-and-use-case-status.md`](./lead-lifecycle-feature-and-use-case-status.md).
The status document wins if the documents disagree.

## Delivery rules

- Complete one slice before implementing the next.
- Mark a criterion complete only with code and test evidence.
- Record blocked validation separately from passing validation.
- Preserve V1 scope: no dynamic rules engine, scoring, or unrelated policy hardening.
- A2P 10DLC approval gating is explicitly out of V1 scope by product decision.

## Status summary

| Slice | Gaps | Status | Validation |
|---|---:|---|---|
| 1 — Enrollment and re-entry safety | 1, 3 | Complete | `make check` passed |
| 2 — Pre-send fact population | 2 | Complete | `make check` passed |
| 3 — Uncertain-send reconciliation | 4 | Complete | `make check` passed |
| 4 — Durable provider failure handling | 5 | Complete | `make check` passed |
| 5 — Selective CRM webhook retry | 6 | Complete | `make check` passed (1,259 passed, 2 skipped) |
| 6 — Durable Temporal dispatch boundary | 7 | Complete | `make check` passed (1,280 passed, 2 skipped) |

## Slice 1 — Enrollment and re-entry safety

### Acceptance criteria

- [x] Domain admission decision distinguishes same-campaign active, active elsewhere,
  terminal automatic re-entry, and permitted explicit re-entry.
- [x] Admission runs after the existing lead-scoped pessimistic lookup.
- [x] A partial unique index prevents more than one non-terminal workflow per lead.
- [x] A first-enrollment race returns `ALREADY_ENROLLED` or
  `ALREADY_ACTIVE_ELSEWHERE`, never generic `FAILED`, and leaves no orphan enrollment.
- [x] Only `MANUAL_ADMIN` may re-enter after `COMPLETED`, `SUPPRESSED`, or `CLOSED`.
- [x] Every terminal admin re-entry requires a non-blank reason at the shared starter.
- [x] The reason is stored as `manual_reentry_reason` in transition metadata.
- [x] Automatic dormant and CRM-tag paths cannot re-enter a terminal lead.
- [x] The dormant selector excludes leads with any prior workflow in the workspace.
- [x] Focused domain, application, API, and PostgreSQL concurrency tests pass.
- [x] Lint and type checking pass for changed files.

### Scope guardrails

- No configurable cooldown is added; terminal workflows require explicit admin action.
- Assigned-agent resume remains separate from terminal campaign re-enrollment.
- Initial assigned-agent enrollment remains unchanged when campaign policy allows it.
- No new workflow states or generic enrollment framework are introduced.

### Evidence and validation log

- Existing migration: `0085_enforce_single_active_workflow_per_lead.py`.
- Existing admission rule: `app/domain/campaigns/enrollment_admission.py`.
- 2026-08-09: deep audit found missing race mapping and starter-level reason enforcement;
  Slice 1 reopened until those criteria and admin-only terminal re-entry are validated.
- 2026-08-09: the shared starter now rolls back a losing database transaction, reloads the
  winning workflow, and returns `ALREADY_ENROLLED` or `ALREADY_ACTIVE_ELSEWHERE`.
- 2026-08-09: terminal re-entry is admin-only and requires a non-blank API/starter reason;
  selected paused-search and standard manual-enrollment paths preserve that rule.
- 2026-08-09: CRM-tag and dormant paths surface terminal/manual-entry outcomes distinctly.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 562 source files,
  1,244 tests passed, and 2 tests skipped.

## Slice 2 — Pre-send fact population

### Current implementation

- [x] The final automated-send path loads fresh global, campaign, channel, and other-channel
  sent timestamps from durable outbound-message history.
- [x] The final automated-send path loads the latest inbound timestamp when the inbound
  repository is supplied for scheduled messages and compares it with the scheduled timestamp.
- [x] Current `HUMAN_HANDOFF` and `HUMAN_OWNED` workflow states populate the corresponding
  human-control facts at send time.
- [x] History lookup failures produce `MISSING_REQUIRED_DATA` and prevent provider dispatch.
- [x] Existing inbound AI continuation behavior remains explicit: the direct reply may send
  without the global 24-hour cadence window; normal cadence and draft sends retain it.
- [x] Production Temporal cadence wiring supplies the inbound-message repository.
- [x] Send-path coverage proves a lead with no prior sent history can send, a prior send inside
  the global window is blocked, and a history lookup failure is fail closed.

### Remaining validation

- [x] A PostgreSQL send-history query test covers global, campaign, channel, pending-message,
  and workspace-isolation scopes.
- [x] The complete repository check passed and all six production `send_outbound_message`
  callers were inspected.
- [x] Draft review, cadence, inbound continuation, and handoff acknowledgment all use the
  shared final send path. Handoff acknowledgments and direct AI replies retain their existing
  explicit frequency-window exceptions.

### Evidence and validation log

- 2026-08-09: `send_outbound_message` now refreshes history immediately before pre-send
  evaluation through `load_pre_send_history_facts`; provider dispatch is blocked when the
  supplied history lookup raises or cannot produce required data. Existing direct callers
  without inbound history retain their prior behavior; production cadence wiring supplies it.
- 2026-08-09: focused tests covered no prior activity, a prior send inside the 24-hour global
  window, and lookup failure; PostgreSQL scope queries also passed.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 563 source files,
  1,247 tests passed, and 2 tests skipped.

## Slice 3 — Uncertain-send reconciliation for the dormant path

### Current implementation

- [x] A narrow `OutboundSendReconciliation` record is keyed by workspace and outbound-message
  idempotency key, separate from paused-search occurrence records.
- [x] Standard dormant/cadence `UNCERTAIN` sends persist a pending reconciliation with the
  workflow and Temporal workflow identifiers needed for recovery.
- [x] An unresolved outbound message remains non-dispatchable; retries return the existing
  reconciliation identifier and do not call the provider again.
- [x] Provider delivery callbacks can resolve a reconciliation as confirmed or failed and
  confirmed delivery wakes the waiting workflow through the transactional Temporal signal outbox.
- [x] The standard cadence workflow applies a bounded 24-hour timeout and records
  `TIMED_OUT` with an operator-visible failure reason rather than redispatching.

### Scope guardrails

- Paused-search occurrence reconciliation remains unchanged and continues using its existing
  occurrence-specific timeout and touch-count rules.
- No new workflow state or automatic retry after timeout is introduced.
- Provider callbacks only resolve a pending reconciliation; duplicate callbacks and already
  resolved records do not reopen or redispatch the message.

### Evidence and validation log

- 2026-08-09: Added the durable reconciliation domain record, PostgreSQL model/repository,
  migration `0086_create_outbound_send_reconciliations.py`, cadence wiring, callback resolution,
  and Temporal timeout activity.
- 2026-08-09: Focused tests passed for durable creation, retry/no-duplicate behavior, callback
  confirmation and workflow wake-up, and idempotent timeout handling.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 568 source files,
  1,250 tests passed, and 2 tests skipped.

## Slice 4 — Durable provider failure handling

### Acceptance criteria

- [x] Temporary provider failures use bounded exponential backoff with a maximum of three
  provider attempts.
- [x] Attempt count, last attempt time, next retry time, and failure kind are persisted on the
  outbound message and survive a simulated restart.
- [x] Permanent failures are not retried; uncertain outcomes continue through Slice 3
  reconciliation rather than entering the retry loop.
- [x] Exhausted/permanent provider failures create a distinct durable operator-review record,
  and cadence pauses use `provider_failure_exhausted` rather than a generic policy pause.

### Evidence and validation log

- 2026-08-09: Added migration `0087_add_provider_failure_state.py`, outbound attempt-state
  columns, `OutboundProviderFailure` persistence, and cadence/Temporal wiring.
- 2026-08-09: Added tests for temporary retry bounds, attempt persistence, permanent-failure
  review records, and restart-safe exhausted failures.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 568 source files,
  1,250 tests passed, and 2 tests skipped.

## Slice 5 — Selective CRM webhook retry

### Acceptance criteria

- [x] Follow Up Boss resource fetches classify transient, permanent, and unknown failures.
- [x] Retryable, permanent, and exhausted external-event dispositions persist failure reason,
  failure kind, attempt count, and next retry time.
- [x] Retryable envelopes replay through a durable worker with a maximum of three attempts and
  row-lock claiming; terminal failures remain operator-visible.
- [x] Replay updates the original event and preserves provider-event idempotency, so child
  side effects are not duplicated.

### Evidence and validation log

- 2026-08-09: Added migration `0088_extend_external_event_retry.py`, retry metadata on
  `ExternalEvent`, and provider fetch failure classification.
- 2026-08-09: Added `retry_external_events` and the `crm_webhook_retry_worker` with bounded
  replay, row-lock claiming, and a Makefile target.
- 2026-08-09: Focused webhook, provider-client, replay, and persistence tests passed.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 571 source files,
  1,259 tests passed, and 2 tests skipped.

## Slice 6 — Durable Temporal dispatch boundary

### Acceptance criteria

- [x] Standard cadence and fallback sends persist a complete `OutboundSendRequest` and pending
  reconciliation transactionally before returning control to Temporal.
- [x] Provider calls run only in the dispatch worker after live CRM refresh and locked current
  policy, workflow, consent, suppression, history, quiet-hours, ownership, and payload checks.
- [x] Due requests are claimed with `FOR UPDATE SKIP LOCKED`; known temporary failures use a
  bounded three-attempt backoff and re-run all pre-dispatch checks before each attempt.
- [x] Success, terminal failure, and uncertain outcomes update the request, outbound message,
  reconciliation, operator failure record where applicable, and durable Temporal signal outbox.
- [x] A stale `DISPATCHING` request becomes `UNCERTAIN` and is never blindly redispatched.
- [x] Temporal waits on `DISPATCH_PENDING`, resumes through the existing durable signal, and
  advances through the idempotent `ALREADY_SENT` path only after durable provider confirmation.

### Operational readiness follow-up

- [x] Add opt-in Prometheus metrics, worker lifecycle logging, queue-age gauges,
  and an outbound dispatch runbook.
- [x] Add a permission-checked, read-only admin exception surface for failed,
  uncertain, and stale dispatching durable send requests.
- [x] Add the exceptions to the frontend Attention queue with lead links and
  safe context details; no blind retry or resolution command is exposed.
- [x] Temporal activity retries are safe after a commit-before-ack crash because enqueue uses the
  workspace-scoped idempotent request record and no longer owns the provider side effect.

### Evidence and validation log

- 2026-08-09: Added migration `0089_create_outbound_send_requests.py`, tenant-isolated request
  persistence, row-lock claiming, stale-dispatch recovery, worker configuration, and local worker
  start/stop wiring.
- 2026-08-09: Extracted shared live CRM refresh and pre-send policy services so enqueue/direct
  sends and dispatch-worker attempts apply the same fail-closed safety behavior.
- 2026-08-09: Added tests for transactional enqueue and idempotency, worker success, bounded
  retries, permanent and uncertain failures, post-enqueue CRM activity/opt-out, paused workflows,
  real PostgreSQL claim/recovery behavior, Temporal wake-up, and crash recovery without duplicate
  provider calls.
- 2026-08-09: `make check` passed: Ruff clean, strict mypy clean across 581 source files,
  1,280 tests passed, and 2 tests skipped.
