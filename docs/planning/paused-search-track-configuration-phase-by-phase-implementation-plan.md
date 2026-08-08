# Paused-Search Track Configuration

## Phase-by-Phase Implementation Plan

**Status:** Implementation plan for approval  
**Related proposal:** `paused-search-track-configuration-client-proposal.md`  
**Scope:** Guided admin configuration, repeatable paused-search cycles, reply reclassification, optional per-step reminders, API/backend/frontend/database changes, migration, and time-machine verification

> This is an implementation plan, not a declaration that the feature is complete. Each phase has a small delivery slice, targeted tests, and an explicit exit gate. The feature is not done until the time-machine scenarios pass against the real application behavior.

## Execution ledger

The ledger is updated after each phase. A phase is checked only after its implementation work, focused tests, and exit gate are complete.

- [x] Phase 0 — contract freeze, baseline, and current-behavior audit
  - Native arm64 baseline: 130 backend tests passed.
  - Frontend baseline: 44 tests passed, 1 expected test skipped.
  - Contract decisions and legacy behavior inventory recorded below.
- [x] Phase 1 — domain contract and pure validation
  - Added bounded track-mode, interim-permission, step-action, reply-policy, and channel-sequence enums.
  - Added compatibility mapping from legacy `review_required` to the canonical step action.
  - Added cycle and AI-interaction limits plus permission/action validation findings.
  - Added regression coverage for legacy mapping, recurring permission, action conflicts, and policy combinations.
  - Domain tests: 33 passed; paused-search regression tests: 130 passed; Ruff and mypy passed.
- [x] Phase 2 — database schema and persistence
  - Added Alembic revision `0082_add_paused_search_policy_contract`.
  - Persisted track mode, interim-contact policy, reply policy, channel sequence, cycle limit, AI-interaction limit, and canonical step action.
  - Backfilled `action` from legacy `review_required` while retaining the old column for compatibility.
  - Added repository round-trip coverage for repeat policy and reminder action.
  - Migration applied at head; persistence suite: 7 passed; paused-search regression suite: 131 passed; Ruff and mypy passed.
- [x] Phase 3 — application services and backend administration/API
  - Threaded policy fields and canonical step actions through the existing draft/update/validate/preview/publish write path.
  - Extended API request/response schemas while retaining `review_required` only as a temporary compatibility field.
  - Added API coverage for policy/action round-trip and request-bound cycle limits.
  - Paused-search regression suite: 144 passed; focused API/application suite: 21 passed; Ruff and mypy passed.
- [x] Phase 4 — runtime scheduling, actions, and channel execution
  - Added explicit runtime handling for `send`, legacy-compatible `review`, `skip`, and idempotent `reminder` actions.
  - Added `PausedSearchAgentReminder`, repository port, PostgreSQL table/migration `0083`, and Temporal activity wiring.
  - Added occurrence status `reminder_created`; reminder/skip actions never call an SMS/email provider.
  - Enforced sequential-only channel execution until simultaneous delivery has a real runtime implementation; simultaneous configuration is now a publish-blocking validation error.
  - Fixed sequential paused-search execution to retain the `waiting_for_response` → `active_nurture` transition before sending the next step.
  - Made recurring occurrence message idempotency occurrence-specific so a later maintenance occurrence is not mistaken for a duplicate of the first.
  - Added an application lifecycle test covering two bounded maintenance touches, reactivation email → SMS sequencing, cumulative four-touch accounting, final `waiting_for_response`, provider-call uniqueness, and no further scheduling.
  - Added a paused-search Temporal matrix test proving two sequential occurrences execute and the workflow stops after the final result.
  - Phase 4 focused gates: cadence application file 26 passed; paused-search Temporal workflow files 16 passed; Ruff, mypy, and `git diff --check` passed.
  - The broader deterministic time-machine harness remains Phase 7; Phase 4 is complete without pulling that future test infrastructure forward.
- [x] Phase 5 — inbound replies, reclassification, and repeatable cycles
  - Added a pure `decide_paused_search_reply` policy decision with hard-stop precedence and explicit re-anchor timing requirements.
  - Added coverage for continue, restart, re-anchor, review/remind, end, changed-track, and hard-stop outcomes: 20 domain tests passed.
  - Wired inbound workflow transitions to cancel pending reminders independently of occurrence cancellation; production webhook dependency wiring now provides the reminder repository.
  - Updated preview fixtures so recurring maintenance declares explicit interim-contact permission instead of relying on the removed implicit behavior.
  - Integrated the published reply policy into inbound processing for active leads with pinned paused-search tracks; hard-stop outcomes remain authoritative.
  - Continue/restart resume through the Temporal reschedule path without an immediate AI reply; end completes automation; review and timing-less re-anchor hold for review.
  - Pending occurrences and reminders are cancelled before policy-driven continuation, and the selected decision is returned and persisted in inbound audit metadata.
  - Re-anchor now reuses the existing structured lead-state classifier once, accepts only a same-track timezone-aware future timing, and preserves the prior timing boundary and label when timing is missing, malformed, or in the past.
  - Restart-after-delay now uses the published `restart_delay_days` setting: inbound processing interrupts stale work immediately, then queues an idempotent delayed Temporal resume signal; continue, re-anchor, and end outcomes unblock or terminalize through the same signal contract without an immediate AI reply.
  - End/restart integration coverage verifies cumulative touch-count preservation, pending occurrence/reminder cancellation, and duplicate webhook protection; full paused-search inventory: 119 passed, 1 skipped; full suite: 1,183 passed, 2 skipped; Ruff and mypy passed.
