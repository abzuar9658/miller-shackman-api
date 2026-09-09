# Production-state consistency — Jira ticket drafts

These Markdown files are review drafts, not published Jira issues. Twenty tickets are drafted so far.
Drafting alone is not implementation or release approval. Scoped owner decisions are recorded below.
Each ticket's implementation and testing gates still apply.
Do not implement or publish a draft merely because it appears here.

## Recorded owner decisions

[16-A — Scoped approval record](../production-state-consistency-approvals.md), recorded 2026-09-09:
the user approved preservation/recovery-only scope and the conservative recovery-evidence rule,
provided they conform to the actual codebase and recorded product decisions. The source recheck
supports that repair direction; it does not claim recovery is already implemented. Engineering/test
review, named assignments, merge evidence and separate production authorization remain open.
This approval does not extend to 16-B, CRM courtesy writes or Jira publication. The original twenty
drafts remain unchanged; the register records the later decision, not blanket implementation approval.

## Engineering start order

**Start with 16-A → 9-A → 11-A. Do not start 16-B because it is the newest draft.**
There are real dependencies, but the twenty tickets are **not one strict sequential chain**.
Preparation can begin now; none is marked fully ready for implementation by this documentation pass.
16-A is closest: its scoped product/recovery approval is recorded, but assignment and technical/test
review remain open. No preceding ticket, legitimate-lifting feature or CRM courtesy write blocks it.

### How to use this guide

- **Recommended slot** is a suggested one-engineer pick order, not a dependency on every earlier row.
  After the initial three, this is scheduling guidance, not a new owner-approved priority decision.
  It keeps 14-B then 13-B as the next policy priorities and brings 17-A ahead of dispatch-dependent
  work. If a slot is blocked, pick another whose own gates are satisfied; do not idle all Class A
  repairs while waiting for a Class B decision or release.
- **Before affected implementation** identifies hard start prerequisites and contracts/decisions
  that must be agreed before coding the affected behavior. An approved contract is not integrated
  code; where an integrated prerequisite is required, record the actual revision and passing tests.
- **Integration before release** can block shipping a completed journey without blocking independent
  preparation or agreed contract-level work. Do not duplicate an unfinished foundation in a dependent
  PR. Resolve its interface before dependent code; integrate and test it before claiming acceptance.
- **Route-specific** means required whenever that route is included, not optional safety. Where the
  draft permits containment, agree and expose the unsupported route with an owned safe disposition;
  do not quietly remove promised behavior or call untested sending/recovery complete.
- **Readiness is a document snapshot, not a deployment audit.** All implementer, independent-reviewer
  and release/recovery-operator assignments remain **unassigned in this guide**; use each draft's
  Owners field for additional roles. No upstream integration or behavioral test pass is asserted.
  Read each linked draft's dependencies, remaining gates and implementation/merge/live checklists.
  The scoped approval register supplements 16-A's unchanged checklist.

### Common start, merge and release gates

Before starting a ticket's affected implementation:

1. **Assign the people and baseline.** Name the implementer, independent reviewer and applicable
   product/API/web/runtime/recovery owners. Record branch revisions, actual integrated prerequisites
   and current working behavior; retrace the relevant end-to-end journey on that branch.
2. **Approve the executable scope and test contract.** Agree on outcomes, exclusions, protected
   behavior, public test boundaries, allowed fakes, literal expected results and positive controls.
   Earlier approval to draft or “looks good” is not proof all these gates are closed. Retain 16-A's
   recorded scope/recovery approval; escalate material conflicts rather than guessing around it.
3. **Close the relevant pre-code design/decision gates.** Compare the required technical alternatives,
   approve the smallest complete approach, and identify shared-contract owners and exact blockers.
   R1–R4 are **local to each ticket**, not one global checklist. Close their design portions before
   affected code where specified; production cohort/activation approvals remain later gates.
4. **Use test-first execution.** Once the contract is approved, write and run the first meaningful
   failing behavior test **before the implementation fix**; proceed one scenario at a time to green.
   Missing dependencies, invalid fixtures and skipped tests are not the required red. Preserve
   already-green safeguards and demonstrate their sensitivity rather than fabricating failures.

Before merge, supply the ticket's red/green, regression and independent-review evidence, including
real persistence/concurrency, execution and API/UI checks where required. Before release or historical
repair, separately authorize the environment, bounded cohort, operators and tested rollout/recovery
plan. **Class A and Class B must never share a PR.** Every B activation also needs its own D7/G7
owner sign-off and applicable D5 briefing; that release sign-off is distinct from design approval.
This guide authorizes no Jira publication, deployment, customer contact or production data operation.

### Twenty-ticket execution and readiness matrix

**Planning snapshot: 2026-09-09. Every row is not ready for implementation.** An “open gate” below
means unfinished work or approval, **not permission to start**.

All rows also require the common gates above. “None” means no blanket preceding-ticket requirement,
not permission to skip design/tests or bypass safety. Shared-contract references are not an instruction
to wait for every neighboring ticket. Exact route blockers must be recorded during that ticket's review.

