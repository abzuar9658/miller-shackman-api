# Paused Search Build Checklist and Execution Tracker

> **Superseded for paused-search track routing.** Use
> `paused-search-dynamic-track-classification-correction-plan.md` as the current contract.
> This historical tracker must not be used to restore fixed categories, routing mappings, or
> existing-data migration behavior.

## Purpose

This tracker turns `paused-search-implementation-plan.md` into a development
execution checklist. Use it during planning, implementation, review, QA, and
rollout so every slice is complete across product, architecture, backend,
frontend, workflow, testing, audit, and operations.

## Operating rule

Do not mark a slice complete because code compiles. Mark it complete only when
all required gates below are satisfied, reviewed, and tested.

## Global architecture gates

For every slice, confirm:

- [x] Domain rules stay in `app/domain` or explicit application services.
- [x] API routes stay thin and delegate to use cases.
- [x] Provider-specific details stay in `app/infrastructure`.
- [x] Tenant-owned reads/writes include `workspace_id`.
- [x] External actions are idempotent.
- [x] Important state changes write audit records or transition history.
- [x] Safety/compliance rules are not admin-overridable.
- [x] Semantic interpretation uses structured LLM output, not regex.
- [x] Regex/deterministic matching is limited to narrow compliance checks.
- [x] Existing abstractions are reused before adding new ones.
- [x] Route/profile/track state changes use existing audit/outbox patterns where applicable.

## Business-rule ownership gates

### Code-owned rules

- [x] Consent, suppression, do-not-contact, opt-out precedence.
- [x] A2P 10DLC SMS blocking.
- [x] Handoff and human-ownership precedence.
- [x] Workflow state transition legality.
- [x] Pre-send safety checks.
- [x] Review-hold behavior for uncertainty.
- [x] LLM schema validation and confidence thresholds.
- [x] Version pinning and explicit migration behavior.

### Admin-owned settings

- [x] External CRM tag aliases mapped to internal `ai_nurture`.
- [x] Approved paused-search reason labels or aliases.
- [x] Reason-to-track mappings.
- [x] Cadence steps, channels, templates, and phase timing.
- [x] Fallback timing and reactivation windows.
- [x] Lead-level overrides with required reasons.
- [x] Draft/publish/version lifecycle for strategy changes.

## Standard slice completion gates

Each slice must include:

- [x] Updated or new design doc section if behavior changed.
- [x] Domain/application implementation.
- [x] Persistence changes and Alembic migration when needed.
- [x] Repository methods with workspace isolation.
- [x] API schemas and endpoint behavior when needed.
- [x] Frontend read/write surface when the slice exposes operator controls.
- [x] Audit, event, or workflow transition records for important decisions.
- [x] Proposal/review artifacts are persisted explicitly when AI-assisted review is involved.
- [x] Unit tests for business rules.
- [x] Fake-based application tests.
- [x] Postgres tests for repositories/migrations when persistence changes.
- [x] Temporal tests when workflow timing/signals change.
- [x] UI tests for visible operator/admin behavior.
- [x] Edge-case tests listed for the slice.
- [x] `make lint`, `make typecheck`, and targeted `pytest` pass for backend work.
- [x] `pnpm lint`, `pnpm typecheck`, and targeted `vitest` pass for frontend work.
- [x] Rollback notes for risky persistence or workflow changes.

Implementation should preferentially extend known system seams rather than
inventing parallel ones. Relevant anchor points include:

- `process_crm_tag_campaign_enrollment.py`
- `run_dormant_selector_batch.py`
- `CampaignExecutionConfig` and campaign admin version models
- `WorkflowState` transition rules
- existing business-flow harness and related fake-based use-case tests

## Slice 1 — Persisted paused-search profile + operator controls

Goal: make paused-search a durable, explicit, auditable lead concept.

Build checklist:
- [x] Choose dedicated table vs canonical lead extension and record decision.
- [x] Add domain model/enums for active state, reason, timing, source.
- [x] Add migration with `workspace_id`, constraints, and indexes.
- [x] Add repository port + Postgres adapter.
- [x] Add API schemas/endpoints for read, set, update, clear.
- [x] Add lead-detail UI display and edit affordance.
- [x] Record actor, source, reason, timestamps, and change history.

Tests and edge cases:
- [x] Unknown timing is valid but explicit.
- [x] Clearing paused-search state is audited.
- [x] Duplicate updates are idempotent or safely versioned.
- [x] Workspace isolation is enforced.
- [x] Only authorized roles can edit.

## Slice 2 — LLM lead-state analysis + AI-first classification flow

Goal: use LLM intelligence as the first classifier while preserving safe review
fallback and human override.

Build checklist:
- [x] Define prompt version and structured output schema.
- [x] Validate bounded outcomes, reason, timing, readiness, risk, confidence,
  and evidence.