- [x] Phase 6 — guided frontend configuration and readback
- [x] Phase 7 — deterministic time-machine test harness
  - Added the reusable test-only `PausedSearchTimeMachine` with an explicit timezone-aware clock, real schedule/execute use cases, occurrence idempotency, provider outcomes, reminders, workflow transitions, and normalized runtime snapshots.
  - Added a deterministic matrix for preview/runtime agreement, maintenance permission blocking, reactivation boundaries, sequential channels, final waiting-for-response state, reminder/skip actions, cumulative caps, duplicate scheduling, and provider failure behavior.
  - Reused the existing inbound processing and Temporal matrix suites for reply cancellation, handoff, suppression, delayed restart, duplicate webhook, and durable workflow coverage rather than creating a second simulation engine.
  - Fixed preview reactivation projections to plan from the same bounded reactivation boundary as runtime, and blocked permission-based maintenance when explicit interim-contact permission is absent.
  - Phase 7 focused gate: deterministic harness suite, preview suite, paused-search lifecycle suite, and Temporal matrix pass with Ruff and mypy.
- [x] Phase 8 — remove/deprecate unwanted behavior
  - Phase 8A established the compatibility-only boundary for persisted legacy versions.
  - Phase 8B added the workspace-scoped, read-only legacy inventory and active workflow pin report.
  - Phase 8C removed legacy draft request fields and deprecated editor choices; new draft schemas reject unknown legacy fields and deprecated policies/actions.
  - Existing response/read models, database columns, pinned workflow versions, and compatibility runtime paths remain intact.
  - Exit evidence: backend `make check` passed with 1,193 tests passed and 2 skipped; frontend `pnpm check` passed with 104 tests passed and 1 skipped; `git diff --check` passed for both projects.
  - Operational follow-up: run the inventory for each pilot workspace and review any remaining legacy pins before Phase 9 rollout; no automatic migration or deletion is part of Phase 8.
- [x] Phase 9 — pilot rollout and final signoff (code/readiness gate)
  - Pilot execution is fail-closed behind the persisted workspace
    `recurring_paused_search_enabled` control and the deployment
    `RECURRING_PAUSED_SEARCH_PILOT_WORKSPACE_IDS` allowlist; an empty allowlist
    enables no recurring work.
  - Rollback behavior and operating thresholds are documented in
    `docs/runbooks/paused-search-operations.md`.
  - Sink providers remain available for safe local testing without external SMS
    or email delivery.
  - The expected business scenario is covered and passing: CRM-tagged lead →
    paused-search classification → version-pinned workflow → outbound email →
    human-request reply → handoff, CRM tag, notification, and terminal workflow
    state.
  - Deterministic time-machine, schedule/pilot-control, inbound/handoff, and
    Temporal paused-search suites pass.
  - Real workspace activation and external-provider sends remain an explicit
    operational decision requiring a named pilot workspace and signoff; no
    production workspace was enabled by this change.

## 1. Target outcome

An authorized brokerage admin can create a bounded paused-search track by answering business questions rather than combining unexplained technical fields. The system translates those answers into a versioned workflow, rejects unsafe combinations, previews the actual behavior, and executes it durably through the existing paused-search/Temporal foundation.

The target workflow must support, among others:

- An AI-drafted low-pressure message when a lead enters a track
- Monthly maintenance messages when interim contact is explicitly permitted
- A requested-date or six-month reactivation boundary
- Final reactivation through configured channels, sequentially by default
- A waiting-for-response state after the final message
- Reclassification after every meaningful reply
- Continue, restart, re-anchor, review, optional reminder, handoff, suppression, or completion outcomes
- Cumulative touch, duration, cycle, and AI-interaction limits
- Version-pinned workflows that do not silently change when an admin publishes a new version

## 2. Non-negotiable product and architecture rules

- Keep the existing modular monolith and Temporal workflow architecture. Do not create a second nurture engine or a generic workflow/rules engine.
- Keep business decisions in domain/application code. AI drafts, classifies, extracts, and summarizes; it never authorizes a send, consent decision, suppression decision, or handoff by itself.
- Keep the existing route family and tenant isolation. Every new read/write remains workspace-scoped and permission-checked.
- Preserve immutable published track versions and pinned active workflows.
- Treat agent reminders as optional per step. Do not create reminders unless the step explicitly selects the reminder action.
- Require channel consent independently for email and SMS. Waiting-for-rates language alone is not interim-contact permission.
- SMS remains subject to all workspace compliance rules. Unknown consent or blocked compliance means no SMS send.
- Run current eligibility, suppression, ownership, human-activity, quiet-hours, frequency, and idempotency checks immediately before every provider call.
- A reply cancels or invalidates pending automated actions before classification and scheduling can continue.
- Restarting a cycle never resets cumulative limits or audit history.
- Do not invent timing from vague language. Hold, review, or use an explicitly configured bounded fallback.

