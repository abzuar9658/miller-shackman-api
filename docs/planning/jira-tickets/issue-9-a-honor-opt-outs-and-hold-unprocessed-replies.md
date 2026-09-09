# Issue 9-A — Honor STOP without AI and hold outreach while replies are unresolved

**Status: DRAFT — stakeholder and test-contract review required.**
This is the second proposed Jira description, not a published issue or permission to implement.
Agreement to continue drafting is not approval of every acceptance scenario or a production release.

## 1. Business impact — read this first

**The promise:** An AI outage must not make us ignore a lead's STOP or continue scheduled outreach
as though their reply never arrived.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | A lead replies STOP, but the AI call fails before the platform records the opt-out. An ordinary reply can also fail processing while later campaign messages continue. After the existing retries run out, the failure has no dedicated operator-facing outcome. |
| What changes after deployment? | Recognized opt-out keywords are applied without depending on AI. For other replies, automated outreach waits while the reply is unresolved. If processing succeeds, its normal business outcome is applied; if retries run out, the lead stays protected and the failure becomes visible for review. |
| Why does this matter? | It reduces unwanted messages after an opt-out and avoids treating a responsive lead as silent. Failed replies become work someone can find instead of disappearing into technical logs. |
| What will agents notice? | Some outreach that wrongly continued during an outage will now wait. Exhausted replies appear in Attention with the reason and a link to the lead/reply context. Acknowledging that item is not permission to restart outreach. |
| How long before review? | This Class A release retains the existing three-attempt retry policy, with 30-second then 60-second retry delays. Actual elapsed time also includes processing and worker polling. It does **not** deliver or promise the separate 30-minute policy. |
| Does SMS STOP now trigger an email instead? | **No.** This ticket retains today's STOP workflow outcome: suppression ends the current eligible nurture workflow. Cross-channel continuation is an approved target for Issue 13's separate Class B release, not part of this fix. The saved consent fact remains channel-specific. |
| Will this add exhaustion emails or notifications to managers? | Not in this slice. Exhaustion must be visible in the application without notification delivery. The separate timing/notification release owns the new escalation behavior. Existing notifications for other review and handoff outcomes remain unchanged. |
| What are the limits? | Free-text requests such as “please stop texting me” still need classification; they remain held if AI is unavailable. A message already handed to a provider cannot be recalled. This does not control messages an agent sends directly outside the platform. |

**Merging is not deployment.** These protections take effect when the relevant API and workers run
the fix. Historical review/recovery and production data changes require separate authorization.
Issue 16's preservation and required recovery must protect affected outreach before re-enablement.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — opt-out enforcement and reply-processing safety; confirm at publication |
| Source / delivery class | Production-state consistency Issue 9 / **Class A: ordering, durable reply hold, exhaustion visibility** |
| Components | Inbound receipt and worker; suppression; send checks; workflow coordination; existing lead/Attention surfaces |
| Repositories | miller-schackman-api; minimal miller-schackman-web mapping/presentation changes only if needed for the promised visibility |
| Implementation prerequisite | Issue 16-A preservation integrated and its relevant tests passing; this ticket's outcomes and testing boundaries approved |
| Owners | Assign implementer, independent reviewer, release operator, and operator responsible for unresolved replies |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; recheck the implementation branch |
| Closure boundary | Covers this Class A slice, not the whole of Issue 9 or generic background-work recovery |

**Included:** valid, matched lead replies entering the current normalized inbound pipeline; exact
hard-word opt-outs; durable protection from accepted receipt through classification/disposition;
retry/crash safety; pending-reply checks on application send paths; exhaustion visibility with
tenant/ownership controls; tests and a bounded rollout/backlog-review runbook.

**Excluded:**
- Issue 9-B's 30-minute receipt-based retry window and new notification escalation/fan-out
  (**D7 Class B: separate owner release sign-off required**). Keep existing retry parameters;
  do not sneak in a different timeout or attempt budget.
- Issues 12/13's channel fallback, carrier-error mapping, and consent-policy unification; new
  keyword lists, natural-language keyword heuristics, or opt-back-in capabilities.
