# Gap Remediation Implementation Plan

**Source of truth for the gaps themselves:**
[`lead-lifecycle-feature-and-use-case-status.md`](./lead-lifecycle-feature-and-use-case-status.md)
— "Open architectural gaps" section (Gaps 1–7) and "Approved implementation plan" table.
This document is the *how*; that document is the *what/why*. If they ever disagree, the
status doc's Decision/Slice text wins and this file must be corrected to match.

**Status:** Slices 1, 2, 3, 4, and 5 implemented and validated. Admission outcomes are surfaced in
batch/tag reporting, terminal manual re-entry requires an explicit reason recorded in
transition metadata, and final outbound sends populate durable pre-send history facts.
Validation on 2026-08-09 passed Ruff, strict mypy, and the full test suite (1,259 passed;
2 skipped).

---

## Resolved decisions (previously open questions)

1. **Paused-search concurrency — resolved: one workflow, period.** A lead may hold exactly
   one active workflow at a time: either the dormant nurture workflow or a single
   paused-search workflow, never both and never several paused-search workflows. The
   partial unique index is therefore scoped to all non-terminal states with no
   paused-search exemption.
2. **Slice 1 enforcement mechanism — resolved: lock plus partial unique index.**
   Pessimistic lock via `get_latest_for_lead_for_update`, plus a partial unique DB index on
   `lead_workflows(workspace_id, lead_id)` covering non-terminal states. The lock alone
   leaves a first-enrollment race open because a brand-new lead has no row to lock. The
   starter maps the integrity violation onto the existing rejection status — no new error
   types or bespoke recovery paths.
3. **Slice 2 fail-closed behavior on lookup error — resolved: reuse
   `MISSING_REQUIRED_DATA`.** If a pre-send fact lookup cannot produce a reliable value,
   the send is blocked with the existing `PreSendReasonCode.MISSING_REQUIRED_DATA`, the
   same code the rule already emits for unknown data. No new status, no new exception
   class, no new operator surface.

**Reply handling is not an open question.** The reply ladder is already implemented and
bounded in `app/application/use_cases/evaluate_inbound_action.py`: rejected classification
→ pause for review; opt-out → suppress; human-requested / high-interest / seller-interest /
property-or-advice → handoff with reason; unclear → pause for review; not interested →
complete automation; otherwise → bounded AI continuation, capped at
`_MAX_AI_INTERACTION_TURNS` (5), after which the workflow pauses. No slice may change this
ladder.

---

## Slice 1 — Enrollment & re-entry safety (Gaps 1 + 3) — **implemented**

Delivered as: `app/domain/campaigns/enrollment_admission.py`
(`evaluate_lead_enrollment_admission`), enforced under the existing pessimistic lock in
`start_single_campaign_enrollment`; `LeadStartStatus` extended with
`ALREADY_ACTIVE_ELSEWHERE` and `TERMINAL_REQUIRES_MANUAL_ENROLLMENT`; partial unique index
`uq_lead_workflows_non_terminal_lead` added in migration
`0085_enforce_single_active_workflow_per_lead`; the dormant selector now excludes any lead
that already has a workflow row in the workspace, regardless of campaign. Batch and CRM-tag
results distinguish `ALREADY_ACTIVE_ELSEWHERE` from
`TERMINAL_REQUIRES_MANUAL_ENROLLMENT`. Manual terminal re-entry requires a non-blank reason;
the reason is stored as `manual_reentry_reason` in the workflow-transition audit metadata.

The `lead_manual_enrollment` path permission-checks the actor, requires a reason when the
latest workflow is terminal, and re-runs routing/consent before calling the starter; the
starter records the reason in the transition audit metadata.

**Chokepoint:** `start_single_campaign_enrollment` in
`app/application/services/campaign_enrollment_starter.py` — every enrollment path
(`start_selected_campaign_batch`, `start_paused_search_campaign_enrollment`,
`process_crm_tag_campaign_enrollment`, `lead_manual_enrollment`,
`start_selected_paused_search_track`) already funnels through it.