| Slot | Ticket / class | Before affected implementation | Required integration before release | Readiness: not ready — remaining gates | Parallel work / coordination |
| --- | --- | --- | --- | --- | --- |
| 1 | [16-A — Preserve opt-outs](issue-16-a-preserve-opt-outs-during-crm-refresh.md) · A | No preceding ticket. Approve technical/test boundaries and detailed recovery-evidence mechanics before coding those expectations. | All four refresh paths and concurrent suppression writes; tested bounded recovery. Production repair/re-enablement is separately authorized. | **Handoff open:** conditional scope/recovery-rule approval recorded; assignments and engineering/test review remain. | First implementation priority. Do not wait for 16-B or courtesy CRM delivery. |
| 2 | [9-A — STOP and unresolved-reply safety](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md) · A | **16-A integrated and relevant tests passing.** Approve durable guard/transaction and operator-resolution contracts. | Preserve 16-A through receipt, processing and all applicable send checks; verify recovery protections before affected outreach is re-enabled. | **Start gates open:** approve interim retry/visibility behavior, unchanged STOP lifecycle, test boundaries and guard design. | Preparation can overlap 16-A; dependent implementation cannot skip it. 9-B timing and 13-B fallback are not prerequisites. |
| 3 | [11-A — Correct ownership immediately](issue-11-a-project-crm-reassignment-immediately.md) · A | Verify the **16-A shared-state contract** and approve resolver/transaction/test boundaries. | **16-A preservation contract and tests integrated before release**, including webhook/export refresh overlap. | **Start gates open:** direction accepted; exact fallback, next-fetch, export and source-ordering contract plus assignment/review remain. | Can progress alongside 9-A after shared-contract review. **9-A is priority, not an assignment-resolver dependency; 14-B is not required.** |
| 4 | [14-B — Enrollment-tag CRM control](issue-14-b-use-enrollment-tag-as-crm-control.md) · B | **16-A, 9-A and 11-A integrated** and recorded. Approve R1–R4 behavior/evidence; retain or relocate G5 activity stamping. | Preserve those A foundations; verify tag-write failure/recovery, protected tag cycling and compatible cohort cutover. D5 CRM-control briefing. | **Start gates open:** bound-tag mapping, manual/review hold survival, failed setup recovery and source-ordering limits. | Next policy priority if ready; does not block independent A repairs. Not a blanket prerequisite for 13-B or 17-A. |
| 5 | [17-A — Durable outbound dispatch](issue-17-a-durable-outbound-dispatch.md) · A | **D6/G6 sizing before assignment/estimate and design approval.** Approve R1–R4 design portions and A-only lifecycle; resolve G3 for affected fallback interactions. | Preserve 16-A/9-A, ownership and actual released consent/CRM controls. Prove intent/claim and purpose/occurrence completion on every included route; identify any separately required repairs. | **Sizing/design gates open:** producer coverage, provider evidence, identity, lifecycle/API and recovery. | Can advance alongside independent A work. Coordinate 13-B interfaces; **do not create a blanket 13-B ↔ 17-A dependency or add 17-B policy here.** |
| 6 | [13-B — Consistent consent and fallback](issue-13-b-consistent-consent-and-channel-fallback.md) · B | **16-A and 9-A foundations integrated/verified.** Verify settled G2 mapping; decide G3 and R1–R3 channel/rendering/approval/recovery contracts. | Integrate any separately sized **17-A mechanics required for safe fallback before activation**; preserve actual 11-A/14-B baseline. No partially safe journey-dependent policy release. | **Start gates open:** G2 verification, G3 exception decision and R1–R3. D1/unknown-consent policy is settled, not reopened. | Not inherently blocked by shipping 14-B. Agree dispatch/fallback seams with 17-A without rebuilding A mechanics in B. |
| 7 | [1-A — Visible scheduling holds](issue-1-a-visible-scheduling-holds.md) · A | No blanket preceding ticket. Approve R1–R3 hold identity, correction/revalidation and operator contracts; name any real 2-A/7-A blocker. | Preserve 16-A/9-A; integrate occurrence/send identity with 17-A where touched. The ticket's own hold-to-recovery journey must work. | **Start gates open:** hold/transaction, recovery and scoped reads; R4 cutover/history remains a release gate. | Can progress with 2-A/3-A/4-A. Foundation for 5-A/6-A; no wait for 13-B/14-B/17-B. |
| 8 | [2-A — Reliable instruction delivery](issue-2-a-reliable-instruction-delivery.md) · A | No blanket wait for 7-A's whole sweep. Agree R1–R3 instruction identity, guarded restart, delivery evidence and operator contracts; name concrete recovery blockers. | Preserve 16-A/9-A and 1-A scheduling truth; share recovery with 7-A and respect 17-A send identities on affected wake-ups. | **Start gates open:** identity/evidence, transactions/Temporal and scoped recovery; R4 rollout/history open. | Can progress with 1-A/3-A/4-A. **2-A and 7-A need one shared recovery contract, not circular whole-ticket waits.** |
| 9 | [3-A — Enrollment progress and daily cap](issue-3-a-accurate-enrollment-progress-and-daily-cap.md) · A | No blanket preceding ticket. Approve R1–R3 first-action evidence, cap source/day/atomicity and cap-held continuation/read contracts. | Preserve 16-A/9-A; coordinate 1-A projections, 2-A/7-A recovery and 17-A identities where paths intersect. | **Start gates open:** exact first action, cap accounting and deferred-start journey; R4 historical treatment/rollout open. | Independent foundation. **Does not wait for 8-A/G1 merely to fix start accounting; D2's joint-release gate is closed.** |
| 10 | [4-A — Retained operational evidence](issue-4-a-retained-operational-evidence.md) · A | No blanket preceding ticket. Approve R1–R3 exact retention/runtime/privacy, evidence coverage and scoped history reads. | Reuse 1-A/2-A/3-A/17-A evidence identities where available; verify real retention cutover and older-run investigation. | **Start gates open:** retention/privacy and evidence/read design; R4 operational verification remains open. | Independent retention/evidence lane. No need to wait for every lifecycle fix or a B release; do not create competing evidence records. |
| 11 | [5-A — Durable send-time holds](issue-5-a-durable-send-time-holds.md) · A | **Approved 1-A shared hold contract** before dependent implementation; agree R1–R3 occurrence, engine/recovery and operator design. | **Integrate/reuse 1-A.** Preserve 16-A/9-A; reuse 2-A/3-A/4-A/17-A where integrated and close any actual recovery/send blockers. | **Foundation/design gates open:** existing-occurrence handling and safe revalidation; R4 stranded-lead/cutover plan open. | Preparation can overlap 1-A; do not invent a second review system. General 6-A/7-A/8-A delivery is not automatically required. |
| 12 | [6-A — Visible cannot-proceed outcomes](issue-6-a-visible-cannot-proceed-outcomes.md) · A | **Approved 1-A/5-A hold contracts** and R1–R3 branch/disposition, recovery and operator design. | **Integrate/reuse 1-A/5-A.** Preserve 16-A/9-A; reuse 2-A/3-A/4-A/17-A where integrated. Name concrete 7-A/8-A/10-A blockers only for affected routes. | **Foundation/design gates open:** explicit outcomes, identity and absence handling; R4 history/cutover open. | Follows the shared hold foundation, not every neighboring lifecycle ticket. No new completion or retry policy. |
| 13 | [7-A — Missing-engine recovery](issue-7-a-missing-engine-recovery.md) · A | Agree R1–R3 eligibility/inspection and reconstruction contract with **2-A**; identify exact progress/wait/send dependencies before dependent implementation. | Share 2-A recovery; integrate 1-A/5-A/6-A waits, 3-A progress, 4-A evidence and **17-A duplicate protection where required**. Unsafe/unreconstructable routes stay explicitly contained. | **Start gates open:** engine evidence, guarded reconstruction, bounded recovery and operator contract; R4 cohort/rollout open. | Inspection/design can overlap foundations. **Automatic sending recovery cannot ship ahead of its required reconstruction/dispatch safety.** |
| 14 | [10-A — Exhausted-engine failure visibility](issue-10-a-exhausted-engine-failure-visibility.md) · A | Approve R1–R3 failure/hold/recording design with named **7-A backstop and 17-A send-safety integrations**; no blanket wait for 8-A. | **7-A independent backstop required; 17-A on every affected send route.** Reuse 1-A/5-A/6-A holds, 2-A instructions, 3-A progress and 4-A evidence as required. | **Design/integration gates open:** exhaustion classification, recording failure, recovery authority and reads; R4 operations open. | Source-failure work can be prepared with 7-A. Protect actual 8-A/G1 baseline without making its unresolved policy a universal blocker. |
| 15 | [15-A — Stopped background-work visibility](issue-15-a-exhausted-background-work-visibility.md) · A | Approve R1–R3 per-source evidence, ownership, discovery and allowed-recovery matrix; agree 9-A/16-A inbound and 2-A instruction contracts. | Reuse integrated 9-A/16-A, 2-A and 4-A. **17-A for any lead-sending replay; 7-A for applicable engine reconstruction.** Without safe replay, only an approved non-replaying, owned support disposition. | **Start gates open:** source classification, durable discovery, scoped usable remedy and ownership; R4 rollout/monitoring open. | Visibility need not wait for every recovery feature. Coordinate 9-B/10-A and affected lifecycle projections; no duplicate review/retry owner. |
| 16 | [8-A — Completion and final replies](issue-8-a-completion-lifecycle.md) · A, subject to G1 | **G1 must be decided before completion implementation:** timing, ongoing conversation and final/late ordinary/interested/opt-out replies. Then approve R1–R3. | Reuse 3-A/4-A/6-A state/evidence and integrate 2-A/7-A/9-A/16-A/17-A where boundaries intersect. Required late-reply handling must ship with completion. | **Product-blocked:** G1 unresolved; R1–R4 open. Changed reply/contact entitlement needs its own D7 classification/approval. | Investigate G1 now; skip this slot if unresolved. Does not block 3-A's start/cap fix or unrelated A work; no restored D2 volume gate. |
| 17 | [17-B — Continue after uncertain sends](issue-17-b-continue-cadence-after-uncertain-send.md) · B | Name/verify the **17-A foundation for the affected journeys**; agree R1/R2 consumption/timing and audit/API contracts plus R3/R4 reporting/recovery design. Missing A mechanics stay separate. | **Accepted 17-A coverage before B integration/activation.** Preserve existing safety and actually released policies; identify any real completion dependency rather than claiming to fix G1. | **Foundation/design gates open:** once-only progress, immutable timing, audit-only corrections, reporting and compatibility. | Can be prioritized once 17-A is ready; need not wait for 12-B/14-B or all hold repairs. No new vote on the settled uncertainty policy. |
| 18 | [12-B — Carrier opt-out and safe email fallback](issue-12-b-carrier-opt-out-handling-and-fallback.md) · B | **16-A, 13-B and 17-A integrated coverage identified/verified.** Verify G2, decide affected G3 interaction and approve R1–R3 provider/continuation/operator contracts. | Those foundations on every affected producer, with trusted callback correlation and once-only continuation; preserve 9-A and actual released uncertainty/CRM controls. | **Dependency/design gates open:** G2/G3 and R1–R4 provider, identity, continuation and cutover evidence. | Does not inherently wait for 17-B or 8-A. Reuse their actual baseline only; late/uncertain touches cannot become fallback retries. |
| 19 | [9-B — Reply retry window and escalation](issue-9-b-reply-retry-window-and-escalation.md) · B | **9-A and 16-A integrated, relevant tests passing.** Approve R1–R3 failure/clock/cutoff, durable expiry/notices and real agent/manager routing. | **17-A for any contacting continuation; 2-A where workflow coordination is needed.** Reuse 4-A history and current assignment; coordinate 15-A discovery. | **Dependency/design gates open:** receipt-based clock, success boundary, manager/recipient contract and owned recovery; R4 release/history open. | Can move earlier after its foundations/gates. Not dependent on 12-B/13-B/14-B as new releases or on all of 15-A. |
| 20 | [16-B — Legitimate opt-out lifting](issue-16-b-legitimate-opt-out-lifting.md) · proposed B | **16-A, 9-A and enabled-route 13-B integrated/verified**, plus route-specific **17-A/2-A** as required. Approve R1–R3 real source/role/scope and effective-state/history contracts, including B boundary. | 17-A for offered subsequent outreach; 2-A for coordinated resume. Compatible refresh/recovery/courtesy source-version handling and R4 rollout; no implicit resume/re-entry. | **Capability/design gates open:** G4, launch provider/human permissions, ordering, evidence and usable post-lift journey; R1–R4 remain. | Does not block 16-A and does not require the entire 12-B/14-B/17-B/15-A backlog for narrow consent reads. Courtesy delivery is a separate follow-up. |

