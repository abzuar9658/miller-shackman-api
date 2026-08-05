> **Superseded for paused-search track routing.** Use
> `paused-search-dynamic-track-classification-correction-plan.md` as the current contract.
> This historical recurring-maintenance plan must not be used to restore compatibility or
> existing-data migration behavior.

# Paused-Search Track Control and Recurring Maintenance — End-to-End Implementation Plan

## 1. Purpose and status

This document is the implementation-ready plan for completing bounded paused-
search track control and recurring maintenance behavior. It operationalizes
`paused-search-track-control-and-recurring-maintenance-plan.md` and builds on the
existing paused-search implementation described in:

- `paused-search-implementation-plan.md`
- `paused-search-execution-tracker.md`
- `paused-search-test-matrix-and-verification-plan.md`
- `paused-search-03-nurture-tracks.md`
- `paused-search-04-timing-and-reactivation.md`

The existing foundation is retained. This plan does not create a second nurture
engine, a generic rules engine, a generic workflow abstraction, an MLS/IDX
integration, or an autonomous property-recommendation system.

The implementation is complete only when an administrator can configure a
bounded, versioned track; preview and publish it safely; and the application can
execute recurring maintenance through Temporal with durable occurrence records,
strict limits, immediate interruption, pre-send revalidation, review controls,
fallback-channel safety, terminal behavior, auditability, and end-to-end tests.

### 1.1 Execution status ledger

This ledger is updated after every implementation slice. A checked item means the
code, migration, tests, and documentation for that item are complete; an unchecked
item is not complete even if the design is specified elsewhere in this document.

**Current status:** Phase 1 occurrence accounting, interruption/callback control,
terminal Temporal orchestration, and uncertain-send timeout/operator resolution
control are complete.

**Completed before this implementation sequence:**

- [x] Requirements and architecture contract reviewed and finalized.
- [x] Existing paused-search foundation, versioning, pinning, timing, admin API,
      frontend surface, and baseline tests inventoried.
- [x] Engineer review findings incorporated and independently re-reviewed.

**Completed implementation slices:**

- [x] Slice 0A — added the disabled-by-default
      `recurring_paused_search_enabled` field to the existing workspace
      operational-control domain/model/repository/API path, with additive
      migration `0058_add_recurring_paused_search_flag.py`.
- [x] Slice 0A — added workspace application/API regression coverage and
      repository mapping coverage.
- [x] Slice 0A — applied migration `0058` to the local Postgres harness and
      verified a real repository round trip with the flag enabled.
- [x] Slice 0A — verified with 42 targeted tests, Ruff, mypy, `alembic heads`,
      migration upgrade, and `git diff --check` under the native arm64 Python
      environment.
- [x] Slice 0B — added stable paused-search contract fixture IDs covering timing,
      occurrences, reviews, templates, notifications, and profiles.
- [x] Slice 0B — added the pure legacy migration audit/report service covering
      unknown templates, fallback-policy compatibility, legacy publish-review
      metadata, empty versions, and incomplete workflow cursors.
- [x] Slice 0B — verified with 46 combined targeted tests, Ruff, mypy, and
      `git diff --check` under the native arm64 Python environment.

**Completed implementation slices:**

- [x] Phase 2 — terminal workflow behavior and durable Temporal execution
      orchestration, including terminal/review outcomes, bounded schedule retries,
      single-attempt send execution, and occurrence IDs in cadence snapshots.

**Most recently completed slice:** Phase 2 provider-callback integration hardening,
following uncertain-send timeout and operator resolution.

- [x] Resolved the backend test-call-site type errors and aligned the review
      resolution assertion with the current supersession behavior.
- [x] Formatted the six frontend files reported by Prettier.
- [x] Re-ran the complete backend gate: Ruff passed, mypy passed for 480 files,
      and 1,002 tests passed under the native arm64 environment.
- [x] Re-ran the complete frontend gate: lint, typecheck, 80 tests, and
      `format:check` all passed. The environment still reports the existing Node
      engine warning because it provides Node 20.14.0 while the project requests
      Node >=20.19.0.
- [x] Phase 0 implementation baseline is satisfied. Phase 1 occurrence,
      execution-state, timing-history, capability-profile, template, review,
      notification-policy, and isolation slices are implemented; canonical
      planner adoption and legacy recurring-loop migration remain later gates.

**Phase 1 / Slice 1A — recurring occurrence foundation:**

- [x] Added explicit recurring occurrence status, outcome, terminal behavior,
      logical-touch, provider-identity, and idempotency domain contracts.
- [x] Added bounded recurring step configuration: calendar-day interval,
      maximum occurrences, maximum track duration, and terminal behavior, all
      disabled or compatibility-defaulted for existing tracks.
- [x] Added migration `0059_add_paused_search_occurrences.py`, tenant-scoped
      uniqueness, indexes, and row-level security for occurrence records.
- [x] Added an idempotent PostgreSQL occurrence repository and integrated it
      into Temporal cadence scheduling and paused-search revalidation.
- [x] Added domain and application coverage for calendar-day planning,
      idempotent reuse, and occurrence-limit terminal behavior.
- [x] Verified migration upgrade, targeted persistence/cadence tests, Ruff,
      and mypy. Execution outcomes are completed in Slice 1B below.

**Phase 1 / Slice 1B — execution state and touch accounting:**

- [x] Added a row-locking occurrence execution update path for accepted,
      failed, uncertain, cancelled, and post-acceptance delivery outcomes.
- [x] Kept accepted logical touches separate from provider delivery status and
      made terminal updates idempotent against stale or duplicate workers.
- [x] Added durable workflow `logical_touch_count` persistence and incremented
      it exactly once when a paused-search occurrence reaches `sent`.
- [x] Linked accepted provider message IDs to occurrences and reconciled later
      provider delivery callbacks without creating another touch or send.
- [x] Added the track touch-limit guard and focused fake/Postgres/callback tests.
- [x] Completed occurrence status persistence, logical-touch accounting, provider
      callback reconciliation, and strict touch-limit enforcement.

**Phase 2 — terminal workflow and Temporal orchestration (complete):**

- [x] Terminal planner outcomes now apply the published terminal behavior to the
      workflow (`completed`, `closed`, or an audited review pause) when the
      transition repository is available.
- [x] Terminal schedule results are returned explicitly to Temporal and close the
      workflow without dispatching an execution activity.
- [x] Schedule activity failures use bounded Temporal retries; execution activity
      replay remains single-attempt until provider dispatch is separated behind a
      committed outbox boundary, preventing blind duplicate sends.
- [x] Occurrence IDs are carried through activity results and the workflow query
      snapshot for durable readback.
- [x] Added interruption-driven cancellation of open occurrences for pause,
      suppression, handoff, reassignment, and other terminal workflow transitions.
- [x] Added provider-callback reconciliation for uncertain occurrences, preserving
      idempotent touch accounting and waking the durable workflow through the
      Temporal signal outbox.
- [x] Added the row-locked `resolve_uncertain` repository operation and application
      use-case path for operator resolution to `sent`, `failed`, or `skipped`, with
      explicit status handling, touch-accounting rules, workflow transitions, and
      blocked-review wake-up metadata.
- [x] Added the durable 24-hour Temporal wait/activity for unresolved uncertain
      occurrences, including the row-locked timeout to `failed`, audited
      pause-for-review transition, and timeout signal outbox entry.
- [x] Added dedicated operator-action, timeout, duplicate-resolution, and
      duplicate-timeout tests, including all three resolution outcomes and the
      one-touch-only `sent` rule.
- [x] Wired the authorized operator-resolution API with assigned-lead versus
      manager/admin permission checks, and added the assigned-agent/fallback
      review notification path for timeout outcomes.
- [x] Wired the Twilio, SendGrid, and Mailgun delivery callback routes with the
      occurrence, lead-workflow, and Temporal signal-outbox repositories required
      for uncertain-occurrence reconciliation and workflow wake-up.
- [x] Added API-level SendGrid regression coverage proving that an uncertain
      occurrence becomes `sent`, consumes exactly one logical touch, increments
      the workflow touch count, and creates one `provider_delivery_reconciled`
      Temporal signal entry. The focused provider-callback suite passes 16 tests;
      Ruff and `git diff --check` also pass under native arm64 Python.

**Verification and remaining roadmap:**

- [x] Phase 0 / Slice 0C full-gate verification.
- [x] Baseline maintenance slice for the unrelated mypy/formatting blockers.
- [x] Phase 1 / Slice 1B — occurrence execution state transitions and logical
      touch accounting.
- [x] Phase 2 — uncertain-send timeout and operator resolution; timeout
      orchestration, repository/use-case behavior, signal handling, authorized API
      wiring, review notifications, and dedicated tests are complete.
- [x] R3-1A — strengthened the canonical occurrence-plan contract with explicit
      send/hold/review/cancel/terminalize/expired outcomes, workspace contact-policy
      quiet-hours inputs, compatibility defaults, and shared preview/runtime wiring.
      Focused domain, application, API, Temporal-worker, Ruff, mypy, and diff checks
      pass. This is an increment of R3, not completion of the R3 gate.
- [x] R3-1B — made new occurrence idempotency keys stable across due-time
      rescheduling by using workflow/version/step/occurrence/channel identity, with
      an explicit fallback suffix and read compatibility for legacy timestamp-based
      keys. PostgreSQL creation now resolves conflicts by idempotency key and falls
      back to the historical identity lookup. Occurrences also persist the immutable
      brokerage `timezone_snapshot` used by the planner; migration `0069` is applied
      locally and legacy rows remain readable with a null snapshot.
- [ ] R8-1 release evidence and pilot sign-off, including provider-reconciliation
      replay/dispatch evidence, audited re-enable rehearsal, remaining browser
      state inspection, and human approval before expanding the pilot allowlist.

### 1.2 Slice R0 — formal gate reconciliation and gap matrix

R0 reconciles the execution ledger above with the formal phase Definitions of
Done below. A runtime slice being complete does not imply that the broader phase
gate is complete: the gate also requires the documented contracts, persistence,
integration layers, and verification evidence listed in that phase.

| Phase/gate | Current classification | Evidence or gap | Next slice |
|---|---|---|---|
| Phase 0 — contract, baseline, harness | Partially complete | Engineering baseline, fixtures, migration audit, and automated gates are recorded. Product/engineering approval, formal rollback ownership, and complete contract sign-off remain human-owned evidence. | R8-1 release evidence |
| Phase 1 — domain and persistence foundation | Implementation substantially complete; formal gate partial | R1-1 through R1-5, occurrence foundation, execution state, touch accounting, RLS, templates, reviews, notification policy, and isolation slices are implemented and tested. Canonical planner adoption, legacy recurring-loop migration, and final clean/legacy backfill evidence remain in later gates. | R3-1 canonical planner |
| Phase 2 — validation, publish, preview | Implementation complete; formal gate partial | R2-1/R2-2 provide authoritative validation, shared preview/runtime planning, publish locking/evidence, and immutable template binding. Final cross-phase acceptance and release evidence remain outstanding. | R3-1 canonical planner |
| Phase 3 — occurrence planning | Complete; release migration evidence remains | Basic scheduling, explicit planner outcomes, stable idempotency, touch limits, terminal behavior, timezone snapshots, callback reconciliation, explicit default-pause fallback, persisted step timing bases, and real PostgreSQL scheduler-concurrency evidence now exist. Legacy migration/backfill and non-production transaction-boundary rehearsal remain release evidence. | R3-1 canonical planner |
| Phase 4 — Temporal execution | Implementation substantially complete; migration/release evidence remains | Native orchestration, recurring activity names, explicit recurring input/snapshot fields, interruption signals, terminal handling, signal outbox, uncertain-send timeout, idempotent legacy-baseline policy, recurring duplicate-wake coverage, and recurring 30-day time-skipping coverage now exist. Live migration-job orchestration and production-style restart/replay release evidence remain gaps. | R4-1 recurring-loop contract |
| Phase 5 — send/review/notifications | Implementation substantially complete; release evidence remains | Pre-send checks, occurrence execution, review records/actions, uncertain resolution, callback reconciliation, timeout notification paths, idempotent persisted notification status, explicit commit-before-provider-dispatch, typed provider failure classification, one-fallback channel behavior, and bounded temporary-failure retry now exist. End-to-end notification release evidence remains. | R5-1 safe send and notification delivery |
| Phase 6 — API/frontend/operator UI | Implementation complete; formal gate partial | R6-1 through R6-4 provide server-authoritative preview/publish, occurrence/review operations, policy actions, message review, typed clients, and lead readback. Authenticated browser-state and final cross-phase acceptance evidence remain outstanding. | R8-1 release evidence |
| Phase 7 — migration/support operations | Implementation complete; formal gate partial | R7-1a through R7-1c provide authorized controls, overlap protection, operational reporting, and the support runbook. Live migration rehearsal and complete operator end-to-end evidence remain outstanding. | R8-1 release evidence |
| Phase 8 — hardening/release | Implementation complete; release gate partial | Pilot allowlist/flag controls, hold behavior, structured logs, rollback documentation, and automated regression gates exist. Manual provider replay, audited re-enable, authenticated UI-state coverage, monitoring ownership, and human sign-off remain outstanding. | R8-1 release evidence |

#### R0 ordered implementation slices

The remaining work follows the phase dependencies and avoids extending the
recent occurrence implementation with competing contracts:

1. **[x] R0-1 — contract and evidence register:** planning reconciliation and
   evidence separation are recorded; approval evidence remains human-owned.
2. **[x] R1-1 through R1-5 — foundation:** timing history, capability profiles,
   templates, reviews/notification policy, and persistence isolation are implemented.
3. **[x] R2-1/R2-2 — validation, preview, publish, and template binding:** the
   authoritative planner/validation and immutable publish evidence are implemented.
4. **[ ] R3-1 — canonical occurrence planner:** complete timing, cursor, timezone,
   customer-date, and transaction-boundary contracts.
5. **[ ] R4-1 — recurring Temporal loop:** complete migration, restart/replay,
   duplicate-wake, and long-duration integration coverage.
6. **[ ] R5-1 — safe send and notification delivery:** complete fallback,
   post-commit dispatch, notification delivery/retry, and end-to-end evidence.
7. **[x] R6-1 through R6-4 — API, UI, and review operations:** server-authoritative
   contracts, operator actions, policy decisions, and message reviews are implemented.
8. **[x] R7-1 — live controls, reporting, and runbook:** authorized controls,
   overlap protection, reporting, and support operations are implemented.
9. **[x] R8-1 implementation hardening:** fail-closed pilot controls, rollback
   documentation, structured logs, and automated regression gates are implemented.
10. **[ ] R8-1 release evidence:** execute the non-production manual replay and
    audited re-enable rehearsal, complete remaining UI-state checks, and collect
    human sign-off before pilot expansion.

R0 status: **complete as a planning reconciliation; no implementation slice is
marked complete by this section alone.**

#### R1-1 status

- [x] Added canonical customer-timing status, evidence-type, source, date,
      confidence, confirmation, and supersession fields in the domain model.
- [x] Added workspace-scoped customer-timing repository port and PostgreSQL
      model/adapter with a migration and indexed lead history lookup.
- [x] Added `apply_customer_timing_update`; AI-derived timing remains a candidate
      and operator timing is confirmed explicitly without changing live planning.
- [x] Added domain and fake-application tests for confirmation and AI candidate
      behavior.
- [x] `arch -arm64 uv run mypy app tests` passed; focused tests passed; migration
      head and `git diff --check` passed. Alembic database check remains blocked
      until the local database is upgraded to migration `0061`.

R1-1 is complete as an additive foundation. Compatibility projection into the
legacy profile and planner adoption remain intentionally deferred to R2/R3.

#### R1-2 status

- [x] Added the versioned, code-defined capability profile registry for all
      canonical paused-search reasons with interval, touch, duration, and safety
      restrictions from the approved contract.
