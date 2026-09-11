# Production-state consistency — scoped owner approvals

This register records explicit owner decisions without rewriting the twenty review drafts.
It is not the completed backlog-readiness matrix, a passing-test report, or release authorization.
Earlier decisions recorded elsewhere remain in force; an entry here approves only its stated scope.

## 16-A — Preservation and historical-recovery contract

**Recorded:** 2026-09-09.
**Status:** Owner approval and implementation/test-contract gates satisfied for 16-A;
implementation and local verification evidence delivered; manual acceptance and release gates
remain open. The API PR must stay draft while the disclosed merge gates are unresolved.
**Ticket:** [16-A — Keep recorded opt-outs when CRM data refreshes](jira-tickets/issue-16-a-preserve-opt-outs-during-crm-refresh.md).
**Approval source:** requesting user in [this session](https://cosmos.augmentcode.com/session?agentId=01M1PSSB4QCDWMBS1SMHRFTV4C).

After being asked to approve the preservation/recovery-only scope and recovery-evidence rule,
the user replied:

> if its according to the codebase and product decisions, i approve

**Condition retained:** the approved repair must conform to the actual codebase and recorded
product decisions. This is not permission to guess a missing business outcome or reinterpret the
approval to cover a different design/scope. Any material conflict found on the implementation
branch must be brought back to the owner before proceeding with the affected work.

### Approved product scope

- Preserve platform-observed SMS/email/global restrictions and their evidence through all four
  CRM refresh paths, including overlapping writes; retain ordinary CRM-owned updates, app-owned
  paused-search state and the newest known agent-activity timestamp.
- Keep channel identity: SMS opt-out blocks SMS, email unsubscribe blocks email, and global DNC
  blocks both. Do not indiscriminately latch CRM-only values or invent a new consent policy.
- Include tested, evidence-backed historical-recovery tooling and its bounded runbook.
- Keep START/resubscribe, audited human clearing and CRM courtesy-write/retry features separate.
  They are not prerequisites for the preservation repair and are not approved by this entry.
- Retain the accepted CRM-field limitation: editing a CRM field no longer clears a platform
  opt-out. Disclose the limitation and absence of a delivered lifting replacement to operators.
- Preserve existing baseline-allowed CRM refresh/tag-enrollment behavior; the fix adds no new
  outreach or lifecycle authority. Recovery itself never sends, enrolls or resumes. No workflow-policy
  changes are included. Class A and Class B behavior must remain in separate PRs.

### Approved recovery-evidence rule

1. Keep existing valid platform evidence for the restriction.
2. If that evidence is missing, select the earliest verified matching opt-out occurrence from the
   complete, correctly scoped retained history. Preserve its actual source, event identity and time.
3. Retain original event history. Do not invent past opt-outs/opt-ins or rerun an LLM to manufacture
   a historical consent decision.
4. Missing or contradictory evidence, uncertain identity or conflicting lift evidence requires
   explicit review. Do not guess; keep affected outreach excluded from re-enablement pending review.
5. Never silently undo a proven later legitimate lift. Selecting representative recovery evidence
   is not a rule that an older STOP overrides a later authorized decision.

The ticket's detailed deterministic evidence-selection mechanics, including equal-time handling,
were subsequently approved by the independent recovery reviewer before recovery expectations were
coded; see the [execution contract](issue-16a-execution-contract.md). This approval does not add
a consent-lifting mechanism or authorize production changes.

### Basis for accepting the condition

Targeted source recheck against API baseline **a761c1b**, not a production inspection:

- `preserve_app_owned_lead_state` in app/domain/leads/canonical.py retains paused-search fields
  but not the suppression flags/types/evidence. Preserving restrictions addresses the traced gap.
- The suppression writer in app/application/use_cases/process_contact_suppression_event.py
  records channel flags/types or global DNC plus source/time/event evidence; it does not universally
  set the permission status to DENIED. The approved scope must protect those actual representations.
- The lead upsert in app/infrastructure/persistence/postgres/lead_repository.py replaces mapped
  values on conflict. A simple in-memory merge is not proof of concurrent-write safety.
- Parent workspace CLAUDE.md requires durable platform opt-outs, channel-scoped explicit denials
  and global DNC. [D3/D7](production-state-consistency-review-consensus.md) record the accepted
  CRM-field limitation and separate defect repair from product-policy releases.

These findings support the repair's compatibility with the recorded product decisions. The
historical-recovery selection rule is an approved target, **not claimed existing recovery behavior**.
No implementation, behavioral test pass, deployed capability or complete recoverability is asserted.

### Gates still open

| Gate | Status / next action |
| --- | --- |
| Product scope and conservative recovery rule | Owner approval recorded, subject to the condition above. |
| Implementer, independent reviewer, release/recovery operator | Confirmed in implementation session: Augment Agent; separate review sub-agents; requesting user as operator and merge owner. |
| Implementation branch and technical design | Owner approved Approach A and existing 16A-preserve-opt-outs branch, main target, existing planning baseline. Baseline f5dbf4e; 13 original controls passed. |
| Acceptance/test contract | Independent preservation reviewer approved AC-01–10/13–14 and first full-sync SMS red. Independent recovery reviewer approved B1–B4/N1/N2 and first AC-11 vector on 2026-09-09; details and exact source distinctions in execution contract. |
| Merge evidence | Original evidence is in the execution contract. The 2026-09-10 [remediation supplement](issue-16a-review-remediation-evidence.md) records 301 scoped passes; after the separately approved handoff-test clock correction below, the full suite has 1841 passes and 2 opt-in live-LLM skips, exit 0. Lint/types pass (634 files). R4–R6, real-Postgres interruption/retry and sensitivity checks remain covered. The initial local browser run exposed 12 false-success toasts. After the separately approved frontend correction below, frontend check/build passes (156 passed, 1 existing skip) and the completed [local browser rerun](issue-16a-local-ui-acceptance.md) exits 0 with truthful refusals and no queued/duplicate sends. Work remains unstaged and not ready to merge. Non-deploying CI and independent stakeholder sign-off remain open; no release or recovery authority is implied. |
| Production changes and re-enablement | Separately authorize the exact environment, bounded cohort, operator and runbook after dry-run/rehearsal evidence. No production access, mutation or release authorized here. |
| Jira publication / other tickets | Not authorized by this entry. Other tickets retain their own approvals and gates. |

### 2026-09-10 — recovery review remediation only

The requesting user explicitly approved Approach A in the
[remediation session](https://cosmos.augmentcode.com/session?agentId=01M22VSS150G88K3XDZ1P3CK03):
correct the existing recovery boundaries test-first, add regression/interruption evidence, and
leave everything **unstaged**, with no commit or push. This does not authorize a separate handoff
policy fix, deployment, production recovery, or acceptance-gate waiver. Release and recovery remain
owner-operated. The historical pushed implementation does not contain these unstaged corrections.

### 2026-09-10 — separately approved handoff-test clock correction

After the agent investigated the baseline handoff failure and compared test-only clock freezing
with relative event timestamps, the requesting user replied **"use the best approach out there"**
in the same session. The selected recommendation is to freeze the affected API test's clock at
its existing fixture date using the already-declared `time-machine` dependency, strengthen its
handoff/no-Temporal-start assertions, rerun scoped/full tests and update evidence.

The test had aged beyond the campaign's 60-day freshness threshold; production behavior did not
need changing. This approval covers the test correction and local validation only, not a handoff
policy change, public clock override, dependency addition, UI/CI environment setup, staging,
commit/push, merge, deployment or production recovery. The corrected full suite passes locally;
that result closes the baseline-test gate without waiving the remaining acceptance gates.

### 2026-09-10 — separately approved local synthetic UI preparation

The user answered **“yes please”** when asked to prepare a local, sink-only UI acceptance
environment with synthetic data and no live-provider calls. Authorized work: an isolated local
database, real synthetic-admin sign-in, local FUB transport/sink adapters, a bounded synthetic
recovery rehearsal and browser checks. All application corrections remain unstaged and unpublished.

The [local acceptance record](issue-16a-local-ui-acceptance.md) documents the 16-lead environment,
successful preservation/recovery checks, 12 reproduced false-success send notifications, and the
manual-start-options limitation caused by deliberately disabled Temporal. At this preparation
checkpoint the browser gate was **blocked**, not waived; frontend remediation was separately
approved below. No worker enablement,
provider access, CI workflow change, staging deployment, commit/push, merge, production recovery
or outreach re-enablement is authorized by this local-preparation approval.

### 2026-09-10 — separately approved frontend Send now correction

After the agent proposed a scoped frontend fix versus a broader API error-contract change, the
user replied **“please. but first checkout to same name branch on frontend as well”** in the
[remediation session](https://cosmos.augmentcode.com/session?agentId=01M22VSS150G88K3XDZ1P3CK03).
The frontend was switched to **16A-preserve-opt-outs** before editing, matching the API branch.

This approves option 1: truthful Send now outcome notifications/dialog feedback, regression tests
through the existing application notification provider, and another local sink-only browser run.
It does not change the API contract, consent or workflow policy, or authorize live providers,
worker enablement, CI changes, deployment, production recovery or outreach re-enablement.
Both repositories remain **unstaged and unpublished**. Existing sent controls must not be reset;
the two separate stakeholder clean controls remain reserved for the independent owner check.
See the [local acceptance record](issue-16a-local-ui-acceptance.md) for validation results and limits.

**Next handoff:** review the unstaged single-ticket corrections, resolve the disclosed verification
gates, and perform the authorized stakeholder checks. Publication and draft-PR creation require a
separately authorized delivery step. The owner alone will merge after testing; merging can
trigger the existing main-branch deployment. Recovery is a separate operation described in the
[operator runbook](../runbooks/recorded-opt-out-recovery.md), not an automatic deployment step.
9-A follows after its 16-A prerequisite is integrated and the relevant tests pass. The lifting and
CRM courtesy follow-ups must not delay preservation. The consolidated backlog-readiness pass
remains unfinished; this single approval is not a claim that all twenty drafts are ready.
