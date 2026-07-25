# Paused Search Implementation Plan

## Purpose

This document turns the approved paused-search design into a safe delivery plan.
Each slice must be a complete vertical slice with implementation, tests, audit
behavior, and explicit edge-case handling before the next slice starts.

See also:

- `paused-search-01-lead-profile.md`
- `paused-search-02-enrollment-and-start-semantics.md`
- `paused-search-03-nurture-tracks.md`
- `paused-search-04-timing-and-reactivation.md`

## Delivery principles

- Business rules stay explicit in code; do not build a dynamic rules engine.
- Admins configure bounded policy inputs, not arbitrary workflow logic.
- Semantic interpretation uses structured LLM output, not regex, for paused-
  search reason/timing/routing inputs.
- Every external action and workflow wake-up must remain idempotent.
- Every slice ends with fake-based tests, targeted Postgres tests where needed,
  and Temporal tests where timing/orchestration changes.
- Do not move to the next slice until the current slice is operationally usable.

## Changeability model

### Code-owned rules

Keep these in code and tests:

- safety/compliance precedence
- workflow state legality
- review-hold behavior for uncertainty
- version-pinning rules
- pre-send checks and handoff rules
- LLM output validation schema and confidence thresholds

### Admin-owned settings

Expose these through draft/publish admin settings:

- external tag aliases mapped to internal `ai_nurture`
- paused-search reason labels or aliases mapped to approved families
- reason-to-track mapping
- cadence steps, channels, and templates
- fallback timing policy and reactivation windows
- lead-level overrides and explicit migrations

## Slice sequence

### Slice 1 — Persisted paused-search profile + operator controls

Goal: make paused-search a real persisted lead concept before automation changes.

Deliverables:
- explicit paused-search fields or a dedicated `paused_search_profiles` table
- repository/domain models and lead-detail API exposure
- operator/admin write path to set, update, clear, and confirm paused-search
- audit metadata for source, actor, and timestamps
- lead detail UI visibility for paused-search facts

Tests:
- domain validation for one active primary reason
- repository round-trip and workspace isolation
- API tests for read/write permissions
- UI tests for display and edit behavior

Edge cases:
- unknown timing
- clearing paused-search state
- reassignment of primary reason
- duplicate updates
- workspace isolation on reads/writes

Business result:
- staff can explicitly record and view paused-search leads reliably

### Slice 2 — LLM paused-search analysis + review proposal flow

Goal: add intelligence safely without auto-mutating lead state.

Deliverables:
- focused LLM extraction use case for reason, timing, readiness, and confidence
- strict structured-output schema and validator
- proposal record or review artifact rather than automatic profile mutation
- admin/manager review action to accept, edit, or reject the proposal
- audit of model, prompt version, confidence, and reviewer action

Tests:
- schema validation and low-confidence rejection
- fake LLM tests for clear, ambiguous, and conflicting conversations
- review acceptance/rejection flow tests
- API/UI tests for review queue and proposal details

Edge cases:
- conflicting timing statements
- intent changed to active interest
- missing conversation history
- repeated re-analysis of the same lead
- LLM malformed output

Business result:
- the system can understand conversation meaning without trusting regex or auto-
  changing lead state unsafely

### Slice 3 — `ai_nurture` router + enrollment path selection

Goal: turn the tag into a safe routing gate for paused-search, dormant, or hold.

Deliverables:
- internal `ai_nurture` concept mapped from configurable external tags
- routing use case with precedence: paused-search, dormant fallback, hold/review
- integration into CRM sync/tag enrollment flow
- durable route-decision audit record with reason codes and evidence
- configuration for dormant fallback vs review-first behavior

Tests:
- tag present/absent routing tests
- paused-search precedence over dormant
- review-hold on ambiguity or missing facts
- tag idempotency and duplicate enrollment protection
- integration tests covering CRM tag processing + workflow start decision