- Issue 14's CRM control changes; Issue 8's completion/late-reply policy; Issue 17's general durable
  dispatch migration and uncertain-send behavior. Do not onboard paused-search to that queue here.
- A new general dead-letter dashboard, retry-everything button, or redesign of notifications.
  Issue 15 must later reuse this inbound visibility rather than create duplicate review items.
- Turning native CRM notes/activity into new inbound-message sources. Preserve existing source
  routing, validation, and identity matching; a CRM note is not automatically a lead-authored reply.

**D7 rule:** Class A and Class B must not share a PR. Retaining the current STOP workflow outcome is
an interim release boundary, not a reversal of the already-recorded cross-channel decision.

## 3. Current behavior and business contract

### What the code does today

Normalized inbound webhooks enqueue a pending external event and commit it. The worker later runs
the inbound use case, which saves a pending inbound message, calls the classifier, and only then
checks exact opt-out keywords. A returned unusable classification has an existing review path;
a raised exception instead causes rollback and retry. Saving before the LLM is not the same as
committing safety state before it: a rollback can remove the newly saved inbound message/state.

The existing pre-send reply check compares the newest inbound receipt with the outbound message's
scheduled time. It is not a lead-wide check for unresolved replies and misses a message scheduled
after the reply. A Temporal instruction queued only after processing is not an immediate safeguard.
The worker records EXHAUSTED after its current attempt budget, but does not create the promised
operator-visible review outcome.

### Contract to approve before writing tests

1. **Durable receipt protection.** For a valid reply matched to a lead in its workspace/provider,
   accepted receipt must establish a durable pending-reply guard. It must work while the event is
   queued, while the classifier is running, between retries, and after a worker restart. It cannot
   depend on the classifier or a later Temporal signal succeeding. An in-memory flag is insufficient.
2. **Exact hard words do not need AI.** Keep the current whole-message normalization: lowercase
   alphanumeric characters, dropping other characters. SMS keywords are stop, stopall, unsubscribe,
   cancel, end, quit; email's keyword is unsubscribe. Apply the channel restriction and original
   provider/event/time evidence at the safety boundary without waiting for classification. No
   optional summary, CRM write, or notification may undo or delay that durable restriction.
   Skipping classification for a hard word is allowed. If optional AI enrichment is retained, it
   runs only after the safety commit with failures recorded; no untracked fire-and-forget work or
   new mandatory summary dependency is introduced.
3. **Consent and lifecycle remain separate.** Preserve the other channel's consent fields and global
   DNC. Apply the current suppression workflow outcome where that transition is valid. Do not reopen
   a terminal workflow, clear a handoff, or introduce email-after-STOP. Issue 16 prevents later CRM
   refreshes from erasing the recorded restriction.
4. **Pending is lead-wide, not schedule-relative.** Until the reply has an applied business
   disposition, neither channel may send automated outreach for that lead. Cover existing/future
   cadence messages, standard and paused-search execution, queued dispatch, and other application
   send entry points that could bypass the guard. A new message, send-now, approval, or resume request
   does not itself resolve a reply. Keep all unrelated send safeguards.
5. **Apply the result before releasing its guard.** An ordinary reply follows the existing
   classification and routing rules. Remove only that reply's temporary protection after its
   disposition is safely applied. Another unresolved reply, review hold, manual pause, handoff,
   consent block, or terminal state still prevents inappropriate outreach. Successful processing
   is not a blanket cadence resume. A legitimate AI response to the resolved reply must still work.
6. **Retries retain the current budget.** The baseline is three total attempts, exponential delay
   from 30 seconds capped at 10 minutes; the two scheduled retry delays are 30 and 60 seconds.
   Preserve these settings and do not introduce a 30-minute deadline. A raised classifier failure
   remains retryable while attempts remain. A returned rejected classification keeps its existing
   immediate review behavior; do not treat every rejection as a transport outage.