## 3. Delivery method

Each phase is delivered as a small vertical slice:

1. Confirm the contract and affected files.
2. Add or change the smallest implementation surface.
3. Add focused tests using fakes or the existing Postgres harness.
4. Run the phase gate before starting the next phase.
5. Update this document's execution ledger and the test matrix.

No phase is complete because code compiles. The phase must prove its business behavior and failure behavior.

## 4. Existing foundation to retain

The implementation should extend, not duplicate, these existing surfaces:

| Concern | Existing surface |
|---|---|
| Track/domain models | `app/domain/campaigns/paused_search_tracks.py` |
| Timing planner | `app/domain/campaigns/paused_search_timing.py` |
| Validation | `app/domain/campaigns/paused_search_validation.py` |
| Track admin use cases | `app/application/use_cases/paused_search_track_admin.py` |
| Lead enrollment/clear | `app/application/use_cases/lead_paused_search.py` |
| Scheduling | `app/application/use_cases/schedule_next_paused_search_action.py` |
| Inbound classification | `app/application/use_cases/process_inbound_message_event.py` and `apply_lead_state_classification.py` |
| Durable execution | `app/infrastructure/workflows/temporal/lead_nurture.py` and Temporal activities |
| Persistence | `app/infrastructure/persistence/postgres/models.py` and paused-search repositories |
| Admin API | `app/interfaces/api/v1/paused_search_tracks.py` and `app/interfaces/api/schemas/paused_search_tracks.py` |
| Admin UI | `src/components/paused-search/PausedSearchTrackEditor.tsx`, `PausedSearchTrackPreview.tsx`, `PausedSearchTrackStudio.tsx`, and `src/components/settings/pausedSearchTrackForm.ts` |
| Existing tests | `tests/**/test_*paused_search*` and frontend paused-search/API tests |

The detailed recurring-maintenance plan and existing test matrix remain useful implementation references. This document is the current plan for the new guided configuration and repeatable reply-cycle behavior.

## 5. Phase 0 — Contract freeze and baseline audit

### Goal

Turn the approved proposal into an implementation contract before changing runtime code.

### Phase 0 contract decisions

- The canonical per-step action will be `send`, `review`, `reminder`, or `skip`. The current `review_required` boolean is a compatibility input only and will not remain the public configuration model.
- The canonical reply policy will be `continue`, `restart_after_delay`, `reanchor_to_new_timing`, `review_or_remind`, or `end`.
- Channel execution will be sequential by default. A final email/SMS sequence is represented as separate ordered steps; simultaneous delivery requires an explicit future policy and separate safety checks.
- Monthly maintenance requires explicit interim-contact permission plus independent consent for each configured channel. A waiting-for-rates classification alone is insufficient permission.
- Requested timing remains the earliest boundary for reactivation. Maintenance cannot move a message before a strict boundary.
- Any inbound reply cancels or invalidates pending automated actions before reclassification. Hard outcomes such as opt-out, suppression, human request, meaningful interest, and human activity take precedence over same-track continuation.
- Continue, restart, and re-anchor preserve cumulative touch, duration, cycle, and AI-interaction limits. Restart never resets counters.
- Agent reminders are opt-in per step. A send, review, or skip step must not create a reminder unless the explicit reminder action is selected.
- Existing published versions remain pinned and readable. New enrollments will use only the new contract after cutover; unsafe legacy workflows hold for review instead of being guessed or silently rewritten.

### Current behavior audit

The baseline audit identified these implementation facts:

- Track and step versioning, occurrence persistence, Temporal scheduling, pre-send revalidation, review gates, touch limits, and active-workflow pinning already exist and will be extended.
- `PausedSearchTrackStep.review_required` is currently the step-level control; there is no canonical persisted action for reminder or skip behavior.
- `maintenance_interval_days` and step recurrence fields exist, but recurring contact is not yet represented as an explicit permission-aware business policy.
- Reply-time classification already exists, but the new continue/restart/re-anchor decision must become an explicit shared application/domain policy rather than an implicit workflow side effect.
- The current admin editor exposes low-level timing, phase, channel, template, and review fields directly; it does not yet guide admins through business policies or show reply-cycle behavior.
- Version pinning and cumulative logical-touch accounting must be retained; they are not legacy behaviors to remove.

### Behaviors classified for change or removal

- Replace public `review_required` configuration with the canonical per-step action.
- Stop inferring recurring outreach from an interval alone; require an explicit repeat/permission policy.
- Stop treating reminders as implicit; create them only for reminder-configured steps.
- Stop treating final email/SMS as an unspecified multi-channel touch; make ordering explicit.
- Stop any restart path that resets counters or creates an unbounded reply loop.
- Stop any date-guessing fallback for vague timing.
- Keep final send-time safety checks, version pinning, tenant isolation, audit history, and provider uncertainty handling.