1. New pure domain rule in `app/domain/campaigns/` (name TBD, e.g.
   `evaluate_lead_enrollment_admission`) taking the lead's latest workflow, its
   terminal-ness, and whether the request source is automatic
   (`CRM_TAG`/`DORMANT_SELECTOR`) vs. explicit (`MANUAL_ADMIN`), returning an admission
   decision. Extend `LeadStartStatus` with `ALREADY_ACTIVE_ELSEWHERE` and
   `TERMINAL_REQUIRES_MANUAL_ENROLLMENT`.
2. Enforce under the existing pessimistic lock in the starter (per resolved decision 2).
3. Add the partial unique index via Alembic migration, covering all non-terminal states
   with no paused-search exemption (per resolved decisions 1 and 2).
4. Automatic sources are refused when the lead's latest workflow is terminal
   (`COMPLETED`/`SUPPRESSED`/`CLOSED`); `MANUAL_ADMIN` is allowed through with: a required
   reason, a `PermissionCapability` check (pattern already in `lead_manual_enrollment.py`),
   fresh consent/suppression/ownership/eligibility re-checks, and an audit/outbox record.
5. Widen `dormant_candidate_selector.py`'s "already enrolled" exclusion from
   `(workspace_id, campaign_id, lead_id)` to lead-scoped, so a lead active or terminal
   anywhere is excluded from automatic selection.

**Tests:** same-campaign re-enrollment stays idempotent; different-campaign automatic
enrollment is rejected; concurrent enrollment attempts produce exactly one active
workflow; each terminal state blocks automatic entry but allows admin-with-reason entry;
selector excludes a lead active or terminal elsewhere.

## Slice 2 — Pre-send fact population (Gap 2) — **implemented and validated**

1. Add repository lookups to `OutboundMessageRepository` for most-recent-sent timestamps
   (global / per-campaign / per-channel), plus `Handoff`/workflow-state lookups for
   `handoff_active`/`human_owned`, plus last-inbound-message timestamp for
   `lead_replied_since_scheduled`.
2. Wire these into the context builders in `campaign_cadence_execution.py` (both
   `PlanNextOutboundMessageContext` and `OutboundSendContext` construction) and
   `continue_ai_conversation_after_inbound.py`, before `PreSendFacts` is built.
3. Apply fail-closed behavior per resolved decision 3: an unavailable fact blocks the send
   with the existing `MISSING_REQUIRED_DATA` reason code.

Delivered on 2026-08-09: the shared final send path loads durable outbound history through
`load_pre_send_history_facts`, production cadence wiring supplies inbound history, and lookup
failures block provider dispatch with `MISSING_REQUIRED_DATA`. Direct inbound AI replies and
handoff acknowledgments retain their existing explicit policy exceptions for the global
frequency window; normal cadence and draft sends enforce the refreshed history.

**Tests:** a real frequency-limit block and a real simultaneous-channel block driven
through the cadence path (not just `evaluate_pre_send_safety` directly); a lookup failure
blocks the send instead of sending permissively.

## Slice 3 — Uncertain-send reconciliation for the dormant path (Gap 4)

1. New narrow record, e.g. `OutboundSendReconciliation`, keyed on the outbound message's
   idempotency key — deliberately separate from `RecurringOccurrence`, which carries
   paused-search-specific semantics (occurrence numbering, track steps) that don't apply
   to plain dormant/cadence sends.
2. On `UNCERTAIN` from the dormant/cadence path, persist the reconciliation record instead
   of going straight to `_pause_after_block` with no way back.
3. Extend `process_provider_delivery_callback.py` to resolve the record and wake the
   workflow when the provider confirms delivery (symmetric with the existing paused-search
   occurrence auto-resume).
4. Add a bounded timeout (mirroring `timeout_uncertain_paused_search_occurrence`) that
   fails the record out to an operator-visible state if the provider never confirms.
5. While a record is unresolved for a cadence step, no further send may dispatch for that
   step.

**Tests:** `UNCERTAIN` creates the record and blocks re-dispatch; a later delivery
callback resolves it and resumes the workflow; timeout fails it out for operator
resolution.

