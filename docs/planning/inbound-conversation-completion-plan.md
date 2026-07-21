# Inbound Conversation Completion Plan

## Purpose

This document defines the remaining work needed to finish the Phase One inbound
conversation flow so the system can safely decide whether AI should continue,
pause for review, suppress outreach, or hand the lead to a human agent.

It builds on the existing outbound delivery, inbound capture, reply
classification, workflow persistence, and handoff foundations already present in
the backend.

## Current baseline

Already implemented:

- outbound message drafting, planning, sending, and provider delivery updates
- inbound reply receipt for Follow Up Boss, Twilio SMS, and SendGrid email
- inbound message persistence, duplicate-event handling, and conversation linkage
- reply classification, summary generation, preference extraction, and opt-out
  override handling
- persisted workflow transitions for pause and handoff states
- handoff record creation, CRM note/tag updates, and agent notification

Still missing or incomplete:

- fuller resume and recovery alignment across review, handoff, and safe
  continuation states
- turn-cap enforcement and richer decision audit trails for multi-turn AI chats
- broader end-to-end coverage for continue, review, suppress, and race
  conditions

## Target business outcome

The finished flow should support this sequence safely:

1. AI sends an outbound message.
2. The lead replies by SMS or email.
3. The system stores the inbound event idempotently.
4. The system syncs the inbound reply back to the correct CRM lead record.
5. The system evaluates the reply.
6. The application decides one of four outcomes:
   - continue AI conversation
   - hand off to agent
   - pause for human review
   - suppress future outreach
7. Review or handoff cases are made visible in the CRM so agents can act there
   with minimal need to use this application.
8. The durable workflow and Postgres state stay consistent and auditable.

For review-driven cases, the assigned agent should be able to understand that a
lead needs attention directly from the CRM via tags, notes, or both, with tag
names configured by brokerage admins.

## Recommended implementation approach

Keep the webhook-driven application use case as the authoritative owner of
inbound orchestration for the current implementation slices.

- Webhooks should validate payloads, resolve the lead, and call a single
  application use case for inbound processing.
- `process_inbound_message_event` should remain the one authoritative place for
  classification, deterministic decisioning, workflow transitions, handoff
  creation, and CRM sync side effects.
- The inbound CRM sync path should always target the correct CRM lead identifier
  and remain the authoritative place for posting inbound reply notes back to the
  CRM and applying review tags.
- Temporal should continue owning cadence timing and outbound execution, but it
  should not apply a second inbound workflow transition path for the same reply.

This keeps inbound decision-making explicit and auditable in Postgres while the
durable workflow remains responsible for cadence execution and pause/resume
coordination.

## Current implementation status

Status snapshot as of 2026-07-19:

| Phase | Status | Summary |
| --- | --- | --- |
| 1 — deterministic inbound decision policy | complete | The application now derives `continue_ai`, `human_handoff`, `pause_for_review`, and `suppress` from explicit rules over structured classification evidence rather than classifier-supplied handoff verdicts. |
| 2 — inbound orchestration ownership cleanup | complete | `process_inbound_message_event` is the sole authoritative inbound orchestrator for classification, transition, handoff, and CRM sync side effects. |
| 3 — inbound reply signaling into Temporal | complete | `inbound-processed` exists as a lightweight runtime signal that blocks sends without applying a second workflow-state mutation. |
| 4 — durable Temporal signal coordination | complete | All current Temporal signals are delivered through the Postgres-backed outbox and Temporal signal handlers are runtime-only. |
| 5 — real AI continuation branch | complete | `continue_ai` now drafts and sends a conversational reply on the inbound channel, transitions through `response_processing`, and returns to `waiting_for_response` on success; failures move the workflow to `paused`. |
| 6 — outbound policy hardening | complete | SMS is now blocked unless workspace A2P 10DLC status is approved; unknown consent hard-blocking is intentionally excluded from this plan by current product direction. |
| 7 — human review path for unclear inbound | complete | Unclear inbound pauses for review, applies an admin-configured CRM review tag, and sends a best-effort review notification to the assigned agent (or fallback recipient); review completion uses the existing manual resume path. |
| 8 — resume and recovery alignment | complete | Resume eligibility now distinguishes review pauses, manager-only handoff/suppression pauses, terminal suppression, and already-active workflows; committed resume requests continue to recover through the Postgres-backed Temporal signal outbox retry path. |
| 9 — turn-cap enforcement | complete | AI continuation now increments `ai_interaction_count` only after successful sends, hard-stops at five turns in V1, and pauses the workflow instead of allowing an open-ended AI exchange. |
| 10 — audit and reporting hardening | complete | Every processed inbound event now stores a durable `processing_audit` block inside `ExternalEvent.payload_redacted` with classifier metadata, final decision, continuation outcome, workflow linkage, CRM sync side effects, review notification, handoff completion, and signal-queued status. |
| 11 — end-to-end test expansion | complete | Webhook tests now cover SMS/email general-reply and review/handoff response shapes, application and Postgres business-flow harnesses cover continue/review/suppress/handoff paths, and a stale scheduled-send race case is exercised after inbound suppression. |

