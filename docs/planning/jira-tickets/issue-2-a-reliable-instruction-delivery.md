# Issue 2-A — Make workflow instruction delivery reliable and truthful

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the ninth proposed Jira description, not a published issue or permission to implement.
Approval to continue drafting does not approve implementation, production repair or release.

## 1. Business impact — read this first

**The promise:** When an authorized person pauses or resumes a lead, the platform must retain the
instruction, deliver it to the correct automation when permitted, and report what actually happened.
Starting an engine is not delivering an instruction. Saving a request is not proof it was applied.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | If an instruction finds no running engine, the dispatcher can start one and mark the original instruction sent without sending it again. The delivery record claims success that did not happen. |
| Did the old pause necessarily allow an unsafe message? | No. Most instructions repeat state already saved in Postgres, and send-time checks re-read that state. The confirmed defect is false delivery evidence and lost instruction-specific wake-up behavior; an unsafe send from this branch has not been demonstrated. |
| What changes? | A permitted engine restart retains the original instruction and its identity. Success requires evidence of its actual acceptance; application is reported separately. Failed, exhausted or uncertain delivery remains visible rather than silently successful. |
| What will an operator see immediately? | For example, “Pause recorded; engine instruction queued” or “Resume authorized; waiting for the engine.” The persisted business state and instruction progress are separate facts, not contradictory badges. |
| What does “applied” mean? | The correct workflow processed that logical instruction, including its wake-up/control semantics, with correlated evidence. It does not mean a message was sent, delivered, or is now permitted regardless of other safeguards. |
| What if there is no engine for an already paused lead? | Keep the database pause and show that engine delivery could not be confirmed. Do not create an active engine just to obtain a success badge, undo the pause, or pretend it was delivered. |
| What happens after a retry? | Retry the same still-valid logical instruction. Duplicate delivery must not create extra effects, and an older pause/resume must not override a newer decision. |
| Does recovery restart the campaign from step one? | No. Recover the same eligible business workflow, enrollment, campaign version and progress. A new Temporal execution is not a new campaign enrollment. |
| What can support do about a failure? | Discover the affected lead and instruction, see a safe explanation and retry state, correct the operational cause, and use an approved scoped recovery path. Do not toggle Pause/Resume merely to manufacture another instruction. |
| Are handoffs or contact rules changing? | No. Human hand-back still requires the existing explicit authorization and reason. Consent, reply holds, scheduling holds, quiet hours and send protections remain authoritative. |
| Are new customer messages or alerts included? | No new SMS/email/push notification or contact timer. The required attention is in-product instruction status and actionable operational visibility for unresolved failures. |
| What remains separate? | General detection/recovery of every missing engine, generic background-job dead letters, enrollment accounting/completion, and the Class B CRM/consent/uncertain-send policies. |

**Deployment is not historical repair.** Old SENT rows can include both real deliveries and the
false-success branch. Do not trust all of them, relabel all of them as failures, or resend them all.
Any production inventory/repair requires its own approved scope and current-state validation.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — unreliable operator control evidence and lost wake-ups; confirm at publication |
| Source / delivery class | Production-state consistency Issue 2 / **Class A: reliable instruction delivery and truthful outcomes** |
| Components | Temporal signal outbox/dispatcher; guarded restart and signal adapters/handlers; pause/resume response contract; scoped instruction status, attention and recovery |
| Repositories | miller-schackman-api and miller-schackman-web; one complete operator journey |
| Sequence | Ninth draft, following 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B and 1-A. Draft order is not evidence that any predecessor has shipped. |
| Integration dependencies | Coordinate Issue 7's same-workflow recovery and actual engine identity/lifecycle; preserve 16-A/9-A protections and 1-A's queued-versus-successful scheduling distinction. Respect 17-A's send identities where related wake-ups are exercised. Declare the actual integration baseline. |
| Not a prerequisite | Shipping 14-B, 13-B or 17-B. Do not import their policies into this A repair or revert a B policy already separately released. |
| Related boundaries | Issue 7 owns general missing-engine reconciliation; Issue 15 owns general exhausted background work; Issue 4 owns broader evidence retention. This ticket must still deliver and expose the complete instruction-specific failure/recovery journey. |
| Owners | Name implementer, independent reviewer, Temporal/persistence contract owner, API/web owner and release/recovery operator |
| Reviewed baseline | API a761c1b and web 04d4361, traced 2026-09-05 and independently rechecked 2026-09-07; retrace the implementation branch |
| Closure boundary | Truthful queued/accepted/applied outcomes, retained commands after permitted restart, retry/stale-command safety, scoped discoverability and bounded recovery; not an exactly-once messaging platform |

**Included:** pause/resume and the five instruction kinds already sharing this dispatcher:
PAUSE_REQUESTED, RESUME_REQUESTED, INBOUND_PROCESSED, BLOCKED_REVIEW_COMPLETED and
RESCHEDULE_REQUESTED. Their delivery semantics are in scope; their originating business rules are
not being redesigned. Preserve existing payload-specific effects, including inbound continue versus
block and timing/review wake-ups, in both supported engine modes where applicable.

**Excluded:**
- Automatically restarting paused, human-controlled, suppressed, completed, closed or superseded
  business workflows; creating new enrollments; resetting progress or changing resume permissions.
- General periodic missing-engine scans, completion/cap repair, generic command buses, universal
  dead-letter dashboards, notification engines or a new source of truth for lead sendability.
- Changing opt-out/channel fallback, tag-only CRM control, reply deadlines, provider recovery or
  uncertain-send accounting/callback policies. Preserve the separately approved released baseline.
- Re-running the business action that produced a wake-up, such as sending an approved draft again,
  reprocessing a CRM webhook, reclassifying a reply or reissuing an outbound provider request.
- Bulk replay of historical signals, automatic production data correction, changing retry budgets
  to hide failures, or claiming that pause can retract a provider request already in flight.