## Slice 4 — Durable provider failure handling (Gap 5)

1. Replace the single inline retry in `send_outbound_message.py` (`_send_sms`,
   `_send_email`) with bounded exponential backoff and an explicit maximum attempt count.
2. Persist retry attempt state on the outbound message so it survives process restarts.
3. Only `ProviderFailureKind.TEMPORARY` failures are retried; policy failures are never
   retried; `UNCERTAIN` routes to Slice 3's reconciliation record, not a retry loop.
4. Expose exhausted failures via a distinct, operator-visible exception surface — not
   merely a `PAUSED` workflow indistinguishable from a policy-based pause.

**Tests:** backoff/attempt-count bounds are enforced; policy failures are never retried;
exhausted retries surface distinctly from a policy pause; retry state survives a
simulated restart.

## Slice 5 — Selective CRM webhook retry (Gap 6)

1. Change `fetch_resource_by_uri` (and callers in
   `app/infrastructure/crm/follow_up_boss/webhook_event_mappers.py`) to classify a fetch
   failure as transient (retryable), permanent, or unknown, instead of collapsing every
   "no resource" case to `(0, 1)` → `IGNORED`.
2. Add `RETRYABLE_FAILURE` and a permanent-failure status to `ExternalEventStatus`
   (`app/domain/crm_sync.py`); persist failure reason, attempt count, and final
   disposition — Alembic migration required.
3. Replay retryable events through a durable worker with bounded backoff and a maximum
   attempt count. Rely on the existing
   `uq_external_events_workspace_provider_event` constraint so replay cannot duplicate
   side effects.
4. Exhausted or permanent failures surface for operator resolution instead of being
   silently recorded as `IGNORED`.

**Tests:** a transient fetch failure is retried and eventually succeeds; a permanent
failure is recorded terminal and not retried; an exhausted retryable failure surfaces for
an operator; replay does not duplicate side effects.

## Slice 6 — Durable Temporal dispatch boundary (Gap 7)

1. Persist the outbound send request and its idempotency key transactionally *before* the
   provider call (builds directly on Slice 3's reconciliation record).
2. Dispatch from a worker; reconcile provider status by idempotency key / provider message
   id; only then advance the Temporal workflow (`app/infrastructure/workflows/temporal/lead_nurture.py`,
   `campaign_cadence_execution.py`).
3. Recovery from a crash or unknown provider result always goes through reconciliation,
   never a blind re-dispatch — the send-once guarantee is enforced by the persisted
   idempotency key, not by workflow/activity retry timing.

**Tests:** simulated crash after provider dispatch but before durable recording does not
produce a duplicate send on recovery; reconciliation resolves the pending record correctly
in both success and failure outcomes.

### Operational exception surface

The durable dispatch boundary now has an authenticated read-only operator
surface at `/api/v1/workspaces/{workspace_id}/outbound-send-exceptions`. It
lists failed, uncertain, and stale dispatching requests with bounded filters
and returns safe operational metadata only. The existing frontend Attention
queue consumes the same contract and links each exception to its lead. The
surface deliberately has no retry or resolution command until provider
certainty and idempotent operator workflows are designed separately.

**Implemented:** migration `0089_create_outbound_send_requests.py` adds the durable request
boundary. Standard cadence and fallback sends enqueue transactionally; the dispatch worker
performs live CRM refresh plus locked final safety checks, records provider outcomes, and wakes
Temporal through the existing signal outbox. Stale in-flight requests become uncertain and enter
reconciliation without redispatch. Focused crash, retry, policy-change, persistence, and workflow
tests pass, and the full repository check passes with 1,280 tests passed and 2 skipped.

---

## Delivery discipline per slice (applies to all six)

Per `AGENTS.md` / `.augment/rules/rules.md`: explicit domain/application rules (not
prompt- or config-only), fresh permission/eligibility rechecks where relevant, idempotent
external behavior, an audit/outbox record for the decision, focused unit tests written
first or alongside the change, the smallest relevant test suite run first, then the full
regression suite before moving to the next slice.