### Work

- Create a behavior matrix for five starting policies: wait until requested date, permission-based interim contact, agent-managed follow-up, scheduled reactivation, and custom bounded track.
- Define the canonical per-step action enum: `send`, `review`, `reminder`, `skip`.
- Define the canonical reply policy enum: `continue`, `restart_after_delay`, `reanchor_to_new_timing`, `review_or_remind`, `end`.
- Define the channel sequence policy: sequential by default; simultaneous only when explicitly enabled and safe.
- Define the interim-contact permission requirement and how it is represented in the lead profile/evidence.
- Define cumulative counters and limits: logical touches, duration, cycles, and AI interactions.
- Define hard classification precedence: suppression/opt-out and handoff outcomes outrank paused-search continuation.
- Inventory every current path that creates, schedules, sends, reviews, reminds, restarts, or clears paused-search work.
- Mark each current behavior as retain, change, compatibility-only, or remove.
- Record unresolved product choices as approval blockers rather than silently selecting policy.

### Tests and gate

- Completed with the native arm64 prefix so the repository's installed arm64 wheels are used:
  `arch -arm64 uv run pytest tests/domain/campaigns/test_paused_search_timing.py tests/application/use_cases/test_paused_search_track_admin.py tests/application/use_cases/test_schedule_next_paused_search_action.py tests/application/use_cases/test_campaign_cadence_execution.py tests/application/use_cases/test_lead_paused_search.py tests/application/use_cases/test_process_inbound_message_event.py tests/infrastructure/persistence/postgres/test_paused_search_track_repository.py tests/interfaces/api/v1/test_paused_search_tracks_admin.py` — 130 passed.
- Completed frontend baseline: `pnpm vitest run src/lib/api/pausedSearchTracks.test.ts src/components/settings/PausedSearchTracksCard.test.tsx src/app/AdminOperationsRoutes.test.tsx src/app/LeadsRoutes.test.tsx` — 44 passed, 1 skipped.
- The first backend attempt without the native arm64 prefix was not counted as a product failure; it used incompatible arm64 binaries from an x86_64 process and was rerun successfully with `arch -arm64`.
- Phase 0 is complete. Phase 1 may begin with domain-only changes and pure tests.

## 6. Phase 1 — Domain contract and pure validation

### Goal

Make the new behavior explicit and testable without database, provider, or UI dependencies.

### Domain changes

- Add bounded enums/value objects for track mode, per-step action, reply policy, channel sequence, and interim-contact permission.
- Extend `PausedSearchTrackVersion` with the selected business policy and repeat-cycle settings.
- Extend `PausedSearchTrackStep` with the canonical action. Keep `review_required` only as a temporary internal compatibility input until migration is complete.
- Define explicit timing boundary semantics: original requested date, updated requested date, earliest allowed contact, and next due action.
- Define cycle accounting so continuation/restart/re-anchor cannot reset cumulative counts.
- Define a reminder action as a non-send outcome with an assigned-agent scope and due time; do not model it as an implicit side effect of every step.
- Keep message drafting context bounded to recent relevant conversation and the approved rolling summary.

### Validation changes

Extend `paused_search_validation.py` to reject or warn on:

- Interim contact without an approved permission requirement
- A step scheduled before a strict requested-date boundary
- A recurring policy without interval, touch, duration, cycle, or AI limits
- A restart policy that could reset cumulative counters
- A re-anchor policy without a safe timing source
- A reminder without an assigned-agent scope or valid due time
- A channel not permitted by the track or current contact policy
- Simultaneous channels without explicit configuration
- A review action that has no review path
- A track with no terminal behavior or no reply policy where replies can recur

### Tests

- Pure tests for each enum and valid/invalid combination.
- Timing tests for exact dates, monthly intervals, vague timing, and updated timing.
- Precedence tests for opt-out, suppression, human request, meaningful interest, reassignment, and human activity.
- Counter tests proving that restart and re-anchor preserve cumulative limits.

### Exit gate

Domain tests pass, no provider or ORM imports leak into the domain, and the waiting-for-rates configuration can be validated as a deterministic value object.

## 7. Phase 2 — Database schema and persistence

### Goal

Persist the new configuration and runtime facts without losing tenant isolation, versioning, or active workflow safety.

### Schema work

Add an additive Alembic migration after reviewing the current heads. Use explicit enum/string constraints consistent with repository conventions. Likely changes include:

- Track-version columns for business policy mode, interim-contact permission policy, reply policy, channel sequence policy, and repeat-cycle limits.
- Step column for canonical action, replacing external dependence on `review_required`.
- Workflow/cycle columns for current cycle identity, cumulative cycle count, earliest allowed contact, and reclassification/re-anchor metadata where existing columns cannot represent them safely.
- Reminder/task persistence or an explicit integration with the existing assigned-agent task/notification path. The database must support idempotent reminder creation and cancellation.
- Audit/event details for policy selection, reply classification, cycle transition, re-anchor, reminder creation, and removed/blocked actions.
- Constraints and indexes for workspace isolation, one active assignment/workflow, due actions, idempotency keys, and pending action cancellation.