**D7:** A and B must not share a PR. These delivery repairs do not authorize a new contact decision.

## 3. Current behavior and contract to approve

### 3.1 What the code does today

Pause and resume use cases record an internal event, validated workflow transition and signal
outbox entry, then commit before returning REQUESTED with signal_queued=True. That boolean is queue
evidence, not engine receipt. Resume eligibility and human hand-back restrictions are distinct from
pause permissions; do not unify them as a convenience.

The shared dispatcher calls the specific signal method. On TemporalWorkflowNotFoundError it checks
the latest locked business workflow, matching workflow/enrollment and restartable state. Today the
restartable set is QUEUED, ACTIVE_NURTURE, WAITING_FOR_RESPONSE and RESPONSE_PROCESSING. A successful
start is followed directly by mark_sent and increased sent_count, without redispatching the entry.
This is the confirmed defect. A pause normally has already persisted PAUSED and therefore does not
qualify for this restart branch; test that protected case separately rather than expecting all pauses
to restart. Ordinary live-target dispatch currently lacks the restart branch's identity/state checks.

The starter uses the stored Temporal workflow ID and preserves campaign version, execution mode and
pinned track during recovery. Its start method returns no application receipt. The signal adapter
awaits Temporal's signal RPC; a successful RPC is not proof that a workflow worker processed the
handler. Handlers mutate in-memory control flags and a snapshot. They do not check a durable logical
instruction ID or authoritative command revision, and snapshot.last_signal is not a per-command
receipt. Current database state matching an instruction is not proof of engine receipt either.

The outbox has PENDING, DISPATCHING, SENT, FAILED and TERMINAL_FAILURE, workspace-scoped enqueue
deduplication, retry availability, attempt_count and claimed_until. Claiming uses row locks with
SKIP LOCKED. These are useful foundations, not end-to-end exactly-once or ordering guarantees:
- Status writes match temporal_signal_id only; claimed_until is not an ownership check on completion.
- The production worker commits after the entire dispatch batch, including external calls. A crash
  before that commit can roll back claims, attempt increments and earlier status writes even though
  Temporal accepted a signal. Such a row can be retryable immediately; it need not wait five minutes
  as a durably committed DISPATCHING row would.
- Enqueue uniqueness does not deduplicate independently repeated Temporal RPCs. Timestamp ordering
  of claim selection is not guaranteed per-workflow processing order across retries/workers.
- Claiming excludes rows at max_attempts, but retryable failures are not thereby converted into a
  surfaced exhausted outcome. A FAILED or expired DISPATCHING row can become permanently unclaimed.

The result counts are not a durable operator-facing delivery view. Existing lead detail/history do
not expose correlated outbox progress. Web pause/resume copy says the workflow “received” the signal
for REQUESTED. ResumeLeadWorkflowResponse and ApproveRejectedDraftReviewResponse in the web client
still expect signal_failure_reason rather than the API's signal_queued. Web handling of RESTARTED
and “from step 1” is not evidence of a current server path: the traced resume use case queues a
signal and does not perform that step-one restart.

Existing dispatcher restart tests assert SENT and a starter call while their signaler always reports
not found. They encode the partial-success bug; keep their useful identity/mode assertions but
replace the false delivery expectation with a behavioral regression. They use application fakes,
not real Postgres or Temporal. The repository retry test covers enqueue deduplication and failed-row
availability; it does not prove crash recovery, expired-lease fencing or handler deduplication.

### 3.2 Use distinct evidence for each stage

The following are **business/API semantics to approve**, not claims that these enum values or
receipt fields already exist. Prefer extending the current outbox and projections over parallel
instruction state. Keep Postgres workflow state as business truth and Temporal as execution truth.

| Stage / outcome | Required evidence and meaning | Must not imply |
| --- | --- | --- |
| Request recorded / queued | The authorized business action, history and original instruction are durably committed and correlated. Return a stable reference usable by a later scoped read. | Engine receipt, handler completion or provider delivery. |
| Dispatch pending / retry scheduled | Original instruction is still unresolved; show whether a retry is actually scheduled, relevant age and a safe failure category. | “Will retry” for exhausted work, or definitively “not received” after an ambiguous RPC. |
| Accepted by engine | Temporal durably accepted this original signal for the validated business workflow/execution. Record correlated acceptance evidence, not just a successful start. | Applied by a worker. If the UI uses “delivered,” explicitly say “delivered to engine; application pending.” |
| Applied / confirmed already applied | Correlated workflow-side processing evidence identifies this logical instruction and execution and its actual result, including the relevant control/wake-up handling. Duplicate receipt refers to the original application. | A future send is guaranteed, every independent block is cleared, or a DB transition alone proves processing. |
| Superseded / no longer applicable | Authoritative workflow/command identity and newer business outcome prove why this instruction must no longer take effect; retain the relationship and reason. | Delivered/applied when it was not, silently dropped work, or permission to apply it to a successor run. |
| Needs attention / cannot deliver or apply | Invalid target/payload, exhausted attempts or another unresolved operational failure has a durable explanation and permitted next step. Separate transport uncertainty from known rejection. | Business workflow completion, removal of a pause, or deletion of its audit record. |
| Historical outcome unverified | Old evidence cannot establish whether the instruction reached/was processed by the engine. Preserve the original record and state the limitation. | Fabricated receipt, inferred failure for every old SENT row, or automatic replay eligibility. |

1. Keep original instruction identity, workspace/lead/business workflow, event/actor/reason and
   payload semantics through recovery. Identify the relevant enrollment, execution and command
   freshness evidence in the approved contract; do not equate a reused Temporal ID with the same
   business run. Any new receipt/version fields or status migration belong to the R1/R2 design.
2. Record timestamps for their actual events. Restart time is not signal acceptance time, and
   acceptance time is not application time. Record safe structured outcomes, not raw exception,
   payload, message, CRM credential or provider-response dumps in UI/logs.