### Parallel work and dependency traps

- **Safe early preparation:** collect evidence, draft designs and settle owner/test contracts for
  any ticket. This is not permission to implement an unresolved policy or treat mocked foundations
  as shipped. 11-A may progress alongside 9-A once its 16-A contract is verified; 9-A's own start
  still requires integrated 16-A.
- **Independent A lanes:** 17-A sizing/durability and 1-A/2-A/3-A/4-A can progress in parallel after
  their own gates, with agreed ownership of overlapping files, schemas and contracts. Scheduling
  holds, instructions, cap accounting and evidence are not conditional on all B releases.
- **Shared-contract order:** 1-A → 5-A → 6-A is the hold-extension path. Establish 2-A/7-A's shared
  same-journey recovery contract; integrate the exact hold/progress/send foundations each route
  needs. 10-A requires the 7-A backstop; 15-A must not offer replay without its route's safety proof.
- **Policy lanes are independently gated:** 14-B and 13-B need not wait for all A repairs; 17-B
  consumes 17-A; 12-B consumes 16-A/13-B/17-A; 9-B consumes 9-A/16-A; 16-B consumes 16-A/9-A/13-B.
  Route-specific 17-A/2-A requirements still apply. Preserve already released policies, but never
  quietly add them to an A PR or roll them back to simplify a repair.
