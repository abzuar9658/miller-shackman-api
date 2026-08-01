# Paused-search R8 release checklist

This checklist separates automated engineering evidence from approvals that must be
recorded by a human owner before widening the recurring paused-search pilot.

## Automated evidence

- [x] Full backend pytest suite passes.
- [x] Backend mypy passes for app and tests.
- [x] Changed-file Ruff checks pass.
- [x] Frontend `pnpm check` passes: lint, typecheck, 18 test files, 88 tests, and formatting.
- [x] Tenant isolation and PostgreSQL RLS tests pass.
- [x] Paused-search API role and authorization tests pass.
- [x] Clean/legacy Alembic compatibility test passes.
- [x] Local development database upgraded from `0065` to
      `0068_add_paused_occurrence_fallback_marker`.
- [x] Pilot allowlist and recurring flag tests pass.
- [x] DST calendar-day scheduling tests pass.
- [x] Temporal hold propagation tests pass.
- [ ] Browser accessibility and responsive inspection.

## Pilot configuration gate

Both controls are required for recurring maintenance:

1. Set the audited workspace field `recurring_paused_search_enabled` to `true`.
2. Add the workspace UUID to `RECURRING_PAUSED_SEARCH_PILOT_WORKSPACE_IDS`.

An empty allowlist is fail-closed. Enable one workspace at a time and verify the
health strip, occurrence list, review queue, structured worker logs, and provider
outcomes before expanding the list.

## Rollback rehearsal

- [ ] Disable the workspace recurring-maintenance flag.
- [ ] Remove the workspace UUID from the deployment allowlist.
- [ ] Confirm no new occurrence is created and held workflows do not send.
- [ ] Confirm existing occurrences, reviews, audit history, and published versions remain.
- [ ] Reconcile any uncertain provider result before retrying.
- [ ] Re-enable only through an audited change followed by explicit resume/revalidation.

## Manual testing protocol

Execute these steps in order in a non-production workspace. Use synthetic leads and
provider sink/test credentials only. Do not continue to the next step when an expected
hold, suppression, or authorization check fails.

### Step 0 — Environment and evidence setup

- [ ] Record environment, deployment/version, database revision, workspace UUID, tester,
      and test timestamp.
- [ ] Confirm the workspace is not a production workspace and that SMS/email providers
      cannot contact real consumers.
- [ ] Confirm the tester has only the role required for the step being performed.
- [ ] Capture correlation IDs, workflow IDs, occurrence IDs, and audit-event IDs; never
      capture message bodies, access tokens, credentials, or unnecessary contact data.

**Evidence / result:** PASS for local harness setup. API startup was verified on an isolated
port with `SMS_PROVIDER=sink` and `EMAIL_PROVIDER=sink` process overrides; Postgres is at
`0068_add_paused_occurrence_fallback_marker`. Authenticated role and named non-production
workspace still require operator confirmation before state-changing tests.

### Step 1 — Browser accessibility and responsive inspection

- [x] Open the operations dashboard at desktop width and verify readable hierarchy,
      visible focus, keyboard navigation, status meaning, and no horizontal overflow.
- [x] Repeat at tablet width and verify tables, filters, drawers, and action controls
      remain usable without clipped content.
- [x] Repeat at mobile width and verify navigation, occurrence/review details, and
      destructive-action confirmation remain usable.
- [ ] Verify loading, empty, error, permission-denied, and reduced-motion states.

**Evidence / result:** PARTIAL PASS. Playwright Chrome is installed and the frontend was
inspected at desktop (1440px), tablet (1024px), and mobile (390px) widths. The sign-in
surface remained readable with no horizontal overflow at mobile width; keyboard focus
advanced through both credential inputs and the Sign in button. Console warnings/errors
were absent during inspection. Loading, empty, error, permission-denied, and reduced-motion
states were not exercised because no authenticated test session was available.

### Step 2 — Fail-closed controls

- [x] Confirm `recurring_paused_search_enabled` is `false` or the workspace is absent
      from `RECURRING_PAUSED_SEARCH_PILOT_WORKSPACE_IDS`.
- [x] Attempt the approved enrollment/planning path with a synthetic eligible lead.
- [x] Verify no new occurrence is created, no provider call is made, and the workflow
      remains safely held with an audit/log reason.