- [x] Added single-reason resolution with explicit `resolved` and
      `hold_for_review` outcomes for missing, ambiguous, and competing reasons;
      no strictest-profile inference is performed.
- [x] Added bounded override validation that permits only stricter limits and
      requires preservation of profile safety tags.
- [x] Added domain tests covering the complete registry, resolution outcomes,
      and relaxed-override rejection.
- [x] `arch -arm64 uv run mypy app tests`, the full backend test suite (1,028
      tests), changed-file Ruff, and `git diff --check` passed.
- [x] No migration or rollback is required: capability profiles are immutable,
      code-defined policy and are not tenant-persisted in this slice.

R1-2 is complete as a code-defined policy foundation. Track-version persistence,
profile pinning at enrollment, and template-tag enforcement remain deferred to
R2/R3 and R1-3.

#### R1-3 status

- [x] Added immutable workspace-scoped `TemplateVersion` records with approved
      and deprecated lifecycle status, channel, purpose, prompt, content,
      variables, and permitted-use safety tags.
- [x] Added explicit template validation for versions, channels, variables,
      content, purpose, and approved safety tags.
- [x] Added a workspace-scoped PostgreSQL repository and migration
      `0062_add_template_versions.py` with composite uniqueness and indexes.
- [x] Added idempotent seeding from the existing paused-search template library;
      unresolved source keys are returned instead of silently omitted.
- [x] Added domain and fake-application tests for validation and idempotent
      backfill behavior.
- [x] Focused template, legacy-rendering, migration-head, Ruff, mypy, and
      `git diff --check` verification passed; the full backend suite also passed
      with 1,028 tests.

R1-3 is complete as the registry and seed foundation. Track-step
`template_version_id` references, published-track validation, and production
legacy-row backfill reporting remain deferred to R2/R3. Migration rollback is
the reversible drop of the additive `template_versions` table and indexes.

#### R1-4 status

- [x] Added immutable notification-policy, message/terminal/policy review, and
      notification domain records with explicit review transitions and policy
      resolution restrictions.
- [x] Added workspace-scoped repository ports, PostgreSQL adapters, and migration
      `0063_add_paused_search_reviews_notifications.py` for policies, reviews, and
      notifications with indexes, uniqueness, and reversible downgrade behavior.
- [x] Added idempotent workspace-default policy seeding and duplicate-safe review
      and notification persistence. Notification idempotency is enforced by
      workspace and idempotency key so nullable recipients cannot weaken it.
- [x] Added domain, fake-application, and PostgreSQL round-trip tests covering
      review transitions, default policy seeding, duplicate requests, and
      workspace isolation.
- [x] Focused R1-4 tests, the full backend suite, changed-file Ruff/formatting,
      mypy, Alembic head validation, and `git diff --check` passed. The full
      repository Ruff gate still reports six pre-existing line-length findings
      in unrelated test files; no unrelated files were changed for this slice.

#### R1-5 status

- [x] Added additive migration `0064_enable_workspace_isolation.py` without
      rewriting earlier migration history.
- [x] Enabled and forced the existing workspace RLS policy on customer timing,
      template, notification policy, review, and notification tables.
- [x] Added a workspace-scoped composite policy identity and a composite
      notification-to-policy foreign key so a notification cannot reference a
      policy version from another workspace.
- [x] Migration rollback removes the policy foreign key, composite uniqueness,
      and RLS policies in reverse dependency order.
- [x] Existing PostgreSQL RLS integration coverage verifies workspace-context
      denial and service-access behavior; repository tests retain explicit
      workspace-filter coverage for the new records.
- [x] Focused PostgreSQL isolation tests, full backend tests, Ruff,
      formatting, mypy, Alembic head validation, and `git diff --check` pass.
      Migration head is `0064_enable_workspace_isolation`.

#### R2-1 status

- [x] Added one authoritative domain validator returning structured errors and
      warnings for track identity, configuration, steps, platform limits, and
      code-defined pause-reason capability profiles.
- [x] Draft creation, draft update, publish, and non-persistent preview now use
      the same validator. Invalid drafts expose the exact findings instead of a
      second boolean-only rule set.
- [x] Added deterministic timeline preview using the canonical paused-search
      occurrence planner used by runtime scheduling, including local timestamps,
      bounded logical-touch volume, expiration, and a stable SHA-256 preview
      reference.
- [x] Publish acquires a workspace-scoped PostgreSQL `SELECT ... FOR UPDATE` lock
      on the track before reading publish state or applying retirement,
      activation, and reason-mapping mutations.
- [x] The append-only publish audit record now stores the exact validation
      report, normalized step manifest, effective touch/duration bounds, terminal
      behavior, and preview reference used for publication.
- [x] Added domain, fake-application, API-regression, and PostgreSQL tests for
      aggregated findings, profile limits, legacy review gating, deterministic
      preview/runtime parity, locked publish ordering, immutable evidence, and
      workspace-scoped `FOR UPDATE` SQL.
- [x] No migration was required: locking uses the existing track row and publish
      evidence uses the existing immutable audit-log JSONB details. The focused
      suite, full backend suite, changed-file Ruff, mypy, Alembic head validation,
      and `git diff --check` pass; migration head remains
      `0064_enable_workspace_isolation`. The full repository Ruff gate retains
      the six pre-existing unrelated test line-length findings documented in
      R1-4.

Approved-template-version resolution and the external preview/publish API
acknowledgement contract remain in the later R2/R6 slices; R2-1 does not claim
those surfaces.

#### R2-2 status

- [x] Added nullable workspace-scoped `template_version_id` binding on paused-
      search steps, preserving `template_key` as the authored/library key.
- [x] Added migration `0065_bind_paused_search_steps_to_templates.py` with a
      reversible composite foreign key, template identity uniqueness, and a
      lookup index. Existing unresolved legacy rows remain nullable rather than
      being guessed or silently rewritten.
- [x] Draft creation and updates resolve the latest approved workspace template
      for an authored key when no explicit version is supplied; explicit IDs are
      resolved by workspace. Publish persists safe legacy backfills and rejects
      missing, cross-workspace, deprecated, purpose-incompatible, channel-
      incompatible, unsafe, or unsupported template bindings.
- [x] Runtime paused-search execution carries the immutable bound template
      version through cadence planning and uses its content, subject, and prompt
      instead of trusting mutable key-based template lookup. Missing runtime
      bindings fail closed.
- [x] Publish evidence and deterministic preview references include the bound
      template identity and normalized immutable manifest (version, channel,
      purpose, lifecycle status, variables, and permitted-use tags).
- [x] Added domain, application, API, runtime drafting, and PostgreSQL migration
      coverage for binding resolution, publish blocking, safe legacy backfill,
      workspace-scoped persistence, runtime template selection, and evidence.
- [x] Migration upgrade, changed-file Ruff, mypy, focused tests, Alembic head
      validation, and `git diff --check` pass. Migration head is
      `0069_snapshot_paused_occurrence_timezone`.

#### R3-1A status — explicit planner outcomes and quiet-hours policy

- [x] The occurrence planner now returns explicit outcome values for send, hold,
      review, cancel, terminalize, and expiration paths. Legacy serialized outcome
      values remain readable for occurrences created by the first implementation.
- [x] Quiet-hours inputs are explicit on both the legacy next-action planner and
      the occurrence planner. The default remains 10:00–17:00, while a workspace
      contact policy can provide a narrower brokerage-local window or disable the
      window explicitly.
- [x] Recurring scheduling loads the workspace contact policy before planning, and
      preview uses the same policy inputs so preview/runtime timing does not diverge.
- [x] Added coverage for non-sendable cancellation, missing-timing review,
      occurrence terminalization, custom quiet hours, disabled quiet hours, invalid
      windows, application wiring, API preview wiring, and Temporal activity wiring.
- [x] Focused verification passed: 34 timing tests, 58 application cadence/schedule/
      preview tests, 35 API/Temporal-worker tests, changed-file Ruff, changed-file
      mypy, and `git diff --check`.

R3-1A is complete as the planner-contract increment. Customer-date/default-pause
anchors, persisted timing bases, complete cursor/outcome persistence, and scheduler
concurrency evidence are now complete. The remaining post-commit dispatch boundary
belongs to R5, not R3.

R3-1B is complete as the idempotency-key and timezone-snapshot increment. R3-1C now
has real PostgreSQL evidence at the scheduler boundary: concurrent duplicate
planners produce one occurrence 2 and one persisted paused-search cursor state after
occurrence 1 is complete. Backfill/legacy workflow migration policy remains a later
R4 slice.

The customer-date/timing-basis matrix is now implemented. Track versions persist a
validated default pause duration, tracks expose an explicit default-duration fallback
policy, and each step persists a timing basis (customer re-engagement date, workflow
creation, or previous occurrence). Legacy maintenance-interval fallback remains
available and unchanged for existing published tracks.

R4-1 contract increment is implemented: recurring workflows carry an explicit mode
and pinned track version, expose timing/review/migration/cancellation/terminal signals,
and use separately registered recurring schedule/execute activity names while sharing
the locked planner and final pre-send path. Restart/replay and non-production
migration evidence remain release gates.

Recurring Temporal durability evidence now includes a real time-skipping worker test
through the recurring activity names over a 30-day wait, plus the existing duplicate
reschedule-signal and 365-day standard-cadence tests. This proves the contract at the
Temporal worker boundary; a disposable-environment worker restart/replay rehearsal
remains an operational release gate.

The legacy migration boundary is now explicit and fail-closed. Complete legacy
workflow facts produce a deterministic `migrated_legacy` occurrence with occurrence
number zero, zero logical touches, an idempotency key, and a timezone snapshot.
Incomplete pinned-track/cursor facts produce a review hold. Existing accepted-touch
counts at the pinned limit produce a migrated baseline plus terminalization intent;
the baseline never grants a new touch. Database batch enumeration and a disposable
environment migration rehearsal remain separate release evidence.

R5-1 notification durability increment is implemented: uncertain-send timeout review
notifications are written as pending, deduplicated by workspace/idempotency key, and
transitioned to accepted or failed around provider dispatch. The cadence execution
path now commits prepared message/occurrence state before invoking an SMS or email
provider, with an explicit unit test proving callback-before-provider ordering. The
full provider fallback/retry matrix and non-production dispatch rehearsal remain
release gates.

The provider fallback matrix is now explicit. Adapter errors map to permanent,
temporary, or uncertain outcomes; only a permanent pre-acceptance failure may select
the one configured fallback channel. Temporary and uncertain failures stop without
fallback, and fallback dispatch uses a distinct idempotency key while preserving one
logical touch. Temporary failures retry once with the same provider idempotency key;
uncertain failures never retry. Non-production provider replay remains operational
release evidence.

#### R6-1 server-authoritative API/UI contract status

- [x] Added workspace/role-checked unsaved-draft validation and deterministic
      preview routes. Preview responses separate blocking errors from warnings,
      expose the immutable preview reference, and do not persist draft input.
- [x] Added publish acknowledgement fields for draft version, preview reference,
      and warning confirmation. The server recomputes the current reference and
      rejects stale versions, forged references, and unacknowledged warnings.
- [x] Added workspace-scoped approved-template and capability-profile reads, with
      static routes registered before the UUID track-detail route.
- [x] Updated the typed frontend client and paused-search editor to select approved
      templates, render server preview output, require warning acknowledgement, and
      publish only through the acknowledged server contract.
- [x] Added API contract and frontend client tests. Full backend pytest/mypy and
      frontend typecheck/lint/test verification pass; the backend repository Ruff
      gate retains six pre-existing unrelated test line-length findings.

#### R6-2 operator occurrence and review surface status

**Approved approach:** add a dedicated paused-search operations API and adapt the
existing review queue and lead-detail surfaces. Keep occurrence/review rules in
application use cases and domain transitions; the frontend only renders server
responses and submits authorized commands.

- [x] Add workspace-scoped occurrence list/detail read contracts under the
      existing `/paused-search-tracks` route family.
- [x] Add workspace-scoped review list/detail and fixed action contracts for
      message, terminal, and policy reviews. Policy reviews expose only
      `skip`, `resume_after_revalidation`, `migrate`, and `terminalize`.
- [x] Normalize uncertain-occurrence resolution under the documented route
      family without introducing a parallel public `/paused-search` family.
- [x] Enforce assignment/manager/admin authorization, idempotency, actor reason,
      and readback of resulting occurrence/review/workflow state.
- [x] Add typed frontend clients and integrate review queue filters/actions plus
      lead-detail occurrence and terminal-state readback.
- [x] Add focused API, application, frontend, tenant-isolation, and permission
      tests; record migration/rollback impact and verification evidence here.

Implementation notes: this slice is additive and uses the existing occurrence,
review, and workflow tables; no migration or rollback operation is required.
The API action state guard makes repeated commands safe by returning the already
resolved review instead of applying a second transition. The narrow operations
repository port avoids changing the shared cadence/delivery occurrence contract.

Verification evidence: backend full pytest passes, backend mypy passes for 511
source files, changed-file Ruff and `git diff --check` pass, and the focused
PostgreSQL repository compatibility tests pass. Frontend format, typecheck,
ESLint, and Vitest pass with 16 test files and 84 tests. No migration or rollback
work is required for this additive slice. Repository-wide Ruff still reports the
six pre-existing unrelated test line-length findings recorded under R6-1; the
frontend commands still report the existing Node 20.14.0 versus `>=20.19.0`
engine warning.

#### R6-3 policy-review decision execution status

- [x] Approved Approach A: compose existing workflow resume, paused-search
      override, migration, and transition use cases rather than duplicating rules.
- [x] Added migration target and terminal behavior request fields with server-side
      validation for the corresponding policy actions.
- [x] Policy resolution now executes the selected action before saving `resolved`,
      preserving the existing eligibility, permission, audit, occurrence-cancel,
      and Temporal outbox paths.
- [x] Added typed frontend payload support for migration and terminalization data.
- [x] Add focused action-path tests and complete full backend/frontend verification.

Implementation note: the existing route transaction remains the commit boundary;
the composed resume use case receives that commit callback so review and workflow
changes are committed together where supported. No migration is required.

Verification evidence: backend full pytest passes, focused Ruff and mypy checks
pass, and frontend `pnpm check` passes with 16 test files and 85 tests. The known
Node 20.14.0 versus `>=20.19.0` engine warning remains; no migration or rollback
work is required for this additive slice.

#### R6-4 durable message-review execution status

- [x] Enforce `review_required` during paused-search cadence execution after draft
      planning and before any provider call.
- [x] Bind each message review to the exact pending outbound message ID and immutable
      message version, with one review per workspace, occurrence, and review kind.
- [x] Hold Temporal on `review_requested`; approval authorizes only the bound version
      and rejection cancels the pending message without consuming a logical touch.
- [x] Queue append-only review audit events and `blocked-review-completed` Temporal
      signals in the same request transaction as the review and occurrence changes.
- [x] Add message edit support that creates a new immutable outbound-message version,
      cancels the superseded pending version, and remains pending for explicit approval.
- [x] Add message/version readback, typed frontend contracts, an accessible reasoned
      decision/edit dialog, and assigned-agent access to their scoped review queue.
- [x] Add cadence, operation, API-client, route-navigation, and Review Queue page tests.

Migration note: Alembic revision
`0066_link_paused_search_reviews_to_messages` adds nullable message ID/version columns,
an outbound-message foreign key, and a unique workspace/occurrence/kind constraint.
Existing legacy reviews remain readable but cannot be approved as message reviews until
they reference a valid pending message. Downgrade removes the constraint, foreign key,
and columns; rollback should first pause review-required tracks so no held workflow loses
its approved-version binding.