3. Correlated processing evidence is required to claim applied. A specific persisted receipt or
   authoritative workflow execution/history result may establish it; a volatile last-signal string,
   call counter or matching Postgres state cannot. Define retention and lost/delayed-evidence recovery.
4. Accepted-but-not-yet-processed work remains inspectable. A stopped/failing worker must not leave
   a permanent apparent application success. Expose age/application-pending and a bounded operational
   attention rule agreed at R3; lack of a timely receipt is not proof the signal was never accepted.
5. Do not delay saving a safety pause until Temporal is available. Preserve atomic action/event/
   outbox commitment and report partial progress honestly. Failure to persist the intent must not
   return queued success; a delivery failure after commit must not roll back the business decision.

### 3.3 Recover the correct engine and retain the original instruction

1. Validate the target business workflow and still-applicable instruction before delivery, not only
   after not-found. Retain workspace/lead/workflow/enrollment identity checks and current safety state.
   A current business workflow can have a replacement Temporal execution; an old business workflow
   must not gain authority over a new enrollment merely because the lead or Temporal ID matches.
2. On not-found, use the existing bounded same-workflow restart eligibility. Re-read current facts
   under the approved locking/version contract and preserve the actual campaign version, execution
   mode, pinned track and recorded progress. Starting a new business journey is not recovery here.
3. After a permitted start, deliver the retained original instruction and obtain real acceptance
   evidence. Do not substitute a generic reschedule for a pause, resume, unblock or inbound decision.
   If start succeeds but delivery fails/has an uncertain outcome, keep the instruction unresolved
   with accurate restart-versus-delivery evidence and use the same safe retry/reconciliation path.
4. Handle concurrent starts and “already running” without starting duplicates, assuming success or
   dropping the instruction. Verify that the running target belongs to this permitted business
   workflow, then deliver/reconcile the original command. Repeated not-found/start races must be
   bounded by the approved retry contract, not an inner infinite loop.
5. If the business workflow is PAUSED, human-controlled, suppressed, terminal, replaced, missing or
   mismatched, do not widen restart eligibility. A still-relevant undeliverable pause/handoff needs
   honest attention while its persisted restriction stays in force. An actually obsolete instruction
   can be explicitly superseded using evidence; “the DB is paused” alone is not a delivery receipt.
6. Validate payloads and signal-specific requirements. Malformed/unsupported work must not start an
   engine, mark success or permanently stop unrelated entries from progressing. Preserve safe error
   evidence and distinguish an invalid command from a transient transport failure.
7. Engine startup and handler scheduling can race. Exercise delivery before/during initial
   scheduling and a target closing between validation and delivery. The original signal must not
   be lost to initialization, overwritten by a stale activity result or accepted as applied after
   its intended execution has ended. A signal-with-start design still needs these guarantees.

### 3.4 Make retries safe without changing business policy

1. Treat delivery as at-least-once. Retain a stable logical instruction identity across outbox,
   adapter, handler and receipt; duplicate processing must be harmless and auditable, including after
   an accepted RPC whose response/DB commit is lost. Do not assume Temporal deduplicates separate
   application sends merely because their signal names or payloads match.
2. Approve a command freshness/supersession matrix for each signal kind. Older pause after newer
   resume must not stall the current journey; older resume/unblock after newer pause, reply hold,
   handoff or suppression must not release it. Check at processing as well as dispatch so an already
   in-flight old signal cannot win later. Business ordering needs authoritative identity/revision,
   not only wall-clock timestamps, lexical UUID order, SELECT ordering or retry count.
3. Do not drop every older signal by age: an inbound event, review result or timing wake-up can
   still carry distinct necessary work. Define when it is applied, idempotently already applied,
   reconciled against current facts or explicitly superseded. Preserve event-specific evidence and
   the latest legitimate control decision without replaying its originating business side effects.
4. Respect actual transaction boundaries. If using short durable claims before network I/O,
   implement and test ownership-fenced outcome writes and expired-claim recovery; a stale worker
   cannot overwrite a newer receipt/failure/supersession. If retaining a lock-held transaction,
   prove crash rollback/re-delivery and bounded lock duration honestly. Do not claim lease durability
   from an uncommitted row, or add a receipt activity that deadlocks on a dispatcher-held DB lock.
5. Persist attempt/retry outcomes according to the approved lifecycle and preserve existing retry
   budget/backoff values unless separately approved. At exhaustion, both final failure and abandoned
   final claim must become explicit non-retrying attention outcomes. Do not leave “retry scheduled”
   on a row the selector will never claim. One bad entry must not erase evidence for unrelated work.
6. Repeated API requests/lost responses must recover the original logical action or report the
   already-current/stale result; do not create contradictory actions or target a newer run. Current
   external-event enqueue deduplication alone is not an HTTP retry identity contract. Approve the
   narrow request/reference mechanism at R1/R3 and test it without broad command-framework work.
7. Retrying an instruction never re-sends an uncertain/accepted message, approves a draft twice,
   consumes another occurrence, restarts a cadence or reclassifies a reply. Message submission and
   instruction delivery have different uncertainty rules; this ticket does not change the former.
8. Subsequent planning/sending still reads the current workflow and existing restrictions. Preserve
   proper future waits and allow a genuinely eligible due touch through the normal send path once.
   A queued/accepted resume is not a blanket permission to send or a reason to bypass an unresolved
   scheduling/reply/human hold. Do not solve retry safety by disabling all resumes or all nurture.

### 3.5 Complete the operator journey and narrow recovery path

- **Request:** Correct pause/resume API/client types and toast copy. Show the committed business
  outcome alongside instruction progress. “Paused in the database; engine delivery pending” is
  truthful; “workflow received the signal” from REQUESTED alone is not. Do not reuse “restarted from
  step 1” for same-workflow engine recovery. Audit every affected shared consumer, including the
  rejected-draft approval response; fixing delivery evidence must not approve/send the draft again.