7. **Exhaustion is visible and safe.** When that budget is exhausted, preserve the failure as
   EXHAUSTED and retain a durable no-send/review outcome. Show the affected lead, unresolved reply,
   failure category, receipt time/age, and review next step through Attention and lead detail.
   **Proposed review reason for approval:** inbound_processing_exhausted, displayed as “Reply
   processing failed after retries.” A generic PAUSED label alone is insufficient; do not invent
   an AI classification artifact for a call that never produced one.
   Persist exhaustion and its review protection/projection together, or make surfacing durably
   retryable independently of the classifier budget. A failed projection must not leave an
   undiscoverable terminal queue row. Visibility must not depend on CRM or email.
   Use existing roles: ASSIGNED_AGENT sees owned leads; MANAGER/BROKERAGE_ADMIN and authorized
   PLATFORM_SUPER_ADMIN use existing workspace-reporting access. Keep active membership and
   workspace checks; do not invent a new manager role or widen an agent's scope. An unassigned
   matched lead remains visible to authorized workspace operators.
   Known leads without a workflow also need review visibility; do not create a fake workflow or
   demote human-owned/terminal workflows merely to make a card appear.
   Transient processing adds no escalation notification; this slice adds no exhaustion notification
   program. Existing successfully applied review/handoff notifications remain unchanged.
8. **Duplicates and overlapping work are safe.** Stable event/message identity must survive retries;
   replay cannot create a second suppression effect or review item, erase another reply's guard,
   or reset consent provenance. Keep the queued payload needed for a retry when changing transaction
   boundaries. A new checkpoint must not make claimed events unrecoverable or break batch isolation.
9. **No clock-based permission to send.** Guard removal requires an applied disposition, not elapsed
   time, attempt exhaustion, queue acknowledgement, or an Attention acknowledgement. Failed safety
   reads are not evidence that no guard exists. Preserve fail-closed handling of unreadable facts.

**Concurrency boundary:** after the receipt/guard commits, a send that has not crossed its final
provider-dispatch boundary must observe it. Coordinate the final decision with receipt/state writes;
do not claim a check performed earlier is sufficient. If provider handoff already began first,
record that ordering honestly: this ticket cannot unsend it or solve general provider uncertainty.

## 4. Business acceptance scenarios — for approval