Verification evidence: the full backend pytest suite passes, mypy passes for 513 source
files, and focused Ruff checks pass. Frontend `pnpm check` and production build pass with
17 test files and 87 tests. The existing Node 20.14.0 versus `>=20.19.0` warning and Vite
bundle-size warning remain. Browser inspection at desktop, tablet, and mobile widths was
attempted but blocked because the environment has no Chrome executable; no browser-review
claim is made for this slice.

#### R7-1 direct workflow controls and operational safety

**Approved approach:** extend the existing pause, resume, override, transition, occurrence,
and reporting paths. Do not introduce a generic workflow-action engine.

##### R7-1a migration, skip, and terminalization safety

- [x] Migration and skip-next-touch cancel stale open occurrences while preserving their
      immutable history and the workflow's cumulative logical-touch count.
- [x] Occurrence persistence increments `logical_touch_count` only on the first transition
      into `sent`; duplicate delivery callbacks remain idempotent.
- [x] Added direct paused-search terminalization for complete-keep-paused, pause-for-review,
      and close-automation behaviors, using the existing workflow transition and occurrence
      cancellation paths.
- [x] Temporal `RESCHEDULE_REQUESTED` is queued only for pause-for-review; terminal states
      do not receive a continuation signal.

##### R7-1b resume revalidation and no-overlap enforcement

- [x] Manual resume locks the current lead row and latest workflow before re-reading state,
      ownership, suppression, consent, contactability, and current human-activity facts.
- [x] Resume is blocked when CRM-recorded agent activity occurred after the workflow's last
      transition, or when another active paused-search workflow exists for the same lead.
- [x] Added workspace-scoped locked active-workflow reads and a PostgreSQL partial unique
      index for one active paused-search workflow per lead/workspace.
- [x] Added eligibility, action-path, workflow-lock, repository, API-regression, migration,
      and no-overlap coverage.

Migration note: Alembic revision `0067_enforce_active_paused_search_workflow_overlap`
adds the partial unique index on `lead_workflows(workspace_id, lead_id)` for workflows with
a pinned paused-search track in queued or active/recovering states. Downgrade drops only
that index. If legacy data contains overlapping active paused-search workflows, the upgrade
fails closed and requires operator reconciliation before applying the index.

Verification evidence: focused resume/API/repository tests, the full backend pytest suite,
full mypy, changed-file Ruff, `git diff --check`, migration compatibility, and
`alembic heads` all pass. Frontend/browser verification is not part of this backend slice;
the existing Node 20.14.0 versus `>=20.19.0` warning and missing Chrome limitation remain
unchanged.

##### R7-1c operational reporting and support operations

- [x] Workspace operational reporting now includes due, held, review-pending, expired,
      failed, uncertain, terminal, and fallback paused-search occurrence counts.
- [x] Fallback use is persisted on the occurrence when the selected outbound channel differs
      from the authored paused-search channel; this avoids inferring fallback from free text.
- [x] Added the workspace operations dashboard health strip with warning states for due,
      review, uncertain, failed, expired, and fallback work.
- [x] Added the paused-search operations runbook covering stale timers, uncertain sends,
      stuck reviews, provider failures, manual migration/resumption, and escalation data.

Migration note: Alembic revision `0068_add_paused_occurrence_fallback_marker` adds a
non-null `fallback_used` marker with a false backfill default, and revision
`0069_snapshot_paused_occurrence_timezone` adds the nullable immutable timezone snapshot.
Downgrades remove only their respective additive columns. Existing occurrences remain
readable; legacy rows have `timezone_snapshot = null` until a later migration policy is
approved.

Verification evidence: full backend pytest, full mypy, focused backend Ruff, workspace
reporting/API tests, frontend reporting API test, frontend typecheck, lint, and Prettier
checks pass. The package manager continues to warn that the environment uses Node 20.14.0
while the project requires `>=20.19.0`.

##### R8-1 bounded rollout hardening status

- [x] Added a configuration-based pilot allowlist through
      `RECURRING_PAUSED_SEARCH_PILOT_WORKSPACE_IDS`; an empty allowlist is fail-closed.
- [x] Enforced the persisted recurring-maintenance flag during paused-search enrollment,
      occurrence planning, and cadence execution. Disabled or non-allowlisted work holds
      without creating a new occurrence or sending a message.
- [x] Mapped the hold result through the cadence and Temporal contracts so a held workflow
      waits for an explicit resume/unblock signal instead of terminating or busy-looping.
- [x] Added structured completion logs with workspace, lead, workflow, cadence-step,
      occurrence, message, status, and reason identifiers; no message body is logged.
- [x] Added focused coverage for disabled flags, pilot allowlist denial, DST calendar-day
      scheduling, and paused-search enrollment hold behavior.
- [x] Documented pilot activation, rollback, initial alert thresholds, and ownership in the
      paused-search operations runbook.
- [x] Closed the provider-callback wiring gap: Twilio, SendGrid, and Mailgun routes now
      pass the occurrence, lead-workflow, and Temporal signal-outbox repositories into
      callback processing. An API regression test verifies SendGrid uncertain-delivery
      reconciliation, one logical touch, workflow touch accounting, and one
      `provider_delivery_reconciled` signal entry.
- [x] Re-ran the release-focused callback, dispatcher, and audited-settings suite:
      38 tests passed. The full backend suite passed 1,084 tests, mypy passed for
      514 files, and changed-file Ruff plus `git diff --check` passed under native
      arm64 Python.

Verification evidence: focused scheduling, enrollment, cadence, Temporal, and timing tests;
changed-file Ruff; mypy for the backend and changed tests; and `git diff --check` pass.
Full backend pytest and mypy pass. Frontend `pnpm check` passes across 18 test files and 88
tests. Tenant/RLS/API authorization tests pass. The clean/legacy migration compatibility test
passes, and the local development database was upgraded from revision `0065` to head
`0068_add_paused_occurrence_fallback_marker`. Basic responsive sign-in inspection has been
completed at desktop, tablet, and mobile widths; authenticated loading, empty, error,
permission-denied, and reduced-motion states remain untested. Product, QA, security, and
operations sign-off plus production pilot approval remain human-owned release evidence. The
automated provider-callback route, Temporal signal-dispatch, and audited-settings regression
coverage passes; no live provider replay or audited re-enable was performed, so the pilot
remains disabled.
The release checklist is maintained in
`docs/release/paused-search-r8-release-checklist.md`. The local development database is
currently at head `0069_snapshot_paused_occurrence_timezone`.
It contains the ordered manual protocol for environment setup, browser inspection,
fail-closed verification, allowlisted pilot smoke testing, interruption safety, rollback,
and release decision evidence; execute those steps sequentially before widening rollout.

Do not mark a slice complete until its implementation, tests, migration/rollback
notes, and status evidence are recorded here.

## 2. Current implementation baseline

The following behavior already exists and must be extended rather than replaced:

- Domain track models in `app/domain/campaigns/paused_search_tracks.py`.
- Timing planner in `app/domain/campaigns/paused_search_timing.py`.
- Track administration in `app/application/use_cases/paused_search_track_admin.py`.
- Track pinning in `app/application/services/paused_search_track_pinning.py`.
- Paused-search enrollment in
  `app/application/use_cases/start_paused_search_campaign_enrollment.py`.
- Next-action scheduling in
  `app/application/use_cases/schedule_next_paused_search_action.py`.
- Cadence execution in
  `app/application/use_cases/campaign_cadence_execution.py`.
- Temporal orchestration in
  `app/infrastructure/workflows/temporal/lead_nurture.py`.
- Postgres models and repositories in
  `app/infrastructure/persistence/postgres/`.
- Admin API in `app/interfaces/api/v1/paused_search_tracks.py`.
- Admin schemas in `app/interfaces/api/schemas/paused_search_tracks.py`.
- Admin UI in `miller-schackman-web/src/components/settings/PausedSearchTracksCard.tsx`.

Existing behavior that must remain true:

1. Published versions are immutable.
2. New enrollments pin the published version resolved from the reason mapping.
3. Existing workflows retain their pinned version unless an authorized migration
   explicitly changes it.
4. Temporal owns durable waiting, but application rules own every decision to
   send, defer, pause, hand off, suppress, or terminate.
5. Every send runs the shared pre-send checks immediately before provider
   dispatch.
6. Consent, suppression, do-not-contact, A2P 10DLC, human ownership, recent
   activity, quiet hours, frequency limits, and idempotency cannot be relaxed by
   track configuration.

## 3. Scope

### In scope

- Calendar-day recurring maintenance in the brokerage timezone.
- Bounded per-step occurrences and track-level customer-facing touch limits.
- Maximum track duration and explicit terminal behavior.
- Explicit timing-basis semantics.
- Customer-date precedence and missing-date policies.
- Per-step primary and fallback channels.
- Code-defined pause-reason capability profiles.
- Approved, versioned in-application templates.
- Selective per-step message review.
- Action-oriented notifications.
- Draft validation, timeline preview, warnings, publishing, and audit records.
- Durable occurrence, review, retry, cancellation, and terminal records.
- Temporal recurring execution and interruption behavior.
- Operator migration, override, review, and readback surfaces.
- Backend, persistence, API, Temporal, frontend, and end-to-end verification.

### Out of scope

- A dynamic rules engine.
- Weighted lead scoring.
- MLS/IDX or generic listing-marketplace search.
- Voice agents, calling, appointment booking, negotiation, or advice.
- Raw MIME parsing or advanced email-thread reconstruction.
- Automatic handoff without a qualifying application-owned signal.
- Automatic re-enrollment loops.
- Automatic CRM lead closure at track completion.
- Provider-specific objects outside infrastructure adapters.

## 4. Approved V1 decisions

These decisions are part of the implementation contract, not suggestions.

### 4.1 Calendar scheduling

- Recurring intervals use whole calendar days in the brokerage timezone.
- The initial supported recurring interval range is 14 through 365 days.
- “Monthly” means 30 days in V1; calendar-month arithmetic is excluded.
- One-time reactivation delays may be shorter than 14 days, subject to the
  applicable profile and platform limits.
- Dates are calculated in the brokerage timezone and persisted as UTC instants.
- The existing allowed sending window remains the final authority. V1 defaults to
  10:00 through 17:00 brokerage time.
- Quiet-hour deferral rolls a due action forward to the next allowed window; it
  does not create another logical touch.
- DST changes must not change the configured calendar-day meaning.
- V1 does not add holiday-calendar behavior.

### 4.2 Touch and occurrence accounting

- A **scheduled occurrence** is one planned execution of one track step.
- A **logical touch** is one customer-facing outbound message accepted by a
  provider.
- Provider retries of the same idempotent message do not create additional
  logical touches.
- A primary-channel rejection followed by a successful permitted fallback is one
  logical touch, not two.
- Provider acceptance consumes one touch even when later delivery status is
  uncertain.
- A review request, policy block, suppression, skip, cancellation, or provider
  failure before acceptance consumes zero touches.
- Manual agent messages are not counted against automated track touches.
- Track limits are strictest-wins across profile, track, platform frequency, and
  platform AI-interaction limits.
- The pre-flight digest veto applies at initial cadence start, not before every
  recurring occurrence. After a lead clears that veto window, later outreach is
  controlled by the normal operator pause action and immediate pre-send checks.
  This policy is the code-owned constant `RECURRENCE_VETO_POLICY="enrollment_only"`.

### 4.3 Limits

- `max_occurrences` limits executions of one recurring step.
- An occurrence counts toward `max_occurrences` when it is durably created,
  regardless of whether it is later sent, reviewed, skipped, cancelled, or
  deferred. Provider retries and duplicate wake-ups do not create another
  occurrence number.
- `max_total_touches` limits customer-facing automated messages across the track.
- There is no separately configurable phase limit in V1; phase totals are derived
  from step limits.
- Provider retry policy is code-owned and is not the same as touch limits.
- Existing `max_attempts` must be renamed or clarified at the domain/API boundary
  as provider retry behavior. A compatibility migration may retain the old column
  temporarily, but it must not be interpreted as customer-touch repetitions.

### 4.4 Maximum duration and expiration

- Every published track has `max_duration_days`.
- Minimum configurable duration: 30 days.
- Normal maximum: 365 days.
- Platform hard maximum: 730 days.
- Capability profiles may impose a stricter maximum or allow up to the hard cap.
- Duration starts when the paused-search workflow is created.
- Calendar duration continues through ordinary waiting, review hold, and temporary
  deferral. Human handoff, suppression, and terminal completion end automation.
- Expiration cancels remaining automated occurrences, completes the workflow,
  retains the lead's `paused_search` business state, notifies the assigned agent,
  and requires explicit re-enrollment or authorized action for future automation.
- Expiration does not automatically hand off, resume normal nurture, or close the
  lead in the CRM.

### 4.5 Terminal behavior

The published track must contain one of these values:

- `complete_keep_paused`: complete the workflow and retain paused-search state.
- `pause_for_review`: stop automation and create an operator review item.
- `close_automation`: close this automation path until explicit re-enrollment.

The default is `complete_keep_paused`.

Terminal outcomes have these exact workflow semantics:

- `complete_keep_paused` transitions the workflow to `completed` while retaining
  the lead's paused-search business state. The completed workflow cannot resume;
  a future automated path requires explicit re-enrollment.
- `pause_for_review` transitions the workflow to `paused`, creates a terminal
  review record, and permits only an authorized, audited resolution. Resolution
  must re-run eligibility and may resume the workflow, migrate it, or terminalize
  it.
- `close_automation` transitions the workflow to `closed`; only explicit
  re-enrollment can create a future automation path.

No terminal behavior may automatically create `human_handoff`, resume normal
nurture, re-enroll the lead indefinitely, or close the CRM lead. Handoff remains
an application decision based on meaningful interest, a human request, or another
approved trigger.

### 4.6 Customer dates

- A valid explicit customer-provided date is the earliest reactivation date and
  cannot be ignored by track configuration.
- Missing-date policies are `use_fallback_timing` and `hold_for_review`.
- Every track also has `default_pause_duration_days`, used as the fallback
  customer-date anchor when `use_fallback_timing` is selected and no valid date
  exists. It must be at least 30 days, cannot exceed `max_duration_days`, and may
  be tightened by the effective capability profile.
- `ignore_customer_date` is not supported in V1.
- Maintenance before a normal reactivation date is allowed only when the phase
  permits it, the lead did not request no contact until the date, and all
  pre-send checks pass.
- An explicit `no_contact_until` date overrides every maintenance and
  reactivation action, regardless of the configured track or fallback policy.
- An explicit instruction such as “contact me after September” takes precedence
  over track settings.
- Store a customer timing date as a date-only value interpreted in the brokerage
  timezone unless a validated date-time with an explicit timezone is available.
- A past valid date is immediately eligible for the applicable phase after normal
  checks.
- A past valid customer date is immediately reactivation-eligible and takes
  precedence over `use_fallback_timing`; it is never treated as a missing date.
- Conflicting or ambiguous dates cause a review hold rather than an automated
  guess.

### 4.7 Channel fallback

- The track defines permitted channels overall.
- Each step has one primary channel and at most one fallback channel.
- Tertiary fallback is not supported in V1.
- Fallback is allowed only when the primary channel is permanently unavailable,
  independently blocked, or rejected before provider acceptance; the fallback is
  permitted by the step and track, has valid consent, and passes all pre-send
  checks.
- Temporary provider outages are retried or deferred, not immediately switched
  to fallback.
- Unknown or uncertain provider acceptance never triggers fallback.
- An `uncertain` occurrence is not retried automatically. It waits for a provider
  callback for 24 hours, then transitions to `failed`, writes
  `UNCERTAIN_SEND_TIMEOUT`, pauses the workflow for operator review, and notifies
  the assigned agent/manager. An operator may explicitly mark it `sent` (one
  touch), `failed` (zero touches), or `skipped`; each choice is audited. This is
  the only path that may consume a touch by operator action rather than provider
  acceptance.
- Do-not-contact, reply, human ownership, or any all-channel suppression blocks
  both primary and fallback sends.