## Delivery phases

### Phase 1 — deterministic inbound decision policy

Goal: move final inbound action selection into explicit application rules.

Deliverables:

- an application-level decision module that accepts inbound classification and
  workflow context
- four explicit outcomes: `continue_ai`, `human_handoff`, `pause_for_review`,
  and `suppress`
- rules that force handoff for human requests, meaningful buyer/seller intent,
  and questions about specific properties, pricing, financing, legal, tax, or
  investment topics
- rules that force review for low-confidence, invalid, or ambiguous replies
- review outcomes that can trigger CRM-visible tagging through an
  admin-configured review tag
- tests proving inbound review outcomes are represented distinctly from full
  handoff outcomes
- tests proving the final decision comes from app logic, not raw model output

Implementation note for the first slice:

- the app should compute an explicit inbound action and reason code even before
  every downstream branch exists
- `continue_ai` may be represented as a decision outcome before the full
  conversational-reply branch is implemented; until Phase 5, the runtime may
  still conservatively pause after recording that decision
- CRM review tagging should be wired so it can apply even when the inbound event
  originated from the CRM itself, while inbound-note write-back remains skipped
  for CRM-originated messages

### Phase 2 — inbound orchestration ownership cleanup

Goal: remove split ownership between webhook code and Temporal for inbound state
changes.

Deliverables:

- one documented owner for post-intake inbound orchestration
- removal of duplicate transition paths for the same inbound reply
- one authoritative path for CRM side effects such as posting inbound notes and
  applying review tags
- updated tests proving one inbound reply results in one authoritative decision
  path

Implementation decision:

- Phase 2 keeps `process_inbound_message_event` as the sole authoritative owner
  for inbound reply orchestration.
- The dormant Temporal inbound reply transition signal/activity path should be
  removed so inbound replies cannot be processed through two competing state
  transition mechanisms.

### Phase 3 — inbound reply signaling into Temporal

Goal: make the durable workflow runtime aware of inbound replies without
reintroducing duplicate workflow-state mutations.

Design decision:

- Postgres and `process_inbound_message_event` remain the authoritative path for
  inbound classification, deterministic decisions, workflow transitions, handoff
  creation, CRM sync, and audit state.
- Temporal receives a lightweight, non-mutating `inbound-processed` signal. The
  signal only blocks further runtime sends and records awareness in the workflow
  snapshot; it does not call any activity or apply a second workflow
  transition.
- Phase 3 defines the signal semantics. Phase 4 changes the delivery transport
  from a synchronous post-commit call to a durable Postgres-backed outbox so the
  signal intent commits with the authoritative inbound state.

Signal payload:

- `workspace_id`
- `lead_id`
- `occurred_at` (the inbound event `received_at`)
- `external_event_id`
- `conversation_id`
- `inbound_message_id`
- `workflow_transition_id`
- `inbound_action` (e.g. `human_handoff`, `pause_for_review`, `suppress`, `continue_ai`)
- `reason` (the `InboundActionReasonCode` value)

Deliverables:

- `InboundProcessedLeadNurtureWorkflowSignal` in the application port
- `InboundProcessedWorkflowSignal` in the Temporal workflow layer
- `signal_inbound_processed_lead_nurture_workflow` on the
  `LeadNurtureWorkflowSignaler` port and `TemporalClientWorkflowStarter`
  implementation
- `LeadNurtureWorkflow.inbound_processed` signal handler that sets
  `_send_blocked = True` and updates `last_signal` / `last_activity` metadata
- webhook handling that commits authoritative inbound state before any runtime
  coordination is attempted
- tests for starter, workflow signal handler, and inbound processing result flow

Edge cases and behavior:

| Scenario | Behavior |
| --- | --- |
| Duplicate inbound event | No second signal; Postgres dedupe is authoritative. |
| No lead found / unsupported provider / rejected payload | No use-case execution; no signal. |
| No active workflow for lead | Inbound processing succeeds; no signal attempted. |
| Signal delivery is delayed or the dispatcher is down | Inbound processing still commits successfully; the queued signal remains pending in Postgres until a dispatcher claims it. |
| Inbound arrives while workflow is sleeping before a scheduled send | Signal sets `_send_blocked=True` and the workflow waits until unblocked, preventing the stale send. |
| Inbound arrives during an already-running cadence activity | The signal cannot interrupt an active activity; pre-send checks inside the activity remain the final safety net. |
| `continue_ai` action | Signal still blocks runtime sends conservatively; real AI continuation is Phase 5. |
| `human_handoff`, `pause_for_review`, or `suppress` | Signal blocks runtime sends; Postgres transition remains authoritative. |
| Workflow already closed / not found | Dispatcher marks a terminal delivery failure; inbound processing remains successful because Postgres already owns the business state. |
| Rapid multiple inbound replies | Each unique event may signal; setting `_send_blocked=True` repeatedly is idempotent. |
| CRM-originated inbound | CRM note write-back is skipped, but the runtime signal still fires if a workflow exists. |

Intentionally deferred:

- automatic unblock for `continue_ai` until Phase 5
- separate audit events for runtime signals

### Phase 4 — durable Temporal signal coordination

Goal: make all Temporal coordination retryable without letting Temporal become the
source of truth for business state.

Consistency invariants:

- Postgres is authoritative for inbound processing, workflow state, handoff, and
  suppression.
- Every signal intent is written in the same transaction as the authoritative
  state change that produced it.
- Temporal only mirrors runtime awareness; no Temporal signal handler mutates
  business state in Postgres.
- Every outbound send still re-runs pre-send checks against Postgres.
- Duplicate or retried runtime signals must be safe and idempotent.

Deliverables:

- dedicated `temporal_signal_outbox` table with workspace scoping, idempotency,
  retry metadata, and terminal-failure visibility
- `TemporalSignalOutboxRepository` plus Postgres implementation with
  `FOR UPDATE SKIP LOCKED` claiming
- durable signal intents for all current Temporal signals:
  `inbound_processed`, `pause_requested`, `resume_requested`, and
  `blocked_review_completed`
- application use cases that mutate Postgres first, then enqueue the matching
  signal intent: inbound processing, CRM human activity, contact suppression,
  manual resume, and approved draft review
- runtime-only Temporal signal handlers that block or unblock sends without
  running Postgres-mutating activities
- `dispatch_temporal_signals` use case and background worker
- `TemporalClientWorkflowStarter` translation of workflow-not-found errors into
  an application-level exception so the dispatcher can mark terminal failures
- webhook and API responses updated to report `signal_queued` while no longer
  pretending synchronous delivery is guaranteed
- repository, use-case, webhook, and starter tests covering enqueue, retry,
  dedupe, and terminal failure behavior for all supported signals

Edge cases and behavior:

| Scenario | Behavior |
| --- | --- |
| API process crashes after commit | The queued signal row remains in Postgres and will be dispatched later. |
| Temporal is temporarily unavailable | Dispatcher marks the row failed with backoff and retries later. |
| Dispatcher crashes after claiming a row | The lease expires and another dispatcher run can reclaim the row. |
| Signal succeeds but the row update fails | The row may be retried; the workflow signal must remain idempotent. |
| Duplicate inbound webhook / suppression / CRM activity replay | External-event dedupe prevents a second authoritative mutation, and the outbox idempotency key prevents duplicate queued rows. |
| Duplicate resume or draft-review request | Outbox idempotency key prevents duplicate signal rows for the same external event. |
| Workflow no longer exists when dispatch runs | Dispatcher records a terminal failure instead of retrying forever. |
| Payload corruption or unsupported signal type | Dispatcher records a terminal failure for operator visibility. |
| Pause signal arrives after a reply already blocked the workflow | Setting `_send_blocked=True` is idempotent and remains safe. |
| Resume signal arrives while the workflow is still running | The workflow unblocks runtime sends; the authoritative state was already changed in Postgres. |

Operational notes:

- run the dispatcher as a separate process via `make temporal-signal-dispatcher`
- monitor pending or repeatedly failed `temporal_signal_outbox` rows
- monitor the dispatcher worker process separately from the Temporal worker
- treat `terminal_failure` rows as reconciliation work, not as business-state
  corruption
- terminal failures for `resume` or `blocked_review_completed` mean the workflow is
  no longer running; investigate whether the workflow was closed or whether a new
  workflow needs to be started manually

### Phase 5 — real AI continuation branch

Goal: allow safe non-handoff inbound replies to continue the conversation.

Deliverables:

- a dedicated conversational reply drafting path for inbound continuations
- reuse of existing safe send orchestration only after a new reply is drafted
- state transitions that reflect response processing and return to waiting for
  response after successful send
- tests for outbound → inbound → AI continue → waiting for next reply

Implementation details:

- new use case `continue_ai_conversation_after_inbound` that orchestrates the
  continue branch: transition to `response_processing`, plan an outbound reply
  on the inbound channel, send it, and transition back to `waiting_for_response`
  on success or `paused` on failure
- reuses `plan_next_outbound_message_for_lead` and `send_outbound_message` so the
  continuation respects all existing pre-send, contactability, and provider
  safety checks
- idempotency: the continuation uses a synthetic cadence step id derived from the
  inbound message id so duplicate inbound events do not produce duplicate sends
- `process_inbound_message_event` now branches into the continuation path when the
  inbound decision is `continue_ai` and all required dependencies are present;
  when dependencies are missing it falls back to the existing conservative pause
- workflow model now allows `waiting_for_response → response_processing` and
  `response_processing → waiting_for_response` / `paused` / `human_handoff`
- pre-send policy now treats `response_processing` as a sendable workflow state
- added tests for SMS continuation, email continuation, planning-blocked pause,
  dependency-missing fallback, and duplicate-event idempotency

### Phase 6 — outbound policy hardening

Goal: enforce the product rules required before enabling a more autonomous loop.

Deliverables:

- SMS blocked unless workspace A2P 10DLC status is approved
- unknown-consent hard-blocking is intentionally excluded from the current
  implementation scope by product direction for manual testing
- updated contactability and cadence tests for these blocked cases

### Phase 7 — human review path for unclear inbound

Goal: turn ambiguous replies into an explicit operational state instead of a
silent pause.

Deliverables:

- a persisted review-needed path for rejected or unclear classifications
- CRM-visible review tagging with an admin-configured tag name so assigned
  agents can work primarily from the CRM
- optional notification hook for assigned agent or operator review
- explicit resume/review completion behavior via the existing manual resume path
- tests proving unclear inbound is visible and actionable

Completed notes:

- `process_inbound_message_event` sends a best-effort review notification when the
  inbound action is `pause_for_review`, using the assigned agent's email when
  available and falling back to the configured `fallback_recipient_email`.
- Notification failures are captured in the result and webhook response but do not
  fail inbound processing.
- The idempotency key is derived from the inbound message id so repeated events
  cannot trigger duplicate notifications.
- Review completion is handled by the existing `resume_lead_workflow` path; an
  authorized user must explicitly resume AI outreach after reviewing the lead.

### Phase 8 — resume and recovery alignment

Goal: make resume behavior match the new inbound decision model.

Deliverables:

- resume rules that distinguish unresolved review, active handoff, suppression,
  and safe continuation states
- prevention of automatic resume after handoff
- recovery behavior when signal delivery fails after state changes were already
  committed