- **Inspect:** Authorized lead detail/history must show instruction kind/reference, requested time,
  business workflow, delivery/application status, retry availability or attention reason, relevant
  restart/receipt evidence and current next step. Distinguish current instructions from prior runs.
  A refresh must retain this information; an ephemeral response or toast is not sufficient.
- **Discover:** Surface actionable failed/exhausted and operationally overdue instructions in the
  existing attention experience, with a path to the matching lead/command. Ordinary queued work
  need not create an alert on every retry. Correlate one issue per logical instruction/attention
  episode and do not double-count projections or hide separate unresolved problems on that lead.
- **Scope:** Reuse existing lead-view and action permissions. Assigned agents see their permitted
  leads and an accessible explanation/escalation route; wider operators retain only their existing
  workspace scope, including unowned leads. Recovery privileges need separate explicit approval;
  seeing an error does not grant manager-only hand-back rights or worker/service-role access.
- **Read correctly:** Filter by workspace/ownership/lead/status before paging, with complete traversal
  and declared count semantics. Test a relevant instruction beyond unrelated first-page rows. Seen
  is acknowledgement, not delivery/resolution; unresolved seen items remain discoverable. Distinguish
  loading, empty, permission failure, unavailable engine evidence and failed reads from success.
- **Recover:** Provide a tested, narrowly authorized action or supported operator procedure for the
  same unresolved instruction after correcting its operational cause. It must revalidate current
  target/command applicability, preserve identity and audit actor/reason, bound retries and show the
  subsequent result. No blind status reset, bulk replay, manufactured new resume, or automatic
  clearing of business restrictions. An invalid original payload cannot be silently rewritten;
  approve a traceable correction/superseding instruction when necessary.
- **Refresh:** Refetch affected detail/instruction/attention data after requests and recovery. Show
  accepted-but-pending application and failed action results honestly. Use existing query patterns;
  no new live-push guarantee or arbitrary polling system is implied. A failed read must not erase
  the last known unresolved issue or render “nothing needs attention.”

### 3.6 Remaining implementation and release gates

These gates settle mechanics and evidence, not the already-decided A/B contact policies.

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Instruction identity and truthful evidence | Approve exact queued/accepted/applied/superseded/attention mapping; logical request/command identity, execution correlation, per-kind freshness rules, receipt durability/retention and proposed additive schema/payload/status changes. Existing SENT cannot be treated as universal proof. | Outbox/handler/API-contract implementation |
| R2 — Recovery, transaction and Temporal contract | Approve guarded restart versus atomic delivery approach, claim/commit/ownership fencing, duplicate and ambiguous-RPC recovery, attempt-count durability and repeated-crash bounds, final-attempt handling, startup/in-flight command races, supported SDK behavior and running-history/old-payload compatibility. Identify concrete Issue 7 dependencies without widening restart policy. | Dispatcher/worker/engine implementation and integrated acceptance |
| R3 — Operator and scoped recovery contract | Approve own-agent/wider-role read/action matrix, API/client copy and command reference, attention aging without a contact deadline, pagination/count/seen behavior, safe diagnostic fields and permitted bounded retry/escalation procedure. | API/UI/recovery implementation |
| R4 — Rollout and historical evidence | Name release/operator owners; approve producer/API/web/worker/migration order, old-worker containment, historical inventory and separately authorized repair, monitoring, regression commands and evidence-preserving rollback. | Production rollout/live acceptance |