- If a lead opts out of the primary channel and the next step has no permitted
  fallback, create a review hold with the channel, lead, and step as context;
  do not silently skip the track forever.
- Primary and fallback use channel-compatible approved template versions.

### 4.8 Review

Publishing review and message review are separate controls.

- Only brokerage admins may publish a track.
- Publishing requires validation, timeline preview, and explicit confirmation.
- A second-person publish approval is not required in V1.
- `requires_review_before_publish` is removed from the V1 request, response, and
  domain contract. The existing field is retained only as legacy migration
  metadata; stored drafts that have it set must be explicitly resaved under the
  new contract before publication. No published version can rely on this field.
- `review_required` is configured per step.
- Assigned agents may review their assigned leads; managers may review appropriate
  team leads; brokerage admins may review any workspace lead.
- Reviewers may approve, reject, or edit and approve.
- Rejecting a message review closes that occurrence as `skipped` with zero
  touches and allows the fixed recurrence policy to plan the next occurrence;
  rejecting a terminal review leaves the workflow paused and requires a separate
  authorized terminal or resume action. Neither rejection sends automatically.
- Every review action is audited.
- Approval never bypasses immediate pre-send checks.
- Approval applies to a specific generated message version. Editing creates a new
  version and requires approval again.
- The code-owned default review expiry is 48 elapsed hours from request.
- A message review that expires closes its occurrence as `skipped` with reason
  `MESSAGE_REVIEW_EXPIRED`, consumes zero customer-facing touches, and advances
  to the next occurrence only when the recurring step, duration, and touch limits
  still permit it.
- A terminal review that expires leaves the workflow in `paused`, writes
  `TERMINAL_REVIEW_EXPIRED`, and sends a manager escalation; no automatic
  transition to `closed`, resume, or send occurs.
- Review expiry is not administrator-configurable in V1. `review_expiry_at` is
  computed from the named 48-hour domain constant and persisted on the review.

#### Policy-review lifecycle

`review_kind=policy` is used when automation is blocked by a policy or channel
condition that requires an operator decision rather than message approval. V1
triggers are:

- permanent provider failure with no permitted fallback;
- channel opt-out or consent loss with no permitted fallback;
- uncertain-send timeout after provider reconciliation is unavailable;
- no published track mapping for the confirmed pause reason;
- a policy/compliance block that cannot be resolved by an automatic retry.

A policy review has no generated message to approve and never uses the
message-edit flow. It appears in the same review queue with its policy reason,
current occurrence, provider/channel details, and recommended action. It remains
open until an authorized action; it has no automatic 48-hour expiry. Manager
escalation occurs after 24 hours and repeats according to the notification policy.

The only policy-review resolution actions are:

- `skip`: close the occurrence with zero touches; advance only if the reason is
  safe to advance and the planner permits it;
- `resume_after_revalidation`: close the policy review and plan a new future
  occurrence only after consent, suppression, ownership, human activity,
  channel, and feature-flag checks pass;
- `migrate`: pin a new eligible published version and cancel stale future work;
- `terminalize`: apply an authorized terminal behavior.

These actions are audited and idempotent. `approve`, `reject`, and message edit
are invalid for `review_kind=policy` and return a structured conflict response.
The review status becomes `resolved` only after the selected action commits.

### 4.9 Capability profiles

Capability profiles are code-defined platform policy. Admins may choose stricter
settings but may not add capabilities, relax safety restrictions, allow prohibited
content, or exceed profile maximums.

Initial profiles and maximums:

| Reason | Recurring interval | Max touches | Max duration | Restriction |
|---|---:|---:|---:|---|
| `rented_temporarily` | 30–180 days | 5 | 730 days | Prefer customer/lease date |
| `timing_not_right` | 30–180 days | 4 | 365 days | Generic, low-pressure messages |
| `waiting_for_rates` | 30–90 days | 6 | 365 days | No rate predictions or financial advice |
| `waiting_for_inventory` | 14–60 days | 6 | 180 days | Approved, fresh listing context only |
| `financial_prep` | 30–90 days | 6 | 365 days | No mortgage, credit, tax, or investment advice |
| `personal_life_timing` | 60–180 days | 4 | 730 days | Respectful content; no sensitive assumptions |
| `other_known_pause` | 60–180 days | 4 | 365 days | Generic content; review unclear timing |

The effective profile is resolved at enrollment from one canonical
`pause_reason_code`. Multiple simultaneous reasons are not supported in V1. If
classification or operator input produces competing or ambiguous reasons, the
lead enters `hold_for_review` with the evidence recorded; the application never
chooses a strictest profile implicitly. The resolved profile version is pinned
with the workflow and changes affect new enrollments unless an explicit migration
is performed.

### 4.10 Templates

- Unknown, inactive, or unpublished template references block publishing.
- V1 uses an approved, versioned in-application template library.
- Track steps reference `template_version_id`, not arbitrary text or a free-form
  template key.
- SMS and email templates are channel-specific.
- Allowed variables are explicit and validated before publishing and rendering.
- Missing required context must produce a safe review/hold outcome, not invented
  content.
- A referenced template version cannot be deleted while used by a published track
  version or active workflow.
- Template content and permitted-use tags are platform/engineering-managed in V1.
  Brokerage admins select published approved templates and configure track
  metadata such as `message_goal`, but cannot edit arbitrary template bodies or
  prompts.
- Each approved template version carries code-defined permitted-use tags such as
  `no_financial_advice` and `listing_context_allowed`. Capability-profile
  validation requires all tags for the selected reason; admins cannot add safety
  tags, and only platform-approved template publication can do so.

### 4.11 Timing updates and reply confirmations

- When a reply or authorized operator action changes the canonical customer timing
  record or its compatibility projection `reengagement_not_before`,
  the workflow recomputes only the next occurrence anchor. It does not reset the
  current recurring-step occurrence counter or rebuild historical occurrences.
- Future occurrences are planned lazily when the Temporal wait wakes.
- A reply such as “still not ready, contact me in 60 days” creates a timing
  candidate, which the application timing-update use case validates and promotes
  to the canonical timing record, emits a reschedule signal, and preserves the
  current occurrence count. If no valid date can be extracted, the lead enters
  `hold_for_review`.
- An operator timing override follows the same next-occurrence-only rule and is
  separately audited.

## 5. Canonical domain model

The following names are the target internal contract. Existing names may be
retained temporarily through compatibility adapters, but the application layer
must expose these semantics.

### 5.0 Customer timing contract

The canonical customer timing record is an application-owned, workspace-scoped
history. It is separate from the track configuration and from the automation's
maximum duration.

Each record contains:

- `customer_timing_id`, `workspace_id`, `lead_id`, and optional `workflow_id`;
- `timing_kind`: `reactivation_date` or `no_contact_until`;
- `effective_date` as a date-only value, plus `effective_timezone`;
- `source`: `lead_message`, `crm_activity`, `assigned_agent`, `operator`, or
  `system_import`;
- `evidence_message_id`, `evidence_activity_id`, or redacted evidence reference;
- extraction/classification model and prompt version when AI produced the
  candidate;
- confidence, ambiguity status, `observed_at`, `confirmed_at`, superseded-record
  reference, and audit metadata.

The current lead projection retains `reengagement_not_before` for compatibility,
but it is derived from the active canonical timing record and is not an
independent source of truth. A candidate extracted by the LLM is never effective
until the application timing-update use case validates it. The update flow is:

1. Inbound CRM/provider event is deduplicated and stored.
2. The reply-classification service may return a structured timing candidate and
   evidence, but cannot mutate lead timing or schedule a send.
3. `apply_customer_timing_update` validates date shape, timezone, source,
   confidence, no-contact meaning, and conflicts with the current record.
4. The use case either confirms the candidate, supersedes the previous record,
   or creates an ambiguity/review hold.
5. It writes a `customer_timing.updated` audit/outbox event and signals Temporal
   to recompute only future scheduling.

An explicit no-contact-until instruction is stored as `timing_kind=no_contact_until`
and overrides all track timing. A normal reactivation date is stored as
`timing_kind=reactivation_date` and does not itself prohibit maintenance before
the date. Conflicting active records are retained for evidence but exactly one
confirmed record may be effective; unresolved conflict produces `hold_for_review`.

### 5.1 Timing-basis contract

`timing_basis` is a closed enum with these values:

- `after_phase_start`: one-time step due `delay_days` after the phase starts.
- `after_previous_step`: one-time step due `delay_days` after the previous
  distinct step closes successfully or with an advancing skip outcome. Human,
  suppression, safety, and handoff stops do not create a next step.
- `after_previous_occurrence`: recurring step due `interval_days` after the
  previous occurrence reaches a terminal outcome.
- `before_customer_date`: one-time step due `delay_days` before the valid
  customer date; only valid for a phase that permits customer-date scheduling.
- `before_pause_end`: one-time step due `delay_days` before the resolved pause-end
  anchor. The anchor is the confirmed `reactivation_date` when present, otherwise
  `workflow_created_at + default_pause_duration_days` when
  `use_fallback_timing` applies. If neither is available, the planner returns
  `hold_for_review`.
- `at_customer_date`: one-time step due on the valid customer date; only valid
  for reactivation.

If `before_customer_date` or `before_pause_end` produces a due date already in the
past while its resolved anchor is still future, a maintenance occurrence is skipped with
`BEFORE_DATE_ELAPSED` and zero touches. For reactivation, the step is scheduled
at the nearest allowed window before the customer date, or immediately when no
earlier window remains. If the customer date is itself past, the past-date rule
in Section 4.6 applies.

Missing or ambiguous dates use the track's missing-date policy. No other timing
basis may be accepted from API payloads or persisted configuration.

### 5.2 Track-version configuration

`PausedSearchTrackVersion` must contain or resolve:

- `track_version_id`, `workspace_id`, `track_id`, `version_number`, `status`.
- `track_family`, `enabled`, `allowed_channels`.
- `default_for_reason_codes` and resolved capability profile reference.
- `default_pause_duration_days`, `max_duration_days`, `max_total_touches`.
- `terminal_behavior`.
- `missing_customer_date_policy`.
- `notification_policy_id` or an immutable notification-policy snapshot.
- Existing fallback timing and reactivation-window configuration where still
  applicable. New versions use `missing_customer_date_policy` plus explicit
  `timing_basis`; `fallback_timing_policy` is not accepted on new requests.
- `created_by_user_id`, `created_at`, `published_at`, and audit metadata.

### 5.3 Track step

`PausedSearchTrackStep` must contain or resolve:

- `step_id`, `workspace_id`, `track_version_id`, `step_order`, `phase`.
- `timing_basis`.
- `delay_days` for one-time or phase-relative timing.
- `interval_days` for recurring timing.
- `max_occurrences` for recurring steps.
- `primary_channel` and optional `fallback_channel`.
- `template_version_id`.
- `message_goal`.
- `review_required`.
- Review expiry is code-owned in V1: each occurrence stores `review_expiry_at`
  using the 48-hour default; no step-level skip or expiry policy is configurable.

Invalid combinations must be rejected, including missing interval for a recurring
step, fallback not included in allowed channels, customer-date timing on a step
that cannot use a customer date, and reactivation steps with incompatible phase
timing. Published phases must be ordered and reachable: maintenance may precede
reactivation, reactivation may not return to maintenance, and a track must have a
reachable terminal outcome.

### 5.4 Runtime occurrence

Add an append-only, workspace-scoped occurrence record. It must include:

- `occurrence_id`, `workspace_id`, `lead_id`, `workflow_id`.
- Pinned `track_version_id`, `step_id`, `phase`, `occurrence_number`.
- `scheduled_for`, `due_at`, `created_at`, and relevant timezone/anchor metadata.
- Status: `planned`, `deferred`, `review_requested`, `approved`, `sent`,
  `skipped`, `cancelled`, `expired`, `failed`, `uncertain`, or
  `migrated_legacy`.
- Logical touch result and provider attempt metadata without treating attempts as
  touches.
- `idempotency_key`, provider message ID when accepted, and correlation ID.
- Cancellation/skip/failure reason; manual actions require the actor and role,
  while automated actions record the system actor and correlation ID.
- Created/sent/closed timestamps.

Uniqueness must prevent duplicate logical occurrences for the same workspace,
workflow, pinned version, step, occurrence number, and schedule identity.

Occurrence/cursor behavior is explicit:

- `deferred`, `review_requested`, `approved`, and `uncertain` keep the same
  occurrence open; no new occurrence number or cursor advance is allowed.
- `sent` and `already_sent` close the occurrence and advance the cursor exactly
  once.
- `skipped` and `expired` close the occurrence and advance to the next planned
  step/occurrence only when the reason is not a human, suppression, or safety
  stop. They consume zero logical touches.
- `cancelled` for reply, handoff, reassignment, suppression, opt-out, or track
  migration closes the occurrence and stops future automation until an explicit
  application action resumes or migrates it.
- A permanent provider failure with no valid fallback closes the occurrence as
  `failed`, creates a policy review hold, and does not automatically advance.
- `migrated_legacy` is historical bookkeeping and never advances a new cursor or
  consumes a touch.

The workflow runtime stores the current occurrence ID, step cursor, occurrence
number, and accepted logical-touch count in Postgres. Temporal may cache these in
its query snapshot, but Postgres is authoritative.

### 5.5 Review record

Add a durable review record linked to the occurrence and generated message:

- reviewer-eligible workspace and lead/workflow identifiers;
- generated message version and channel;
- `review_kind`: `message`, `terminal`, or `policy`;
- status `pending`, `approved`, `rejected`, `edited_pending`, `expired`,
  `resolved`, or `superseded`;
- requested and acted timestamps, plus nullable `review_expiry_at` (`NULL` for
  policy reviews, 48-hour deadline for message and terminal reviews);
- reviewer, decision, reason, edited content reference, and audit metadata.

### 5.6 Template model

Add or reuse a template registry with:

- workspace scope where appropriate;
- template key, channel, purpose, and allowed variable schema;
- immutable template versions;
- lifecycle status `draft`, `published`, `retired`;
- approval/audit metadata;
- safe rendering and validation methods.

The send-path contract is explicit:

1. Published track step resolves `template_version_id`.
2. The occurrence stores that immutable template version reference.
3. The recurring execution context passes the reference through the cadence/send
   context; it must not collapse it back to an arbitrary key.
4. Outbound drafting loads the template version and validates channel, variables,
   capability tags, prompt version, and approved context.
5. Rendering produces a versioned message body/subject with the template version
   and occurrence ID attached.
6. The outbound message record stores the rendered message reference, template
   version, occurrence, channel, idempotency key, and provider result.
7. Provider callbacks reconcile against the outbound message and occurrence; they
   never re-resolve a different template.

`CampaignCadenceStep` and `_paused_search_steps_as_cadence_steps` must carry the
canonical template version during the compatibility period. Legacy published
versions may continue using their immutable `template_key` through a read-only
adapter, but recurring execution is disabled for any published version whose key
cannot be resolved to a published approved template version. New versions cannot
store only a free-form key.

### 5.7 Notification policy

The notification policy is a real versioned domain/persistence object, not an
undefined reference from a track version. It must contain:

- `notification_policy_id`, `workspace_id`, and immutable version metadata;
- enabled event types such as review request, reply/human request, handoff,
  touch-limit completion, duration expiration, policy pause, permanent provider
  failure, unassigned lead, compliance failure, and publish validation failure;
- recipient roles and assignment/team escalation rules;
- manager escalation timeout and repeated-failure threshold;
- routine-completion digest enabled flag and digest cadence;
- delivery channels supported by the existing notification port;
- audit metadata and an immutable snapshot reference from published tracks.

V1 seeds a workspace default notification policy. Admins may choose stricter or
less noisy notification behavior only within code-owned recipient and safety
rules. Missing assignees route to the appropriate manager or brokerage admin.
The V1 seeded defaults are manager escalation after 24 hours without review or
handoff acknowledgement, and manager escalation after three permanent provider
failures for the same lead within 24 hours. These defaults are named constants,
audited, and testable.