Status: complete. Review pauses remain resumable through the existing manual
resume path; handoff-owned and suppression-driven pauses now require privileged
resume handling or remain terminal where appropriate; and resume signal delivery
recovery continues through the Postgres-backed Temporal signal outbox worker.

### Phase 9 — turn-cap enforcement

Goal: keep V1 bounded and prevent open-ended AI conversations.

Deliverables:

- tracked AI/lead turn counts per workflow or conversation
- configurable maximum back-and-forth count
- automatic pause or handoff when the cap is reached

Status: complete for V1 with an explicit code-based cap of five AI continuation
turns per conversation. The counter now advances only after a successful AI
continuation send, and cap breaches pause the workflow rather than sending
another automated reply.

### Phase 10 — audit and reporting hardening

Goal: make each inbound decision explainable after the fact.

Deliverables:

- stored classifier intent, confidence, prompt version, model, and extracted
  preferences
- stored final application decision and why it was chosen
- stored CRM sync and review-tag side effects associated with that decision
- stored send-block reasons when continuation was allowed in principle but not
  sendable at the moment of reply

Status: complete. `process_inbound_message_event` now writes a single
normalized `processing_audit` dictionary into the processed `ExternalEvent` before
returning. The audit covers the classification result, the explicit application
decision, the AI continuation outcome (status, increment, pause/block reason,
send-block reasons, outbound message and provider references), workflow linkage
(workflow id, transition id, transition status, final state), CRM sync status,
review tag application, review notification outcome, handoff completion outcome,
and whether a Temporal signal was queued. Tests verify the audit for continue-AI
success, continue-AI blocked at the turn cap, pause-for-review, human handoff,
and classification-rejected paths.

### Phase 11 — end-to-end test expansion

Goal: prove the complete conversation loop under realistic conditions.

Deliverables:

- webhook tests for inbound SMS and email continuation outcomes
- workflow tests for signal-driven pause/handoff/continue behavior
- business-flow harness coverage for continue, handoff, suppress, and review
  scenarios
- race-condition tests where inbound arrives before a scheduled outbound send

Status: complete. Phase 11 now includes webhook-level inbound coverage for SMS and
email general-reply routing plus explicit review-pause and handoff response
fields, application-level business-flow harness coverage for continue/review/
suppress/handoff paths, a representative real-Postgres continue-AI business-flow
scenario, and a focused stale scheduled-send race test that proves inbound
suppression prevents the queued follow-up from sending.

## Delivery order

Original implementation order:

1. Phase 1 — deterministic inbound decision policy
2. Phase 2 — inbound orchestration ownership cleanup
3. Phase 3 — inbound reply signaling into Temporal
4. Phase 4 — durable Temporal signal coordination
5. Phase 6 — outbound policy hardening
6. Phase 5 — real AI continuation branch
7. Phase 7 — human review path for unclear inbound
8. Phase 8 — resume and recovery alignment
9. Phase 9 — turn-cap enforcement
10. Phase 10 — audit and reporting hardening
11. Phase 11 — end-to-end test expansion

Phase 6 is intentionally moved ahead of Phase 5 so automated continuation is not
built on top of permissive send-policy gaps.

From the current codebase state, the next implementation priority should be:

1. finish Phase 8
2. implement Phase 9
3. finish Phase 10
4. expand Phase 11

## Definition of done

This plan is complete when:

- safe inbound replies can continue the conversation automatically
- risky inbound replies hand off deterministically
- unclear inbound replies become explicit review work
- review-required leads are clearly surfaced in the CRM with admin-configured
  tags so agents can act there
- opt-outs suppress outreach immediately
- inbound replies follow one authoritative application-owned transition path
- Temporal and Postgres remain consistent without duplicate inbound state
  mutation
- Postgres remains the auditable source of truth for decisions and transitions
- SMS compliance rules are enforced and the narrowed consent behavior matches the
  current product decision for manual testing
- tests cover continue, handoff, review, suppression, and race conditions

## Current next execution slice

Phases 1 through 11 are complete. The inbound conversation completion plan is
now fully implemented; any next slice should come from a new follow-up plan
rather than this checklist.