# Issue 16-A — execution contract and evidence

## Authority and scope

API baseline: `f5dbf4e679810f6dc558acb7bee3645eb748a2ca` (app/tests match reviewed `a761c1b`).
Owner approved Approach A, existing branch `16A-preserve-opt-outs`, target `main`, a separate
review sub-agent, and themselves as release/recovery operator. The existing planning commits
are accepted in the PR baseline. The owner will merge after testing; no merge, deployment or
production recovery is authorized here.

Independent `issue16a-independent-contract-review` approved AC-01–10/13–14 and the first full-sync
SMS-preservation test. On 2026-09-09, independent `issue16a-independent-recovery-contract-review`
explicitly approved B1–B4/N1/N2 below and the first AC-11 dry-run/apply/repeat scenario after tracing
the actual writers. No recovery expectations or recovery implementation preceded that approval.
This record supplements, not replaces, the ticket and scoped owner-approval register.

**Current verification update (2026-09-10):** the separately approved, test-only handoff clock
correction closes the baseline failure recorded below. The current unstaged source passes the
full suite (**1841 passed, 2 opt-in live-LLM skips**, exit 0) and the **301-test** recovery scope.
The [remediation supplement](issue-16a-review-remediation-evidence.md) contains the causal diagnosis,
test-first red/green results and current source fingerprint. No production routing policy changed.
The subsequently authorized [local sink-only UI preparation](issue-16a-local-ui-acceptance.md)
uses the same source and is complete. Its authenticated browser run found 12 false-success toasts
for correctly refused sends and exited **1**. The user then separately approved a frontend-only
correction on the matching `16A-preserve-opt-outs` branch. The current frontend check/build passes
(156 tests passed, 1 pre-existing skip) and the completed local browser rerun exits **0**, with
truthful feedback for all 12 refusals and no queued or duplicate sends through readback/offline faults.
The local acceptance record distinguishes this current evidence from the failed runs. Backend source
remains unchanged. Independent stakeholder acceptance is still open; historical results below remain
historical. Non-deploying CI, publication, release and production recovery require separate authorization.

## Independently approved recovery details (B1–B4, N2)

- **B1 — Selection:** retain a complete existing platform provenance tuple (nonempty provider and
  source event ID, parseable timezone-aware occurrence). Otherwise select the earliest verified
  occurrence from the complete retained history for the scoped lead/restriction. Equal instants
  sort by provider then source event ID, case-sensitive lexicographic string order. Row UUID/input
  order is not a consent tiebreaker. Duplicate evidence with the same identity/kind/time contributes
  one candidate; contradictory facts for the same identity are unresolved. Existing provenance
  that contradicts its matching retained event is unresolved, never silently replaced.