Edge cases:
- tag removed after routing
- lead already enrolled
- recent reply before start
- no contactable channels
- human-owned or suppressed lead tagged by mistake

Business result:
- tagging a lead triggers the right nurture evaluation path instead of one generic campaign

### Slice 4 — Paused-search track admin model + publish flow

Goal: let admins manage paused-search strategy without code changes.

Deliverables:
- paused-search track draft/publish data model, or safe extension of existing campaign versioning
- reason-to-track mapping model
- cadence-step phase metadata: maintenance vs reactivation
- workspace nurture settings UI/API for tracks, mappings, and fallback timing
- publish audit trail and immutable version snapshots

Tests:
- draft/update/publish/retire workflow tests
- mapping validation tests
- version pinning tests for new vs existing enrollments
- UI tests for editing, publishing, and previewing track changes

Edge cases:
- multiple tracks for same reason
- disabled track still referenced by a lead
- invalid fallback timing policy
- publish with missing required steps
- concurrent draft edits

Business result:
- the business can tune paused-search strategy through admin controls safely

### Slice 5 — Paused-search cadence execution in Temporal

Goal: make long-running paused-search nurture actually execute over time.

Deliverables:
- extend scheduling/execution use cases for maintenance/reactivation phases
- persist next-action timing derived from paused-search track + lead profile
- Temporal wake/sleep/reschedule logic for long waits
- explicit recomputation on profile change, override, pause, reply, or ownership change
- version-pinned execution for long-lived workflows

Tests:
- cadence scheduling tests for known and unknown timing
- Temporal workflow tests for sleep, wake, defer, reschedule, and close
- repository tests for next-action persistence under locking
- integration tests for maintenance touch then later reactivation

Edge cases:
- year-long waits
- quiet-hours deferral at wake-up
- updated `reengagement_not_before`
- ownership changes during waiting period
- worker restart during long wait

Business result:
- the system can remember a paused lead for months and wake up at the right time reliably

### Slice 6 — Lead overrides, migration tools, and operational controls

Goal: give humans controlled escape hatches without corrupting workflow state.

Deliverables:
- lead-level override actions: change timing, switch track, skip next touch, manual pause/resume
- explicit migrate-workflow-to-new-version action
- reporting of why a lead is in its current path and when the next action is due
- admin/manager authorization rules for each override

Tests:
- permission tests for overrides
- migration audit tests
- recomputation tests after each override action
- UI tests for override affordances and readbacks

Edge cases:
- override during `waiting_for_response`
- migration to retired track
- resume after suppression or handoff restrictions
- conflicting operator actions close together

Business result:
- operators can safely adapt live lead journeys without editing raw workflow data

### Slice 7 — Hardening, end-to-end business flow, and rollout gates

Goal: prove the whole paused-search system works under real business scenarios.

Deliverables:
- end-to-end harness covering: profile set, LLM proposal, tag routing, track pinning, long wait, maintenance touch, reactivation, reply, handoff
- observability and audit queries for route decisions and next scheduled action
- rollout checklist, support runbook, and pilot-safe feature flag controls

Tests:
- full business-flow tests using fakes
- targeted Postgres + Temporal integration tests
- failure-mode tests for duplicate events, malformed LLM output, and stale timer recompute

Edge cases:
- repeated tag application
- lead becomes opted out mid-track
- tag added before review completed
- old workflow version after settings publish

Business result:
- the paused-search system is pilot-ready, supportable, and safe to evolve

## Implementation gate for every slice

A slice is not done until all of these are true:

- business behavior is documented and implemented
- unit/application/integration tests for that slice pass
- audit behavior is visible and queryable
- failure and edge cases are covered explicitly
- admin/config ownership vs code ownership remains clear
- the next slice can build on it without reworking the previous slice

## Recommendation

Build in the sequence above. It gives you the smartest path with the lowest risk:
manual truth first, LLM understanding second, routing third, admin strategy
control fourth, durable timing fifth, operator overrides sixth, and full
hardening last.