- [ ] Verify draft validation and preview remain available if that is part of the test.

**Expected result:** recurring execution is blocked without data deletion or sending.

**Evidence / result:** PASS for the recurring paused-search path. The local demo workspace
reported `recurring_paused_search_enabled=false`. A local test lead was marked with the
documented `timing_not_right` paused-search reason, then manual enrollment returned
`review_hold` with `recurring_paused_search_disabled`. No workflow or enrollment ID was
returned, and the lead had zero paused-search occurrences afterward. The dormant-route
attempt performed before selecting the paused-search lead is not included as Step 2 evidence.

### Step 3 — Allowlisted pilot smoke test

- [x] Enable the workspace flag through the audited control path and add only the test
      workspace UUID to the deployment allowlist.
- [x] Re-run eligibility and enrollment for a synthetic lead; verify the pinned track,
      step, schedule, and one occurrence are read back correctly.
- [x] Verify the occurrence enters the expected review/approved/send state and that
      structured logs contain identifiers but no message body or credentials.
- [x] Verify the provider sink/test adapter records at most the intended idempotent call.

**Expected result:** only the allowlisted, enabled workspace can execute recurring work.

**Evidence / result:** PASS for the clean synthetic pilot lead. The workspace flag was
enabled through the audited settings endpoint and the isolated API instance was started
with only the test workspace in the pilot allowlist plus SMS/email sink providers. A new
synthetic lead with an active `timing_not_right` paused-search profile, an eligible
published campaign, and no existing workflow enrolled successfully with HTTP 200,
`status=started`, and `route=paused_search`. The workflow was pinned to the maintenance
track step and one occurrence was read back as `planned`, occurrence 1, with no message
or provider ID. The current Temporal worker emitted structured scheduling logs containing
workspace, lead, workflow, occurrence, and cadence-step identifiers without message body
or credential fields. Because the occurrence is scheduled for a future date, the SMS and
email sink adapters recorded zero provider calls. The earlier unsuitable-lead attempts
remain non-pass evidence only and did not alter this result.

### Step 4 — Review, send, and interruption safety

- [x] For a review-required occurrence, approve or reject with an explicit reason and
      verify the audit record and occurrence transition.
- [x] For an approved send, verify one logical touch, provider acceptance metadata, and
      the next planned occurrence (when within configured bounds).
- [x] Before a pending send, add synthetic human activity, an inbound reply, or an
      audited manual pause and verify
      the pending send is cancelled/held, the workflow pauses or hands off, and no
      provider call occurs afterward.
- [x] Verify repeated callback or wakeup delivery does not create a second occurrence,
      logical touch, or provider send.

**Evidence / result:** PASS for Step 4. The empty
workspace template registry was backfilled through the existing template-registry use
case with 14 approved paused-search email templates. The published
`paused-search-timing-not-right` track was updated and republished through the audited
draft/preview/publish path as version 2; both maintenance and reactivation steps now
have immutable template bindings. A CRM-backed sendable fixture using lead
`6df554c2-526d-4141-8935-61c749fe2493` enrolled on the `paused_search` route and
created occurrence `e4aa220c-ab53-4479-b761-a616fb880e28`. It reached `sent` with
`logical_touch_count=1` and sink-provider acceptance metadata via provider ID
`sink-email-62e6ca16-d302-4fd0-808c-89b86ba735d1`; the sink occurrence's delivery
status field remained unset. No SMS or email provider outside the sink was called.
The CRM adapter did refresh the lead and wrote its normal
outbound activity note during this test; this was not a fully isolated synthetic
CRM fixture and must not be treated as a production-data pass. The workflow was
then paused for cleanup.