- **B2 — Lift evidence:** the baseline has no authorized lift writer/audit schema. A permissive CRM
  snapshot, START text, workflow resume, or missing flag is not verified lift evidence. Do not invent
  a database lift event or claim automatic detection. The bounded operator input must support
  explicit consent-review holds by lead ID (including a known later legitimate lift reported during
  the operator's inventory). Such leads are reported unresolved and never modified. Apply must
  explicitly acknowledge that the remaining scope has been reviewed for unrecorded later lifts.
  This is an operational exclusion/attestation, not a lifting route or proof no external lift exists.
  If a future lifting schema is introduced, review this maintenance tool before reuse.
- **B3 — Identity:** all joins include workspace. Linked suppression events must match both the
  scoped lead ID and any non-null CRM lead ID; contradictions are unresolved. For an orphan
  (`lead_id IS NULL`, status `ignored`, reason `lead_not_found`), accept only an exact
  `contact_suppression.<known kind>` with `provider=follow_up_boss`, matching the scoped lead's
  `(workspace_id, crm_provider=follow_up_boss, crm_lead_id)`. This adapter is a verified producer
  of that CRM identity. The baseline does not persist CRM provider separately on external_events;
  a non-CRM provider orphan cannot be disambiguated by guessing and is unresolved. Do not join
  on email/phone, across tenants, or by provider event ID alone. Never mutate original event rows.
- **B4 — Legacy provenance:** the mapper's `*_source=follow_up_boss.customFields` alone is a
  CRM-snapshot marker, not platform event evidence. A source-provider key remains platform evidence
  even when its value is `follow_up_boss`. Partial/malformed platform tuples require review; do not
  invent missing keys. An active restriction with empty/unknown provenance and no verified history
  is unresolved and remains restricted. Absent evidence is not proof of permission. Empty evidence
  with verified matching history can be restored using B1. Routine refresh retains ambiguous
  existing restrictions without fabricating provenance; only proven CRM-only restrictions may clear.
- **N2 — Inbound evidence:** join inbound_messages to external_events via external_event_id plus
  workspace and lead, checking provider identity. Require a classified inbound record and its
  persisted processing_audit classifier.opt_out_detected=true or decision.reply_route=suppress.
  Use external_events.provider_event_id as the original source event identity, **not** the inbound
  row UUID (and do not assume it equals provider_message_id). Use inbound_messages.received_at as
  occurrence time. The existing writer applies exactly those source values. No raw-body parsing,
  classifier rerun, or imagined inbound_messages.opt_out_detected column.
- **Provider history:** generic failed/bounced/dropped delivery is not consent evidence. A known
  explicit provider unsubscribe code may be accepted only after its retained payload, linked
  outbound identity, and channel mapping are independently verified; otherwise report for review.
- **Bounds/completeness:** explicit nonempty workspace and bounded lead IDs; full retained history
  per lead, bounded by a validated event ceiling. Exceeding the ceiling is unresolved, never a
  truncated successful repair. No date-limited selection that accidentally misses earlier evidence.
  Default dry-run writes no database state. Apply rechecks under a row lock and commits per lead;
  safe interruption/retry retains original events and other restrictions. Report candidate,
  already-correct, changed (would-change in dry-run), unresolved and failed totals plus references.
  No workflow/message/provider/enrollment capabilities are passed to the repair boundary.

## Persistence mechanism stated before AC-09 scaffolding (N1)

Use the existing upsert port without forcing every application fake to implement a new method.
At the Postgres write boundary: INSERT ON CONFLICT DO NOTHING RETURNING for a missing identity;
on conflict, SELECT FOR UPDATE by `(workspace_id, crm_provider, crm_lead_id)`, with
`populate_existing` to avoid SQLAlchemy identity-map staleness, merge durable restrictions and
newest activity from that locked record, then update/return. The unique constraint serializes
concurrent first inserts; DO NOTHING cannot erase a concurrent committed restriction. Ordinary
upserts still allow deliberate app-owned paused-profile changes; CRM callers retain their existing
paused-profile merge. No new lock is taken before a CRM/network fetch. Transaction owners retain
commit/rollback control; this ticket does not change lifecycle policy or transaction boundaries.

AC-09 will use independent committed sessions and asyncio barriers, exercising stale refresh after
suppression and suppression after refresh, initial-identity contention and identity-map freshness.
Assertions use a fresh repository read. No single-session rollback fixture is concurrency proof.

## Historical execution evidence — original implementation

Executed on 2026-09-09 at implementation revision `4bca9c31887231ef119fc2bbea620df61d8b4b57`,
against baseline `f5dbf4e679810f6dc558acb7bee3645eb748a2ca`. Later revisions through `251715e`
were documentation-only. **These historical results predate the recovery defects identified on
2026-09-10; they are not current acceptance evidence.** The [review-remediation supplement](issue-16a-review-remediation-evidence.md)
records R4–R6 corrections, added real-Postgres interruption coverage, final checks and independent
review of the now-unstaged source. No further commit or push is authorized. The historical PR-creation
attempt failed; no PR was created, and any future PR must remain draft until the open gates close.

Environment: local ARM Mac, existing Python 3.12 environment, synthetic data and disposable
Postgres databases. A local-only guard checked both database hosts before running tests and passed
the configured URLs to the child process in memory; credentials were not printed. External CRM,
LLM and messaging integrations were faked; no real customers or production data were contacted.

**Not a green full suite or release approval:** the full run has one baseline-reproducing failure;
authenticated UI/staging acceptance, real providers and production containment are not verified.
The requesting owner alone will merge after testing. The checked-in workflow deploys after a main
push, so neither main nor the deployment workflow was used to obtain a CI result.

### Reproducible commands and final results

Run from the API repository, only after verifying an authorized local/test database configuration.
These are the underlying pytest invocations; isolated sensitivity runs used the same interpreter
with the detached checkout as working directory/PYTHONPATH and the guarded local configuration.

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/arch -arm64 .venv/bin/python -m pytest -o addopts= -q -ra --tb=short --show-capture=no
/usr/bin/arch -arm64 .venv/bin/python -m ruff check .
/usr/bin/arch -arm64 .venv/bin/python -m mypy app tests scripts/recover_recorded_opt_outs.py
````
</augment_code_snippet>

| Check | Actual result |
| --- | --- |
| Full pytest suite | **1 failed, 1808 passed, 2 skipped**, 10 warnings, 38.35s; exit **1** |
| Ruff | All checks passed; exit **0** |
| Mypy, including the recovery CLI | No issues in **630 source files**; exit **0** |
| Restored isolated-checkout scope below | **269 passed, 0 failed, 0 skipped**, 2 warnings, 14.90s; exit **0** |
| Live-LLM cases | Two explicit opt-in tests skipped; no live-provider validation claimed |

The failing node is
`tests/interfaces/api/v1/test_webhooks.py::test_follow_up_boss_crm_webhook_completes_tag_time_human_handoff`.
Its handoff-set assertion produces `set() != {None}`. Running that exact node with the full-run
flags above fails on both the untouched baseline and the fix (one failure each, exit 1). No test
was weakened, skipped or marked expected-failure to conceal it. Resolution requires separate scope
approval; reproducing a baseline failure does not waive the merge gate.

Scoped command (also rerun after restoring every sensitivity mutation):

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/arch -arm64 .venv/bin/python -m pytest -o addopts= -q -ra --tb=short --show-capture=no \
  tests/application/services/test_crm_lead_refresh.py tests/application/use_cases/test_crm_sync.py \
  tests/application/use_cases/test_recover_recorded_opt_outs.py tests/application/use_cases/test_refresh_opt_out_send.py \
  tests/infrastructure/crm/test_refresh_opt_out_people.py tests/infrastructure/persistence/postgres/test_lead_opt_out_durability.py \
  tests/infrastructure/persistence/postgres/test_lead_repository.py tests/infrastructure/persistence/postgres/test_opt_out_lead_detail.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery.py tests/infrastructure/persistence/postgres/test_opt_out_recovery_delivery_history.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery_history.py tests/scripts/test_recover_recorded_opt_outs.py
````
</augment_code_snippet>

### Qualifying red and isolated sensitivity evidence

These records distinguish original test-first evidence from later sensitivity checks. They do not
claim that every later parameterized case was independently red before implementation.

| ID | Revision and exact behavior disabled / original scenario | Observed failure | Restored result |
| --- | --- | --- | --- |
| R1 | Unchanged application code at baseline f5dbf4e; original `test_full_sync_preserves_recorded_sms_opt_out_and_original_evidence` (now generalized in SYNC below) | saved.sms_opted_out was False; 1 failed, exit 1 | Same test plus original paused-search control: 2 passed, exit 0 |
| R2 | Baseline plus SMS fix; original `test_full_sync_preserves_recorded_opt_out_and_original_evidence[email]` | saved.email_unsubscribed was False; 1 failed/1 passed, exit 1 | SMS/email plus original paused-search control: 3 passed, exit 0 |
| R3 | Uncommitted minimal recovery scaffold after approved B1–B4/N1/N2; `RECOVERY::test_recovery_dry_run_apply_and_repeat_restore_original_email_evidence` | No-op scaffold returned CLEAN; preview.would_change was 0 instead of 1; 1 failed, exit 1 (not an import error) | Same node: 1 passed, exit 0; later included in the 269-pass run |
| M1 | Detached 4bca9c3: make `preserve_durable_lead_state` return incoming state unconditionally | Four path selectors below: 60 failed/4 passed, exit 1; recorded restrictions lost (24 sync, 12 on-demand, 12 people, 12 pre-send failures). Four clean people controls passed. | Restore domain function; 269 passed, exit 0 |
| M2 | Detached 4bca9c3: replace locked-row durable merge with incoming record in Postgres upsert | DURABILITY stale-refresh + concurrent-first-insert selectors: 4 failed/4 passed, exit 1; stale-after-opt-out SMS/email/DNC and opt-out-first insert lost their flags | Restore merge; all eight pass in M3 run, then 269 passed, exit 0 |
| M3 | Detached 4bca9c3: recovery upserts the original lead instead of the restored lead, leaving status/report logic intact | R3 selector plus the eight restored M2 cases: 1 failed/8 passed, exit 1; fresh saved.email_unsubscribed was False instead of True | Restore recovery write; 269 passed, exit 0 |

R1/R2 were generalized before the implementation commit; R3's no-op scaffold was also uncommitted.
Their exact intermediate source snapshots are not retained as git revisions; the contemporaneous
tool results are in the [implementation session](https://cosmos.augmentcode.com/session?agentId=01M22VSS150G88K3XDZ1P3CK03).
M1–M3 are reproducible mutations of the pinned implementation, not claims of baseline snapshots.
M2 demonstrates the locked-state merge guard, not a separately measured lock-removal experiment.
All mutations were isolated from the PR branch and restored; no deliberate breakage is delivered.

M1 used these selectors with the pytest flags above and `--tb=line`:

- `SYNC::test_sync_preserves_recorded_opt_out_and_original_evidence`
- `REFRESH::test_on_demand_refresh_keeps_recorded_opt_out_and_evidence`
- `PEOPLE::test_people_refresh_keeps_recorded_opt_out_through_real_mapping`
- `SEND::test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard`

### Acceptance mapping

Aliases below are paths relative to `tests/`. An exact single-node command is the full-run command
above plus the expanded `tests/<file>::<function>` selector. Without a parameter suffix pytest runs
every listed parameter combination. **G** means that node and all its parameters were included in
the 269-pass run at 4bca9c3 (exit 0, no skips), not a fabricated separately measured result.
**Control** means a baseline-regression expectation, not qualifying red evidence.

| Alias | Test file |
| --- | --- |
| SYNC | application/use_cases/test_crm_sync.py |
| REFRESH | application/services/test_crm_lead_refresh.py |
| PEOPLE | infrastructure/crm/test_refresh_opt_out_people.py |
| SEND | application/use_cases/test_refresh_opt_out_send.py |
| DURABILITY | infrastructure/persistence/postgres/test_lead_opt_out_durability.py |
| RECOVERY | infrastructure/persistence/postgres/test_opt_out_recovery.py |
| HISTORY | infrastructure/persistence/postgres/test_opt_out_recovery_history.py |
| DELIVERY | infrastructure/persistence/postgres/test_opt_out_recovery_delivery_history.py |
| DETAIL | infrastructure/persistence/postgres/test_opt_out_lead_detail.py |
| CLI | scripts/test_recover_recorded_opt_outs.py |

Vector **C** = permissive, permissive-missing-DNC, unknown-missing-DNC, explicit-false.
Vector **P** = omitted raw fields, unknown/null raw fields, explicit-false raw fields,
permissive custom fields. Vector **S** = permissive, unknown-missing-DNC, explicit-false.

| AC / cases | Exact selector(s) | Red / sensitivity or control | Green | Boundary / remaining gap |
| --- | --- | --- | --- | --- |
| AC-01 / SMS, full and incremental × C | SYNC::test_sync_preserves_recorded_opt_out_and_original_evidence | R1; M1 | G | Real sync orchestration; repository/CRM fakes |
| AC-01 / SMS, on-demand × C | REFRESH::test_on_demand_refresh_keeps_recorded_opt_out_and_evidence | M1 | G | Real on-demand refresh; CRM/repository fakes |
| AC-01 / SMS, people × P | PEOPLE::test_people_refresh_keeps_recorded_opt_out_through_real_mapping | M1 | G | Real webhook handler/mapper, synthetic raw payloads; no live FUB |
| AC-01 / SMS, pre-send × S | SEND::test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard | M1 | G | Real send use case, provider fakes |
| AC-02 / email, full and incremental × C | SYNC::test_sync_preserves_recorded_opt_out_and_original_evidence | R2; M1 | G | Recorded FUB event is deliberately not a CRM-only marker |
| AC-02 / email, on-demand × C | REFRESH::test_on_demand_refresh_keeps_recorded_opt_out_and_evidence | M1 | G | Real refresh, fake transport/repository |
| AC-02 / email, people × P | PEOPLE::test_people_refresh_keeps_recorded_opt_out_through_real_mapping | M1 | G | Real raw mapping, not live FUB |
| AC-02 / email, pre-send × S | SEND::test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard | M1 | G | Actual restriction reason and zero email-provider calls |
| AC-03 / DNC, full and incremental × C | SYNC::test_sync_preserves_recorded_opt_out_and_original_evidence | M1 | G | Global flag/evidence preserved |
| AC-03 / DNC, on-demand × C | REFRESH::test_on_demand_refresh_keeps_recorded_opt_out_and_evidence | M1 | G | Both channels remain blocked |
| AC-03 / DNC, people × P | PEOPLE::test_people_refresh_keeps_recorded_opt_out_through_real_mapping | M1 | G | Both channel reason sets asserted |
| AC-03 / DNC-SMS and DNC-email × S | SEND::test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard | M1 | G | No provider call on either blocked channel |
| AC-04 / added restrictions, full/incremental and on-demand | SYNC::test_sync_adds_crm_restrictions_without_replacing_platform_evidence; REFRESH::test_on_demand_refresh_adds_crm_restrictions_without_replacing_platform_evidence | Preservation regression; M1 covers common merge, not these separate vectors | G | Literal original and added-source evidence |
| AC-04 / CRM adds email or DNC plus conflicting SMS evidence | DURABILITY::test_crm_restrictions_preserve_platform_sms_evidence_at_write_boundary | Direct-write regression; no separate mutation of these two cases | G | Real DB upsert, fresh session, repeated write, other-tenant control; independent closeout approved |
| AC-05 / clean people × P; clean SMS/email × S | PEOPLE::test_people_refresh_keeps_recorded_opt_out_through_real_mapping; SEND::test_pre_send_refresh_dispatches_unrestricted_control | Control; four clean people cases also pass M1 | G | Real send use case dispatches once to recording fake; not real delivery |
| AC-05 / CRM-only additions | DURABILITY::test_crm_restrictions_preserve_platform_sms_evidence_at_write_boundary; SYNC::test_sync_clears_only_proven_crm_restrictions | Existing CRM semantics control alongside mixed-source preservation | G | New channel/DNC flags and provenance honored; not a new opt-in path |
| AC-06 / full/incremental × with/without SMS block × no/missing/older/newer/first activity | SYNC::test_sync_preserves_app_owned_paused_search_state | Original paused-profile control; additional durable-state regression | G | 20 cases; ordinary fields and newest activity asserted, not whole-old-record retention |
| AC-07 / old-new-old-new and new-old-new-old | REFRESH::test_repeated_reordered_on_demand_refresh_keeps_recorded_restrictions | Preservation regression; M1 covers common merge | G | Four refreshes per order; every saved restriction checked |
| AC-07 / missing, error, timeout | REFRESH::test_on_demand_refresh_failure_keeps_recorded_restrictions_without_upsert | Control; no write is expected | G | Failure is not a successful unrestricted replacement |
| AC-08 / SMS, email, DNC-SMS, DNC-email × S | SEND::test_pre_send_refresh_blocks_recorded_opt_out_not_unrelated_guard; SEND::test_pre_send_refresh_dispatches_unrestricted_control | M1 plus matched permitted controls | G | Exact restriction reason; otherwise-valid destinations/clock/guards; no fallback change |
| AC-09 / SMS,email,DNC × both commit orders | DURABILITY::test_stale_refresh_cannot_erase_committed_opt_out | M2 | G | Independent committed sessions, deterministic events, stale identity-map read and fresh verification |
| AC-09 / concurrent first inserts, opt-out-first and refresh-first | DURABILITY::test_concurrent_first_inserts_return_one_lead_with_durable_opt_out | M2 | G | Real unique-constraint contention; returned identity/state checked |
| AC-10 / same CRM ID, other tenant clean or opted-out | DURABILITY::test_refresh_preserves_opt_out_without_touching_same_crm_id_in_other_workspace | Tenant-isolation control | G | Real persisted restrictions; other workspace unchanged |
| AC-10 / exact and ambiguous orphan identity, mismatched tenant/provider | RECOVERY::test_recovery_matches_orphan_identity_without_guessing_or_crossing_tenants | Identity safety regression; no deliberate tenant-guard bypass | G | Source identity evidence, no contact-address guessing |
| AC-11 / erased email, dry-run/apply/repeat | RECOVERY::test_recovery_dry_run_apply_and_repeat_restore_original_email_evidence | R3; M3 | G | Real Postgres, original source/time, ordinary fields and activity unchanged |
| AC-11 / SMS,email,DNC,clean through repair/refresh/GET | DETAIL::test_lead_detail_preserves_recovered_opt_outs_after_crm_refresh | Recovery/write regressions M2/M3 cover mechanism | G | Real DB and API read with actor override; not authenticated UI |
| AC-11 / hard keyword, classifier, reply-route suppression | HISTORY::test_recovery_uses_real_inbound_processing_audit_not_body_or_message_id | Recovery regression; no historical AI rerun | G | Real inbound writer/audit, distinct original event vs message IDs; fake LLM inputs |
| AC-12 / existing/missing provenance × reversed evidence order | RECOVERY::test_recovery_keeps_valid_provenance_else_earliest_with_stable_ties | Deterministic-selection regression | G | Literal source/time and equal-time tie assertions |
| AC-12 / ambiguous provenance, malformed times, missing/repointed links, non-opt-out reference, contradictory duplicates, incomplete audit | RECOVERY::test_recovery_reports_ambiguous_provenance_without_modifying_lead; HISTORY file | Conservative no-write safety regressions | G | Parameterized failure and incomplete-evidence cases; original history unchanged |
| AC-12 / delivery codes none, 21614, 21610 | DELIVERY::test_delivery_history_never_invents_opt_out_and_flags_unverified_unsubscribe | Control: ordinary failure is not opt-out; 21610 requires review | G | Retained synthetic provider events; no carrier call or automatic carrier repair |
| AC-12 / held/unheld, dry-run/apply, exhausted history | RECOVERY::test_recovery_excludes_review_holds_and_incomplete_history; CLI::test_consent_review_holds_never_reach_repository | Conservative exclusion control | G | CLI holds do not create runtime sending holds |
| AC-12 / lock failure, next lead, safe retry | RECOVERY::test_recovery_reports_lock_failure_continues_other_leads_and_retries_safely | Storage-failure/recovery regression | G | Real Postgres failure isolation and subsequent repair |
| AC-12 / invalid bounds, private/existing/symlink report, interruption/cancellation/fsync failure, totals | CLI file | CLI boundary safety regressions | G | All CLI cases run; partial report cannot claim completion; no credentials/bodies emitted |
| AC-13 / paused,human_handoff,completed,suppressed,closed + clean control | DETAIL::test_recovery_and_crm_refresh_preserve_populated_lifecycle_in_lead_detail | Lifecycle no-side-effect control; independent closeout approved | G | Populated workflows, enrollments, messages, handoffs/history; real DB and GET, not UI |
| AC-14 / allowed tag, mismatch, repeated sync | SYNC::test_sync_starts_matching_campaign_when_pulled_lead_has_configured_tag; SYNC::test_sync_does_not_start_campaign_when_pulled_lead_tag_does_not_match; SYNC::test_repeat_sync_for_tagged_lead_is_idempotent_when_already_enrolled | Baseline regression controls | G | Existing application enrollment behavior; separate API handoff failure remains open |
| AC-14 / SMS,email,DNC × CRM-only,platform,empty,partial,unknown provenance | SYNC::test_sync_clears_only_proven_crm_restrictions | CRM-only clear is a control; platform/ambiguous preservation is the repair | G | 15 cases; CRM-only may clear, platform event from FUB remains durable |

The scope also runs existing lead-repository regression coverage and recovery request validation.
Existing pre-send failure/eligibility controls and wider workflow tests ran in the full suite;
they do not change the disclosed full-suite failure into a passing result.

### Operator/CLI rehearsal — not a browser acceptance test

Executed the actual CLI as a subprocess against a disposable migrated local database at 4bca9c3.
Synthetic cohort: one historical SMS opt-out, one email unsubscribe, one DNC, one clean control,
and one explicitly held lead. No API/worker/provider process was started. The operator workflow
was exercised by a temporary driver outside the repository; it is not a persistent stakeholder demo.

| Stage | CLI exit | Scoped / processed | Candidate | Would change | Changed | Already correct | Clean | Unresolved | Failed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dry-run | 1 | 5 / 5 | 3 | 3 | 0 | 0 | 1 | 1 | 0 |
| Apply, reviewed-for-lifts | 1 | 5 / 5 | 3 | 0 | 3 | 0 | 1 | 1 | 0 |
| Repeat after CRM refresh | 1 | 5 / 5 | 3 | 0 | 0 | 3 | 1 | 1 | 0 |

**Pass:** dry-run left rows unchanged; apply restored three restrictions; permissive CRM refresh
retained the repairs while updating the ordinary stage field; repeat made no changes. The clean
and held leads were unchanged. Each exclusively created report had mode 0600. The driver exited
0, but each CLI invocation correctly exited 1 because the held lead remained unresolved; those
are not contradictory results. The existing harness removed only its disposable database after
the rehearsal; synthetic test records were discarded, and production was untouched.

The executable [operator runbook](../runbooks/recorded-opt-out-recovery.md) gives exact dry-run,
apply, repeat, containment and rollback procedures. Container execution, drain/restart sequencing,
callback backlog and production deployment were **not run**. Reports and temporary mutations
are not included in the PR; the non-sensitive counts and reproducible tests are the durable evidence.

### Independent review and remaining acceptance gates

- **Standards:** `issue16a-final-standards-review` found 0 documented violations and 0 warranted
  smell findings; static review, not a claim of runtime verification.
- **Spec:** `issue16a-final-spec-review` found missing AC-04 real-persistence and AC-13 populated
  lifecycle coverage, plus unfinished evidence/runbook and UI acceptance. The two test gaps were
  corrected at 4bca9c3; `issue16a-review-coverage-closeout` independently confirmed both closed.
  The evidence and runbook are now provided. No reviewer granted unconditional release approval.
- **Still blocked:** the baseline-reproducing handoff test needs an owner-approved disposition;
  do not silently mark it xfail. PR CI has not been verified; the repository currently couples its
  checked-in CI workflow to main deployment. Do not merge to test it.
- **Not verified:** authenticated browser/staging acceptance, real CRM/provider behavior,
  production containment/rollback, affected-record inventory and any production recovery.
  The local API tests override the actor and do not establish the authenticated UI journey.
- **Stakeholder setup not yet available:** provide an authorized corrected local/staging URL,
  brokerage-admin access and named synthetic SMS/email/DNC/clean/paused/handoff leads. Prepare
  stale/failed CRM refreshes and bounded recovery from developer-side tooling; the current lead
  page has no dedicated CRM-refresh or opt-out-repair button. Do not relabel **Import FUB history**
  or agent-directory **Sync now** as those actions.
- Use **Leads** → lead detail → **Decision snapshot**, **SMS automation**, **Email automation**,
  **Lead record**, **Handoff context** and **Lead activity** for the unchecked stakeholder list in
  the PR. Reload/reopen after each prepared refresh/repair. If using **Send now**, prepare an
  otherwise-valid deferred test message and sink/sandbox destinations first; it is not a consent
  override. No new frontend code or re-subscribe/clear route is included.

Next step: resolve the stated merge gates, run the agent's own authorized UI checks, then have the
owner perform the independent stakeholder checklist. Recovery and production release still require
separate, bounded authorization; successful repair never authorizes resume/enrollment/outreach.