Do not store arbitrary admin-defined if/then rules in JSON. JSON may hold bounded AI profile or audit detail data, but business policy fields must be explicit and validated.

### Migration strategy

- Backfill existing `review_required=true` steps to `review` and `false` steps to `send` only after confirming that this reflects current behavior.
- Give existing published versions an explicit compatibility policy rather than silently changing their runtime semantics.
- Do not reset existing occurrence touch counts, workflow duration, or provider identities.
- Existing active workflows remain pinned. Any workflow that cannot be safely interpreted receives a hold-for-review outcome, not an automatic send.
- Add read compatibility first, then write the new representation, then remove old write paths after the migration is verified.
- Provide a rollback note for each migration and test upgrade from the current local Alembic head.

### Tests

- Repository round trips for every new field.
- Workspace isolation and RLS tests.
- Unique active-workflow/assignment and idempotent reminder tests.
- Legacy-row backfill tests, including null/unknown timing and old review flags.
- Migration upgrade and clean-database compatibility tests.

### Exit gate

Migration upgrades cleanly, rollback impact is documented, repository tests pass, and no active workflow loses its pinned version or counters.

## 8. Phase 3 — Application services and backend administration

### Goal

Make the new contract usable by admin use cases and enforce all behavior rules server-side.

### Work

- Extend `PausedSearchTrackConfigInput` and step input with business-policy fields and canonical step actions.
- Keep `create_draft_paused_search_track` and `update_draft_paused_search_track` as the single write path.
- Add server-side normalization from the guided policy input to the persisted version/step configuration.
- Make draft validation and preview use the same planner and validator as runtime scheduling.
- Require optimistic locking for draft updates and publish against the expected draft version.
- Require explicit warning confirmation only for warnings; all errors remain publish blockers.
- Generate a plain-language behavior summary from the saved configuration, not from unsaved UI assumptions.
- Record audit events for draft policy changes, publish, retire, restore, validation confirmation, and compatibility blocks.
- Add an application service for reply-policy evaluation so inbound handling and Temporal wake-up use the same decision logic.
- Add an idempotent reminder/task service or port integration; a `send` or `skip` step must not create a reminder.

### API changes

Extend the existing paused-search route family and schemas rather than introducing a parallel API:

- Draft create/update accepts guided policy fields and per-step actions.
- Detail/list responses expose policy, reply behavior, action, limits, and compatibility status.
- Validate/preview returns findings, behavior summary, projected actions, timing boundaries, cycle/counter information, and preview reference.
- Publish requires the preview reference, expected draft version, and warning confirmation when applicable.
- Operations responses expose cancelled pending actions, reply classification, cycle transitions, reminders, and terminal reasons.
- Add a safe endpoint or response section for time-machine scenario results; it must be deterministic and must not send real messages.
- Keep role checks: brokerage admins/managers configure and publish according to existing permissions; agents receive only permitted operational views/actions.

### Tests

- Use-case tests for create/edit/validate/preview/publish/retire and optimistic-lock failures.
- API contract tests for request/response shape, validation payloads, permission failures, workspace isolation, and publish confirmation.
- Tests that old fields cannot be used to bypass the new policy contract.
- Audit assertions for every state-changing admin action.

### Exit gate

The API can create, validate, preview, and publish a waiting-for-rates track without the frontend, and the returned summary exactly describes the persisted configuration.

## 9. Phase 4 — Runtime scheduling, actions, and channel execution

### Goal

Execute the configured track through the existing planner and Temporal workflow without stale or duplicate sends.

### Work

- Update the domain planner to produce explicit action outcomes: send, review, reminder, skip, hold, cancel, terminalize, or expired.
- Support an enrollment message as a normal bounded step, drafted from approved conversation context and still subject to send-time rules.
- Support monthly maintenance as a repeatable step with calendar-safe scheduling and cumulative caps.
- Preserve a requested-date/reactivation boundary even when maintenance is enabled.
- Execute final email and SMS steps sequentially by default. If simultaneous delivery is supported, require explicit policy and independent pre-send checks.
- Enter `waiting_for_response` after the configured final send and do not schedule another automated step until a response or terminal policy resolves it.
- Persist every occurrence, action outcome, logical touch, provider identity, and idempotency key.
- Use row locks/version checks to prevent a reply, reassignment, suppression, or review decision from racing with a send.
- Route reminder actions to the assigned-agent task/notification path and make creation/cancellation idempotent.
- Keep uncertain provider outcomes in the existing reconciliation path; never blindly retry an uncertain send.

### Tests

- Enrollment send, monthly maintenance, final sequential email/SMS, and waiting-for-response tests.
- Per-step send/review/reminder/skip tests, including proof that send creates no reminder.
- Quiet hours, channel consent, SMS compliance, frequency, ownership, suppression, and pre-send race tests.
- Temporal restart, timer cancellation, stale cursor, duplicate worker, and uncertain provider tests.