- **Do not invent global blockers:** G1 blocks 8-A's completion implementation, not every ticket
  mentioning replies. G2 is state/provenance verification, not a new fallback vote. G3 blocks the
  affected configured provider-fallback interaction. D1/D2 remain settled. 16-A must not wait for
  the lifting or CRM courtesy follow-ups; no ticket order authorizes historical bulk replay.

**Next engineering handoff:** assign 16-A's implementer/reviewer and release/recovery operator,
approve its technical/test boundaries, then demonstrate the first failing preservation test.
Advance 9-A only after its 16-A integration gate is met; keep the matrix updated with real evidence.

## Draft review history — not implementation order

This newest-first record preserves the review focus at drafting time. Its ordinal draft labels and
historical counts are not start slots or evidence of readiness; use the engineering guide above.

**Latest draft to review:**

[Issue 16-B — Lift an opt-out only through verified resubscription or an audited human action](issue-16-b-legitimate-opt-out-lifting.md)

Read **Business impact**, **§3.2 — Scope**, **§3.3 — Provider trust**, **§3.5 — Workflow control**,
**§3.6 — Human/support journey** and **§3.7 — Remaining gates**, then the acceptance scenarios.
This is a separately gated **Class B** follow-up to 16-A: verified START/resubscribe or an authorized
human clear replaces only the specifically covered restriction, with durable original/lift history.
No implicit DNC/other-channel clear, provider unblock, automatic resume/re-entry or old-touch resend.
R1–R4 remain open: actual source/provider/role/scope matrix, ordering/effective-state/refresh/recovery
design, usable evidence/permissions/post-lift journey, compatible rollout and monitoring. No human
role grant, resulting permission status or email resubscribe callback is assumed from an enum.
Preserve integrated 16-A/9-A/13-B and route-specific 17-A/2-A safeguards. The separate CRM courtesy
update must not become the local source of authority; its delivery/retry feature is still undrafted.
G4 is not closed by drafting, and D7 owner release approval/briefing remain required; A/B cannot
share a PR. All nineteen earlier drafts are unchanged. Twenty drafts cover the seventeen source
issues plus these separately scoped follow-ups, without closing earlier decisions or release gates.

**Nineteenth draft / separate reply retry and escalation policy:**
[Issue 9-B — Retry reply classification for 30 minutes, then escalate for review](issue-9-b-reply-retry-window-and-escalation.md)