The canonical application DTO is `PausedSearchNotificationRequest` with:

- `notification_id`, `workspace_id`, event type, and correlation ID;
- lead/workflow/track/occurrence/review/handoff identifiers as applicable;
- resolved recipient user ID, destination, role, and delivery channel;
- subject, safe body, and optional redacted lead/contact preview;
- immutable notification-policy version and idempotency key.

V1 delivery channels are email and persisted in-app notification. Automated SMS
is not used for internal notifications. The notification repository persists
delivery attempts with statuses `pending`, `accepted`, `failed`, or `uncertain`
and a unique `(workspace_id, idempotency_key, channel, recipient_id)` key.
Temporary delivery failures use bounded exponential retry; uncertain delivery is
reconciled by provider status/callback and is never blindly duplicated. Recipient
resolution is an application service that checks workspace membership, role,
assignment, and notification policy before creating the DTO. Contact details and
message previews are included only for recipients authorized to view that lead.
Notification creation and its audit/outbox event commit before provider delivery.
Manager escalation is scheduled by the existing Temporal workflow timer/activity;
no process-local timer or unbounded cron is introduced.

## 6. Architecture and code boundaries

Domain and application code may depend on canonical types and ports only.

### Domain

Extend:

- `app/domain/campaigns/paused_search_tracks.py`
- `app/domain/campaigns/paused_search_timing.py`
- `app/domain/workflows/models.py` where a legal state transition is required.

Add pure functions for:

- configuration validation;
- capability-profile resolution;
- timing-basis planning;
- occurrence-limit evaluation;
- touch-limit evaluation;
- duration expiration;
- terminal outcome selection;
- customer-date precedence;
- fallback eligibility classification;
- timeline preview calculation.
- missing-track routing: if no published mapping exists for a reason, return
  `hold_for_review` with `NO_TRACK_MAPPING` and do not start occurrence planning.

### Application

Extend or add use cases under `app/application/use_cases/` for:

- draft validation and preview;
- occurrence planning/creation;
- recurring occurrence execution;
- review request/decision;
- fallback decision;
- terminalization/expiration;
- notification dispatch;
- live-track migration and rescheduling.

Reuse the existing pre-send and outbound execution paths. Do not create a second
send implementation for recurring maintenance.

### Ports

Extend existing repository and notification ports only where necessary. Add ports
for occurrence, review, template registry, and notification-policy persistence if
no existing equivalent exists. Keep Temporal native in the workflow layer; do not
introduce a generic `WorkflowEngine` port.

The notification port gains `send_paused_search_notification` accepting the
canonical DTO and returning `NotificationSendResult`. The notification delivery
repository owns durable status, idempotency, and callback reconciliation. Existing
typed preflight, handoff, and review methods remain compatible until their callers
are migrated.

### Infrastructure

All SQLAlchemy models, migrations, Temporal activities/workflows, provider
adapters, and notification delivery details remain under infrastructure.

### Interfaces

Keep FastAPI routes thin. Request validation belongs in Pydantic schemas and
business validation belongs in domain/application services. React data access
continues through `src/lib/api/` and TanStack Query.

### Temporal contract

Paused-search recurring execution remains inside the existing
`LeadNurtureWorkflow`; V1 does not create a second Temporal workflow. Existing
standard cadence workflows continue with `execution_mode=standard_cadence`.
Recurring workflows use `execution_mode=paused_search_recurring` and retain the
existing deterministic workflow ID derived from workspace, lead, and campaign
enrollment. A duplicate start returns the existing workflow rather than creating
another one.

The target `LeadNurtureWorkflowInput` contains:

- `workspace_id`, `lead_id`, `campaign_version_id`, and `workflow_id`;
- `execution_mode`;
- pinned `paused_search_track_version_id` when recurring mode is selected.

Recurring mode uses these native activities:

- `schedule-next-paused-search-occurrence` receives workspace, lead, workflow,
  pinned track version, current occurrence ID, and `occurred_at`; it returns
  `occurrence_id`, planner outcome, step ID, scheduled time, reason code, and
  terminal/expiration status.
- `execute-paused-search-occurrence` receives `occurrence_id`, revalidates all
  current rules, and returns occurrence status, provider/message identifiers,
  accepted logical-touch result, next-cursor decision, and notification events.
- `reconcile-paused-search-uncertain-occurrence` receives `occurrence_id` and
  provider reference, reconciles callback/status information, and returns the
  explicit operator-review or send outcome.

Existing standard-cadence activities remain unchanged. New signals are:

- `paused-search-timing-updated`;
- `paused-search-review-resolved`;
- `paused-search-migration-requested`;
- `paused-search-occurrence-cancelled`;
- `paused-search-terminalized`.

Existing pause, resume, inbound-processed, blocked-review-completed, reschedule,
and close signals remain supported. The workflow query snapshot adds execution
mode, pinned track version, current occurrence ID, occurrence status, step cursor,
accepted touch count, and terminal/review status. Postgres remains authoritative
for all business state, occurrence/review state, counters, audit, and outbox
events; Temporal stores only orchestration flags, timer state, and a read-only
query snapshot. Legacy workflows are identified by `execution_mode` and are
migrated to `paused_search_recurring` only by the Phase 7 migration job.

### Persistence isolation and transaction contract

Every new tenant-owned table has `workspace_id`, an application workspace filter,
and PostgreSQL RLS enabled and forced for the application role. RLS policies use
the existing `app_current_workspace_id()` context and the narrowly controlled
`app_rls_service_access_enabled()` service path, and deny cross-workspace
reads/writes. New tables use composite foreign keys or application-validated
same-workspace
references wherever a relationship crosses tables, plus composite unique
constraints that include `workspace_id`. Alembic migrations create, verify, and
roll back the policies; integration tests exercise both RLS and repository
filters.

This requirement also applies to existing paused-search tables touched by the
feature: add the required `(workspace_id, entity_id)` unique constraints and
composite relationships for track/version/step/mapping/workflow references, or
document and test an equivalent same-workspace validation when PostgreSQL cannot
express the relationship without an unsafe rewrite. UUID equality alone is never
accepted as tenant isolation.

The workflow migration adds a persisted workflow-kind discriminator and a
PostgreSQL partial unique index for one non-terminal paused-search workflow per
`(workspace_id, lead_id)`. Terminal states are `completed`, `suppressed`, and
`closed`; an explicit migration must lock and close/cancel the old active record
before creating or activating another one. Standard non-paused campaign
workflows are not incorrectly blocked by this paused-search-only constraint.

The occurrence/send transaction is:

1. Begin a database transaction.
2. Lock the workflow row with `SELECT FOR UPDATE`.
3. Load current lead, profile, pinned version, contact policy, consent,
   suppression, ownership, activity, and counters.
4. Reject stale version/occurrence state and enforce the feature flag.
5. Check occurrence uniqueness and create or claim the occurrence.
6. Update cursor and accepted-touch counters only under the explicit outcome
   rules in the occurrence contract.
7. Append audit and transactional-outbox events.
8. Commit.
9. Only after commit invoke the provider/send path.

If provider dispatch succeeds but the post-dispatch database update fails, do not
blindly retry. The provider callback/status reconciliation locates the occurrence
by provider reference or idempotency key and closes it as accepted/sent. If
acceptance cannot be determined, it becomes `uncertain` and follows the 24-hour
operator-review rule. A provider callback arriving before local reconciliation
must be idempotent and must not create a second touch.

### Runtime sequence contracts

#### Recurring send

1. Temporal timer wakes `LeadNurtureWorkflow`.
2. `schedule-next-paused-search-occurrence` locks/reloads Postgres state and
   creates or returns one occurrence.
3. Temporal waits until the stored due instant or an interrupting signal.
4. `execute-paused-search-occurrence` opens the final transaction, revalidates
   all pre-send rules, commits the claimed occurrence, and then dispatches.
5. Provider result/callback reconciles the occurrence and touch count.
6. Temporal receives the result and schedules the next occurrence or applies the
   terminal outcome.

#### Review-required send

1. Execution creates `review_kind=message` and `review_expiry_at`.
2. Notification delivery creates an idempotent review notification.
3. Temporal waits for `paused-search-review-resolved` or the 48-hour expiry.
4. Approval creates/uses the approved message version and re-runs pre-send checks.
5. Rejection or expiry closes the occurrence as `skipped` with zero touches.

#### Fallback and uncertain provider result

1. Primary channel is preflight-checked and dispatched once.
2. Permanent pre-acceptance failure may select the one permitted fallback after a
   fresh pre-send check; temporary failure defers/retries the same occurrence.
3. Uncertain acceptance never selects fallback and waits for provider
   reconciliation.
4. Callback or the 24-hour timeout produces one audited outcome and never blindly
   duplicates the provider call.

#### Expiration and human interruption

1. A timer or signal wakes the workflow.
2. The application locks the workflow and marks pending occurrences cancelled or
   expired with a reason.
3. It writes transition, notification, and outbox events in the same transaction.
4. Temporal closes or holds according to terminal behavior; no stale timer may
   send afterward.

## 7. Phase plan

Each phase is a releasable implementation slice. A phase may be developed in
parallel internally, but its Definition of Done is a hard gate before dependent
phases are accepted.

### 7.0 Ownership, dependencies, and migration groups

| Phase | Primary owners | Depends on |
|---|---|---|
| 0 Contract/baseline | product, architecture, backend, QA, operations | none |
| 1 Domain/persistence | backend, platform/DBA, QA | Phase 0 |
| 2 Validation/preview | backend, frontend, QA | Phase 1 |
| 3 Occurrence planner | backend, QA | Phase 1–2 |
| 4 Temporal execution | backend/platform, QA | Phase 3 |
| 5 Send/review/notification | backend, integrations, QA, operations | Phase 3–4 |
| 6 API/frontend/operator UI | backend, frontend, QA, accessibility | Phase 2 and Phase 5 contracts |
| 7 Migration/support operations | backend, platform/DBA, operations, QA | Phase 4–6 |
| 8 Hardening/release | all owners, security, product | Phase 0–7 |

Use migration groups rather than preassigning revision numbers:

1. Track-version and step configuration fields.
2. Customer timing history and compatibility projection.
3. Approved template registry and version references.
4. Notification policy, delivery, and feature-control fields.
5. Occurrence, review, cursor, counter, and legacy-baseline records.
6. RLS policies, same-workspace constraints, indexes, and no-overlap guards.

Canonical field dictionary:

| Field | Type/nullability | Default/owner | Mutability |
|---|---|---|---|
| `default_pause_duration_days` | integer, required | draft default 60; domain validation | draft only after publication |
| `max_duration_days` | integer, required | no implicit default; profile-bounded | draft only after publication |
| `max_total_touches` | integer, required | no implicit default; profile-bounded | draft only after publication |
| `terminal_behavior` | closed enum, required | `complete_keep_paused`; domain | draft only after publication |
| `missing_customer_date_policy` | closed enum, required | `use_fallback_timing`; domain | draft only after publication |
| `timing_basis` | closed enum, required | no implicit default for API; UI may choose explicitly | draft only after publication |
| `delay_days` | integer, required | 0 for one-time steps | draft only after publication |
| `interval_days` | integer, nullable | null for non-recurring steps | draft only after publication |
| `max_occurrences` | integer, nullable | null for non-recurring steps | draft only after publication |
| `primary_channel` | channel enum, required | no implicit API default | draft only after publication |
| `fallback_channel` | channel enum, nullable | null | draft only after publication |
| `template_version_id` | UUID, required for new versions | none | immutable after publication |
| `review_required` | boolean, required | false | immutable after publication |
| `logical_touch_count` | integer, required | 0 at new workflow; migration backfill | application only |
| `occurrence_number` | integer, required | starts at 1 per recurring step | occurrence creation only |
| `brokerage_timezone_at_scheduling` | IANA timezone string, required | workspace snapshot | immutable per occurrence |
| `recurring_paused_search_enabled` | boolean, required | false | audited workspace-control action |

Database nullability and defaults must match this dictionary. Domain validation,
not database defaults alone, owns cross-field constraints.

### Phase 0 — Contract freeze, baseline, and test harness

#### Goal

Freeze the decisions in this document, identify current behavior that must remain
backward compatible, and establish a test/observability baseline before schema
changes.

#### Deliverables

- Update the source planning document with approved decisions or link this plan as
  the implementation contract.
- Record the target enums, field semantics, state transitions, and compatibility
  rules in domain documentation.
- Inventory current migrations, repositories, API schemas, frontend forms,
  Temporal activities, and tests that use `max_attempts`, `delay_hours`,
  `maintenance_interval_days`, and `fallback_timing_policy`.
- Produce a field-by-field migration matrix before schema work starts:

  | Existing field | Target field/behavior | Required compatibility work |
  |---|---|---|
  | `PausedSearchTrackVersion.maintenance_interval_days` | `interval_days` on recurring steps plus fallback configuration | Backfill only where the old value is unambiguously a recurring interval |
  | `PausedSearchTrackVersion.reactivation_window_days` | Retained as phase timing input | Preserve in published snapshots and map into the new planner |
  | `PausedSearchTrackVersion.fallback_timing_policy` | Replaced on new versions by `missing_customer_date_policy` plus explicit `timing_basis` | `HOLD_FOR_REVIEW → hold_for_review`; `USE_MAINTENANCE_INTERVAL → use_fallback_timing` while preserving the maintenance interval; `USE_REENGAGEMENT_NOT_BEFORE → use_fallback_timing` with the existing reengagement date resolved as the customer timing anchor. Existing immutable versions continue through the legacy compatibility adapter |
  | `PausedSearchTrackVersion.max_total_touches` | Retained with runtime enforcement | Add occurrence/touch counters and pre-send guard |
  | `PausedSearchTrackStep.channel` | `primary_channel` plus optional `fallback_channel` | Backfill existing channel as primary and fallback as null |
  | `PausedSearchTrackStep.delay_hours` | `delay_days` plus `timing_basis` | Preserve old hourly behavior through a compatibility adapter until migrated |
  | `PausedSearchTrackStep.template_key` | `template_version_id` | Seed and publish template versions, then backfill references |
  | `PausedSearchTrackStep.max_attempts` | Provider retry policy | Stop using it as a customer-touch limit and document the adapter |
  | `PausedSearchTrackVersion.requires_review_before_publish` | Removed from V1 contract | Preserve legacy value for warning/reconfirmation; never use it to block a new publish path |

  The matrix must include migration SQL, API compatibility behavior, repository
  mapping, fixture updates, and every existing test file that constructs the old
  dataclasses.
- Existing published versions retain an hourly compatibility adapter so their
  pinned behavior is not silently changed. For new-version conversion, use
  `delay_days = max(1, ceil(delay_hours / 24))`; values below 12 hours and values
  that are not whole-day multiples are emitted as migration warnings for admin
  attention. No conversion may schedule an existing step earlier than its legacy
  delay.
- Existing drafts with `requires_review_before_publish=true` are not silently
  published. They are marked for admin reconfirmation, surfaced with a
  `LEGACY_PUBLISH_REVIEW_FIELD` warning, and become publishable only after an
  admin saves the new draft contract and acknowledges the normal publish preview.
- Decide whether existing track tables are extended or a new occurrence/review/
  template table set is added. The occurrence and review records must be new
  durable concepts even if track tables are extended.
- Add shared test fixtures/fakes for track versions, profiles, workflows,
  occurrences, templates, providers, reviewers, and notification capture.
- Identify the owner of the initial approved template library and choose the
  migration/seeding mechanism before recurring execution is enabled.
- Add feature flags or workspace controls needed to keep recurring execution off
  until all later phases pass.
- Define the workspace setting `recurring_paused_search_enabled`, defaulting to
  `false`. When false, recurring planning and occurrence endpoints are disabled
  and the UI hides recurring execution controls; draft validation and preview
  remain available. Phase 8 enables it per pilot workspace.