### Exit-gate result

The API-created paused-search track now executes through the application and Temporal seams with two bounded maintenance occurrences, a final sequential email/SMS reactivation sequence, cumulative touch limits, and response waiting. The final step clears the paused-search cursor and a subsequent schedule attempt returns `no_cadence_step` without another provider call. Phase 4 is complete; Phase 5 reply-policy integration is the next active phase.

## 10. Phase 5 — Inbound replies, reclassification, and repeatable cycles

### Goal

Make every lead reply safe, deterministic, and consistent with the published reply policy.

### Work

- In `process_inbound_message_event`, cancel/invalidate pending occurrences and reminders before applying continuation logic.
- Deduplicate inbound events using workspace and provider event identity before side effects.
- Re-run structured classification with latest inbound content and bounded recent context.
- Apply hard outcomes first: opt-out, do-not-contact, human request, meaningful interest, human activity, ownership change, and review hold.
- Completed the first integration slice: an active lead with a pinned paused-search version now evaluates the published reply policy before generic AI continuation. Hard outcomes remain authoritative.
- `continue` and `restart` decisions resume the workflow through the existing Temporal reschedule path without sending an immediate AI reply; `end` maps to completion; `review` and timing-less `re-anchor` map to review hold.
- The selected paused-search reply decision is returned and persisted in inbound processing audit metadata.
- Pending occurrence/reminder cancellation is performed before a policy-driven continuation, preventing stale scheduled work from sending.
- For a pinned `reanchor_to_new_timing` version, reuse the existing structured lead-state classifier rather than adding a second timing-specific LLM call. Apply the result only when it selects the pinned track and returns a timezone-aware future boundary.
- For the same paused-search outcome, evaluate the pinned version's reply policy:
  - continue at the next step
  - restart after a configured delay
  - re-anchor to a newly captured timing boundary
  - hold/review/remind
  - end
- Preserve the original timing boundary and window label when the reply provides no new timing or an invalid/past timing. Replace them only when the new evidence is explicit, valid, and auditable.
- Never reset cumulative touches, duration, cycles, AI interactions, or audit history on restart.
- Prevent duplicate cycle creation when repeated webhooks or near-simultaneous replies arrive.
- Keep new published versions from silently changing an active workflow; migration remains explicit and permission-controlled.

### Tests

- Reply before a scheduled action cancels the action and prevents sending.
- Same-category waiting-for-rates reply continues/restarts according to policy.
- Updated timing re-anchors the next cycle.
- Changed intent triggers handoff rather than restarting.
- Opt-out/suppression permanently blocks future automated contact.
- Repeated replies do not create duplicate cycles or reset caps.
- Low-confidence/ambiguous classification holds for review.
- Completed slice coverage: continue resumes without an immediate AI send; re-anchor accepts a future same-track timing and rejects missing/past timing; the reused classifier is called once; existing hard-stop and inbound transition suites remain green.
- Completed restart/end slice coverage: `restart_delay_days` is persisted and exposed in track configuration; restart queues a delayed, idempotent Temporal resume; end and restart preserve cumulative counters and cancel pending reminders/occurrences; duplicate webhook delivery does not create another cycle.

### Exit gate

Every supported reply outcome has a single application-owned path, and the workflow cannot send a stale pending action after a reply.

## 11. Phase 6 — Guided frontend configuration and readback

### Goal

Replace the raw low-level editor experience with a guided business-policy builder while retaining bounded advanced controls where appropriate.

### Frontend/API client work

- Extend `src/lib/api/pausedSearchTracks.ts` types and client functions for the published policy fields, step actions, readback summaries, validation, and deterministic preview inputs. Compatibility-only legacy tracks and the runtime time-machine result contract remain explicitly out of this phase.
- Update query/mutation invalidation and dirty-state handling for optimistic-lock conflicts.
- Render structured server validation findings with field links and correction guidance.

Completed: the frontend API contract now includes track mode, interim-contact policy, reply policy, channel sequencing, cumulative cycle/AI limits, restart delay, step actions, recurrence, and fallback channels. Draft save, exact preview, publish, lifecycle, template, and readback clients match the backend routes. Publish errors for permission and stale/conflicting drafts are surfaced with actionable guidance.

### Editor work

Refactor `PausedSearchTrackEditor` and `pausedSearchTrackForm.ts` into guided sections:

1. Track purpose and classification guidance
2. Starting policy/preset
3. Timing and interim-contact permission
4. Per-step action: send, review, reminder, or skip
5. Reply behavior: continue, restart, re-anchor, review/remind, or end
6. Channels and sequence order
7. Content/template/profile selection
8. Limits and terminal behavior
9. Plain-language summary and exact timeline preview

Add conditional fields and explanations so an admin is not shown irrelevant technical settings. Keep code-owned limits read-only and explain why they cannot be overridden.

### Preview and operations work