Approve the applicable gates and §4–5 test boundaries before implementation. A design may be
simplified, but no unresolved gate may be closed by weakening the promised observable behavior.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic data, fixed clocks,
recording transports and real local/disposable integrations where the claim requires them.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A current restart-eligible workflow has a queued resume/wake-up and its Temporal execution is missing; dispatch it. | Same business journey is recovered; the original instruction reaches the actual target and has correlated acceptance/processing evidence. Restart and delivery outcomes are separate. | Start alone marks SENT/applied, signal discarded, or indirect DB reconstruction used as receipt proof. |
| AC-02 | Request authorized pause while the dispatcher is stopped; fail enqueue/commit separately. | Successful commit saves pause, history and one queued instruction; fresh reads/copy say delivery pending. Persistence failure produces no queued-success or partial committed action. | Pause waits for Temporal availability, falsely reported receipt, or state saved without recoverable instruction. |
| AC-03 | Request a permitted resume/hand-back on a live workflow, then dispatch/process it. | Committed resume is initially queued, then accepted and applied with evidence; current permissions/reason/safeguards remain. Future scheduled work still waits. | API success presented as handler completion or hand-back permission widened. |
| AC-04 | Parameterize all five outbox signal kinds and applicable standard/recurring modes, including inbound continue/block and review/timing payloads, on live and permitted recovered engines. | Exact original payload meaning, target, pinned version and mode survive. Observe the intended workflow control/wake-up outcome and truthful status. | Replacing every signal with reschedule, losing inbound decision/actor/event context, or fixing only one signal kind. |
| AC-05 | Start succeeds but the retained signal is rejected, times out, or finds the target closed; later recover. | Restart evidence remains distinct; no unsupported acceptance/application claim, bounded retry/reconciliation of the same command, eventual observable outcome. | Restart success consumes the instruction or uncertainty is asserted to be definite non-delivery. |
| AC-06 | Start fails transiently; repeat with no configured restart dependency, missing enrollment, wrong enrollment or a non-restartable state. | Transient work follows retry policy; unavailable/invalid recovery stays actionable or is evidenced as superseded. No false SENT or unauthorized engine start. | Missing dependency silently turns into success, unlimited restart loop, or retries manufacture an enrollment. |
| AC-07 | Pause is committed to PAUSED while the engine is missing; repeat for human-owned/handoff, suppressed, completed and closed states. | No widened restart eligibility or active-engine creation; restrictions remain and delivery is honestly unresolved/not applicable according to evidence. | Resuming/starting protected work to make pause delivery pass, or claiming DB pause proves handler receipt. |
| AC-08 | An instruction belongs to an older business workflow/enrollment; its old Temporal ID is live, missing or reused by a successor. | Validate before both normal dispatch and restart; old work cannot affect the successor. Retain explicit obsolete/mismatch evidence and history. | Guard only the not-found path or route an old instruction to whichever workflow is latest for the lead. |
| AC-09 | Race two recoveries and an independent start; receive already-running and repeated not-found outcomes. | At most one intended live execution; validate target identity and retain/deliver original command with bounded attempts. | Already-running counted as signal success, two business journeys, or unbounded start/signal loops. |
| AC-10 | Invalid/unsupported signal payload is next to a valid entry. | Invalid entry has safe actionable evidence and no engine start; valid work can progress with independently retained outcome. | Crash loop, raw sensitive payload shown, or failure rolls back/loses all unrelated delivery evidence. |
| AC-11 | Fail delivery transiently, advance a fixed clock around retry availability, then succeed within the existing budget. | Only eligible attempts occur; accurate attempt/next-retry status and original identity persist; acceptance/processing result remains truthful. | Ignored backoff, budget reset, duplicate business effects or “applied” before receipt. |
| AC-12 | Reach the final allowed failure; separately abandon a final DISPATCHING claim and let its lease expire. | Both become durable, discoverable, non-retrying attention outcomes under the approved lifecycle, with recovery guidance. | Permanently excluded FAILED/DISPATCHING row still says a retry will occur, or increasing max_attempts hides exhaustion. |
| AC-13 | Crash before/after claim commit, after start, and before/after signal acceptance/status commit; read from independent DB sessions. | Actual persisted boundaries match the design; pending/claimed/accepted uncertainty recovers without losing the instruction or inventing evidence. | Fake-only durability proof, assumed five-minute delay after a rolled-back claim, or lost earlier batch outcomes. |
| AC-14 | Temporal accepts the signal but its response or DB outcome commit is lost; retry and replay the workflow. | Stable logical identity, harmless duplicate handling and correlated receipt recovery; no extra business transition, touch or provider submission. | Treating equal payloads as automatic Temporal deduplication, or accepting a call-count-only test as proof. |
| AC-15 | Two independent dispatchers contend; a claim expires and an older worker later reports success/failure. | Claim/outcome ownership and monotonic evidence are protected by the approved real transaction/fencing design. | Stale worker overwrites newer acceptance/application/supersession or both mint unrelated commands. |
| AC-16 | Pause → resume → pause occur on the same workflow; delay/reorder/duplicate their signals, including one already accepted but not processed. | Current authoritative decision wins; older resume cannot release the new pause and older pause cannot strand a valid later resume. Explicit supersession/processing audit. | Wall-clock/claim-order-only protection or last arriving signal blindly sets engine flags. |
| AC-17 | While resume/unblock is pending, persist a newer reply hold, scheduling hold, human handoff, suppression, terminal decision or workflow replacement. | Later protection remains authoritative through dispatch, processing and send checks; obsolete work cannot release it. | Delivery retry clears an independent hold or resurrects a terminal/successor journey. |
| AC-18 | Lose the pause/resume HTTP response and repeat that logical request; also replay it from an old tab after a newer control decision. | Return/recover original command or truthful already-current/stale result; no duplicate transition or contradictory new command affecting the newer state. | New external-event UUID on every retry treated as sufficient request idempotency. |
| AC-19 | Temporal accepts a signal while no worker is processing tasks, or a handler repeatedly fails. | Accepted/application-pending remains distinct and inspectable; agreed operational age/failure attention appears without falsely asserting non-acceptance. | Successful RPC hides an unapplied instruction permanently or timeout invents a provider-delivery failure. |
| AC-20 | Receive late/duplicate processing evidence and evidence from the wrong command, run or workspace; separately make DB state match without any signal. | Only correctly correlated evidence can establish applied; repeated receipt is harmless, mismatch rejected and ambiguous history stays explicit. | last_signal/current DB state or another execution's receipt closes this instruction. |
| AC-21 | Recover a current workflow after earlier completed touches, with a future next action and pinned track/campaign version. | Same enrollment/progress/claims remain; correct future scheduling and instruction wake-up, no immediate provider call. | Step-one reset, invented track switch, touch consumed by recovery or send at restart time. |
| AC-22 | An otherwise permitted due touch follows successful resume/recovery; redeliver the instruction around it and exercise already-claimed/uncertain message controls. | One intended test-provider submission for the fresh touch; existing claims and uncertainty policy prevent resubmission, and subsequent legitimate progress still works. | Extra send from instruction retry, refunded/duplicated touch, or all resumes disabled to satisfy no-send cases. |
| AC-23 | Deliver necessary inbound/review/timing wake-ups after unrelated newer events, including duplicate handoff/review notifications. | Approved per-kind freshness rules retain necessary signal-specific work or explicitly justify supersession; no repeat send, reply classification or originating business action. | Blanket age filter discards necessary wake-ups, every signal becomes resume, or human-control rules change. |
| AC-24 | Read/act as owning agent, unrelated agent, wider permitted role, inactive member and other workspace; include unowned lead. | Only authorized detail/attention/evidence/action access; own-agent navigation is usable without granting privileged recovery/hand-back. | Cross-tenant information/count leakage, raw service-role repository exposed, or wider role granted to fix a route. |
| AC-25 | Put relevant unresolved instructions beyond the first page of unrelated rows; mark seen, retry unchanged, then resolve or create a new failure episode. | Scope-before-pagination, complete traversal, declared counts, no duplicate projection; seen never resolves and a new issue remains actionable. | Empty filtered first page claims no work, endless per-attempt duplicate alerts, or seen hides unresolved work everywhere. |
| AC-26 | Exercise real API response shapes in web tests: request queued, accepted, applied, rejected, exhausted, unavailable reads and same-journey engine restart. | Truthful copy/types and distinct loading/empty/error states; refetch retains instruction progress. No “received” from REQUESTED or “from step 1” for this recovery. | Fixture-only obsolete signal_failure_reason contract or a failed read rendered healthy. |
| AC-27 | Correct an operational failure and use the approved narrow recovery path; race it with new pause/ownership/workflow changes and repeat the action. | Current permission/applicability checks, original logical identity, bounded attempts, actor/reason audit and fresh visible outcome. Invalid/obsolete work is not blindly retried. | Unconditional status reset, new generic resume to repair delivery, or duplicate underlying provider request. |
| AC-28 | Inventory synthetic historical SENT rows with real acceptance, false-start success and insufficient evidence, alongside pending/exhausted/superseded work. | Evidence-based classifications and an idempotent scoped recovery rehearsal; preserve uncertainty and original audit. | All SENT treated as verified or failed, fabricated timestamps/receipts, or bulk historical replay. |
| AC-29 | Deliver around workflow initialization/first activity and run representative old/new payloads, worker versions and history replay in both modes. | Original instruction's effects survive initialization and stale results; compatible histories and explicit unsupported evidence handling. | Startup assertion/lost flag ignored, old worker falsely claims new receipt semantics, or resetting all workflows substitutes for compatibility. |
| AC-30 | Pause races with a future timer and with the final pre-send/provider boundary. | Current DB checks stop eligible-to-block work; explain any irreversible in-flight boundary accurately, without extra sends or erased audit. | Claiming all already-submitted messages are cancelled, or removing DB checks because a signal was accepted. |
| AC-31 | Demonstrate request → durable queue → missing-target recovery → real signal processing → fresh API/UI status, plus delivery failure and scoped operator recovery. | Complete synthetic journey with real Postgres/Temporal evidence and an API-to-UI demonstration; each stage is supported by its own evidence. | Mocked starter/signaler success plus static UI fixtures presented as end-to-end acceptance. |
| AC-32 | Run ordinary nurture and safety regressions on the declared release baseline, including consent, replies, handoff, scheduling and existing uncertainty/CRM behavior. | Working sends and independent safeguards preserved; no Class B policy introduced or reverted. | New fallback/tag/reply-timeout/uncertain-as-sent behavior hidden in this delivery PR. |

