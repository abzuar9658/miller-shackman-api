# Paused Search Build Checklist and Execution Tracker

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

- [ ] Domain rules stay in `app/domain` or explicit application services.
- [ ] API routes stay thin and delegate to use cases.
- [ ] Provider-specific details stay in `app/infrastructure`.
- [ ] Tenant-owned reads/writes include `workspace_id`.
- [ ] External actions are idempotent.
- [ ] Important state changes write audit records or transition history.
- [ ] Safety/compliance rules are not admin-overridable.
- [ ] Semantic interpretation uses structured LLM output, not regex.
- [ ] Regex/deterministic matching is limited to narrow compliance checks.
- [ ] Existing abstractions are reused before adding new ones.
- [ ] Route/profile/track state changes use existing audit/outbox patterns where applicable.

## Business-rule ownership gates

### Code-owned rules

- [ ] Consent, suppression, do-not-contact, opt-out precedence.
- [ ] A2P 10DLC SMS blocking.
- [ ] Handoff and human-ownership precedence.
- [ ] Workflow state transition legality.
- [ ] Pre-send safety checks.
- [ ] Review-hold behavior for uncertainty.
- [ ] LLM schema validation and confidence thresholds.
- [ ] Version pinning and explicit migration behavior.

### Admin-owned settings

- [ ] External CRM tag aliases mapped to internal `ai_nurture`.
- [ ] Approved paused-search reason labels or aliases.
- [ ] Reason-to-track mappings.
- [ ] Cadence steps, channels, templates, and phase timing.
- [ ] Fallback timing and reactivation windows.
- [ ] Lead-level overrides with required reasons.
- [ ] Draft/publish/version lifecycle for strategy changes.

## Standard slice completion gates

Each slice must include:

- [ ] Updated or new design doc section if behavior changed.
- [ ] Domain/application implementation.
- [ ] Persistence changes and Alembic migration when needed.
- [ ] Repository methods with workspace isolation.
- [ ] API schemas and endpoint behavior when needed.
- [ ] Frontend read/write surface when the slice exposes operator controls.
- [ ] Audit, event, or workflow transition records for important decisions.
- [ ] Proposal/review artifacts are persisted explicitly when AI-assisted review is involved.
- [ ] Unit tests for business rules.
- [ ] Fake-based application tests.
- [ ] Postgres tests for repositories/migrations when persistence changes.
- [ ] Temporal tests when workflow timing/signals change.
- [ ] UI tests for visible operator/admin behavior.
- [ ] Edge-case tests listed for the slice.
- [ ] `make lint`, `make typecheck`, and targeted `pytest` pass for backend work.
- [ ] `pnpm lint`, `pnpm typecheck`, and targeted `vitest` pass for frontend work.
- [ ] Rollback notes for risky persistence or workflow changes.

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
- [ ] Choose dedicated table vs canonical lead extension and record decision.
- [ ] Add domain model/enums for active state, reason, timing, source.
- [ ] Add migration with `workspace_id`, constraints, and indexes.
- [ ] Add repository port + Postgres adapter.
- [ ] Add API schemas/endpoints for read, set, update, clear.
- [ ] Add lead-detail UI display and edit affordance.
- [ ] Record actor, source, reason, timestamps, and change history.

Tests and edge cases:
- [ ] Unknown timing is valid but explicit.
- [ ] Clearing paused-search state is audited.
- [ ] Duplicate updates are idempotent or safely versioned.
- [ ] Workspace isolation is enforced.
- [ ] Only authorized roles can edit.

## Slice 2 — LLM paused-search analysis + review proposal flow

Goal: use LLM intelligence safely before any automatic state mutation.

Build checklist:
- [ ] Define prompt version and structured output schema.
- [ ] Validate reason, timing, readiness, risk, confidence, and evidence.
- [ ] Persist proposal/review artifact with model metadata.
- [ ] Add review UI for accept, edit, reject, and re-run.
- [ ] Accepting a proposal writes the paused-search profile through Slice 1 path.

Tests and edge cases:
- [ ] Clear pause, ambiguous pause, active intent, opt-out, and no-history cases.
- [ ] Malformed/low-confidence LLM output routes to review.
- [ ] Re-analysis does not overwrite accepted human truth silently.
- [ ] No regex path can decide semantic reason/timing/routing.

## Slice 3 — `ai_nurture` router + enrollment path selection