- [x] Support bounded classification outcomes for paused-search, dormant,
  human handoff, blocked, and review-needed states.
- [x] Write paused-search profile directly when the paused-search classification
  is valid and above threshold.
- [x] Persist durable AI classification artifact with model metadata and applied-vs-review status.
- [x] Re-run classification on meaningful replies from paused-search and dormant
  leads before the workflow continues.
- [x] Add review UI for low-confidence, conflicting, or timing-unclear cases.
- [x] Add manual override UI for edit, clear, reject, and re-run behavior.
- [x] Enforce human-override precedence so re-analysis does not silently churn trusted state.

Tests and edge cases:
- [x] Clear pause, dormant silence, ambiguous pause, active intent, opt-out,
  and no-history cases.
- [x] High-confidence valid classification writes the paused-search profile.
- [x] Active-interest classification routes to handoff instead of nurture.
- [x] Malformed/low-confidence LLM output routes to review.
- [x] Meaningful replies to paused-search and dormant leads trigger
  re-classification before automation continues.
- [x] Re-analysis does not overwrite accepted human truth silently.
- [x] No regex path can decide semantic reason/timing/routing.

## Slice 3 — `ai_nurture` router + enrollment path selection

Goal: make the tag a safe evaluation gate, not a send command.

Build checklist:
- [x] Map external tags to internal `ai_nurture` concept.
- [x] Add router use case with fixed outcomes: paused-search, dormant, handoff, suppressed/rejected, human-owned hold, consent/contactability hold, hold/review.
- [x] Auto-start the dormant path when dormant routing wins and existing start checks pass.
- [x] Draft dormant first-touch messages from recent conversation context and known lead facts.
- [x] Integrate with CRM tag enrollment flow.
- [x] Persist route decision, evidence, config version, and idempotency key.
- [x] Start only eligible workflow/enrollment paths.

Tests and edge cases:
- [x] Tag absent never starts nurture.
- [x] Paused-search profile takes precedence over dormant fallback.
- [x] Accidental tag on a hot lead routes to handoff instead of nurture.
- [x] Dormant route does not wait for a second manual approval step after routing.
- [x] Dormant drafting uses recent conversation context instead of generic copy alone.
- [x] Suppressed, human-owned, no-consent, or recent-reply leads do not start.
- [x] Duplicate tag events do not create duplicate workflows.
- [x] Tag removed after routing is handled safely.

## Slice 4 — Paused-search track admin model + publish flow

Goal: let admins change strategy without creating a freeform rules engine.

Build checklist:
- [x] Add track draft/publish/version model or safely extend campaign versions.
- [x] Add reason-to-track mapping and fallback timing policy.
- [x] Add maintenance/reactivation phase metadata.
- [x] Add backend admin API for draft, detail/list, publish, and retire.
- [x] Pin new enrollments to immutable published versions.
- [x] Enforce track-level touch limits that cannot exceed the code-owned AI interaction cap.

Tests and edge cases:
- [x] Invalid mappings cannot publish.
- [x] Existing workflows keep old version after new publish.
- [x] Retired tracks remain readable for pinned workflows.
- [ ] Concurrent draft edits are safe. (Requires optimistic-locking / version column on draft versions; not yet implemented.)

Current implementation note:

- backend domain/use-case/repository/migration foundation is implemented
- published reason mappings point to immutable published track versions
- older versions remain readable after replacement or retirement
- backend admin API surface now exists for draft create/update, list/detail,
  publish, and retire; dedicated web UI remains a frontend slice
- seeded/default paused-search template keys now resolve to concrete subject/body
  copy plus step-specific drafting prompts used at execution time

## Slice 5 — Paused-search cadence execution in Temporal

Goal: reliably run long waits, maintenance touches, and reactivation.

Build checklist:
- [x] Compute next action from profile, pinned track, phase, and safety state.
- [x] Persist `next_action_at` and the pinned paused-search track step cursor.
- [x] Add Temporal sleep/wake/reschedule behavior.
- [x] Re-load current lead/workflow facts before paused-search send execution.
- [x] Re-run pre-send checks immediately before provider calls.
- [x] Recompute phase at wake-up from current facts rather than trusting stale scheduled assumptions.
- [x] Re-run classification on meaningful replies before continuing the current
  path.

Tests and edge cases:
- [x] Year-long wait survives workflow restart semantics. (Covered by a dedicated Temporal time-skipping integration test for the durable year-long wait.)
- [x] Quiet hours defer send.
- [x] Updated timing reschedules stale timers.
- [x] Reply can keep the lead paused-search, move it to review, or hand it off
  after re-classification.
- [x] Human activity, reassignment, opt-out, or suppression pauses/stops.
- [x] Duplicate wake-ups do not send twice.

Current implementation note:

- completed in this slice: track-version pinning, workflow-row step cursor,
  durable `next_action_at` planning, interruptible Temporal waiting, explicit
  reschedule signaling, duplicate-wake protection, and stale-timer stop tests
- existing pause/resume/inbound stop signals now interrupt long waits instead of
  allowing the workflow to trust the original timer blindly
- paused-search outbound execution now consumes the pinned track step through the
  shared outbound planning/sending path, reusing pre-send checks, idempotency,
  provider dispatch, CRM refresh/human-activity safety, and cursor advancement
  after a sent/already-sent outcome
- execution-time compliance/channel blocking is now explicitly proven for
  paused-search sends and inbound continuation flows; blocked channels do not
  bypass contactability or pre-send safety checks
- remaining hardening: broader end-to-end business-flow harness, rollout gates,
  and operational reporting/runbook coverage

## Slice 6 — Lead overrides, migration tools, and operational controls

Goal: provide safe human control over live journeys.

Build checklist:
- [x] Add actions for timing change, track switch, skip touch, pause, resume.
- [x] Add explicit migrate-to-new-version action.
- [x] Require actor, role, reason, old value, and new value.
- [x] Show current path, pinned version, and next action in UI.

Tests and edge cases:
- [x] Resume re-runs eligibility, consent, ownership, and suppression checks. (Recent-activity check is not explicitly re-run on resume; it is covered by the ongoing pre-send gate before every send.)
- [x] Migration to invalid/retired track is blocked unless explicitly supported.
- [x] Conflicting operator actions are serialized or safely rejected. (Workflow/profile reads use `SELECT FOR UPDATE` where needed; timing override and track migration reject incompatible workflow states.)
- [x] Override during `waiting_for_response` does not lose reply handling. (Overrides are rejected in `waiting_for_response`; the lead continues to wait for the reply and then re-classifies it.)

Current implementation note:

- lead detail now exposes paused-search timing override, track migration,
  skip-next-touch, pause, and resume controls
- lead detail readback also surfaces resolved and superseded routing-review
  history so support/operators can reconstruct why the route changed
- resume re-checks workflow state, actor permissions, and contactability before
  allowing a paused workflow to continue; the per-send pre-send gate covers
  recent activity, opt-out, and channel consent at execution time
- track migration rejects target versions that are not published or are disabled/retired

## Slice 7 — Hardening, end-to-end business flow, and rollout gates

Goal: prove the whole system is pilot-ready.

Build checklist:
- [x] Add end-to-end business-flow harness.
- [x] Add audit/reporting readback for route, profile, track, next action, handoff.
- [x] Reuse workspace operational control as the pilot automation gate and document it.
- [x] Reuse existing audit/transition/reporting surfaces for LLM failures, route holds,
  workflow failures, and send blocks.
- [x] Document rollback/migration strategy.

Tests and edge cases:
- [x] Full flow: AI classification → optional review or override → tag → route
  to dormant or paused-search → track pin → wait → touch → reply-time
  re-classification → reactivation or handoff.
- [x] Duplicate CRM events, malformed LLM output, stale timers, and mid-track
  suppression/stop paths are covered across focused tests.
- [x] New published settings do not mutate existing workflows automatically.

## Release readiness checklist

Before pilot release:

- [ ] Product owner approves business behavior.
- [ ] Engineering approves architecture boundaries.
- [ ] QA signs off on slice edge cases.
- [ ] Support has a runbook for holds, failures, and overrides.
- [ ] Admin configuration defaults are reviewed.
- [ ] Feature flag and rollback plan are ready.
- [x] No automated message can bypass pre-send checks. (Enforced in code for every paused-search and dormant outbound send.)

Current implementation note:

- AI-routed paused-search leads now auto-start the workflow path through CRM-tag
  enrollment and immediately pin a published paused-search track version before any
  cadence execution can occur
- if a lead is paused-search active but no published track mapping exists, the route
  now fails safely into review-hold instead of silently falling back to dormant sends
- duplicate paused-search CRM tag events return `already_enrolled` and do not create
  duplicate enrollments or duplicate Temporal starts
- backend admin APIs for paused-search tracks are now available for future frontend
  integration; the remaining track-administration work is frontend-only

## Verification notes

- Backend confidence gate must be run as `arch -arm64 make check` on this machine. The
  default shell runs under x86_64 emulation, but the Python virtual environment and
  wheels are arm64 native, so a plain `make check` fails with an architecture mismatch.
- Frontend `pnpm check` passes on Node 20.14.0 / pnpm 9.1.0. It prints a non-blocking
  engine warning because `package.json` wants Node `>=20.19.0`; the warning does not
  fail the gate.
- Known remaining hardening gaps that are not release blockers:
  - Concurrent draft edits on paused-search track versions do not use optimistic locking.
  - Resume does not explicitly re-check recent agent activity; the per-send pre-send
    gate covers this at execution time instead.