- Store this setting in `WorkspaceOperationalControlModel` through a dedicated
  field and repository method. The workspace-control dependency reads it for
  enrollment, occurrence planning, Temporal activities, and recurring API
  mutations. Brokerage admins can view it; operations/platform admins control
  pilot activation through the workspace allowlist and audited setting change.
- Disabling the flag prevents new recurring occurrences and wakes active recurring
  workflows into a safe hold. It does not delete planned occurrences, history, or
  standard non-recurring paused-search workflows. Re-enabling requires the normal
  feature-flag audit and revalidation before a held workflow resumes.
- Define structured audit event names and correlation fields.
- Freeze the canonical customer timing contract, Temporal input/activity/signal
  contract, notification DTO/delivery contract, API route compatibility policy,
  and occurrence cursor/outcome matrix before schema implementation begins.

#### Required tests

- Unit tests proving the approved enum values and legacy-field compatibility.
- Application tests proving feature-disabled workspaces retain current behavior.
- Integration smoke tests proving existing pinned workflows can still be loaded.
- API contract tests proving current track create/detail/list responses remain
  readable during the transition.
- Frontend regression tests for the existing track settings surface.

#### Definition of Done

- [ ] Product and engineering sign off on every approved V1 decision in Section 4.
- [ ] A migration/backward-compatibility strategy is written.
- [ ] Unit tests for the new shared fixtures and policy constants pass.
- [ ] Application integration tests load an existing published track and pinned
      workflow without data loss.
- [ ] Existing paused-search API and frontend tests pass.
- [ ] Feature flag behavior is tested for enabled and disabled workspaces.
- [ ] Audit event names and required identifiers are documented.
- [ ] The field migration matrix and legacy-workflow/template migration owners are
      approved.
- [ ] Customer timing ownership, Temporal contracts, notification DTOs, API route
      policy, and occurrence cursor behavior are approved as implementation
      contracts.
- [ ] `recurring_paused_search_enabled` storage, default, API behavior, UI behavior,
      and pilot rollout procedure are documented and tested.
- [ ] `make lint`, `make typecheck`, and targeted backend tests pass.
- [ ] `pnpm lint`, `pnpm typecheck`, and targeted frontend tests pass.
- [ ] Rollback steps for every later migration are documented.

### Phase 1 — Domain, profiles, templates, and persistence foundation

#### Goal

Implement the canonical configuration and runtime persistence model without
changing live execution yet.

#### Deliverables

- Add domain enums and value objects for timing basis, terminal behavior, missing
  customer-date policy, occurrence status, review status, and fallback outcome.
- Define `RecurringOccurrenceOutcome` separately from the existing
  `PausedSearchTimingReasonCode`. Keep `PausedSearchTimingReasonCode` for the
  legacy/non-recurring planner until all callers migrate. Define and test the
  mapping between old reason codes and new outcomes.
- Extend `PausedSearchTrackVersion` and `PausedSearchTrackStep` with the approved
  configuration fields.
- Add the canonical customer timing history and compatibility projection, with
  source/evidence/confidence fields, confirmed-versus-ambiguous status, and the
  `apply_customer_timing_update` use case. Persist timing audit/outbox events and
  never allow an LLM result to mutate effective timing directly.
- Implement code-defined capability profiles and single-reason profile resolution;
  competing reasons must produce a review hold.
- Implement the approved template registry and published template-version lookup.
- Seed the initial approved template library through an idempotent migration or
  explicit seed script. Convert every existing `template_key` used by a published
  track into a published template version, or flag that track for admin attention
  before the feature flag can enable recurring execution.
- Define and persist the versioned notification-policy model, seed a workspace
  default, and snapshot the selected policy into published track versions.
- Add Alembic migrations for configuration fields, templates, occurrences, and
  reviews. Every tenant-owned table must contain `workspace_id`, indexes, and
  appropriate composite uniqueness constraints.
- Add RLS enable/force policies and same-workspace composite foreign-key or
  validation constraints for every new tenant-owned table. The migration must
  set the workspace context used by the policies and include upgrade, downgrade,
  and cross-workspace denial tests.
- Enforce V1's one-active-mapping rule with
  `unique(workspace_id, reason_code)` on active published reason mappings.
  Multiple unpublished drafts may exist; replacing a mapping displaces the old
  mapping in one transaction and writes an audit record.
- Add repository ports and Postgres adapters with workspace filtering on every
  read/write.
- Add occurrence and review audit/event persistence using existing outbox/audit
  conventions.
- Add a `migrated_legacy` occurrence status for imported pre-occurrence workflows;
  it is historical bookkeeping and never counts as a touch.
- When creating a `migrated_legacy` baseline, backfill `logical_touch_count` from
  existing provider-accepted outbound history for the same workspace/workflow.
  If the count already meets the pinned version's `max_total_touches`, complete
  the workflow with `TOUCH_LIMIT_AT_MIGRATION` and notify operations; do not grant
  additional automated touches.
- Implement compatibility mapping from existing fields:
  - map `delay_hours` to the new timing representation;
  - map existing `max_attempts` to provider retry semantics, not occurrences;
  - retain legacy template-key reads only during migration;
  - preserve old published versions for pinned workflows.
- Add data migration/backfill validation and a report for rows that cannot be
  safely converted.

#### Required unit tests

- Valid and invalid timing-basis combinations.
- Interval minimum/maximum and profile-specific maximums.
- Duration minimum, normal maximum, and 730-day hard maximum.
- Max-occurrence and max-touch validation.
- Single-reason profile resolution and competing-reason review hold.
- Terminal behavior validity.
- Customer-date and missing-date policy validity.
- Customer timing source, evidence, conflict, no-contact, supersession, and
  compatibility-projection rules.
- Default pause duration is bounded by track duration and the effective profile.
- Primary/fallback channel compatibility.
- Template reference lifecycle and allowed variables.
- Occurrence status transition legality.
- Review status transition legality.
- Policy reviews allow only pending → resolved through an explicit resolution
  action; they have no expiry timestamp and cannot use message approval states.

#### Required application/integration tests

- Track draft persistence round trip with workspace isolation.
- Published track snapshot contains immutable profile/template references.
- Customer timing history round trips with source/evidence and only one confirmed
  effective record; ambiguous candidates create a review hold.
- Existing published track versions remain readable after migration.
- Each legacy `PausedSearchFallbackTimingPolicy` value maps to the documented
  compatibility behavior, including `USE_REENGAGEMENT_NOT_BEFORE`.
- Occurrence uniqueness rejects duplicate schedule identities.
- Review records are scoped to the correct workspace and workflow.
- RLS and application-filter integration tests reject cross-workspace reads,
  writes, joins, foreign references, and notification delivery.
- Template deletion/retirement is blocked while referenced.
- Migration backfill is idempotent and reports invalid legacy rows safely.
- Legacy touch-count backfill is idempotent and filters only accepted automated
  messages belonging to the pinned workflow.

#### Definition of Done

- [ ] Domain models and policy functions are implemented without vendor imports.
- [ ] Alembic migrations apply and downgrade in a disposable Postgres database.
- [ ] Repository tests prove tenant isolation and composite uniqueness.
- [ ] RLS policies are created, exercised, and rolled back in a disposable
      Postgres database; application filters provide the required defense in depth.
- [ ] Unit tests cover every validation rule and state transition.
- [ ] Fake-based application tests cover configuration, occurrence, review, and
      template persistence orchestration.
- [ ] Template seeding/backfill is idempotent and every enabled published track
      resolves to a valid published template version.
- [ ] Notification policy defaults and immutable published snapshots are tested.
- [ ] `RecurringOccurrenceOutcome` and `PausedSearchTimingReasonCode` coexist
      without changing legacy caller behavior.
- [ ] Postgres integration tests cover migration, round trip, locking, and
      idempotent backfill.
- [ ] Existing published versions and pinned workflows remain loadable.
- [ ] No code path interprets `max_attempts` as customer-facing repetitions.
- [ ] Audit records exist for configuration and lifecycle changes.
- [ ] `make lint`, `make typecheck`, and targeted pytest pass.
- [ ] Migration rollback and invalid-data remediation are documented.

### Phase 2 — Validation, publish contract, warnings, and timeline preview

#### Goal

Make every draft explainable and safe to publish before any recurring execution
is enabled.

#### Deliverables

- Extend `paused_search_track_admin.py` validation to return structured blocking
  errors and non-blocking warnings.
- Reject invalid phases, unsupported channels, missing or unpublished templates,
  invalid timing combinations, excessive repetitions, excessive duration, profile
  violations, missing terminal behavior, and unreachable steps.
- Add explicit publish validation for template variables, content restrictions,
  SMS/A2P requirements, review requirements, and expected touch volume.
- Validate template permitted-use tags against the effective capability profile;
  for example, `waiting_for_rates` rejects a template without
  `no_financial_advice`, and `waiting_for_inventory` requires
  `listing_context_allowed` when listing context is selected.
- Build one domain timeline planner used by both preview and runtime scheduling.
- Add preview output containing:
  - projected local and UTC dates;
  - phase and step sequence;
  - occurrence number and maximum occurrences;
  - maximum possible logical touches;
  - duration/expiration date;
  - customer-date assumptions;
  - quiet-hour adjustments;
  - channel and fallback path;
  - review holds;
  - terminal behavior;
  - warnings and blocking errors.
- Add explicit publish confirmation requiring the admin to acknowledge the
  preview and warnings.
- Add optimistic locking for draft versions so concurrent edits cannot silently
  overwrite one another.
- Remove `requires_review_before_publish` from new request/response schemas and
  handle stored legacy drafts with the explicit reconfirmation warning and save
  flow defined in Section 4.8.
- Persist the exact validation/preview summary used for publication in the audit
  record.

#### Required unit tests

- Every blocking validation rule.
- Warning versus error classification.
- Timeline calculations for maintenance, reactivation, recurring steps, customer
  dates, missing dates, quiet hours, and duration expiration.
- Timeline calculation with no customer date uses `default_pause_duration_days`
  only under `use_fallback_timing`; `hold_for_review` never silently falls back.
- Maximum-touch calculation across primary/fallback outcomes.
- Profile-specific cadence and content restrictions.
- Draft optimistic-lock conflict.
- Preview determinism: identical input and reference time produce identical output.

#### Required application/API integration tests

- Draft create/update returns structured validation results.
- Preview uses unsaved draft input and never persists it accidentally.
- Publish rejects stale draft versions.
- Legacy drafts carrying `requires_review_before_publish=true` cannot publish
  until an admin explicitly resaves the new contract and acknowledges the preview.
- Publish persists an immutable snapshot and preview/audit metadata.
- Published track cannot reference an unpublished template.
- New publish does not mutate existing pinned workflows.
- API responses distinguish `errors`, `warnings`, `preview`, and `publishable`.
- Workspace isolation applies to preview and publish operations.

#### Definition of Done

- [ ] An invalid track cannot be published through API or UI.
- [ ] Every publishable track has a deterministic preview and terminal behavior.
- [ ] Unknown/inactive/unpublished templates are blocking errors.
- [ ] Profile maximums cannot be bypassed by request payload or direct API call.
- [ ] Preview and runtime call the same domain planner.
- [ ] Concurrent draft edits are rejected safely and tested.
- [ ] Publish confirmation and audit records include actor, version, warnings,
      preview reference, and correlation ID.
- [ ] Unit, fake application, Postgres, and API integration tests pass.
- [ ] Existing admin API tests remain green.
- [ ] `make lint`, `make typecheck`, and targeted pytest pass.

### Phase 3 — Occurrence planning, touch limits, and terminal logic

#### Goal

Turn a published track into a bounded sequence of durable occurrences without
yet relying on a long-running Temporal loop for all orchestration.

#### Deliverables

- Introduce `plan_recurring_occurrence` and `PausedSearchOccurrencePlan` to
  calculate the next occurrence from the pinned version, current lead profile,
  current workflow state, previous occurrence, and current time. This is a new
  return contract, not a compatible extension of `PausedSearchNextActionPlan`.
  Retain `plan_paused_search_next_action` for the existing non-recurring path
  until all callers have migrated and its removal is separately approved.
- Implement all supported timing bases with explicit anchor data.
- Implement `before_pause_end` using the resolved customer-date/default-duration
  anchor and return `hold_for_review` when no anchor is available.
- Implement recurring step repetition and `max_occurrences`.
- Implement track-wide `max_total_touches` using accepted logical touches, not
  provider attempts.
- Implement `max_duration_days` and expiration handling.
- Implement phase transition and no-step-in-phase behavior.
- Implement terminal behavior after final occurrence, touch limit, or expiration.
- Create the occurrence before dispatch under a transaction and lock the workflow
  row with `SELECT FOR UPDATE` where current repository conventions require it.
- Read the workspace `WorkspaceContactPolicy.quiet_hours_start` and
  `quiet_hours_end` values and pass them into planning; never hardcode 10:00–17:00
  inside the new planner. The existing defaults remain 10:00–17:00, and a
  brokerage may configure a narrower window.
- Snapshot `brokerage_timezone_at_scheduling` on every occurrence. Display and
  audit local due times using that snapshot even if workspace timezone settings
  later change.
- Define the idempotency key as
  `{workflow_id}:{track_version_id}:{step_id}:{occurrence_number}:{channel}`.
  A fallback attempt appends `:fallback`. Implement this as a domain function and
  test uniqueness across duplicate wake-ups, retries, and repeated steps.
- Make planner outcomes explicit: `send`, `hold`, `review`, `defer`, `cancel`,
  `terminalize`, or `expired`.
- Record reason codes for every non-send outcome.

#### Required unit tests

- First occurrence, subsequent recurring occurrence, and final occurrence.
- Occurrence limit reached before total touch limit.
- Total touch limit reached across multiple steps and phases.
- Primary/fallback successful-touch accounting.
- Provider failure with zero touch.
- Duration expiration before and after a due occurrence.
- Duration during review and temporary deferral.
- Phase transition at customer date and reactivation window.
- A track with `use_fallback_timing` and a valid past customer date enters
  reactivation immediately rather than falling back to maintenance timing.
- A changed workspace timezone does not alter an occurrence's stored local
  schedule or audit display.
- A narrower workspace quiet-hours window defers a due occurrence to the next
  permitted local window.
- All terminal behaviors.
- No-step, disabled-track, inactive-profile, non-sendable-workflow, and stale-
  cursor outcomes.
- Cursor matrix tests for deferred/review/uncertain (stay open), sent/skipped
  (advance), human/suppression cancellation (stop), and permanent failure without
  fallback (policy review hold).

#### Required application/integration tests

- Concurrent planners create exactly one occurrence.
- Duplicate planner retries return the existing occurrence safely.
- A completed occurrence advances the cursor exactly once.
- A failed/review/skipped occurrence follows the configured policy without
  consuming a logical touch incorrectly.
- A deferred, review-requested, or uncertain occurrence is not duplicated or
  advanced; a hard policy block does not retry automatically.
- Track migration recomputes future occurrences without rewriting history.
- Reply, suppression, ownership, and human activity cancel pending occurrences.
- Expiration writes terminal transition and notification event once.
- Concurrent enrollment/planning cannot create overlapping active paused-search
  workflows for one lead/workspace.

#### Definition of Done

- [ ] Recurring steps produce bounded, uniquely identified occurrences.
- [ ] Touch limits are enforced in application code, not only preview/UI.
- [ ] Provider retries cannot increase customer-touch counts.
- [ ] Duration and terminal behavior are enforced before selecting a send.
- [ ] Occurrence creation and cursor advancement are transactionally safe.
- [ ] Unit tests cover all planner outcomes and boundary conditions.
- [ ] Fake-based application tests cover concurrency/idempotency behavior.
- [ ] Postgres integration tests prove locking, uniqueness, and history retention.
- [ ] Audit/transition/outbox events are emitted once for important outcomes.
- [ ] No existing send path can bypass the new limits.
- [ ] `PausedSearchOccurrencePlan` and the legacy plan have an explicit migration
      boundary and both are covered by tests.