Goal: make the tag a safe evaluation gate, not a send command.

Build checklist:
- [ ] Map external tags to internal `ai_nurture` concept.
- [ ] Add router use case with fixed outcomes: paused-search, dormant, handoff, suppressed/rejected, human-owned hold, consent/contactability hold, hold/review.
- [ ] Integrate with CRM tag enrollment flow.
- [ ] Persist route decision, evidence, config version, and idempotency key.
- [ ] Start only eligible workflow/enrollment paths.

Tests and edge cases:
- [ ] Tag absent never starts nurture.
- [ ] Paused-search profile takes precedence over dormant fallback.
- [ ] Suppressed, human-owned, no-consent, or recent-reply leads do not start.
- [ ] Duplicate tag events do not create duplicate workflows.
- [ ] Tag removed after routing is handled safely.

## Slice 4 — Paused-search track admin model + publish flow

Goal: let admins change strategy without creating a freeform rules engine.

Build checklist:
- [ ] Add track draft/publish/version model or safely extend campaign versions.
- [ ] Add reason-to-track mapping and fallback timing policy.
- [ ] Add maintenance/reactivation phase metadata.
- [ ] Add admin UI for draft, preview, publish, retire.
- [ ] Pin new enrollments to immutable published versions.
- [ ] Enforce track-level touch limits that cannot exceed the code-owned AI interaction cap.

Tests and edge cases:
- [ ] Invalid mappings cannot publish.
- [ ] Existing workflows keep old version after new publish.
- [ ] Retired tracks remain readable for pinned workflows.
- [ ] Concurrent draft edits are safe.

## Slice 5 — Paused-search cadence execution in Temporal

Goal: reliably run long waits, maintenance touches, and reactivation.

Build checklist:
- [ ] Compute next action from profile, pinned track, phase, and safety state.
- [ ] Persist `next_action_at` and action reason.
- [ ] Add Temporal sleep/wake/reschedule behavior.
- [ ] Re-load current facts before every send or phase change.
- [ ] Re-run pre-send checks immediately before provider calls.
- [ ] Recompute phase at wake-up from current facts rather than trusting stale scheduled assumptions.

Tests and edge cases:
- [ ] Year-long wait survives workflow restart semantics.
- [ ] Quiet hours defer send.
- [ ] Updated timing reschedules stale timers.
- [ ] Reply, human activity, reassignment, opt-out, or suppression pauses/stops.
- [ ] Duplicate wake-ups do not send twice.

## Slice 6 — Lead overrides, migration tools, and operational controls

Goal: provide safe human control over live journeys.

Build checklist:
- [ ] Add actions for timing change, track switch, skip touch, pause, resume.
- [ ] Add explicit migrate-to-new-version action.
- [ ] Require actor, role, reason, old value, and new value.
- [ ] Show current path, pinned version, and next action in UI.

Tests and edge cases:
- [ ] Resume re-runs eligibility, consent, ownership, suppression, and recent activity checks.
- [ ] Migration to invalid/retired track is blocked unless explicitly supported.
- [ ] Conflicting operator actions are serialized or safely rejected.
- [ ] Override during `waiting_for_response` does not lose reply handling.

## Slice 7 — Hardening, end-to-end business flow, and rollout gates

Goal: prove the whole system is pilot-ready.

Build checklist:
- [ ] Add end-to-end business-flow harness.
- [ ] Add audit/reporting queries for route, profile, track, next action, handoff.
- [ ] Add operational runbook and pilot feature flag.
- [ ] Add monitoring for LLM failures, route holds, workflow failures, send blocks.
- [ ] Document rollback/migration strategy.

Tests and edge cases:
- [ ] Full flow: LLM proposal → profile → tag → route → track pin → wait → touch → reactivation → reply → handoff.
- [ ] Duplicate CRM events, malformed LLM output, stale timers, mid-track opt-out.
- [ ] New published settings do not mutate existing workflows automatically.

## Release readiness checklist

Before pilot release:

- [ ] Product owner approves business behavior.
- [ ] Engineering approves architecture boundaries.
- [ ] QA signs off on slice edge cases.
- [ ] Support has a runbook for holds, failures, and overrides.
- [ ] Admin configuration defaults are reviewed.
- [ ] Feature flag and rollback plan are ready.
- [ ] No automated message can bypass pre-send checks.
