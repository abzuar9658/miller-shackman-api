# Issue 16-A — prepared draft PR handoff

## Delivery status

The original implementation through `251715e` was pushed on `16A-preserve-opt-outs` to
`abzuar9658/miller-shackman-api`. PR creation was attempted as `hammads-turing`, but GitHub returned
HTTP 422: **“must be a collaborator.” No PR was created by that attempt.** No alternate identity
was used.

**Current delivery (2026-09-10): all implementation and review-remediation changes are unstaged.**
Local HEAD is `f5dbf4e`; the historical remote branch does **not** include the new recovery fixes.
No further staging, commit, push or PR creation was attempted. Review the local working tree,
including the four untracked recovery regression files; `git diff` alone omits their contents.

After the user authorizes publishing the reviewed corrections, an owner can grant collaborator
access or create the PR from
[this comparison](https://github.com/abzuar9658/miller-shackman-api/compare/main...16A-preserve-opt-outs?expand=1)
using an authorized account. Do not mistake the current historical comparison for the corrected
source. Choose **draft**, base `main`, head `16A-preserve-opt-outs`.
Suggested title: **fix(16-A): preserve recorded opt-outs across CRM refreshes**.
The remaining sections describe the corrected local source; its latest evidence/runbook updates
are also unstaged. This is not authorization to publish or merge it.

## What changed

Routine CRM refreshes retain platform-recorded SMS opt-outs, email unsubscribes,
do-not-contact restrictions, and their original evidence. Bounded recovery can restore lost
restrictions from verified retained history without sending, enrolling, resuming, or replaying events.

**Draft — not ready to merge.** Issue 16-A only, Class A preservation/recovery. No channel-fallback
policy, START/resubscribe, human-clear route, CRM courtesy write, schema migration or dependency
change is included. CRM permission edits, resume and re-enrollment do not clear a
platform opt-out. The owner-approved existing planning baseline remains in the branch.

- Separately approved companion frontend correction: `miller-schackman-web` is also on
  `16A-preserve-opt-outs`, with truthful Send now feedback, offline/readback safeguards and
  HTTP-status preservation for unreadable errors. Its four changed/new files are unstaged.
- Separately approved test-only correction: freeze the baseline handoff API test's clock using
  the existing `time-machine` dependency and strengthen its completion/no-Temporal assertions.
  Production routing and its freshness policy are unchanged.
- Original implementation: `4bca9c31887231ef119fc2bbea620df61d8b4b57`, predating the recovery corrections.
- Current corrections and source fingerprints: [review-remediation evidence](issue-16a-review-remediation-evidence.md).
- Reviewed baseline: `f5dbf4e679810f6dc558acb7bee3645eb748a2ca`.
- Owner alone merges after testing. **Main push can deploy; never merge just to obtain CI evidence.**
- Nothing was merged, deployed, or recovered in production by this session.

## Before testing

**Local environment prepared, agent-run acceptance passes:** the user separately authorized the sink-only
synthetic setup. Open [the local application](http://127.0.0.1:4173) on the workspace Mac. The
[local acceptance handoff](issue-16a-local-ui-acceptance.md) supplies the private sign-in location,
16 named leads, completed recovery/refresh evidence, screenshots and operating limits. No public
tunnel or staging deployment exists. Two untouched stakeholder clean controls remain.

The baseline frontend at `04d43619d7beaf77799871eb9f985b60d5bb8fe5` showed a false **Message sent**
toast for 7 consent-blocked and 5 inactive-workflow attempts. The subsequently approved frontend
correction now reports truthful outcomes for all 12; the completed local browser rerun exits **0**.
Manual-start options also require the deliberately disabled Temporal service and return HTTP 500.
That sandbox limitation remains; frontend approval does not authorize worker enablement.

The agent has performed the developer-only recovery and stale/missing/failed/timeout CRM refreshes.
The stakeholder needs no database access or recovery commands. There is no dedicated lead-level
CRM-refresh or opt-out-repair button; **Import FUB history** and agent-directory **Sync now** are
not substitutes. Do not resume, enroll or clear restrictions to make acceptance pass.

## What I verified

Current local evidence: 2026-09-10, unstaged source fingerprinted in the remediation supplement.
R4 rejects another lead's referenced event; R5 holds contradictory provenance; R6 retains supporting
and conflicting source references. Thirty-two new cases supplement the original 269-test scope.

| Check | Actual result |
| --- | --- |
| Scoped automated tests, including real disposable Postgres | **Pass:** 301 passed, no failures/skips; exit 0, 32.55s |
| Full webhook/classifier files | **Pass:** 70 passed; exit 0, 3.39s |
| Full automated suite after approved test-clock correction | **Pass:** 1841 passed, 2 skipped; exit 0, 89.95s |
| Ruff | **Pass:** exit 0 |
| Mypy including recovery CLI | **Pass:** 634 source files; exit 0 |
| Recovery sensitivity checks | **Pass:** bypassing referenced-source lookup caused 3 failures; local conflict insertion 5; local references 3; inbound reference union 3. All mutations isolated and reversed; restored selector groups passed 5/9/3/6, each exit 0. |
| Real-Postgres CLI interruption/retry | **Pass:** both before-commit and after-commit-before-report cases, 2 passed, exit 0. Actual SQL rollback/commit, fresh connections, lock release, incomplete private report and no-rewrite retry verified. Controlled cancellation, not an OS/container outage rehearsal. |
| Original standalone CLI/operator rehearsal | **Historical only, at 4bca9c3:** five synthetic leads, dry-run → apply → refresh → repeat. See execution contract. Superseded for current local CLI evidence by the 16-lead rehearsal below; not production acceptance. |
| Current isolated preparation | **Pass:** actual recovery CLI subprocess preview/apply/repeat restored 8 restrictions, then changed 0; real FUB HTTP adapter stale/missing/failure/timeout paths retained restrictions/provenance; 10 lifecycle/history tables unchanged and zero preparation sends. Helper tests: 23 passed; exit 0. |
| Frontend check/build after approved correction | **Pass, exit 0:** lint/types/format, 156 passed and 1 pre-existing skipped test in 23 files, production build. Includes 46 lead-route and 7 API-client cases. Existing bundle-size warning remains. |
| Agent authenticated local browser journey | **Pass, exit 0:** run 20260910T174712060438Z; real login/list/drawer/16 details/reload; 12 truthful refusals and 2 already-sent API replays; desktop/tablet/mobile/dark dialog checks. One deliberately aborted POST plus failed readback/reconnection verifies persistent warning/reason and no queued send. Zero UI/page/nonlocal/HTTP errors; two stakeholder controls untouched. Original failed runs remain historical in the local acceptance record. |
| Real providers, Compose containment/rollback, production recovery | **Not run / Not verified:** no customer outreach or production mutation |
| PR CI | **Not verified:** checked-in workflow runs on main push and includes deployment; PR creation is also access-blocked |

The former full-suite failure was
`tests/interfaces/api/v1/test_webhooks.py::test_follow_up_boss_crm_webhook_completes_tag_time_human_handoff`.
The earlier execution record reproduced that handoff-set failure on untouched f5dbf4e and the
original fix. It was traced to the fixture's July 8 timestamp aging beyond the configured 60-day
freshness threshold while the API used the real clock. The separately approved correction freezes
this test's clock, preserving the real webhook/routing/handoff path and all original assertions.
The strengthened test failed before the freeze and passed afterward. The local full-suite gate is
now closed; no xfail, skip, weakened assertion or production-policy change concealed the failure.
The two remaining skips are opt-in live-LLM tests, not skipped Postgres coverage. Historical red
results and the exact current source fingerprint remain in the remediation evidence.

### Independent review

- **Current Standards:** `issue16a-remediation-final-standards` found no documented violations or
  warranted smell findings.
- **Current Spec:** `issue16a-remediation-final-spec` found no actionable defects or scope creep
  in R4–R6 and the interruption contract. Both reviewers read all four untracked test files.
- **Earlier coverage:** AC-04 real-persistence and AC-13 populated-lifecycle gaps were fixed and
  independently confirmed closed before the remediation; those tests remain in the 301-test scope.
- **Handoff test:** `handoff-clock-fix-scope-review` found no issues in the test-only clock fix;
  existing assertions and production policy remain intact.
- **Frontend closeout:** `issue16a-final-offline-closeout` confirmed the paused-readback and malformed
  HTTP-error fixes and found no actionable defects in the approved scope. The parent ran the checks
  and sink-only browser journey; this review was static, not runtime verification or release approval.
- Independent stakeholder acceptance and non-deploying CI remain open; the original local toast
  blocker is corrected. See the local acceptance record for failed-attempt history and current evidence.

## Manual testing checklist

**Unchecked intentionally:** stakeholder testing is an independent second check, not a replacement.
The local environment, approved notification correction and agent-run checks are documented above.
The owner must still perform this checklist; the agent's passing run is not stakeholder sign-off.

- [ ] **Do:** In **Leads**, open the prepared SMS-opt-out lead after developer-run CRM refresh, then reload. **Expect:** **Decision snapshot → SMS automation** remains **Blocked** with the opt-out reason; ordinary CRM updates appear in **Lead record**.
- [ ] **Do:** Repeat for the email-unsubscribed lead. **Expect:** **Email automation** remains **Blocked** with its unsubscribe reason; the restriction does not become SMS or global.
- [ ] **Do:** Repeat for the do-not-contact lead. **Expect:** Both **SMS automation** and **Email automation** remain **Blocked** after reload.
- [ ] **Do:** On each prepared restricted lead's deferred test message, choose **Send now**, enter the test **Reason**, and confirm **Send now**. **Expect:** No opted-out-channel delivery; DNC prevents both. **Lead activity** must not show a successful blocked-channel send. Do not resume or clear restrictions to make the test work.
- [ ] **Do:** Repeat **Send now** on the matched unrestricted test lead, then reopen **Lead activity**. **Expect:** Its normal permitted test message sends once, with no invented restriction or duplicate.
- [ ] **Do:** Reopen paused, handed-off and terminal leads after developer-run recovery, CRM refresh and repeat recovery. **Expect:** Workflow status and **Handoff context** remain unchanged; **Lead activity** shows no recovery-created outreach, enrollment or automatic restart. The unrelated clean lead stays clean.
- [ ] **Do:** Reopen a restricted lead after a developer-induced CRM refresh failure, then after a successful retry. **Expect:** The restriction remains throughout; ordinary fields update on success. A failed refresh must not make the lead sendable.

## Developer evidence and recovery instructions

- [Approved execution contract, AC mapping, commands and red/green/sensitivity evidence](issue-16a-execution-contract.md)
- [Current recovery corrections, exact test results and unstaged source fingerprints](issue-16a-review-remediation-evidence.md)
- [Local UI access, synthetic cohort, frontend correction and current acceptance evidence](issue-16a-local-ui-acceptance.md)
- [Recovery, containment, verification and rollback runbook](../runbooks/recorded-opt-out-recovery.md)
- [Issue 16-A acceptance contract](jira-tickets/issue-16-a-preserve-opt-outs-during-crm-refresh.md)

Recovery defaults to dry-run; at most 100 explicitly selected leads, bounded history, review holds,
lift-review attestation for apply, row locks, private progress reports and safe repeat behavior.
**A recovery hold excludes repair only; it is not a runtime send hold.** Ambiguous evidence and
retained carrier-unsubscribe hints (including 21610) require review. Ordinary delivery failures
are not opt-out evidence. Keep unresolved outreach contained separately.

### Gates before ready/merge

- [ ] Complete working-tree review; separately authorize publication of these unstaged corrections.
- [ ] Then grant PR-creation access or have an authorized collaborator open the corrected work as a draft.
- [x] Resolve the baseline handoff failure under separately approved test-only scope; full local
  suite passes without changing routing policy or waiving the gate.
- [ ] Obtain safe, non-deploying CI evidence; do not push main or deploy for this purpose.
- [x] Prepare the authorized local UI environment and record agent-run browser evidence, including failures.
- [x] Separately authorize/correct the false-success notification, add/run regression tests and
  repeat the local browser journey. Both branches match; corrections remain unstaged.
- [ ] Record independent stakeholder checks. Manual-start remains outside this limited no-worker
  sandbox's verified scope. Review the untracked frontend API-client test as well as the tracked diff.

Production inventory, containment, corrected-writer rollout, bounded recovery, rollback readiness
and re-enablement require separate operator authorization. Neither merging nor successful repair
authorizes new outreach.