- [ ] `make lint`, `make typecheck`, and targeted pytest pass.

### Phase 4 — Temporal recurring execution and interruption

#### Goal

Execute occurrences durably over days or months with safe wake-up, interruption,
rescheduling, and worker-restart behavior.

#### Deliverables

- Extend `app/infrastructure/workflows/temporal/lead_nurture.py` using native
  Temporal timers, signals, queries, activities, and retries.
- Implement the exact `execution_mode`, recurring workflow input, activity input/
  output, signal, and query contracts from Section 6. Legacy standard-cadence
  inputs remain backward compatible.
- Keep Temporal orchestration separate from domain decisions.
- Wait until the occurrence due time or an interrupting signal.
- Re-load the current workflow, lead, profile, pinned version, occurrence, consent,
  suppression, ownership, and activity facts after every wake-up.
- For a legacy active workflow with no occurrence records, run the approved
  migration job before enabling the new loop: create a `migrated_legacy` baseline
  from its pinned version, step cursor, and `next_action_at` when those facts are
  complete; otherwise move it to an explicit review hold. Never silently create a
  customer touch or silently complete the workflow.
- Recompute phase and next occurrence instead of trusting stale timer assumptions.
- Handle signals for profile/timing changes, pause, resume, reply, human activity,
  suppression, migration, review decision, and terminalization.
- Ensure a worker restart or deployment resumes from durable occurrence state.
- Ensure stale timers and duplicate signals cannot dispatch twice.
- Ensure long waits are bounded by Temporal's durable timer behavior rather than
  process-local sleep or cron.

#### Required unit tests

- Signal-to-application-command mapping.
- Input/output serialization tests for every recurring activity and signal.
- Workflow decision handling for every planner outcome.
- Duplicate signal collapse.
- Stale occurrence/version rejection.
- Retry classification for temporary versus permanent activity failures.
- Terminal and expiration signal handling.

#### Required Temporal/integration tests

- Time-skipping test for a 30-day recurring sequence.
- Time-skipping test for several occurrences ending at `max_occurrences`.
- Time-skipping test for track-wide touch cap.
- Time-skipping test for maximum duration expiration.
- Worker restart/replay test with a year-long wait.
- Reply before due time prevents the stale occurrence from sending.
- Agent activity/ownership change interrupts the wait.
- Suppression and opt-out interrupt the wait and block future sends.
- Timing/profile update wakes and reschedules the workflow.
- Migration to a new version preserves old occurrence history and uses the new
  version only for future planned occurrences.
- Duplicate wake-ups do not create duplicate occurrences or provider calls.
- A DST-boundary time-skipping test preserves calendar-day meaning and the local
  allowed sending window.

#### Definition of Done

- [ ] Temporal owns all long waits and no process-local scheduler is required.
- [ ] Every wake-up revalidates current state before an occurrence can send.
- [ ] Reply, human activity, suppression, ownership, review, and migration signals
      interrupt or reschedule correctly.
- [ ] Time-skipping tests prove recurring execution and terminal behavior.
- [ ] Restart/replay tests prove durable recovery.
- [ ] Duplicate wake-up tests prove one occurrence and one provider call.
- [ ] Temporal code contains orchestration only; business rules remain testable in
      domain/application functions.
- [ ] Failure/retry behavior is documented and tested.
- [ ] Legacy active workflows without occurrence rows are migrated or held by an
      explicit, idempotent job with integration-test coverage.
- [ ] `make lint`, `make typecheck`, and targeted Temporal/integration tests pass.

### Phase 5 — Send execution, fallback, review, and notifications

#### Goal

Connect planned occurrences to the existing safe outbound path while supporting
review-required steps, channel fallback, and action-oriented notifications.

#### Deliverables

- Route recurring occurrence sends through the existing pre-send and outbound
  execution use cases.
- Add a final occurrence-level send guard that verifies:
  campaign/workflow state, eligibility, consent, suppression, A2P, agent veto,
  recent human activity, inbound replies, ownership, quiet hours, frequency,
  touch limits, duration, occurrence status, and idempotency.
- Implement permanent-versus-temporary channel failure classification.
- Implement at-most-one fallback with one logical-touch accounting.
- Block fallback on uncertain provider acceptance.
- Implement review request, approval, rejection, edit-and-approve, expiration,
  supersession, and revalidation.
- Use the review record's `review_kind=message` for per-step review and
  `review_kind=terminal` for `pause_for_review`; the latter appears in the same
  operator queue with terminal-specific reason and expiry data.
- Implement `review_kind=policy` as an operator-resolution hold with no message
  approval, no automatic expiry, 24-hour manager escalation, and the four
  explicit resolution actions in Section 4.8.
- Add `PausedSearchNotificationRequest`, notification delivery persistence,
  recipient resolution, idempotency, bounded retry, uncertain-delivery
  reconciliation, and `send_paused_search_notification` through the existing
  notification port as specified in Section 5.7.
- Notify only when attention is needed:
  review request, reply/human request, handoff, touch limit, expiration, policy or
  human pause, permanent provider failure, unassigned lead, workspace compliance
  failure, and publish validation failure.
- Add manager escalation/digest behavior as a documented V1 operational default.

#### Required unit tests

- Final pre-send decision with each blocker.
- Permanent versus temporary provider error classification.
- Fallback eligibility matrix.
- Uncertain acceptance blocks fallback.
- One logical-touch accounting for fallback.
- Review state transitions and expiration.
- Policy-review creation, queue representation, invalid message-approval actions,
  resolution actions, idempotency, and manager escalation without auto-expiry.
- Revalidation after approval and after edit.
- Notification recipient selection and suppression of routine success notices.
- Notification DTO serialization, delivery persistence, role/assignment
  recipient resolution, redacted content rules, retry, and uncertainty handling.
- Missing-assignee escalation behavior.
- A channel-level SMS opt-out with no permitted next-step fallback creates a
  review hold instead of silently dropping future automation.
- A track with six configured touches cannot send the sixth when the platform
  AI-interaction cap is five.

#### Required application/integration tests

- Fake provider test for accepted send, retry, permanent failure, temporary
  failure, uncertain result, and fallback.
- Existing `FakeSMSProvider`, `FakeEmailProvider`, and outbound fakes prove no
  recurring path bypasses pre-send checks.
- Review API/use-case integration test for approve/reject/edit and audit records.
- Policy-review integration test proves permanent failure, no-fallback opt-out,
  uncertain timeout, and no-track mapping create the correct review kind and can
  resolve only through the policy endpoint/actions.
- Inbound reply integration test cancels pending review/occurrence and routes to
  existing reply-classification flow; create handoff only when that flow returns
  a handoff-required decision.
- Notification integration test proves correct recipient and idempotency.
- Notification provider failure/callback integration test proves no duplicate
  internal notification and correct manager escalation timing.
- Postgres test proves accepted provider result and touch accounting are durable.
- Provider callback test does not create another touch or send.

#### Definition of Done

- [ ] No automated recurring message can bypass existing pre-send checks.
- [ ] Fallback is limited to one permitted channel and never follows uncertain
      acceptance or temporary outage.
- [ ] Touch totals match accepted logical messages in all provider outcomes.
- [ ] Review-required steps never send without approval.
- [ ] Approval/edit/rejection/expiration are audited and idempotent.
- [ ] Notifications are action-oriented, tenant-scoped, and idempotent.
- [ ] `pause_for_review` terminal records are visible and actionable in the
      operator review queue.
- [ ] Unit, fake-based application, Postgres, provider-callback, and inbound
      integration tests pass.
- [ ] Existing cadence and outbound tests remain green.
- [ ] `make lint`, `make typecheck`, and targeted pytest pass.

### Phase 6 — Admin API, frontend controls, and operator review UI

#### Goal

Expose the complete bounded configuration and operational controls without making
the UI a second source of business rules.

#### Deliverables

- Extend `app/interfaces/api/schemas/paused_search_tracks.py` for all configuration
  fields, preview output, warnings, errors, optimistic-lock version, and publish
  confirmation.
- Extend `app/interfaces/api/v1/paused_search_tracks.py` with draft validation,
  preview, publish confirmation, and template/profile options.
- Preserve the existing route family `/{workspace_id}/paused-search-tracks` for
  backward compatibility. Do not introduce a parallel `/paused-search` route
  family in V1. Add the new resources below under the existing router prefix:

  | Endpoint | Minimum role | Rule |
  |---|---|---|
  | `GET /{workspace_id}/paused-search-tracks` | workspace member | Existing list contract; workspace and role scope |
  | `GET /{workspace_id}/paused-search-tracks/{track_id}` | workspace member | Existing detail contract |
  | `POST /{workspace_id}/paused-search-tracks` | brokerage admin | Create draft; returns draft version and validation state |
  | `PUT /{workspace_id}/paused-search-tracks/{track_id}/draft` | brokerage admin | Update draft with optimistic-lock version |
  | `POST /{workspace_id}/paused-search-tracks/{track_id}/draft/validate` | brokerage admin | Validate unsaved draft; no persistence |
  | `POST /{workspace_id}/paused-search-tracks/{track_id}/draft/preview` | brokerage admin | Return deterministic timeline, warnings, and errors |
  | `POST /{workspace_id}/paused-search-tracks/{track_id}/versions/{track_version_id}/publish` | brokerage admin | Requires valid preview acknowledgement; immutable version |
  | `POST /{workspace_id}/paused-search-tracks/{track_id}/retire` | brokerage admin | Retire mapping/future use without rewriting history |
  | `GET /{workspace_id}/paused-search-tracks/templates` | workspace member | Published approved templates only |
  | `GET /{workspace_id}/paused-search-tracks/profiles` | workspace member | Code-defined capability profile metadata |
  | `GET /{workspace_id}/settings` | brokerage admin/operations | Existing settings bundle returns the feature flag, contact-policy snapshot, and rollout status |
  | `PATCH /{workspace_id}/settings/automation` | operations/platform admin | Existing operational-control route changes `recurring_paused_search_enabled` only with audited reason and pilot-allowlist guard |
  | `GET /{workspace_id}/paused-search-tracks/occurrences` | agent | Assigned leads only; managers/admins see permitted broader scope |
  | `GET /{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}` | agent | Assigned lead, or manager/admin scope |
  | `GET /{workspace_id}/paused-search-tracks/reviews` | agent | Assigned review scope; terminal reviews included |
  | `POST /{workspace_id}/paused-search-tracks/reviews/{review_id}/approve` | assigned agent/manager/admin | Assignment/team/workspace guard |
  | `POST /{workspace_id}/paused-search-tracks/reviews/{review_id}/reject` | assigned agent/manager/admin | Rejects occurrence or terminal review according to fixed V1 policy |
  | `PUT /{workspace_id}/paused-search-tracks/reviews/{review_id}` | assigned agent/manager/admin | Edit creates a new message version and audit record |
  | `POST /{workspace_id}/paused-search-tracks/reviews/{review_id}/resolve` | assigned agent/manager/admin | Required for `review_kind=policy`; action is `skip`, `resume_after_revalidation`, `migrate`, or `terminalize` |
  | `POST /{workspace_id}/paused-search-tracks/occurrences/{occurrence_id}/skip` | assigned agent/manager/admin | Explicit skip; reason and revalidation required |
  | `POST /{workspace_id}/paused-search-tracks/workflows/{workflow_id}/pause` | assigned agent/manager/admin | Permission-checked human pause |
  | `POST /{workspace_id}/paused-search-tracks/workflows/{workflow_id}/resume` | assigned agent/manager/admin | Re-runs all eligibility and ownership checks |
  | `POST /{workspace_id}/paused-search-tracks/workflows/{workflow_id}/migrate` | manager/admin | Pins a published eligible version and cancels stale future work |
  | `POST /{workspace_id}/paused-search-tracks/workflows/{workflow_id}/terminalize` | manager/admin | Applies explicit terminal behavior with audit |

  Terminal reviews use the same queue and are identified by
  `review_kind=terminal`.

  `approve`, `reject`, and edit return a structured conflict for
  `review_kind=policy`; policy reviews must use `/resolve`.

  Every write returns `status`, `correlation_id`, validation errors/warnings, and
  the resulting version/occurrence/review state. Draft writes require an expected
  draft revision. Review, skip, pause, resume, migration, and terminalization
  commands require an idempotency key and actor reason. Preview accepts a draft
  payload plus an explicit `as_of` timestamp and never persists it. Publish
  requires the draft revision, preview reference, and warning acknowledgement.
  All response schemas are defined in Pydantic and typed in
  `src/lib/api/pausedSearchTracks.ts`; no route may accept provider-shaped data.
  Static subroutes such as `templates`, `profiles`, `occurrences`, and `reviews`
  must be registered before UUID `/{track_id}` routes or placed in a separate
  router so they cannot be parsed as track IDs.
- Extend `src/lib/api/pausedSearchTracks.ts` with typed clients.
- Add typed clients for every endpoint in the route table, preserving the current
  CRUD paths and adding new subresources without breaking existing callers.
- Replace free-form template-key input with approved template selection.
- Add UI controls for timing basis, delay/interval, max occurrences, max total
  touches, max duration, terminal behavior, customer-date policy, primary/fallback
  channel, profile constraints, review requirement, and notifications.
- Add deterministic timeline preview with local dates, UTC details, maximum
  outreach, warnings, errors, review holds, and terminal outcome.
- Separate blocking errors from warnings visually and accessibly.
- Require explicit publish confirmation and show the immutable version created.
- Add draft conflict handling and retry/readback behavior.
- Add lead-detail/readback surfaces for pinned version, profile, next occurrence,
  touch count, review status, terminal state, and why the next action is held.
- Add review queue actions with role-aware approve/reject/edit controls.
- Render `review_kind=policy` with policy reason and resolution actions rather
  than message approval controls. Terminal and policy reviews remain in the same
  queue with distinct badges and safe action descriptions.
- Create page-level tests for `LeadDetailPage` and `ReviewQueuePage`; these files
  currently have no dedicated `.test.tsx` coverage and must not be treated as
  existing test anchors.

#### Required frontend/unit tests

- Form defaults and bounded input validation.
- Profile constraints prevent invalid values in UI but API remains authoritative.
- Preview rendering for recurring, fallback, review, expiration, and terminal
  outcomes.
- Blocking errors disable publish; warnings require acknowledgement where defined.
- Draft conflict message and refresh behavior.
- Template selection and channel compatibility.
- Review approval/rejection/edit flows.
- Keyboard navigation, accessible labels, focus states, and responsive layout.

#### Required API/frontend integration tests

- Create/edit/preview/publish/retire through the real API contract shape.
- Validate all route-table payloads, including templates, profiles, occurrences,
  reviews, skip/pause/resume, migration, and terminalization.
- Confirm existing `paused-search-tracks` clients remain compatible and no
  `/paused-search` parallel route is introduced.
- API rejects forged values that the UI hides.
- Preview and publish results are rendered from server response, not duplicated
  client calculations.
- Review queue reads and writes are workspace/role scoped.
- Policy-review rows reject approve/reject/edit actions and expose only
  skip/resume-after-revalidation/migrate/terminalize actions allowed by role.
- Lead detail readback reflects occurrence and terminal state after API mutation.
- Existing `AdminOperationsRoutes.test.tsx`, `LeadsRoutes.test.tsx`, and paused-
  search component tests remain green.

#### Definition of Done

- [ ] Every approved configuration decision is represented in the admin API and
      UI or explicitly code-owned.