Read **Business impact**, **§3.2 — Failure categories**, **§3.3 — Original clock and success boundary**,
**§3.4 — Agent/manager obligations** and **§3.6 — Remaining implementation and release gates**,
then the acceptance scenarios. This is **Class B**: eligible classifier outages retry silently
within 30 minutes of original receipt; unresolved expiry becomes protected review plus durable
agent/manager notice obligations. Exact hard words remain immediate under separately integrated 9-A.
Returned rejected answers retain immediate review; unrelated processing failures are not AI outages.
R1–R4 remain open: phase/clock/cutoff rules, durable checkpoints and independent expiry discovery,
actual manager/recipient routing and scoped operator recovery, compatible history/rollout and
measurable lag/coverage bounds. No assumed agent-to-manager hierarchy, extra 24-hour escalation,
automatic post-expiry resume, blind notice resend or provider-delivery guarantee.
Preserve 9-A/16-A and applicable 17-A/2-A foundations; correlate 15-A rather than duplicate reviews.
Individual D7 owner release approval and briefing remain required; A/B must not share a PR.
All eighteen earlier drafts are unchanged. Nineteen drafts now cover all seventeen source issues;
continued drafting closes none of the earlier decisions, test contracts or release gates.

**Eighteenth draft / earlier stopped-background-work visibility:**
[Issue 15-A — Show background work that has stopped retrying](issue-15-a-exhausted-background-work-visibility.md)

Its content is unchanged. Read **Business impact**, **§3.2 — Classification**, **§3.4 — Bounded recovery** and
**§3.6 — Remaining implementation and release gates**, then the acceptance scenarios. This is
**Class A**: each stopped inbound event, engine instruction or event publication becomes queryable
with a safe reason, truthful age/context and an authorized remedy or owned escalation route.
The existing aggregate event-risk card is not a complete terminal-work list. Preserve ordinary
retries, live claims and original identities; correlate 9-A/2-A evidence without duplicate reviews.
No blanket lead hold, new notification policy, automatic backlog replay or universal retry button.
Any offered replay needs its source-specific safety contract and required integrated foundations;
unsupported replay stays visibly contained. Seen, requested, accepted and resolved remain distinct.
R1–R4 source/evidence, ownership/discovery/recovery, scoped operator and history/rollout/monitoring
gates remain open. A/B must not share a PR; the actual released B baseline remains protected.
All seventeen source issues now have at least one draft; policy follow-ups and all earlier gates remain.

**Seventeenth draft / separate carrier opt-out policy:**
[Issue 12-B — Honor carrier-reported SMS opt-outs and use email safely](issue-12-b-carrier-opt-out-handling-and-fallback.md)

Its content is unchanged. Read **Business impact**, **§3.2 — Evidence classification**, **§3.5 — Late callbacks** and
**§3.7 — Remaining implementation and release gates**, then the acceptance scenarios. This is
**Class B**: verified Twilio unsubscribe evidence becomes a durable SMS opt-out; a definitely
rejected, still-unconsumed current touch may continue by usable email through 13-B's checks and
approval contract. No usable channel means its visible review, not a generic provider-failure item.
Use integrated 16-A/13-B/17-A foundations; preserve the actual separately released 17-B policy.
Late evidence can restrict future work but cannot replace an accepted/uncertain/consumed old touch.
G2/G3 and R1–R4 remain open: verify state mapping, resolve the configured paused-search exception,
and approve provider/trust/identity, durable continuation, operator and rollout/recovery contracts.
No generic failure-to-email rule, sender rotation, consent lift, automatic historical restart or
provider-wide delivery guarantee. D7 requires separate B owner release approval and briefing; A/B
must not share a PR. Continuing drafts closes none of these gates or those of the earlier drafts.

**Sixteenth draft / earlier exhausted-engine repair:**
[Issue 10-A — Show when automation gives up after repeated system errors](issue-10-a-exhausted-engine-failure-visibility.md)

Its content is unchanged. Read **Business impact**, **§3.2 — Failure classification**, **§3.6 — Remaining implementation and
release gates**, then the acceptance scenarios. This is **Class A**: terminal activity failures
become actionable same-journey problems instead of leaving a healthy-looking lead with no engine.
Reuse a durable hold/evidence contract and the independently integrated 7-A backstop when recording
also fails. R1–R4 cover classification/identity/state, recording/engine/backstop/send safety, scoped
operator recovery and history/rollout/monitoring. All remain open; no new enum or retry budget is chosen.
Preserve normal bounded retries, protected states, original commands, progress and 17-A send claims.
Exhaustion is not provider rejection, proof of no send, ordinary cancellation or a Workflow Task bug.
No automatic resume after exhaustion, step-one reset, forced handoff, new notification policy or
guessed historical repair. Technical restoration is not business permission to resume; a queued
instruction is not a proved recovery. Preserve the actual released B baseline; A/B need separate PRs.

**Fifteenth draft / earlier completion-lifecycle repair:**
[Issue 8-A — Complete the campaign without losing replies to its final message](issue-8-a-completion-lifecycle.md)

Its content is unchanged; continuing drafting does not close G1 or its implementation/release gates.
Read **Business impact**, **§3.2 — G1**, **§3.6 — Remaining implementation and release gates**, then
the acceptance scenarios. This is **Class A, subject to G1**: record genuine standard-cadence
completion consistently across workflow, enrollment, history and engine, while preserving the
agreed final/late-reply journey and existing controlled manual re-entry into a new run.
**G1 remains unresolved:** no response-window duration, immediate-close default, ongoing-conversation
rule or post-completion reply entitlement is chosen. G1 and R1–R4 block their implementation/release
boundaries. Keep pending dispatch/replies, human control, opt-outs and successor runs protected.
Reuse integrated 2-A/3-A/4-A/6-A/7-A/9-A/16-A/17-A contracts where required; preserve the actual B
baseline. No automatic re-entry, terminal Resume, fabricated completion times or blanket historical
terminalization. Any changed reply/contact policy needs separate approval and D7 classification;
A/B require separate PRs. Completion cannot ship ahead of its required late-reply handling.