AC-28 is a recovery-runbook rehearsal, not approval for production writes. AC-22's once-only
assertion concerns the identified local test touch and known failure model, not provider-wide
exactly-once delivery. Skipped integration scenarios remain missing evidence.

**Transaction-sensitive cases (AC-12–15):** Agree applicability at R2 against the production worker's
actual commit points. An abandoned-lease case requires a genuinely committed DISPATCHING row,
not just an in-memory fake. If a lock-held design cannot produce that state, prove the exclusion
with independent sessions, cover rollback/re-delivery instead, and retain explicit handling of any
supported legacy durable claims. Across repeated pre-commit crashes, compare persisted attempt_count
with recorded transport attempts; rolled-back increments are not consumed retries or proof of a
network-attempt ceiling. Verify bounded recovery/overdue attention without hiding lost retry evidence.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Authorized action → durable instruction and fresh read:** pause/resume APIs/use cases with real
  permission/transition logic, saved command identity and truthful action response (AC-02–03/18/24/26).
- **Instruction dispatch → actual acceptance/processing:** dispatcher and supported signal/starter
  ports, then real Temporal handler/execution behavior. Observe original payload meaning, control
  outcome and correlated evidence, not only starter/signaler invocation counts (AC-01/04–09/14/16–23).
- **Persistence/lifecycle:** real local Postgres, migrations, independent sessions and worker commit
  boundaries for uniqueness, claim ownership, rollback, final-attempt recovery, scoped reads and
  receipt updates. Repository assertions are appropriate for agreed persistence invariants
  (AC-02/08–18/20/24–25/27–28).
- **Durable execution:** actual Temporal test environment and replay; run real business activities
  where state reconstruction, timing, send guards or stale results are the claim. Include startup,
  delayed processing, duplicate commands, supported old payloads and both modes (AC-01/14–23/29–31).
- **Operator journey:** existing frontend route/API/helper tests plus synthetic API-to-UI acceptance
  for detail/attention, permissions, recovery, truthful feedback and paging. Do not introduce a new
  browser or dependency project merely for this ticket (AC-24–28/31).
- **Business-flow protection:** recording CRM/LLM/provider transports, current state transitions,
  send identities and ordinary due/future-send controls (AC-03–04/07/16–18/21–23/30/32).

**Allowed fakes:** external transports, fixed clocks and hand-written repository fakes for fast
application cases. A scripted not-found-then-accepting transport is useful for the first regression;
it does not prove actual Temporal acceptance, ordering, handler processing or database atomicity.
Do not mock the permission, freshness, restart-eligibility or deduplication rule being tested.
Expected payloads, statuses and command ordering come from approved literal scenarios, not from
calling the production decision helper again.

1. Begin with AC-01 at the agreed dispatcher boundary: write/run a meaningful failing test on the
   unchanged baseline showing that successful start does not deliver the original instruction.
   Include the start-success/second-delivery-failure case as its own next slice. Preserve useful
   existing identity assertions; do not keep the current “always not found but SENT” expectation.
2. One scenario → meaningful red → smallest complete repair → same test green. Continue vertically;
   do not implement the full redesign and retrofit tests or write all speculative tests first.