The first interruption attempt with lead `17f32c02-eaaf-407c-a93f-b2d11d71dbb1`
exposed a PostgreSQL `deadlock detected` while the Temporal activity competed with
test cleanup. A lock-ordering fix was implemented in cadence execution and outbound
sending so lead locks precede workflow/message locks; the focused cadence and
outbound-send tests passed. The fixed path was then replayed with an isolated local
CRM fixture using lead `f4ed1ae5-29e9-401e-85ef-df7f84086997`. Enrollment returned
`started` on the `paused_search` route and created planned occurrence
`bbb4296a-5f1d-447c-87c8-5e9ee2edc1b0` under workflow
`7c685b0a-8e58-4642-a0d3-fafed9022431`. The audited manual-pause route was applied
before the due time. After the due time, Temporal logged `no_cadence_step` with
reason `workflow state paused is not sendable`; the occurrence remained `planned`,
with no provider message ID and `logical_touch_count=0`, and the workflow remained
`paused` with `pause_reason=manual_pause`. No deadlock occurred, no CRM provider
call was made, and sink SMS/email providers recorded no send. The initial
interruption replay did not exercise review or duplicate callback behavior; those
follow-up scenarios are recorded below. The attempt involving the existing
human-handoff lead was rejected before workflow creation and is not evidence.

The review-required path was then exercised with isolated synthetic lead
`0fa16ecd-a6f1-4c7b-b292-756e03eb5475`. Its review-required reactivation occurrence
`aedcf918-10f0-4e8d-b622-eae55e6f1cca` entered `review_requested`. An operator rejected
review `5589cfdf-7f67-47b3-bfc7-c53eeb0b6017` with an explicit reason. The persisted
review became `rejected`, recorded a reviewer and reason, and the occurrence became
`skipped` with no provider message ID and `logical_touch_count=0`. The audit event
`paused_search.message_review_reject` was present for that lead.

Duplicate callback safety was exercised with isolated synthetic lead
`046874fc-b1d2-42f6-870a-daaf30673021`. Review
`5c4a7d58-421f-40d9-a261-e2a83ea3c324` was approved with an explicit reason; repeating
the same approval callback and idempotency key returned `already_resolved`. Temporal
logged repeated scheduling for the same occurrence, but no second occurrence was
created. The final occurrence `989d66b5-6aac-4771-b20d-0fdab4e7e1bd` was `sent` once
with `logical_touch_count=1`, one sink provider message ID, and one outbound message
row. The workflow was `waiting_for_response`. The persisted audit event was
`paused_search.message_review_approve`; no duplicate provider message or logical touch
was produced.

### Step 5 — Rollback and recovery

- [x] Disable the workspace flag, then remove the workspace UUID from the allowlist.
- [x] Verify held workflows remain held and no new occurrence or provider send occurs.
- [x] Verify existing occurrences, reviews, audit history, and published versions remain
      readable and unchanged.
- [ ] If an uncertain provider result is produced, reconcile it using the provider ID or
      idempotency key before any retry; record the operator reason.
- [ ] Re-enable only after explicit audited approval and fresh eligibility/revalidation.

**Expected result:** rollback stops new execution without deleting history or duplicating
outreach.

**Evidence / result:** PARTIAL PASS. The recurring flag was restored to `false` through
the audited automation settings endpoint; the pilot allowlist was process-local and
the isolated API and Temporal worker were stopped. The held workflows remained paused
and their occurrences remained readable: the Step 3 planned occurrences stayed
`planned`, the interruption occurrence stayed `planned` with no provider ID, and the
successful send remained readable as `sent` with one logical touch. The published
track version and template bindings remain readable. Uncertain-provider reconciliation
and audited re-enable were not exercised.
### Step 6 — Release decision

- [ ] Attach evidence for every completed step and record any deviation or failed check.
- [ ] Open a defect and stop rollout for any unexpected send, cross-workspace read/write,
      missing audit record, duplicate provider call, or unsafe resume.
- [ ] Obtain the required human sign-offs below before expanding the pilot allowlist.

## Human sign-off

| Area | Owner | Status | Evidence / date |
|---|---|---|---|
| Product behavior and acceptance scenarios | Product owner | [ ] | |
| Engineering implementation and rollback | Engineering owner | [ ] | |
| QA test evidence | QA owner | [ ] | |
| Workspace isolation and sensitive data | Security owner | [ ] | |
| Pilot operations and alert ownership | Operations owner | [ ] | |

## Known environment limitation

Playwright Chrome is now installed and the authenticated sign-in surface has been
inspected at desktop, tablet, and mobile widths. Authenticated loading, empty, error,
permission-denied, and reduced-motion states remain untested. The approved non-production
OpenRouter configuration was used for classification while SMS and email remained sink
backed; no external messaging provider was called. A stale local Temporal worker was
replaced with a current-checkout worker before the passing smoke test.