These are requirements, not passing test results. Use synthetic leads, literal expected results,
fixed clocks and controlled interleavings. “No send” means zero recording-provider calls, not merely
a returned status. Each send-blocking case needs an otherwise equivalent permitted control.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A matched SMS lead sends each exact hard word; the LLM is configured to raise or remain unavailable. | Durable SMS restriction, suppression type and original evidence are visible without waiting for LLM completion; current valid suppression lifecycle runs. | STOP waits for AI, is lost on rollback, or starts email fallback. |
| AC-02 | A matched email lead sends unsubscribe under the same conditions. | Email restriction/evidence persist without AI; unrelated SMS and DNC consent fields are preserved. | Email opt-out is forgotten or misrecorded as SMS/global consent. |
| AC-03 | Exercise case/spacing/punctuation normalization; compare “bus stop”, “please stop texting me”, and email “stop” against the supported exact words. | Exact normalized words take the deterministic path; other text goes through classification and remains protected while pending. A known non-opt-out control remains unrestricted. | Substring matching suppresses everyone, or all free text bypasses classification. |
| AC-04 | Accept a valid reply, delay the worker/classifier, and attempt messages scheduled before, at, and after receipt. | Fresh reads see durable protection; neither channel sends while unresolved, including before the worker starts. Sent/touch counters do not advance. | Only pre-existing scheduled messages are blocked, or a queued reply is invisible to sending. |
| AC-05 | The classifier raises on attempt one/two; roll back its failed work, restart with fresh repositories, and retry at controlled times. | Pending protection and retryable event survive; retries retain stable identity/body and current 30s/60s delays. One failing event does not stop unrelated queued work. | Rollback clears protection, a checkpoint destroys the replay payload, or the attempt budget silently changes. |
| AC-06 | Processing recovers before exhaustion on an ordinary reply. Use one baseline-permitted AI continuation and one paused-search continuation. | The normal disposition is applied once; only this reply's guard clears. The permitted response/next touch can proceed under existing timing and policy, without resetting cadence or inventing re-enrollment. | The new guard deadlocks all replies, skips a touch, or blanket-resumes workflows. |
| AC-07 | A non-hard-word reply is classified as an opt-out after a retry; separately return invalid/low-confidence classification. | Classified opt-out records the existing channel restriction/outcome; rejected classification retains the existing immediate review path and no-send outcome. | An unavailable classifier is treated as consent, or a rejected answer is silently treated as success. |
| AC-08 | All three classifier attempts raise; then poll/restart again. Separately fail the exhaustion projection write and recover it. | EXHAUSTED and a durable review/no-send outcome persist; Attention/lead detail show inbound_processing_exhausted and “Reply processing failed after retries” with the context in §3. Visibility recovers without a fourth classifier attempt or duplicate item. | Only logs/generic PAUSED show failure, projection failure hides a terminal row, or exhaustion makes the lead sendable. |
| AC-09 | Read the exhausted reply using each authorized role, an unrelated assigned agent, an inactive member and another workspace. Include an unassigned lead and a known lead without a workflow. Acknowledge the item. | Correct §3 role/tenant visibility; safe failure description and original reply context; no fake workflow. Acknowledgement never resolves the reply, lifts consent, or permits sending. | Cross-tenant disclosure, a fake AI outcome, or “acknowledge” acting as “resume”. |
| AC-10 | Deliver duplicate events before/after processing, and receive two distinct replies while one is still being classified. Complete them out of order. | Stable event/message identity; one replay has no extra business effect. Resolving either reply cannot remove protection belonging to the other. | A shared boolean clears too early, duplicates create multiple review entries, or replay reopens resolved work. |
| AC-11 | An optional CRM write or post-safety enrichment fails after hard-word recognition; inspect persisted state from another session and restart processing. | Restriction/provenance and any still-needed guard remain durable; auxiliary failure is recorded honestly and retry state remains usable. | In-memory assertions pass while the transaction rolls back the opt-out, or CRM availability controls protection. |
| AC-12 | Commit receipt while a due send is approaching its final check; exercise the reverse ordering separately. Delay/reorder Temporal instructions and separately make the guard read fail. | Receipt committed before final dispatch prevents provider invocation; stale instructions or unreadable guard state cannot permit a send. Provider handoff that genuinely started first is reported as in-flight, not claimed recalled. | Race protection is claimed from a single-session fake or from a Temporal instruction alone; read failure is treated as no guard. |
| AC-13 | Resolve an ordinary reply while another manual/review hold, human handoff/ownership, DNC, or terminal state exists; deliver late success after exhaustion. | No unrelated guard or lifecycle protection is removed. Exhaustion stays a review outcome until authorized resolution; no automatic late-success resume. | “AI recovered” overrides human control, clears consent, or restarts a closed workflow. |
| AC-14 | Use healthy unrestricted/no-pending controls on each affected send path; exercise unsupported/unmatched input and repeated CRM refresh after an opt-out. | Valid baseline sends still work, existing input rejection/ignore behavior does not mutate an unrelated lead, and Issue 16 preserves the restriction through refresh. | Blocking every lead passes the suite, identity is guessed, or this PR absorbs new source/fallback rules. |
| AC-15 | Let a standard and paused-search cadence reach the pending-reply guard, then apply a valid normal disposition; separately exhaust processing. | Temporary holding neither ends the execution loop nor advances/completes the unsent step. Allowed continuation uses existing routing; exhaustion remains visibly held even if signal dispatch is delayed. | A safe-looking zero-send result actually kills nurture permanently, spins a tight retry loop, or drops the held touch. |
| AC-16 | Seed pre-existing exhausted replies without protection/visibility, already-applied events and unresolved identities. Dry-run a bounded workspace scope, reconcile it, interrupt/retry and run again. | Dry-run changes no business state; proven unresolved matched replies become protected/visible once, with original references. Already-applied outcomes are not reopened; ambiguous cases are reported, not guessed. Totals reconcile and other workspaces remain untouched. | Recovery sends, enrolls, resumes, reclassifies history, resets original receipt time, or silently treats missing identity as resolved. |