3. Missing service/import/new enum, setup failure, skipped test and fabricated fake success are not
   meaningful red evidence. Minimal seam scaffolding may be needed; record it separately. Existing
   controls can already pass; scenarios fixed incidentally require sensitivity evidence, not fake red.
4. Independently restore SENT-on-start; strip the original payload; permit a stale resume; remove
   duplicate/claim ownership protection; orphan the final attempt; accept a wrong-command receipt;
   render REQUESTED as received; restore limit-before-scope. Each critical protection must fail for
   its intended reason when broken. Restore the repair and rerun; no mutation ships.
5. Independently review expectations and the integration boundary. Do not relax a test because the
   handler “probably reconstructs from Postgres,” a second RPC is awkward, or the UI cannot read
   the evidence yet. Escalate genuinely ambiguous semantics rather than changing policy to pass.
6. Record exact commands, revisions, exit codes, pass/fail/skip counts and limitations for every
   applicable case. Fake-only application tests never substitute for required Postgres/Temporal proof.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills every applicable case | Reproducible invocation | Business assertion and revision | Revision, exit code and counts | Observed protection failure or justified passing baseline | Named remaining limitation |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are repository-relative within the named API/web repository at the reviewed baseline. They
are navigation hints, not a claim the proposed receipt, scoped reader or repair action exists.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — command producers and action boundary | app/application/use_cases/lead_pause.py; app/application/use_cases/lead_resume.py; app/interfaces/api/v1/leads.py; app/interfaces/api/schemas/leads.py |
| API — outbox lifecycle and contracts | app/domain/workflows/temporal_signal_outbox.py; app/application/ports/repositories.py; app/application/ports/temporal.py |
| API — dispatcher and production transaction | app/application/use_cases/dispatch_temporal_signals.py; app/interfaces/workers/temporal_signal_dispatcher_worker.py; app/application/services/retry_backoff.py |
| API — persistence and initial schema | app/infrastructure/persistence/postgres/temporal_signal_outbox_repository.py; app/infrastructure/persistence/postgres/models.py; alembic/versions/0036_create_temporal_signal_outbox.py |
| API — engine adapter, handlers and activities | app/infrastructure/workflows/temporal/starter.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/activities.py |
| API — shared inbound/review/reschedule producers | app/application/use_cases/process_inbound_message_event.py; app/application/use_cases/lead_draft_review.py; app/application/use_cases/paused_search_operations.py; app/application/services/lead_nurture_rescheduling.py |
| API — other safety/dispatch wake-ups to inventory | app/application/use_cases/process_contact_suppression_event.py; app/application/use_cases/dispatch_outbound_send_requests.py; app/application/use_cases/process_provider_delivery_callback.py; app/application/services/paused_search_track_assignment.py |
| API — business state and read authorization | app/domain/workflows/models.py; app/application/use_cases/apply_workflow_state_transition.py; app/application/use_cases/lead_read.py; app/application/ports/lead_read.py; app/domain/identity/permissions.py |
| Web — action/read contract and detail | src/lib/api/leads.ts; src/pages/LeadDetailPage.tsx; src/pages/HandoffDetailPage.tsx |
| Web — existing attention/presentation | src/pages/AttentionPage.tsx; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/leadPresentation.ts |

**Compare at least two approaches before coding:**
- **Recommended starting point: extend the existing outbox with guarded recover-then-deliver and
  correlated processing evidence.** Reuses current ports/producers and makes stages explicit;
  requires deliberate claim/commit, freshness, receipt and startup-race handling. Keep scoped reads
  indexed and avoid long network work or receipt deadlocks under DB locks. A second signal call alone
  is not the whole design. Choose the smallest evidence mechanism that satisfies §3.2.
- **Alternative: validated atomic signal-with-start for eligible targets, plus the same logical
  command/evidence contract.** Can reduce the start-versus-signal race and extra network round trip,
  but requires verified installed-SDK support, explicit ID conflict/reuse handling, startup-safe
  handlers and running-history compatibility. Never let it create an engine for a protected business
  workflow. Atomic transport still does not prove application or solve stale/duplicate commands.

Neither approach permits a general command bus, calling a starter “delivery,” or widening restart
policy. Obtain design approval before coding. Keep Temporal/SQL vendor details in adapters and
wire the agreed contract through every production caller; optional dependencies must not silently
retain the false-success path. Use additive approved migrations, not edits to historical migrations.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_dispatch_temporal_signals.py
- tests/application/use_cases/test_lead_pause.py; tests/application/use_cases/test_lead_resume.py
- tests/application/use_cases/test_lead_paused_search.py; tests/application/use_cases/test_paused_search_operations.py
- tests/application/use_cases/test_business_flow_harness.py; tests/application/use_cases/test_lead_read.py
- tests/infrastructure/persistence/postgres/test_temporal_signal_outbox_repository.py
- tests/infrastructure/test_temporal_starter.py; tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_postgres_e2e.py
- tests/interfaces/api/v1/test_leads.py
- Web: src/app/LeadsRoutes.test.tsx; src/app/HandoffDetailPage.test.tsx; src/app/AdminOperationsRoutes.test.tsx

Locate/add the exact worker crash, scoped instruction-read and command receipt tests after boundary
approval. Use Python 3.12/uv: one exact pytest node, its file, related suites, then make lint,
make typecheck and make test. For web changes run focused Vitest tests, then pnpm test, pnpm
typecheck and pnpm lint. Record integration targets and skips; local/disposable services and
recording sends only. No real-customer traffic is authorized by this draft.

## 7. Existing affected records and bounded recovery

- Deliver an instruction-specific dry-run inventory/runbook: pending/retryable, leased, exhausted,
  invalid/terminal-failure, accepted/application-pending, actually superseded, and historical SENT
  with verified or insufficient evidence. Distinguish business workflow from Temporal execution.
- Match available command/event/workflow/history evidence, current enrollment/progress and current
  restrictions before proposing repair. Missing evidence must remain explicit; preserve original
  recorded status/time with a linked correction rather than inventing when a handler ran.