**Fourteenth draft / earlier missing-engine repair:**
[Issue 7-A — Recover missing automation engines without restarting the business journey](issue-7-a-missing-engine-recovery.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: independently discover missing engines, including committed failed
starts with no queued instruction, and safely restore the same journey from durable progress.
Keep running waits, human control, terminal/successor state, send claims and original instructions
intact. Unknown health is not confirmed absence; accepted start is not reconstructed execution.
R1–R4 cover population/inspection/eligibility, shared durable recovery and execution safety, scoped
operator recovery, and bounded historical cohort/rollout/monitoring. All remain open. No step-one
reset, widened resume/re-entry permission, bulk revival or new contact/completion policy.
Reuse integrated 1-A/2-A/3-A/4-A/5-A/6-A/17-A contracts where required; contain unreconstructable
routes explicitly. Preserve the actual separately released B baseline. A/B require separate PRs.

**Thirteenth draft / earlier cannot-proceed repair:**
[Issue 6-A — Make cannot-proceed outcomes visible instead of silently ending nurture](issue-6-a-visible-cannot-proceed-outcomes.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: classify configuration/structural failures explicitly, retain a
durable recoverable hold and avoid successful engine completion while the same lead still looks live.
Preserve existing human-control, terminal and response waits; “no next step” alone proves none of them.
R1–R4 cover outcome/identity/persistence, engine/recovery, scoped operator/absence handling and compatible
cutover/history. All remain open. The standard final-send wait remains Issue 8; no new completion,
late-reply, re-entry, contact or automatic restart policy. Reuse 1-A/5-A holds and integrated 2-A/3-A/
4-A/17-A contracts; no invented missing entities or duplicate queue. A/B require separate PRs.

**Twelfth draft / earlier send-time hold repair:**
[Issue 5-A — Keep send-time holds visible and safely recoverable](issue-5-a-durable-send-time-holds.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: a hold discovered while executing a valid schedule becomes the same
durable, visible and recoverable hold as 1-A, rather than ending the engine while the lead looks active.
R1–R4 cover outcome/episode/occurrence integrity, engine signals/revalidation, scoped operator reads
and compatible rollout/stranded-lead handling. All remain open. Future deferral already reschedules;
preserve it and prevent an open occurrence's old time from authorizing a stale send.
No consumed touch, new enrollment, guessed timing, automatic historical resume or new contact policy.
Reuse 1-A/2-A/4-A/17-A contracts where integrated; general cannot-proceed and missing-engine repairs
remain separate. A/B require separate PRs.

**Eleventh draft / earlier operational-evidence repair:**
[Issue 4-A — Keep enough automation history to investigate an incident](issue-4-a-retained-operational-evidence.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: explicit multi-week engine retention, durable business reasons that
survive independently, and authorized access to older runs/records without a latest-only/100-row dead end.
R1–R4 cover exact retention/runtime/privacy, decision identity/coverage/transactions, scoped history
reads, and cutover/real elapsed-time verification. All remain open. The incident's reported 24-hour
setting is not a fresh live measurement; configuration alone is not deployment evidence.
No recovered-history promise without a usable copy, new outreach policy, replay or automatic resume.
Already-closed Temporal executions keep their old cleanup timers. Archival is not presumed supported
or configured in this Docker deployment. A/B require separate PRs.

**Tenth draft / earlier enrollment-progress and daily-cap repair:**
[Issue 3-A — Report accurate enrollment progress and enforce the daily start cap](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: project the correct enrollment lifecycle, evidence its first real
action once, and enforce the existing start allowance across batches, retries and concurrent callers.
Keep cap-held candidates discoverable and safely continuable; distinguish pending capacity, actual
start and provider delivery. R1–R4 cover first-action evidence, cap scope/day/atomicity, deferred-start
and read contracts, and evidence-based history/rollout. These gates remain open.
No invented start times, cap increase, automatic re-entry or new completion/contact policy.
Issue 8 completion and G1 late-reply behavior remain separate; D2's former joint-release gate is
closed. Any genuine source/day policy change requires separate Class B work; A/B need separate PRs.

**Ninth draft / earlier instruction-delivery repair:**
[Issue 2-A — Make workflow instruction delivery reliable and truthful](issue-2-a-reliable-instruction-delivery.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: retain the original instruction after a permitted same-workflow
engine restart; distinguish queued, engine-accepted and actually applied; prevent duplicate/stale
commands from overriding newer decisions; make unresolved delivery discoverable and recoverable.
R1–R4 cover identity/evidence, recovery/transactions/Temporal, scoped operator contracts and rollout.
No step-one reset, widened restart/resume permissions, bulk signal replay or new contact policy.
General missing-engine recovery and background-job dead letters remain separate. A/B need separate PRs.

**Eighth draft / earlier scheduling-hold repair:**
[Issue 1-A — Make scheduling holds visible and safely recoverable](issue-1-a-visible-scheduling-holds.md)

Its content is unchanged; continuing drafting does not close its §3.6 implementation/release gates.
This is **Class A**: an existing schedule-time hold becomes a durable paused/review state,
with reason/history, scoped attention visibility and a safe correction → revalidation → scheduling
journey. No guessed date, consumed touch, occurrence-less skip, automatic resume or new timing policy.
R1–R4 cover hold identity/transactions, recovery/Temporal, operator/read contracts and rollout.
Send-time holds and general missing-engine recovery remain separate; A and B must not share a PR.

**Seventh draft / separate uncertainty policy:**
[Issue 17-B — Continue the cadence after an uncertain send without sending that step again](issue-17-b-continue-cadence-after-uncertain-send.md)

Its content is unchanged; proceeding with the next draft does not close its implementation/release gates.
This is **Class B uncertain-as-sent for journey accounting, not delivery**: consume the applicable
step, occurrence or AI turn once and continue the eligible journey on its configured schedule without
waiting for provider confirmation. Never resend the uncertain touch. Later callbacks, reporting expiry
and any retained manual correction affect audit only; existing safeguards and handoff ownership remain.
Requires the separately integrated 17-A foundation. R1–R4 consumption/timing, audit/API/UI, reporting
and legacy/Temporal recovery gates remain, plus individual D7/G7 owner release approval and briefing.
No fabricated provider acceptance or delivery, automatic bulk resume, or provider-wide exactly-once promise.

**Sixth draft / separate durable-dispatch prerequisite:**
[Issue 17-A — Make every lead send durable before contacting the provider](issue-17-a-durable-outbound-dispatch.md).
The user asked to continue drafting; its content is unchanged and implementation/release gates remain.
This is Class A: commit intent/claim before provider I/O, prevent retry after possible acceptance,
and complete the correct journey durably. Includes paused-search occurrences, AI replies, operator
sends, draft approval and existing handoff acknowledgments while preserving standard cadence.
D6/G6 sizing and R1–R4 identity, provider evidence, lifecycle/API and recovery gates remain.
**17-A does not implement 17-B's no-pause or audit-only callback policy; A and B need separate PRs.**

**Fifth draft / separate consent-and-fallback policy:**
[Issue 13-B — Apply one consent rule and use the other usable channel](issue-13-b-consistent-consent-and-channel-fallback.md).
The user said it looks good; its content is unchanged and its implementation/release gates remain.
Explicit denial blocks its channel everywhere; the other usable channel may carry the same message.
Unknown consent alone does not block; no usable channel means visible review, distinct from global
DNC. D1 is settled; G2/G3 and R1–R3 remain explicit gates, with separate owner release sign-off and briefing.

**Fourth draft / separate CRM-control policy:**
[Issue 14-B — Use the enrollment tag to control CRM-side automation](issue-14-b-use-enrollment-tag-as-crm-control.md).
The user said it looks good; its content is unchanged and its clarification/implementation gates
remain open. Tag removal ends nurture; re-add after a tag-ended run starts fresh. Routine CRM
activity no longer pauses/vetoes sends, with enrollment-tag writes, safe recovery and the D5 briefing.

**Third draft / earlier ownership repair:**
[Issue 11-A — Show CRM reassignment under the correct agent without waiting for sync](issue-11-a-project-crm-reassignment-immediately.md).
The user said it looks good; its content is unchanged and implementation/release gates remain open.
It is the Class A ownership-projection repair, including history-export refresh. “Immediate” means
the next fresh fetch after webhook commit, not live browser push or the Issue 14 policy.

**Second draft / earlier safety work:**
[Issue 9-A — Honor STOP without AI and hold outreach while replies are unresolved](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md).
Its content is unchanged. The user agreed to continue drafting, not to implement or release it.
The 30-minute retry/notification policy and cross-channel continuation remain separate B releases.

**First draft / shared refresh-preservation prerequisite:**
[Issue 16-A — Keep recorded opt-outs when CRM data refreshes](issue-16-a-preserve-opt-outs-during-crm-refresh.md).
Its content is unchanged. It covers preservation/recovery; new consent-lifting and courtesy CRM
updates remain explicit follow-ups. Its implementation approval gates are not marked complete.

## Source-issue map

Source numbering is retained; this table is not the execution order. One source issue may require
multiple independently scoped tickets/PRs. **A and B must not share a PR.**

| Source issue | Release boundary | Draft status |
| --- | --- | --- |
| 1 — Visible scheduling holds | A; R1–R4 design/test/recovery gates remain | [Eighth draft — visible hold and safe recovery for review](issue-1-a-visible-scheduling-holds.md) |
| 2 — Reliable pause/resume signaling | A; R1–R4 evidence/recovery/operator/release gates remain | [Ninth draft — truthful instruction delivery for review](issue-2-a-reliable-instruction-delivery.md) |
| 3 — Accurate starts and daily-cap accounting | A; R1–R4 first-action/cap/deferred-start/history gates remain; no new completion or re-entry policy | [Tenth draft — accurate enrollment progress and daily-cap enforcement for review](issue-3-a-accurate-enrollment-progress-and-daily-cap.md) |
| 4 — Retained operational evidence | A; R1–R4 retention/privacy/evidence/read/cutover gates remain; no invented history or outreach-policy change | [Eleventh draft — retained operational evidence for review](issue-4-a-retained-operational-evidence.md) |
| 5 — Durable send-time holds | A; R1–R4 outcome/occurrence/engine/recovery/operator/cutover gates remain; no new timing or contact policy | [Twelfth draft — durable send-time holds and safe recovery for review](issue-5-a-durable-send-time-holds.md) |
| 6 — Visible cannot-proceed outcomes | A; R1–R4 outcome/identity/persistence/engine/recovery/operator/cutover gates remain; preserve response waits and separate completion/re-entry policy | [Thirteenth draft — explicit cannot-proceed outcomes and safe recovery for review](issue-6-a-visible-cannot-proceed-outcomes.md) |
| 7 — Missing-engine recovery | A; R1–R4 population/inspection/lineage/reconstruction/operator/history/rollout gates remain; no reset, widened restart eligibility or new contact policy | [Fourteenth draft — independent missing-engine detection and same-journey recovery for review](issue-7-a-missing-engine-recovery.md) |
| 8 — Completion lifecycle | A subject to unresolved G1 timing/late-reply contract; R1–R4 lifecycle/persistence/engine/re-entry/history/rollout gates remain; no automatic re-entry or unapproved reply policy | [Fifteenth draft — consistent completion without losing final replies, for review](issue-8-a-completion-lifecycle.md) |
| 9 — Inbound safety and reply hold | A ordering/hold/visibility; separate B receipt-based timing/agent-manager escalation, with R1–R4 and individual D7 release gates open | [Second draft — 9-A implementation gates remain open](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md); [nineteenth draft — 9-B retry window and escalation for review](issue-9-b-reply-retry-window-and-escalation.md) |
| 10 — Exhausted-engine failure visibility | A; R1–R4 classification/identity/recording/engine/backstop/send-safety/operator/history/rollout gates remain; no automatic resume, repeated possible send or new contact policy | [Sixteenth draft — visible exhausted failures and safe same-journey recovery for review](issue-10-a-exhausted-engine-failure-visibility.md) |
| 11 — Immediate ownership projection | A repair; do not mix Issue 14 policy | [Third draft — direction accepted; implementation gates remain open](issue-11-a-project-crm-reassignment-immediately.md) |
| 12 — Carrier opt-out handling/fallback | B; integrated 16-A/13-B/17-A, G2/G3, R1–R4 evidence/continuation/operator/cutover gates and individual owner release approval remain; no late same-touch replacement | [Seventeenth draft — durable carrier SMS opt-out and safe email continuation for review](issue-12-b-carrier-opt-out-handling-and-fallback.md) |
| 13 — Consistent consent and channel fallback | B; D1 settled, G2/G3 and implementation/release gates remain | [Fifth draft — direction accepted; implementation/release gates remain](issue-13-b-consistent-consent-and-channel-fallback.md) |
| 14 — Tag-only CRM control | B; D5 briefing and individual owner release approval | [Fourth draft — direction accepted; clarification and implementation gates remain open](issue-14-b-use-enrollment-tag-as-crm-control.md) |
| 15 — Exhausted background-work visibility | A; R1–R4 source/evidence/ownership/discovery/recovery/operator/history/rollout gates remain; no blanket hold, automatic replay or new contact/notification policy | [Eighteenth draft — actionable stopped-work visibility for review](issue-15-a-exhausted-background-work-visibility.md) |
| 16 — Preserve opt-outs and provide sanctioned lifting | A preservation/recovery: scoped owner approval recorded; engineering/test/assignment gates remain. Separate B lifting with G4 and R1–R4 gates open; CRM courtesy delivery remains a follow-up | [First draft — 16-A](issue-16-a-preserve-opt-outs-during-crm-refresh.md); [16-A approval record](../production-state-consistency-approvals.md); [twentieth draft — 16-B legitimate lifting for review](issue-16-b-legitimate-opt-out-lifting.md) |
| 17 — Durable dispatch and uncertain outcomes | A dispatch, subject to D6/G6 sizing; separate B uncertainty policy, subject to 17-A integration and D7/G7 approval; each has R1–R4 gates | [Sixth draft — 17-A durability contract](issue-17-a-durable-outbound-dispatch.md); [seventh draft — 17-B implementation/release gates remain](issue-17-b-continue-cadence-after-uncertain-send.md) |

## Remaining backlog-readiness work

1. Draft the other **Issue 16 follow-up — CRM courtesy opt-out notes/custom-field updates and safe
   retries**, using 16-B's source/supersession compatibility boundary. Local suppression/lifting
   must not depend on successful CRM delivery. Draft it or explicitly defer it with an owner; it
   does not block 16-A. Do not assign its release class by assumption.
2. Maintain the **execution/readiness matrix above** with named owners, verified prerequisite revisions,
   resolved or explicitly deferred decisions, and actual start/merge/live evidence. The dependency
   mapping is consolidated; assignments and approval/integration gates are not closed by this edit.
   Prioritize 16-A's remaining handoff gates. D1/D2 remain settled; no new broad consensus review.
3. Close remaining owner and acceptance/test approvals and package for Jira. Publication still requires the user's
   explicit go-ahead; drafting, implementation approval and production release are distinct.

## Standard for every draft

- Business-readable current/after behavior, production impact, unchanged behavior, and limitations.
- Explicit release class, scope, exclusions, prerequisites, and decision ownership.
- Numbered acceptance cases with expected and forbidden results agreed before implementation.
- Approved test boundaries, allowed fakes, legitimate-send/positive controls, and protected behavior.
- One scenario at a time: meaningful red → minimal fix → green; independent expectation review,
  sensitivity checks for critical protections, and real-integration evidence where needed.
- Safe recovery/deployment/rollback instructions and a distinction between merged and accepted live.

[Main issue plan and business-impact guide](../production-state-consistency-issues.md) ·
[D1–D7 consensus](../production-state-consistency-review-consensus.md)