For AC-04/12/14, cover the existing durable standard-cadence dispatch and direct paused-search path
separately, plus AI continuation, deferred send-now and draft approval where they invoke sending.
Guard enforcement is in scope; moving all those journeys to durable dispatch is not.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — approval is required before implementation:**
- **Receipt/application:** current normalized inbound webhook → enqueue/commit → real queued
  processor and inbound use case → repository reads. Use real opt-out/routing logic, not just
  tests of the private keyword function. Add receipt-before-worker coverage (AC-01–08, AC-10–11).
- **Send journeys:** real cadence/continuation/operator entry points and final send/revalidation
  logic with recording SMS/email fakes; set up real pending state through receipt (AC-04/06/12–15).
- **Persistence:** real disposable Postgres, committed ingress, failed processing rollback, fresh
  reads/restarted workers and independent transactions with deterministic barriers. Include
  duplicate claims and multiple replies; single-session fixtures do not prove these claims.
- **Execution:** the existing Temporal workflow test harness plus a local/test engine integration
  for hold/continuation and delayed instructions. Exercise standard and paused-search execution;
  test that a blocked touch is not silently completed or abandoned (AC-12/15).
- **Read surface:** actual lead/review APIs plus frontend Attention mapping/page tests for assigned
  agent and manager views; prove failure reason, reply context, age and permissions (AC-08–09/13).
- **Backlog reconciliation:** bounded dry-run/apply boundary against synthetic histories and real
  persistence, without replaying message-processing side effects (AC-16). This is a proposed
  capability; its callable/command is not claimed to exist at the reviewed baseline.

**Allowed fakes:** CRM/LLM/provider transports, a controllable clock, and hand-written repository
fakes for fast application tests. The LLM fake supplies a response, raises, or waits on a barrier;
the application still decides and persists the business outcome. Inject external failures without
mocking the safety decision, manufacturing a pre-paused workflow, or replacing persistence proof.

### Red → green, one behavior at a time

1. Approve an acceptance case and its expected/forbidden outcomes. Write one behavioral test and
   run it against unchanged application code; record the actual business-assertion failure.
2. For a new guard/read/reconciliation boundary, separately recorded interface/no-op scaffolding is allowed
   to make the test runnable. An import/collection error, absent service, skip, or empty selection
   is not the meaningful red result. Do not implement the behavior in the scaffolding.
3. Make the smallest correction, rerun the same test to green, then take the next scenario. Do not
   build the entire change first and backfill tests. Expected results come from §3–4, not the patch.
4. Baseline behavior controls may pass immediately. If a shared fix makes a later defect test pass,
   establish sensitivity against the baseline or an isolated mutation; do not manufacture a red.
5. In isolated tests, restore classifier-before-keyword ordering, disable the durable guard or its
   final-send check, and disable exhaustion projection separately. Each relevant test must fail for
   its intended business reason; restore the fix and rerun. Never leave mutations in the PR.
6. Inspect changed/deleted assertions independently. Business expectation changes require owner
   approval; “all tests pass” is not acceptance without red/green, sensitivity and integration proof.

| AC / parameterized case | Actual test name + command | Baseline revision + red failure | Fix revision + green result | Sensitivity / baseline control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each row | Exact reproducible invocation | Business assertion, not setup failure | Exit code and pass/fail/skip counts | Disabled protection and observed failure, or justified control | Explicit remaining limitation |

## 6. Engineering starting points — navigation, not a prescribed design

Paths here are repository-relative navigation hints at the stated baseline. Trace their callers
again before edits. Keep provider types and SQL in adapters, policy in domain/application code,
workspace scoping everywhere, and state transitions/audit/outbox writes consistent.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — receipt and processing | app/interfaces/api/v1/webhooks.py; app/application/use_cases/enqueue_inbound_message_event.py; process_inbound_message_event.py and process_queued_inbound_message_events.py in that use-case directory |
| API — saved suppression and refresh | app/application/use_cases/process_contact_suppression_event.py; Issue 16-A's shared preservation/persistence boundary |
| API — partial existing reply check | app/application/services/pre_send_facts.py; app/domain/campaigns/pre_send.py |
| API — sending and revalidation | app/application/use_cases/send_outbound_message.py; revalidate_outbound_send_request.py; dispatch_outbound_send_requests.py; campaign_cadence_execution.py in the same directory |
| API — persistence and workflow instructions | app/infrastructure/persistence/postgres/crm_sync_repository.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/application/use_cases/dispatch_temporal_signals.py |
| API — visible state and review | app/application/use_cases/lead_read.py; review_queue_read.py; lead_review_hold_resolution.py; app/interfaces/api/v1/leads.py |
| Web — Attention/lead display | src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/agentAttentionItems.ts; src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx |

**Simplest sufficient design:** reuse the current event/message records, suppression writer,
workflow/audit conventions and Attention surfaces wherever possible. Do not assume a new hold table,
workflow state, service framework or dependency is needed. Compare reusing existing durable pending
records with an explicit persisted guard before selecting the smallest complete design; obtain the
required design approval. A Temporal signal outbox is an instruction channel, not proof of a
persisted lead-wide hold. Conversely, a hold must not become an unresolvable second source of truth.

The transaction design must protect receipt/consent from failed processing without losing queued
payloads, event claims, or idempotency. Do not hold database locks across LLM/CRM calls. Document the
final send/receipt serialization point and demonstrate it in real persistence tests. Any discovery
that needs broader dispatch repair must be scoped explicitly, not hidden inside this ticket.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_process_inbound_message_event.py
- tests/application/use_cases/test_process_queued_inbound_message_events.py
- tests/application/use_cases/test_send_outbound_message.py
- tests/application/use_cases/test_revalidate_outbound_send_request.py
- tests/application/use_cases/test_dispatch_outbound_send_requests.py
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_send_deferred_outbound_message_now.py
- tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_crm_sync_repository.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/interfaces/api/v1/test_webhooks.py; tests/interfaces/api/v1/test_leads.py

Use Python 3.12/uv: run one exact pytest node, its file, the related suites, then make lint,
make typecheck and make test. Record the actual invocations and selected test counts in the PR.
For web changes, add/update the affected Vitest tests and run pnpm test, pnpm typecheck and pnpm lint.
Confirm test infrastructure targets are local/disposable before running integration tests; skipped
Postgres/Temporal tests are missing evidence, not a pass. No real-lead sends or live fault injection.

## 7. Existing failures, review and recovery boundary

- Deliver a bounded inventory/containment runbook for pending, retryable and exhausted inbound
  events in the affected workspace. Distinguish known lead identity, missing identity, already
  applied outcomes and unresolved replies. Do not infer opt-outs from an arbitrary failed event.
- Deliver the tested bounded reconciliation boundary in AC-16; production execution remains a
  separately authorized operation. Reconcile only proven unresolved, pre-existing exhausted
  replies into the same protected, visible review outcome. Preserve original event IDs/body access controls,
  receipt times, restrictions and audit history; repeat execution must not duplicate review items.
- Previously erased, evidence-backed restrictions belong to Issue 16's recovery. Do not rerun AI
  over old replies and present the new inference as an originally recorded opt-out.
- No bulk replay of the entire inbound pipeline: it may repeat AI replies, handoff acknowledgements,
  CRM writes or other external effects. An individual replay needs explicit scope, idempotency and
  send-safety review. Deployment does not authorize it.
- An exhausted reply stays held until a verified, authorized resolution. Attention acknowledgement
  alone is never that resolution. Document the exact supported review route and operator action;
  if existing controls cannot safely resolve this case, record that limitation and a named follow-up
  rather than advertising a working retry/resume capability or quietly clearing the guard.
- Dry-run reports must make no business-state changes. Production application/recovery requires
  approved environment, workspace/event scope, operator, commands, outcome counts and exclusions.
  Unresolved scope remains contained; do not enable outreach to make a backlog look healthy.

## 8. Production rollout, acceptance and rollback

1. **Before release:** name the operator; review this slice's interim retry/visibility behavior;
   confirm Issue 16 preservation/recovery prerequisites. Inventory queued work and older API/worker
   versions that could accept a reply without a guard or send without checking it.