- An old instruction can now be harmful or obsolete. Never bulk replay all SENT/FAILED entries,
  copy them to the latest workflow, reset all attempt counts, change paused state or delete claims.
  Ambiguous provider-message effects remain protected by their separate send identity/uncertainty
  contract; signal recovery is not permission to resend the message.
- Any approved replay/recovery is bounded to identified still-applicable commands, rechecks current
  authority/identity, retains logical idempotency and records the operator/reason and actual new
  attempt/evidence time. Rehearse duplicate execution and supersession on synthetic data first.
- No new production repair command is claimed to exist. If the selected narrow procedure requires
  one, approve its public boundary, dry-run, permissions, transaction behavior and tests before use.
  Do not tell operators to repair this via undocumented direct database updates or pause/resume spam.
- Production mutation needs separate environment/workspace/lead/command scope, operator, exact
  procedure, limits and verification approval. Report safe counts and necessary identifiers only;
  exclude raw payloads, message/contact content, credentials and unredacted transport errors.
- Live acceptance requires verified recovery of applicable in-scope work or explicit containment
  with a named follow-up owner. Neither deployment nor relabeling old SENT as unverified delivers
  an instruction that was never received. General missing-engine reconciliation remains Issue 7.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test-contract gates, name owners and inventory actual
   API/web/producer/dispatcher/Temporal versions and dependencies. Record separately shipped A/B
   changes. This repair does not authorize new outreach policy or broad infrastructure migration.
2. **Safe rehearsal:** run the AC-31 journey plus start-success/signal-failure, paused missing target,
   stale resume, lost acceptance response, final-attempt abandonment, pagination/permission failure
   and old-history replay. Use real disposable integrations and recording providers.
3. **Compatible deployment:** approve additive schema and producer/consumer order. Old dispatchers
   can still mark start as SENT and old handlers cannot supply new receipts/freshness behavior;
   contain/drain incompatible versions before claiming the contract live. Do not silently interpret
   absent old fields as proof of acceptance/application or blanket-reset long-running workflows.
4. **Historical handling:** execute only separately approved §7 procedures and verify scoped fresh
   evidence. Report recovered, superseded, still-unverified and separately blocked commands. Keep
   existing pauses, human ownership and message/occurrence claims intact.
5. **Operator acceptance:** demonstrate recorded versus queued versus accepted versus applied,
   actionable failure, authorized recovery and the current business state. Explain that a visible
   failure can coexist with a safely persisted pause, and engine recovery never means step-one restart.
6. **Observe:** safe counts/age by queued, retrying, exhausted, accepted-awaiting-processing and
   superseded outcome, restart without delivery, duplicate/stale rejection and receipt failures.
   Separate engine acceptance metrics from applied-command and customer-message metrics. Wire
   durable outcomes/readability; unused dispatcher result counters alone are not operational proof.

**Rollback:** contain incompatible dispatchers/recovery actions first. Preserve original instructions,
claims, business state/history and receipt/supersession evidence; do not turn unresolved work into
SENT or restore the old “received” UI. An older handler may not understand newer payload/freshness
semantics. Document a compatible rollback/forward-fix path with continued status access and bounded
retry handling; do not drop new evidence/constraints or replay all commands to make old code run.
Any production rollback mutation needs the same scope and approval discipline as recovery.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact, unchanged behavior and Class A boundary; applicable
  R1–R4 and §4–5 test boundaries are closed with named owners before their implementation/release.
- [ ] Original instruction survives permitted restart; acceptance and application are separately
  evidenced, with protected/no-target and superseded outcomes reported honestly.
- [ ] Duplicate, stale/in-flight, crash, concurrent-claim and exhausted work have tested durable
  outcomes without weakening existing send/resume restrictions or resetting progress.
- [ ] Authorized users can request, discover, inspect and recover the instruction through the
  approved API/UI/operator path; scoped paging/counts, feedback and error/seen behavior are correct.
- [ ] Each applicable acceptance case has meaningful red/green or unchanged-control/sensitivity
  evidence and exact commands. Required real Postgres/Temporal and API-to-UI proof is attached;
  missing/skipped integrations are blockers to the corresponding claim, not passing evidence.
- [ ] Release/history/rollback rehearsal and separately authorized recovery or containment are
  documented. No bulk replay, secret/raw-payload leakage or customer send was used for validation.
- [ ] Independent review confirms unchanged policy and no new source of truth or unnecessary
  framework. A/B changes are not mixed in a PR; merged code and accepted-live outcome are distinct.

## 10. Source references and review record

- [Main issue plan — Issue 2 and its business-impact appendix](../production-state-consistency-issues.md)
- [D1–D7 consensus and ship-class gate](../production-state-consistency-review-consensus.md)
- [Issue 1-A — visible scheduling holds and queued recovery boundary](issue-1-a-visible-scheduling-holds.md)
- [Issue 9-A — existing reply and opt-out safety](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 16-A — durable opt-out preservation](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 17-A — separate outbound-dispatch durability](issue-17-a-durable-outbound-dispatch.md)

**Draft review (2026-09-07):** Independent product/safety reader and technical/test-contract reviews
found no material blockers to stakeholder review. Clarifications name the shared draft-approval
client mismatch and distinguish real committed-claim tests from rollback/attempt-count evidence.
Document/reference checks passed with exit code 0: 52 source/test paths, all draft/index links,
table/whitespace checks, AC-01–32, ten main sections, four gates and nine indexed drafts. The prior
eight drafts match their recorded aggregate SHA-256 baseline; API/web worktrees remain clean.
These reviews do not close R1–R4 or approve implementation/publication. No application code or
earlier ticket draft was changed, and no behavioral tests, production recovery or release ran as
part of this draft review. Implementation and integrated acceptance evidence remains outstanding.