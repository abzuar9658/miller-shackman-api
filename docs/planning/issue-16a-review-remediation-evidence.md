# Issue 16-A — recovery review remediation

## Authority and status

Owner approved **Approach A** (correct the existing recovery boundaries) in the
[implementation session](https://cosmos.augmentcode.com/session?agentId=01M22VSS150G88K3XDZ1P3CK03).
Keep this work **unstaged**: no commit, push, merge, deployment or production recovery.
This supplements the [execution contract](issue-16a-execution-contract.md), not its policy scope.

On 2026-09-10, independent `issue16a-remediation-contract-review` read the contract, current
implementation and writers and **APPROVED** R4–R6, the first R4 scenario and the interruption
boundaries below, before any remediation test or implementation was written.

Starting checkout: HEAD `f5dbf4e679810f6dc558acb7bee3645eb748a2ca` with unstaged Issue 16-A
implementation matching the app/tests/scripts tree at `251715eab957d198e544f876f45900a1dde0ca7b`.
The previously reported 269 passes do not prove these newly identified recovery cases.
**Status: R4–R6 corrections and the separately approved handoff-test clock correction are locally
verified; the full suite passes and all changes remain unstaged. Issue 16-A is still not ready to
merge.** The separately authorized [local UI setup](issue-16a-local-ui-acceptance.md) is prepared,
but the completed authenticated browser run found 12 false-success notifications and exits 1.
UI acceptance and non-deploying CI remain open. Historical failing results below are retained,
not relabeled as successes.

## Approved behavioral regressions

- **R4 — Referenced source identity:** A's complete provenance names an event belonging to B in
  the same workspace, with a different CRM identity. Its provider, source ID, kind and instant
  otherwise match. Dry-run and apply must hold A as unresolved, preserve A/B/history and report
  the conflicting source. Resolve references only by workspace/provider/event ID, then validate
  lead/CRM ownership and exact event type. No cross-workspace lookup or inferred address match.
- **R5 — Contradictory facts:** local provenance entries sharing one provider/source ID but
  disagreeing on kind or occurrence are unresolved, even without retained external history.
  Compare local/local and local/history facts; never partially repair another channel on a held lead.
- **R6 — Report lineage:** retain actual supporting/conflicting lead-provenance, external-event
  and inbound-message row references on preview, apply, repeat and unresolved outcomes. Stable
  deduplication must not drop distinct inbound rows. Reports contain no message bodies or addresses.
- **Controls:** complete valid local provenance is still usable when its retained event is absent.
  Equivalent timestamp offsets are not a contradiction. Distinct provider/event identities remain
  independent. Missing inbound/source detection and complete bounded history requirements stay intact.
- **Interruption:** exercise actual Postgres SQL and independent connections. Cancellation after
  upsert/before commit must roll back the active lead and release its lock. A committed prefix
  survives interruption after commit/before durable reporting; retry reads fresh state, treats that
  prefix as already correct without rewriting timestamps, and repairs only the remaining scope.
  The interrupted report must not claim completion. Recovery does not send, enroll or resume.

## Execution evidence

All runs below used Python 3.12 via `/usr/bin/arch -arm64`, with a session-only launcher checking
that configured runtime/migration URLs both target loopback, agree on port/database, and have no
URL overrides. Values passed to pytest in memory, never printed. The existing harness created,
migrated and removed only disposable local databases. No live providers or production data.

Common pytest flags: `-o addopts= -q -ra --tb=short --show-capture=no`.
Selectors below are relative to `tests/infrastructure/persistence/postgres/`.

| Case | Exact selector | Meaningful red | Green observed so far |
| --- | --- | --- | --- |
| R4 | `test_opt_out_recovery_provenance.py::test_recovery_holds_provenance_referencing_another_leads_event[False]` | Before adapter changes: `unresolved=0`, `WOULD_CHANGE`, empty references; 1 failed, exit 1, 2.47s | Both dry/apply cases plus existing recovery/history files: 49 passed, exit 0, 8.99s |
| R5 | `test_opt_out_recovery_provenance.py::test_recovery_holds_contradictory_local_provenance_without_history` | After R4 only: same/different instants × dry/apply wrongly returned WOULD_CHANGE/CHANGED; 4 failed, exit 1, 1.99s | Same three files with R5 guard: 53 passed, exit 0, 9.82s |
| R6 local | `test_opt_out_recovery_references.py::test_recovery_reports_local_provenance_on_preview_apply_and_repeat` | Empty references instead of the retained lead-provenance reference; 1 failed, exit 1, 1.71s | Same node: 1 passed, exit 0, 1.72s |
| R6 inbound/early hold | `test_opt_out_recovery_references.py` plus R4 function without parameter suffix | Three inbound origins omitted inbound-row references; R4 dry/apply omitted local references. 5 failed, 1 passed, exit 1, 3.48s | After adapter reference aggregation: recovery/provenance/references/history/delivery/CLI files, 99 passed, exit 0, 11.71s |

The existing provenance-selection test's expected references were strengthened to include retained
lead-local provenance and deterministic ordering. No safety assertion was removed or weakened.
An initial lint run caught three line-length errors (exit 1); corrected before subsequent checks.
The interruption test added two further line-length errors and one invariant session-factory type
error; all were corrected, with final Ruff and strict mypy returning exit 0. No runtime production
change was needed for the interruption scenarios.

The red observations above are contemporaneous test-first results from this session. Their exact
intermediate source snapshots were not committed; this document does not invent a historical git
revision for them. The separately measured mutations below are reproducible sensitivity evidence,
not substitutes for or claims about those original snapshots.

### Recovery-only verification — 2026-09-10, before the handoff-test correction

| Check | Actual result |
| --- | --- |
| Expanded source-lookup and reference files | **24 passed**, 1 warning, 13.88s; exit **0** |
| New real-Postgres interruption file | **2 passed**, 1 warning, 3.14s; exit **0**, later included in both full-suite runs and the scoped run |
| Entire Issue 16-A scope, command below | **301 passed**, 0 failed, 0 skipped, 2 warnings, 33.07s; exit **0** |
| Full suite on the recovery-only checkpoint source | **1 failed, 1840 passed, 2 skipped**, 10 warnings, 62.84s; exit **1** |
| Prior full-suite run during this pass | Same counts and failure, 78.71s; exit **1**, before the test-only session-factory annotation correction |
| Ruff | All checks passed; exit **0** |
| Strict mypy including the CLI | No issues in **634 source files**; exit **0** |
| Git whitespace check | `git diff --check`; exit **0** |
| Restored isolated copies | All four source-set fingerprints matched the recovery-only checkpoint; verifier exit **0**; all restored selectors passed below |

There are **32 new parametrized cases**: provenance 6, references 6, source lookup 18 and
interruption 2. No Postgres test was skipped. The two full-suite skips are the explicit opt-in
live-LLM cases; no live-provider validation is claimed.

The failing node at that checkpoint was
`tests/interfaces/api/v1/test_webhooks.py::test_follow_up_boss_crm_webhook_completes_tag_time_human_handoff`,
at its handoff-set assertion (`set() != {None}`). The earlier untouched-baseline reproduction is
recorded in the execution contract; the recovery-only pass reran the current suite, not a fresh
baseline checkout. Its later test-only resolution is recorded separately below. No xfail, skip or
weakened assertion was used to conceal the failure.

### Approved handoff-test clock correction — 2026-09-10

After the user authorized investigation, the agent proposed two test-only approaches: freeze the
scenario clock with the existing `time-machine` dependency, or make event timestamps relative to
execution time. The user replied **"use the best approach out there"**. The recommended frozen-clock
approach was selected; this authorization does not change routing policy or permit publication.

The fixture's inbound event is dated `2026-07-08T12:00:00+00:00`, but the real API router captures
`datetime.now(UTC)`. At the observed September 10 execution time the signal was over 60 days old.
The stored classification artifact identified `no_fresh_lead_signal_for_handoff`: the application
correctly overrode the proposed handoff to dormant. A debugger experiment changed only the clock
to the fixture date and the unchanged API test passed; restoring the actual clock reproduced the
failure while the existing fresh/stale classification controls passed. This is a fake-backed API
flow, not evidence of a live CRM, LLM or notification integration.

Only `tests/interfaces/api/v1/test_webhooks.py` changed in this correction:

- First require a non-null completion record explicitly, retain the handoff identity assertion and
  add a check that no Temporal workflow starts. The original notification, CRM tag/custom-field/
  note, no-enrollment and commit assertions remain.
- Then wrap this test's client/request context in `time_machine.travel(NOW, tick=False)`. The context
  restores the clock even on exceptions. Shared fixtures, production code, policy and dependencies
  are unchanged; no public clock parameter or freshness bypass was introduced.

Let **H** be the full failing node named above and **C** be
`tests/application/services/llm/test_lead_state_classification.py`.

| Check | Actual result |
| --- | --- |
| H after stronger assertions, before freezing time | **1 failed**, 1 warning, 0.93s; exit **1**, `handoff_record is None` |
| H after freeze, plus `C::test_accepts_handoff_for_fresh_lead_authored_signal` and `C::test_overrides_stale_handoff_after_outbound_followups` | **3 passed**, 1 warning, 1.09s; exit **0** |
| Full webhook file plus C | **70 passed**, 1 warning, 3.39s; exit **0** |
| Same 16-file Issue 16-A scope below | **301 passed**, no skips, 2 warnings, 32.55s; exit **0** |
| Full suite after the clock correction | **1841 passed, 2 skipped**, 10 warnings, 89.95s; exit **0** |
| Repository Ruff and strict mypy, including recovery CLI | All checks passed; **634 source files**, exit **0** |
| Git whitespace and unstaged-only checks | Exit **0**; no staged content |

The two skips are still the explicit opt-in live-LLM cases; no Postgres coverage was skipped.
This closes the local baseline-test failure gate, not UI acceptance, CI or release approval.
The single-node red selected H only; the first green selected H and the two named C controls using
the common flags above. The file-level command was:

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/arch -arm64 .venv/bin/python -m pytest -o addopts= -q -ra --tb=short --show-capture=no \
  tests/interfaces/api/v1/test_webhooks.py tests/application/services/llm/test_lead_state_classification.py
````
</augment_code_snippet>

Underlying commands, from the API repository **only after validating an authorized local/test
configuration**. Actual pytest runs used the session-only loopback guard described above; the
launcher and scratch copies are disposable, not a required new repository dependency.

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/arch -arm64 .venv/bin/python -m pytest -o addopts= -q -ra --tb=short --show-capture=no
/usr/bin/arch -arm64 .venv/bin/python -m ruff check .
/usr/bin/arch -arm64 .venv/bin/python -m mypy app tests scripts/recover_recorded_opt_outs.py
git diff --check
````
</augment_code_snippet>

Exact scoped invocation:

<augment_code_snippet mode="EXCERPT">
````bash
/usr/bin/arch -arm64 .venv/bin/python -m pytest -o addopts= -q -ra --tb=short --show-capture=no \
  tests/application/services/test_crm_lead_refresh.py tests/application/use_cases/test_crm_sync.py \
  tests/application/use_cases/test_recover_recorded_opt_outs.py tests/application/use_cases/test_refresh_opt_out_send.py \
  tests/infrastructure/crm/test_refresh_opt_out_people.py tests/infrastructure/persistence/postgres/test_lead_opt_out_durability.py \
  tests/infrastructure/persistence/postgres/test_lead_repository.py tests/infrastructure/persistence/postgres/test_opt_out_lead_detail.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery.py tests/infrastructure/persistence/postgres/test_opt_out_recovery_delivery_history.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery_history.py tests/scripts/test_recover_recorded_opt_outs.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery_provenance.py tests/infrastructure/persistence/postgres/test_opt_out_recovery_references.py \
  tests/infrastructure/persistence/postgres/test_opt_out_recovery_source_lookup.py tests/infrastructure/persistence/postgres/test_opt_out_recovery_interruption.py
````
</augment_code_snippet>

### Actual database interruption and recovery boundary

Exact node: `test_opt_out_recovery_interruption.py::test_cli_interruption_preserves_committed_prefix_and_retries_from_real_postgres`,
parameters `before-commit` and `after-commit-before-report`. Both invoke the actual CLI `main`
with the real Postgres repository; the test injects controlled `asyncio.CancelledError` at the
approved boundary, not a fake successful persistence result.

- Before commit: observe the actual uncommitted second-lead UPDATE, cancel, then use an independent
  connection to verify rollback and reacquire its row lock with a one-second database lock timeout.
- After commit/before report: the second repair survives even though its result is absent from the
  interrupted report. In both cases the first repair survives; the third scoped lead and unrelated
  clean control remain untouched until the authorized retry (the clean control is never repaired).
- CLI interruption returns **130**. The mode-0600 report contains the durable header/first-result
  prefix but **no completion marker**. Retry uses a new file and fresh database reads, returns **0**,
  recognizes the committed prefix as already correct and repairs only the remaining scope. It does
  not rewrite already-correct `updated_at` values or modify the original incomplete report.
- Source events and workflow/enrollment/handoff/transition/conversation/message history snapshots
  stay unchanged. The larger scope also retains its existing populated-lifecycle/API coverage.

This is controlled cancellation against real SQL/commits, **not** an OS kill, power-loss, container,
live-provider or production-disruption rehearsal. It does not replace authenticated UI acceptance.

### Isolated sensitivity checks

Four copies of the recovery-only checkpoint source were created under the session temp directory.
Only `.py` files under `app`, `tests`, `alembic`, `scripts/__init__.py`,
`scripts/recover_recorded_opt_outs.py`, `pyproject.toml` and `alembic.ini`
were copied: no dotenv, credential files, logs, git metadata or dependency environment. Every child
received guarded local database configuration in memory and used its own disposable harness database.
The main working tree was never mutated for these experiments.

| ID | Exact disabled behavior in the copy | Meaningful failure | Restored same selectors |
| --- | --- | --- | --- |
| M4 | Adapter: use an empty tuple-IN source list instead of `source_ids`; ordinary lead/CRM history filters remain | Foreign suppression source (dry/apply) and real foreign inbound source wrongly return would-change/changed: **3 failed, 2 passed**, 5.20s, exit **1**. Provider/workspace collision controls pass. | **5 passed**, 4.11s, exit **0** |
| M5 | Planner: change only the local-tuple ledger insertion from `seen.setdefault` to `seen.get`; history ledger retained | Contradictory local tuples are accepted, including a case with an independent DNC fact: **5 failed, 4 passed**, 4.13s, exit **1**. Independent-source and local/history contradiction controls pass. | **9 passed**, 3.82s, exit **0** |
| M6-local | Make `lead_opt_out_provenance_references` return an empty tuple | Successful local-evidence preview and both early-unresolved cases omit required local references: **3 failed**, 2.61s, exit **1** | **3 passed**, 2.78s, exit **0** |
| M6-inbound | Remove only the adapter's final union of collected references into the planner report | All three real inbound origins lose both distinct inbound-row references: **3 failed, 3 passed**, 3.89s, exit **1**. Local-only and early-unresolved controls pass. | **6 passed**, 3.80s, exit **0** |

Every mutation was reversed using its inverse patch before the restored runs. All copies then
matched the source-set fingerprint below. Each sensitivity/red/restored run had one Alembic
deprecation warning and no skips. The main full suite was rerun after reversal and retained only
the disclosed handoff failure; deliberate breakage is not delivered.

Exact selector groups, using the common pytest flags above. **P**, **S**, **R** expand to
`tests/infrastructure/persistence/postgres/test_opt_out_recovery_provenance.py`,
`test_opt_out_recovery_source_lookup.py` and `test_opt_out_recovery_references.py` in that same
directory. No parameter suffix means all parameters, not a guessed separately executed result.

- **M4:** `P::test_recovery_holds_provenance_referencing_another_leads_event`;
  `S::test_recovery_holds_local_provenance_referencing_another_leads_real_inbound`;
  `S::test_recovery_ignores_same_event_id_in_other_provider_and_workspace`.
- **M5:** `P::test_recovery_holds_contradictory_local_provenance_without_history`;
  `S::test_recovery_requires_consistent_local_sources_before_repairing_any_restriction`;
  `S::test_recovery_holds_local_history_contradictions_without_partial_repair`.
- **M6-local:** `R::test_recovery_reports_local_provenance_on_preview_apply_and_repeat`;
  `R::test_recovery_retains_partial_local_and_source_refs_on_early_unresolved`.
- **M6-inbound:** `R::test_recovery_reports_both_inbound_and_source_rows_through_repeat`;
  both M6-local selectors as controls.

### Source fingerprints — recovery-only checkpoint

HEAD remains `f5dbf4e679810f6dc558acb7bee3645eb748a2ca`; the index has no staged content.
The recovery-only checkpoint changes two production recovery files, strengthens one existing test,
adds four test files and updates evidence/runbook/handoff documents. The user's existing ticket-area
`AGENTS.md` edit is untouched. No new schema, dependency, frontend, CRM refresh policy or consent
lifting behavior was introduced by the remediation.

Recovery-only source-set SHA256: `972163ec1120f7bf03a1c4f8d9977d91c29b5d1314dd2c4621c1866830be4c25`.
It covers **733 files** from the copy allowlist above (excluding `__pycache__`). Calculation:
on POSIX Python 3.12, apply `sorted` to the relative `pathlib.Path` objects (component-wise path
ordering, **not** sorting their rendered strings). For each ordered object, concatenate its
`.as_posix()` UTF-8 bytes, NUL, original file bytes, NUL; SHA256 the result. Documentation and
scratch drivers are intentionally outside this fingerprint.

| File (relative to API root) | SHA256 |
| --- | --- |
| `app/application/use_cases/recover_recorded_opt_outs.py` | `e2e6705e00ee62000e6b79de5d663011a31204ea66889ef8bfa746a80bfa52fe` |
| `app/infrastructure/persistence/postgres/opt_out_recovery.py` | `e79037496d20f0f3085353bbae4aeca2cb4172c7416aab989eb6f68f626ee14a` |
| `tests/infrastructure/persistence/postgres/test_opt_out_recovery.py` | `e8fe9d36971e02f49749f7aed110c5be6bb44f1cd8a86130656ef1023e9c5b8d` |
| `tests/infrastructure/persistence/postgres/test_opt_out_recovery_provenance.py` | `9f42556d1d00edce1a58411cf4c76c7bfdf3283ffd2676060fd93b3518e1b97c` |
| `tests/infrastructure/persistence/postgres/test_opt_out_recovery_references.py` | `e59710067a06d0f17c74d1470fd53e688e97d917cdd9e5ee450cc3ec4f4ce7e1` |
| `tests/infrastructure/persistence/postgres/test_opt_out_recovery_source_lookup.py` | `8acd2e20ab3396509c543dcc360ae145f4bfd328907edffdc5e4454aa45fdaf8` |
| `tests/infrastructure/persistence/postgres/test_opt_out_recovery_interruption.py` | `2bf7a1e22f75c7f8a29d4f3bebd2e050875e6a41089d301363588ba7bfdc6b89` |
| `scripts/recover_recorded_opt_outs.py` (unchanged from original implementation) | `605155f3f509d5b890dcef1be7485afa1f6523f65666b40440b910c1da6b3330` |

### Current source after the handoff-test correction

Using the same 733-file allowlist and ordering recipe:

- Current source-set SHA256: `4852b99a7c7b180509f936c42737a47f8a32fe4eba16b22bb31563865a0dc4b9`.
- `tests/interfaces/api/v1/test_webhooks.py` SHA256:
  `1c02744351ab19a6593deaff9d43151ac043df92c7e53b850f280952773af47b`.
- All eight hashes in the recovery-only table remain unchanged. Replacing only the handoff-test
  bytes **in memory** with that file's bytes from HEAD reconstructs the recorded recovery-only
  aggregate exactly; the verifier exited **0**. No working-tree file was reverted for this check.
- The 1841-pass full-suite result above applies to this current aggregate. Historical sensitivity
  copies/results apply to the recovery-only aggregate, not a claimed rerun of those mutations.

Use `git diff 251715eab957d198e544f876f45900a1dde0ca7b -- app tests scripts` for the corrections
to the original reviewed implementation. **Also read the four untracked test files**; ordinary
`git diff` omits their contents. Nothing was staged merely to make those files appear in the diff.

### Independent review

- **Standards — `issue16a-remediation-final-standards`:** 0 documented violations and 0 warranted
  smell findings. Reviewed both changed modules, strengthened existing expectations and all four
  untracked test files against documented standards and the approved seams.
- **Spec — `issue16a-remediation-final-spec`:** 0 actionable defects or scope-creep findings.
  Independently traced suppression/inbound writers and checked R4–R6 and interruption semantics.
- These were static read-only reviews, not independent execution of the reported tests and not
  release or recovery approval. The parent executed the checks above.
- **Evidence — `issue16a-remediation-evidence-closeout`:** identified one reproducibility issue:
  the aggregate fingerprint recipe did not distinguish Path-object ordering from string ordering.
  Corrected the recipe above. The reviewer independently reproduced the aggregate using Path
  ordering and verified all eight individual hashes; no other material inaccuracies or unsafe
  instructions were found. This was documentation/source inspection, not another test execution.
- **Handoff clock — `handoff-clock-fix-scope-review`:** no issues in the separately approved
  test-only diff. Confirmed the existing dependency/precedent, exception-safe clock restoration,
  unchanged production policy and retained/stronger assertions. Static review only; the parent
  executed the new red/green, scoped and full-suite checks.

## Separately authorized local UI preparation — historical checkpoint, 2026-09-10

The user approved local, sink-only acceptance preparation with synthetic data and no live-provider
calls. The [local handoff](issue-16a-local-ui-acceptance.md) records access, a persistent 16-lead
cohort, exact evidence, screenshots and scope limits. Real password authentication and Postgres
persistence were used without actor or dependency overrides; FUB transport and messaging were
synthetic/local. Private runners enforce an OS loopback-only boundary and an isolated restricted-role
database. No application source, dependencies, frontend, CI workflow or production state changed.

- Actual recovery CLI subprocess preview/apply/repeat: 8 historical restrictions restored;
  repeat changed 0. FUB HTTP adapter stale/missing/failure/timeout checks retained restrictions and
  original provenance. Ten lifecycle/history table snapshots stayed unchanged; no preparation sends.
- Real Chromium login/list/keyboard drawer/16 details/reload and sampled desktop/tablet/mobile
  checks completed. Seven consent-blocked and five inactive-workflow Send now requests were refused
  without changing message/lifecycle histories, but all 12 displayed **Message sent**. Browser
  run `20260910T105403279646Z` intentionally exits **1** on these findings; acceptance is blocked.
- Two clean controls were accepted once by local sinks across the browser runs; duplicate requests
  did not send or advance again. Two separate stakeholder controls remain unexercised.
- The completed browser run recorded no page errors or HTTP errors in its selected routes. A later
  targeted manual-start-options GET returned HTTP 500 because its dependency attempts to connect
  to deliberately disabled Temporal. No broader route-health or workflow-execution claim is made.
- Private helper tests: **23 passed**, exit 0; web-runner syntax exit 0. Final health/authenticated
  16-lead readback passed, exit 0. No additional send requests were needed for that check.
- The tested 733-file source fingerprint above is unchanged; frontend remains clean at
  `04d43619d7beaf77799871eb9f985b60d5bb8fe5`. Both indexes contain no staged changes. The prior
  backend full-suite result remains applicable, not a newly run UI/full-suite success.

At that preparation checkpoint, frontend remediation had not yet been authorized. The user then
approved scoped frontend result handling, tests and another sink-only browser run, first requiring
the frontend to switch to the API's `16A-preserve-opt-outs` branch. The following evidence supersedes
the former toast blocker, not the historical preparation observations.

## Approved frontend correction — current evidence, 2026-09-10

- Outcome-aware toasts/dialog feedback now distinguish provider acceptance, already-sent, refusal,
  inactive and uncertain/error results. Network/readback failures retain the warning/reason; offline
  confirmation is disabled and cannot queue a later send. HTTP error-body decoding preserves known
  access/not-found status gates. No backend consent/workflow policy or API schema changed.
- `pnpm check && pnpm build` on Node 20.19.5: **exit 0**; lint, typecheck, formatting and build pass;
  **156 passed, 1 pre-existing skip**, 23 test files, 62.69s. The skipped outbound-drafting UI case
  also exists at frontend HEAD. The existing bundle-size warning remains.
- Final completed browser record **20260910T174712060438Z**, exit **0**: all 16 authenticated lead
  journeys, 7 consent refusals, 5 inactive refusals and 2 already-sent API replays pass. Desktop,
  tablet, mobile and dark-mode dialogs pass; transport failure/read-only recovery and real browser
  offline/reconnection preserve warnings and do not duplicate/queue sends. Zero UI findings, page
  errors, HTTP errors or nonlocal requests. Two stakeholder clean controls remain unused.
- Local helper tests: **23 passed**, exit 0. Earlier toast-assertion failures are retained and
  explained in the [local acceptance record](issue-16a-local-ui-acceptance.md), not relabeled passes.
- Independent `issue16a-final-offline-closeout` found no actionable in-scope defect; static review,
  not independent execution. Frontend tests use the real App notification provider and public API client.
- Backend's **733-file** fingerprint still matches the 1841-pass source above; no new backend full
  run is claimed. Frontend's four changed/new source files and their aggregate are recorded in the
  local acceptance record. Both repos remain unstaged and unpublished, on matching branch names.

## Remaining acceptance gates

- The previous full-suite handoff failure is **resolved locally** by the approved test-only
  correction above; it no longer requires an owner waiver.
- Authenticated local agent-run acceptance now passes after the approved frontend correction.
  Independent stakeholder acceptance remains open; a local environment is not a staging deployment.
  Manual-start execution and live-provider behavior remain outside the verified sandbox scope.
- Non-deploying CI: actual safe CI evidence, not local commands relabeled as CI or a main push.
  Rechecked `.github/workflows/deploy.yml`: its only trigger is a `main` push, and successful
  checks lead to image build and production deployment. No workflow or GitHub mutation was made.
- Production inventory, containment, recovery and re-enablement remain separately authorized.

Next: obtain approval for the scoped UI correction and separately for safe non-deploying CI;
add/update and run affected tests, repeat browser checks and obtain stakeholder acceptance. Keep
the work unstaged until the user authorizes a different delivery step. Historical pushed code is
not this corrected source.