- Extend `PausedSearchTrackPreview` to show action outcomes, consent assumptions, timing boundaries, cycle counters, pending-response state, optional reminders, and blocked paths.
- Add a deterministic scenario selector for the approved timing projections. The full projected state/actions/messages/reminders/handoffs/audit-event time-machine result contract remains Phase 7.
- Show final email/SMS sequencing explicitly rather than presenting them as a simultaneous generic touch.
- Keep the editor bounded to the current published API contract; compatibility-only legacy-track handling remains a backend/Phase 7 concern until its API contract is defined.

Completed: deterministic preview scenario presets use the existing server preview contract with one reference timestamp (`baseline`, `before requested date`, and `after requested date`). The full runtime time-machine harness remains Phase 7.

### Tests

- Form default/preset tests and conversion round trips.
- Per-step action and reply-policy interaction tests.
- Validation error rendering and publish confirmation tests.
- Preview/timeline tests for initial send, monthly maintenance, final channel sequence, reply, reminder, and terminal outcomes.
- Responsive/accessibility tests for admin and operations surfaces.

Completed Phase 6 verification: frontend tests passed (104 passed, 1 skipped), typecheck, lint, formatting, and production build passed; backend paused-search admin API and application tests passed, including policy readback and `restart_delay_days`.

### Exit gate

An admin can configure the waiting-for-rates example without seeing or editing raw internal fields, and the UI summary matches the API preview response.

## 12. Phase 7 — Deterministic time-machine test harness

### Goal

Prove the actual runtime behavior over months, replies, retries, restarts, and policy changes.

### Harness design

- Use a controllable clock and calendar-day timezone handling.
- Use fake CRM, LLM, SMS, email, notification/task, repository, event, and Temporal dependencies.
- Drive the same application use cases used by production entry points; do not create a test-only workflow implementation.
- Capture workflow state, occurrence records, scheduled actions, provider calls, reminders, counters, and workflow transition/audit evidence in the harness snapshot. Reuse the existing inbound processing fakes and Temporal matrix for CRM updates, classification artifacts, handoffs, suppression, delayed restart, and durable signal assertions.
- Support advancing time, injecting replies/human activity, restarting workflows, delivering duplicate webhooks, and returning provider failures/uncertain outcomes.
- Compare runtime results with the behavior summary generated by the preview endpoint.

### Required scenarios

- Enrollment message sends only when allowed.
- Monthly maintenance with explicit permission.
- Monthly maintenance without permission produces no send.
- Six-month boundary prevents premature reactivation.
- Final email then SMS follows configured sequential order and channel checks.
- Final send enters waiting-for-response.
- Reply cancels pending work before reclassification.
- Same waiting-for-rates reply follows continue/restart/re-anchor policy.
- New timing changes the next boundary safely.
- Interest or human request hands off and stops AI.
- Opt-out suppresses every future channel.
- Optional reminder appears only on reminder-configured steps.
- Send/review/skip steps do not create unintended reminders.
- Cumulative caps stop repeated cycles.
- Track publish/version pinning does not alter an active workflow silently.
- Reassignment, workflow restart, duplicate webhook, provider failure, and uncertain send are safe.

### Exit gate

All required runtime scenarios pass against the real domain/application/Temporal seams, the dedicated inbound and Temporal suites remain green for reply/handoff/suppression behavior, and preview output agrees with runtime output for the deterministic lifecycle scenario.

## 13. Phase 8 — Remove and deprecate unwanted behavior

Removal happens only after the new path is proven and legacy data is classified.

### Behaviors to remove from new configuration

- Raw free-form combinations that bypass a guided policy.
- External/API reliance on `review_required` instead of the canonical step action.
- Monthly or recurring contact inferred solely from `maintenance_interval_days`.
- Automatic reminders created as a side effect of enrollment or every step.
- Simultaneous SMS/email as an implicit default.
- Restart logic that resets touch, duration, cycle, or AI limits.
- Continuation/restart without an explicit reply policy.
- Date guessing for vague timing.
- Any send path that trusts schedule-time eligibility without a final re-check.
- Any workflow start without a published pinned track version.

### Compatibility and retirement strategy

- Existing published versions remain readable and pinned for active workflows.
- Legacy versions become compatibility-only and cannot be used for new enrollments after the cutover flag is enabled.
- Legacy workflows with missing or unsafe policy data are held for review rather than automatically migrated into guessed behavior.
- Add an admin migration path for explicitly reviewed active leads; record actor, reason, source version, target version, and recomputed next action.
- Remove old frontend controls and old write fields after all supported clients use the new API contract.
- Remove compatibility mapping only after migration reports show no remaining active references.

#### Phase 8A compatibility boundary

- The admin use case now rejects new draft input that explicitly opts into the
  legacy `review_required` behavior, while persisted published versions remain
  readable and executable through the existing compatibility mapping.
- No database column is removed in this slice. `maintenance_interval_days` and
  the legacy review field remain available for pinned historical versions until
  an active-reference report and reviewed migration are complete.
- The API contract and frontend write path must be migrated next so guided
  drafts express recurring behavior through explicit step actions and policies;
  only then can the legacy fields be made read-only and eventually dropped.