- [ ] The UI cannot publish without server validation and preview confirmation.
- [ ] Unknown templates, invalid profiles, and unsafe channels are visibly blocked.
- [ ] Preview uses backend planner output and displays maximum outreach clearly.
- [ ] Reviewers can complete authorized message reviews with audit readback.
- [ ] Operator surfaces show why a lead is waiting, blocked, cancelled, or done.
- [ ] Review and occurrence endpoints have explicit HTTP contract, role, tenant,
      assignment, and manager-scope tests.
- [ ] Frontend unit/component tests and API integration tests pass.
- [ ] `pnpm lint`, `pnpm typecheck`, targeted Vitest, backend lint/typecheck, and
      targeted API tests pass.
- [ ] Responsive and accessibility review is completed at desktop, tablet, and
      mobile widths.

### Phase 7 — Live migration, overrides, reporting, and support operations

#### Goal

Allow authorized operators to manage live workflows safely and give support the
information needed to explain every decision.

#### Deliverables

- Extend existing lead workflow override use cases for recurring settings,
  occurrence skip, explicit track migration, terminalization, and review hold.
- Require actor, role, reason, old value, new value, target version, and impact
  summary for every manual action.
- Revalidate eligibility, suppression, consent, ownership, human activity, and
  workflow state before resume or migration.
- Prohibit migration to unpublished, disabled, or retired versions unless an
  explicit product policy later permits it.
- Define migration behavior for a currently pending occurrence: cancel the stale
  occurrence, retain history, and plan from the new pinned version.
- If a live workflow is migrated to a version with a lower touch limit, reject the
  migration when the current accepted touch count is already at or above the new
  limit. If at least one touch remains, preserve the count and enforce the lower
  limit for future sends; never reset counters during migration.
- Ensure no overlapping active paused-search workflow exists per lead/workspace.
  Enforce this at both the application and persistence/concurrency boundary;
  concurrent enrollment integration tests must prove only one active workflow can
  exist for a lead in a workspace.
- Add API/UI readback for timeline, occurrence history, touch count, provider
  outcome, review, profile, terminal reason, and audit trail.
- Add operational queries/metrics for due, held, expired, failed, review-pending,
  fallback, terminal, and uncertain occurrences.
- Add support runbook for stale timers, uncertain sends, stuck reviews, provider
  failures, suppression, and manual migration.
- Document that a terminal `pause_for_review` reuses the review record with
  `review_kind=terminal`, appears in the operator queue, and can only be resolved
  by an authorized action that is separately audited.

#### Required tests

- Unit tests for migration/override validation and state transitions.
- Fake application tests for serialized operator actions and re-planning.
- Postgres integration tests for workflow locking and no-overlap constraints.
- Feature-flag tests prove disabling recurring execution holds active recurring
  workflows, preserves history, and leaves standard non-recurring workflows
  enabled.
- API permission tests for agent, manager, brokerage admin, and super admin.
- Integration tests for migration while waiting, reviewing, due, and human-owned.
- Readback tests proving old and new versions, occurrence history, and reasons are
  visible after migration.
- Notification/audit tests for manual actions.

#### Definition of Done

- [ ] Authorized operators can safely skip, pause, resume, migrate, and
      terminalize according to role rules.
- [ ] Unauthorized users cannot mutate live track execution.
- [ ] Migration preserves historical records and cancels stale future work.
- [ ] No overlapping active paused-search workflows can be created.
- [ ] Every manual decision is auditable and visible to support.
- [ ] Reporting identifies all non-send and failure outcomes.
- [ ] Unit, fake application, Postgres, API, and end-to-end operator tests pass.
- [ ] Runbook includes recovery actions and escalation paths.
- [ ] Backend and frontend lint/typecheck/test gates pass.

### Phase 8 — Full hardening, rollout, and release sign-off

#### Goal

Prove the complete business flow and release the feature behind a safe pilot gate.

#### Deliverables

- Extend the existing business-flow harness to cover:
  AI classification → pause reason/profile → track pin → preview/publish →
  recurring wait → maintenance occurrence → review or send → fallback → reply/
  agent activity interruption → reclassification/handoff → terminal outcome.
- Add targeted Postgres + Temporal integration suite.
- Run duplicate CRM/provider events, stale timers, worker restarts, malformed
  template context, malformed LLM output, and mid-track suppression scenarios.
- Add structured logs and metrics containing workspace, lead, workflow, track
  version, occurrence, message, handoff, correlation, and reason identifiers.
- Add dashboards/alerts for provider failures, uncertain sends, stuck reviews,
  expired tracks, repeated deferrals, and workflow failures.
- Add feature flag, pilot workspace allowlist, migration plan, rollback plan, and
  support ownership.
- Perform a security review of workspace isolation, role checks, sensitive data
  exposure, audit records, and notification content.
- Perform accessibility and responsive UI review.

#### Required tests

- Full fake-based business-flow tests covering acceptance scenarios 1–35 (and any
  later additions) listed in Section 8 of this document.
- Real Postgres integration tests with migrations applied from a clean database.
- Temporal time-skipping and restart/replay tests.
- Provider callback and uncertain-send tests.
- API authorization and tenant-isolation tests.
- Frontend route/component regression and accessibility tests.
- Load/concurrency test for duplicate planner/wake-up attempts where practical.
- Full backend and frontend check commands.

#### Definition of Done

- [ ] All acceptance scenarios pass.
- [ ] All required test layers pass: domain, application, Postgres/API, Temporal,
      provider integration, frontend, and end-to-end.
- [ ] No known send-safety, touch-limit, version-pinning, tenant-isolation, or
      duplicate-send defect remains open.
- [ ] Audit/readback can explain every send, hold, fallback, review, cancellation,
      terminal, and migration outcome.
- [ ] Monitoring and alert ownership are documented.
- [ ] Pilot feature flag and rollback have been tested in a non-production
      environment.
- [ ] Product, engineering, QA, security, and operations sign off.
- [ ] Release notes describe configuration changes, migration behavior, limits,
      and operator actions.
- [ ] `make check` and `pnpm check` pass, or unrelated environment failures are
      recorded with evidence and an owner.

## 8. Mandatory acceptance scenarios

The following scenarios are release-blocking end-to-end tests:

1. A valid 30-day email maintenance step creates one occurrence, sends once, and
   schedules the next occurrence.
2. A recurring step stops exactly at `max_occurrences`.
3. A track stops exactly at `max_total_touches` across maintenance and
   reactivation phases.
4. A track expires at `max_duration_days`, completes with the configured terminal
   behavior, and does not send afterward.
5. A valid customer date prevents reactivation before that date.
6. An explicit no-contact-until date blocks maintenance before that date.
7. Missing customer timing follows fallback or review policy as configured.
8. An SMS primary step falls back to email only after permanent pre-acceptance
   blocking and only when email checks pass.
9. Temporary provider outage retries/defer and does not immediately fallback.
10. Uncertain provider acceptance blocks fallback and prevents blind resend.
11. A review-required occurrence never sends without approval.
12. A reply before a due occurrence cancels stale automation and reclassifies the
    lead before any next action.
13. Human activity, reassignment, suppression, or opt-out stops future automation.
14. Publishing a new version does not mutate existing pinned workflows.
15. Explicit migration changes future planning, retains old history, and is
    permission-checked and audited.
16. Duplicate CRM events, Temporal wake-ups, provider callbacks, and retries do
    not create duplicate workflows, touches, or sends.
17. An invalid template, profile limit, channel, phase, timing, or terminal
    configuration cannot publish through API or UI.
18. Workspace A cannot read, preview, mutate, review, or receive notifications
    for Workspace B.
19. Competing pause-reason evidence produces `hold_for_review` and never causes
    an implicit strictest-profile selection; one confirmed canonical reason is
    required before profile and track resolution.
20. A 30-day recurring occurrence crossing a DST boundary retains the correct
    brokerage-local calendar date and allowed sending window.
21. A reason with no published track mapping produces `hold_for_review` with an
    explicit `NO_TRACK_MAPPING` reason and does not start occurrence planning.
22. A track configured for six touches cannot send a sixth message when the
    platform AI-interaction cap is five.
23. A live workflow migrated to a lower touch limit is rejected when already at
    the limit and preserves its accepted-touch count when one or more touches
    remain.
24. An uncertain provider result waits for its callback timeout, creates no
    automatic duplicate, and requires an audited operator resolution.
25. `before_pause_end` schedules against a confirmed customer date when present,
    uses the configured default pause duration when fallback timing applies, and
    holds for review when no anchor exists.
26. A timing candidate records source, evidence, confidence, and audit history;
    an LLM candidate cannot change effective timing without application
    confirmation.
27. A legacy template key resolves through the compatibility adapter, while an
    unresolved key prevents recurring execution and is surfaced for migration.
28. A legacy draft with `requires_review_before_publish=true` cannot publish until
    an admin resaves the new contract and acknowledges the preview.
29. Disabling `recurring_paused_search_enabled` holds recurring workflows without
    deleting occurrences and leaves standard non-recurring workflows unaffected.
30. RLS and same-workspace constraints prevent cross-workspace occurrence, review,
    template, notification, and workflow references.
31. Provider dispatch occurs only after the occurrence transaction commits, and a
    post-dispatch database failure is reconciled without a blind duplicate.
32. Deferred/review/uncertain outcomes retain the occurrence, sent/skipped outcomes
    advance exactly once, and hard policy blocks do not retry automatically.
33. Each legacy `fallback_timing_policy` value maps deterministically: hold,
    maintenance-interval fallback, and existing reengagement-date compatibility
    behavior are preserved for immutable published versions.
34. Permanent provider failure, no-fallback channel opt-out, uncertain timeout,
    and no-track mapping create `review_kind=policy`; approve/reject/edit are
    rejected and only policy resolution actions are accepted.
35. A policy review remains open without automatic expiry, escalates after 24
    hours, and resolves exactly once through skip, resume-after-revalidation,
    migration, or terminalization.

## 9. Audit and observability requirements

Every important decision must record:

- `workspace_id`, `lead_id`, `crm_lead_id`, `workflow_id`, `track_id`,
  `track_version_id`, `step_id`, `occurrence_id`, `message_id`, `review_id`,
  `handoff_id`, and `correlation_id` as applicable;
- event type, timestamp, actor, role, old/new state, policy/profile version;
- planner reason, validation errors/warnings, and pre-send blockers;
- provider attempt and acceptance status without logging credentials;
- template version, channel, fallback outcome, and touch accounting;
- terminal, expiration, cancellation, review, migration, and notification reason.

Metrics must cover:

- planned, due, sent, skipped, deferred, reviewed, cancelled, expired, failed,
  uncertain, and terminal occurrences;
- touch-limit and duration-limit completions;
- fallback rate and provider failure rate;
- review age and expired review count;
- stale timer/duplicate wake prevention;
- workflow interruption and reclassification outcomes;
- policy-block and compliance-block counts.

Message content, phone numbers, email addresses, credentials, and provider tokens
must not be added to unnecessary logs or metrics.

## 10. Migration and rollback strategy

1. Deploy additive schema changes first.
2. Backfill templates/profile references and report invalid rows.
3. Deploy read-compatible domain/repository code.
4. Deploy validation and preview with recurring execution disabled.
5. Identify every active paused-search workflow without occurrence rows. For each,
   create an idempotent `migrated_legacy` baseline from its pinned version, step
   cursor, and `next_action_at` when complete. If those facts are incomplete, put
   the workflow into an explicit review hold and notify operations. This migration
   must be approved and tested before new-loop execution is enabled.
6. Enable occurrence creation in shadow or pilot mode without provider dispatch.
7. Enable Temporal recurring execution for an allowlisted workspace.
8. Compare preview, occurrence, send, and touch metrics before widening rollout.
9. Enable fallback/review/notification features only after their integration gates
   pass.

Rollback rules:

- Disable the feature flag to prevent new recurring occurrence execution.
- Do not delete occurrence, review, audit, template, or published-version history.
- Existing workflows must fail safe into hold/terminal behavior rather than resume
  an untested path.
- Provider uncertainty must never be resolved by blind replay during rollback.
- Database downgrades are allowed only before data-bearing rollout and only using
  a reviewed migration procedure.
- Published versions remain readable so pinned workflows can be inspected and
  safely completed or explicitly migrated.

## 11. Verification commands

Run commands from the relevant subproject.

Backend targeted verification:

- `uv run pytest tests/domain/campaigns/test_paused_search_timing.py`
- `uv run pytest tests/application/services/test_paused_search_drafting_templates.py`
- `uv run pytest tests/application/use_cases/test_paused_search_track_admin.py`
- `uv run pytest tests/application/use_cases/test_paused_search_track_pinning.py`
- `uv run pytest tests/application/use_cases/test_seed_default_paused_search_tracks.py`
- `uv run pytest tests/application/use_cases/test_schedule_next_paused_search_action.py`
- `uv run pytest tests/application/use_cases/test_campaign_cadence_execution.py`
- `uv run pytest tests/application/use_cases/test_lead_workflow_overrides.py`
- `uv run pytest tests/infrastructure/persistence/postgres/test_paused_search_track_repository.py`
- `uv run pytest tests/interfaces/api/v1/test_paused_search_tracks_admin.py`
- `uv run pytest tests/interfaces/api/v1/test_paused_search_track_occurrences.py`
- `uv run pytest tests/interfaces/api/v1/test_paused_search_reviews.py`

Add and run new targeted suites for occurrence planning, review, templates,
preview, fallback, notifications, and Temporal recurring execution.

Backend release verification:

- `make lint`
- `make typecheck`
- `make test`
- `make check`

Frontend targeted verification:

Run these commands from `miller-schackman-web/`.

- `pnpm vitest run src/app/AdminOperationsRoutes.test.tsx`
- `pnpm vitest run src/app/LeadsRoutes.test.tsx`
- `pnpm vitest run src/pages/LeadDetailPage.test.tsx`
- `pnpm vitest run src/pages/ReviewQueuePage.test.tsx`
- paused-search component and review-queue tests

Frontend release verification:

- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- `pnpm check`

On the current development machine, backend checks may need the documented
`arch -arm64 make check` invocation because of the Python wheel architecture. A
Node engine warning below the declared minimum must be resolved or explicitly
recorded before release sign-off.

## 12. Final project Definition of Done

The feature is complete only when all of the following are true:

- [ ] The approved configuration contract is implemented in domain, persistence,
      API, and UI layers.
- [ ] Recurring maintenance is calendar-day based, bounded, durable, and
      interruptible.
- [ ] Occurrence counts, logical touches, provider retries, and uncertain sends
      are distinct and correctly enforced.
- [ ] Maximum duration, customer-date precedence, fallback policy, review, and
      terminal behavior are enforced in application code.
- [ ] Customer timing has canonical source/evidence/conflict history and no LLM
      result can directly mutate effective scheduling.
- [ ] Preview and runtime use the same planner.
- [ ] The existing `LeadNurtureWorkflow` contract, recurring activities, signals,
      Postgres authority, and legacy execution mode are implemented and tested.
- [ ] Published versions are immutable and active workflows remain pinned unless
      explicitly migrated.
- [ ] Templates are approved/versioned and invalid references block publishing.
- [ ] Capability profiles prevent unsafe configurations and cannot be relaxed by
      admins.
- [ ] Every automated send passes immediate pre-send checks and idempotency.
- [ ] Every new tenant table has application filtering, RLS, same-workspace
      relationship constraints, and cross-workspace denial tests.
- [ ] Provider dispatch occurs only after the occurrence transaction commits, with
      uncertain-result reconciliation and no blind resend.
- [ ] Replies, suppression, human activity, reassignment, and handoff interrupt
      future automation safely.
- [ ] Every phase's listed unit, application, persistence/API, Temporal, frontend,
      and end-to-end tests pass; phases without a particular layer explicitly
      state that layer is not part of their deliverables.
- [ ] Audit records, metrics, alerts, runbook, migration, rollback, and feature
      flag controls are complete.
- [ ] Product, engineering, QA, security, and operations approve pilot release.