2. **Rehearse locally/staging:** synthetic SMS/email STOP with unavailable AI; ordinary reply with
   delayed classification; due standard/paused-search touch; permitted continuation; exhaustion
   visible to the right roles. Use sink/sandbox providers and fresh persistence reads.
3. **Deploy in a safe sequence:** record the exact containment and API/worker rollout order.
   Mixed versions must not create an unguarded send window. Schema changes, if justified, need
   compatible migration/rollback plans; a deploy must not bulk resume, re-enroll or replay leads.
4. **Handle the existing backlog separately:** review the bounded dry-run, authorize only its
   explicit targets, verify protection/visibility and retain unresolved exclusions before affected
   sending resumes. If no historical operation is needed, record a complete inventory proving that.
5. **Stakeholder acceptance:** demonstrate that STOP is honored without AI, a waiting reply blocks
   both channels, legitimate processing still reaches its normal outcome, exhausted work appears
   in Attention, and acknowledging it does not restart contact. Show a healthy lead still sends.
6. **Observe:** record guard-bypass attempts, oldest unresolved replies, exhausted/review counts,
   missing review projections, retry failures and blocked workflow progression using safe audit
   metadata. Assign someone to check the queue; this A release does not promise new alert delivery.

**Rollback:** never clear opt-outs, delete reply evidence, or blindly remove guards. Contain affected
sending/receipt processing before reverting to code that can bypass protection. Keep unresolved
replies visible or explicitly assigned to an operator under the containment runbook. Rehearse the
procedure; production rollback and data repair require approval.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4, including the interim three-attempt policy, visible review without
      new exhaustion notifications, unchanged STOP lifecycle, and retained human controls.
- [ ] Issue 16 prerequisite verified; implementer/reviewer assigned; baseline recorded.
- [ ] Reviewer approves §5 boundaries and the first meaningful failing scenario.
- [ ] Durable guard/transaction design approved, including release/resolution semantics and exact
      operator limitations; any additional dependency is explicit, not assumed available.

### Ready to merge
- [ ] All acceptance IDs and relevant send/source combinations map to actual tests/checks, with
      red/green evidence and sensitivity for ordering, durable protection and exhaustion visibility.
- [ ] Real rollback/restart/concurrency and workflow progression checks pass; integration skips
      are not counted as acceptance. Relevant regression, lint/type and frontend checks pass.
- [ ] Independent review confirms no Class B timing, fallback, tag-control or uncertain-send changes.
- [ ] Attention/lead-detail evidence proves correct context and role isolation, including cases
      that cannot be displayed merely by changing a workflow to PAUSED.
- [ ] Runbook specifies safe containment, bounded inventory/reconciliation, review limitations,
      actual commands, rollout and rollback; no unverified retry/resume UI is advertised.
- [ ] Supported resolution is verified, or its limitation and a named follow-up are explicitly
      recorded in the runbook and Attention next-step text before merge. A visibility-only item
      must not misleadingly offer a working retry/resume action.

### Production acceptance complete — not merely merged
- [ ] Required versions deployed; affected backlog verified or explicitly contained; no old writer
      bypasses safety and no unapproved historical replay/send occurred.
- [ ] Sink/sandbox acceptance, operator briefing and bounded observation results recorded.
- [ ] Named operator owns unresolved work and release owner accepts the interim A behavior.
- [ ] Separate Issue 9-B and relevant Issue 13/15 follow-ups remain tracked; parent not declared done.

**Evidence status at drafting:** source/code trace and document validation only. No application
implementation, new behavioral tests, runtime pass, Jira publication, deployment or data operation.

## 10. References and decision precedence

- [Issue 16-A — preservation prerequisite](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Source Issue 9 and the business-impact/readiness appendix](../production-state-consistency-issues.md)
- [Consensus — D1, D4 and D7 release boundaries](../production-state-consistency-review-consensus.md)
- Parent workspace AGENTS.md / CLAUDE.md: product, ownership, layering and design-approval rules.

The parent plan describes the full target, including Class B behavior. This ticket states the
proposed Class A executable scope. If code tracing exposes a conflicting business expectation,
stop that part and ask the owner; do not change expectations to make the implementation pass.