- The next exit evidence is a workspace-scoped inventory of active versions,
  workflows, and supported clients, followed by an audited migration report.

#### Phase 8B inventory and non-destructive migration preparation

- Added a read-only workspace-scoped legacy inventory use case and admin route at
  `GET /{workspace_id}/paused-search-tracks/legacy-inventory`.
- The report identifies persisted legacy versions, their pinned active workflow
  references, workflow state, and next action without mutating data.
- Inventory queries filter every persistence read by `workspace_id`; empty
  legacy sets produce an empty report and do not issue a workflow query.
- The report is evidence for a later reviewed migration, not an automatic
  conversion or deletion mechanism.

#### Phase 8C guided write-path cleanup

- New draft request schemas no longer accept `review_required` or
  `maintenance_interval_days`; historical response models retain both fields
  for compatibility readback.
- The admin adapter supplies the internal maintenance column from the guided
  default pause duration so existing persistence/runtime contracts remain
  intact without exposing the legacy request field.
- New drafts reject legacy compatibility choices including simultaneous
  sequencing, review/reminder actions, restart-after-delay and
  review-or-remind reply policies, and maintenance-interval fallback timing.
- The editor no longer renders deprecated timing, reply, sequence, action, or
  review controls. Persisted legacy versions remain readable and executable.

### Exit gate

No new track or enrollment can enter an unwanted legacy behavior, and every retained legacy workflow has a visible compatibility status and safe runtime outcome.

## 14. Phase 9 — Pilot rollout and final signoff

### Work

- Keep recurring paused-search execution disabled by default and enable one pilot workspace at a time.
- Verify admin permissions, consent data, SMS compliance, templates, notification routing, and assigned-agent ownership before enabling sends.
- Monitor due, held, reviewed, sent, cancelled, failed, uncertain, terminal, handoff, opt-out, and re-anchor outcomes.
- Provide support readback for track version, current state, next action, last classification, counters, and audit history.
- Run rollback rehearsal: disable new enrollment/execution, preserve active workflows safely, and verify no pending action bypasses suppression or handoff.
- Update the release checklist, operations runbook, and test matrix.

### Final signoff requirements

- Backend targeted tests, persistence/API tests, frontend tests, and time-machine tests pass.
- `make check` passes in `miller-schackman-api/`.
- `pnpm check` passes in `miller-schackman-web/`.
- Migration upgrade and tenant-isolation checks pass.
- Browser inspection covers desktop, tablet, and mobile admin flows.
- Preview and runtime summaries match for the required scenarios.
- No unresolved publish-blocking validation errors remain.
- The client-approved policy decisions are recorded and auditable.

## 15. Test command checklist

Run the smallest relevant command after each phase, then expand at the gates:

### Backend targeted checks

- `uv run pytest tests/domain/campaigns/test_paused_search_timing.py`
- `uv run pytest tests/application/use_cases/test_paused_search_track_admin.py`
- `uv run pytest tests/application/use_cases/test_schedule_next_paused_search_action.py`
- `uv run pytest tests/application/use_cases/test_campaign_cadence_execution.py`
- `uv run pytest tests/application/use_cases/test_lead_paused_search.py`
- `uv run pytest tests/application/use_cases/test_process_inbound_message_event.py`
- `uv run pytest tests/application/use_cases/test_paused_search_time_machine.py`
- `uv run pytest tests/infrastructure/test_temporal_paused_search_track_matrix.py`
- `uv run pytest tests/infrastructure/persistence/postgres/test_paused_search_track_repository.py`
- `uv run pytest tests/interfaces/api/v1/test_paused_search_tracks_admin.py`

### Frontend targeted checks

- `pnpm vitest run src/lib/api/pausedSearchTracks.test.ts`
- `pnpm vitest run src/components/settings/PausedSearchTracksCard.test.tsx`
- `pnpm vitest run src/app/AdminOperationsRoutes.test.tsx`
- `pnpm vitest run src/app/LeadsRoutes.test.tsx`

### Full gates

- Backend: `make check`
- Frontend: `pnpm check`
- Time machine: the dedicated paused-search deterministic harness suite
- Browser: manual/automated responsive and accessibility inspection

## 16. Definition of done

This work is complete only when:

- Admins can configure the approved business behaviors without unsafe low-level combinations.
- API, backend, database, and frontend contracts agree on the same versioned model.
- Initial, recurring, final, review, reminder, skip, reply, handoff, suppression, and terminal actions are explicit.
- Existing unwanted behavior is removed from new paths and legacy behavior is compatibility-only or safely migrated.
- Every outbound action is revalidated immediately before provider dispatch.
- Every reply cancels stale work and is reclassified before continuation.
- Repeated cycles cannot reset cumulative limits or create duplicate work.
- Published versions and active workflow pins remain auditable and safe.
- The time-machine harness proves the waiting-for-rates example and all listed edge cases.
- Full backend/frontend checks and release verification pass.
- The client-facing behavior summary matches what the application actually does.