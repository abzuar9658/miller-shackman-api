# Production-state consistency — scoped owner approvals

This register records explicit owner decisions without rewriting the twenty review drafts.
It is not the completed backlog-readiness matrix, a passing-test report, or release authorization.
Earlier decisions recorded elsewhere remain in force; an entry here approves only its stated scope.

## 16-A — Preservation and historical-recovery contract

**Recorded:** 2026-09-09.
**Status:** Conditional owner approval recorded for product scope and recovery-evidence rule;
engineering/test review and assignment remain open. Not yet marked ready for implementation.
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
remain subject to independent engineering/test review before recovery expectations are coded.
This entry does not approve a new event-ordering or consent-lifting mechanism by implication.

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
| Implementer, independent reviewer, release/recovery operator | Assign named people; none were assigned by this approval. |
| Implementation branch and technical design | Retrace actual writers/readers; record baseline and existing behavior; compare suitable approaches and obtain required design approval. |
| Acceptance/test contract | Reviewer approves public test boundaries and the first meaningful failing scenario; review detailed recovery expectations before coding them. No tests have been written or run for this approval. |
| Merge evidence | Still required: red → green, regression controls, real persistence/concurrency/recovery evidence, applicable checks and independent review. |
| Production changes and re-enablement | Separately authorize the exact environment, bounded cohort, operator and runbook after dry-run/rehearsal evidence. No production access, mutation or release authorized here. |
| Jira publication / other tickets | Not authorized by this entry. Other tickets retain their own approvals and gates. |

**Next handoff:** assign the engineer/reviewer and complete 16-A's technical/test start gates.
9-A follows after its 16-A prerequisite is integrated and the relevant tests pass. The lifting and
CRM courtesy follow-ups must not delay preservation. The consolidated backlog-readiness pass
remains unfinished; this single approval is not a claim that all twenty drafts are ready.