# Issue 10-A — Show when automation gives up after repeated system errors

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the sixteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not authorize production access, historical repair, sends or release.

## 1. Business impact — read this first

**The promise:** When automation cannot complete a required step after its existing allowed attempts,
the lead no longer looks healthy while receiving no follow-up. The application records an actionable
system-error hold with a safe reason and retained history. An authorized operator can correct or
escalate the cause, then use the permitted recovery path without restarting the campaign or sending
the same message again. If the outage also prevents recording, an independent check finds the
stranded work after service recovery; the failed engine is not its own only witness.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | A scheduling or sending activity can exhaust its retries and fail the engine execution. There is no failure handler that records that exhaustion against the lead; the application can keep displaying the last healthy-looking state. |
| What changes for agents? | Lead detail and Attention explain that nurture is blocked by a system problem, which journey is affected, when the problem was observed and what the permitted next action is. Existing protected states keep their own meaning and ownership. |
| Does every temporary error need human intervention? | No. Normal bounded retries remain. A transient error that recovers within those attempts continues normally; this ticket handles the final failure, not each intermediate attempt as a new review item. |
| Is this the same as a rejected or uncertain message? | No. A failed automation activity does not prove that its provider call failed or never happened. Message outcome, send claim and engine failure are distinct facts. |
| Can the system just retry until it works? | No. Exhaustion must not be hidden by an unlimited outer loop, repeated engine starts or a reset attempt counter. This ticket adds no automatic resume-after-exhaustion policy. |
| Will recovery start from step one? | No. Restore only the permitted same journey, with its pinned configuration, progress, waits, budgets and original send identities. Missing evidence is a visible limitation, not permission to guess. |
| What if the database is down too? | An immediate saved hold cannot be promised. The system reports the recording outage honestly, stops new work through the failed path and relies on the independently monitored 7-A backstop to classify the affected journey after recovery. |
| Can a late error replace a STOP, pause or handoff? | No. Preserve the newer contact restriction, human control, terminal outcome or successor. Attach relevant operational evidence without weakening that disposition or changing who may resume. |
| Does “seen” mean repaired? | No. Acknowledgment, cause correction, recovery requested, engine restored and business hold released are different facts. A new failure must not disappear behind an old seen marker. |
| Will customers or every agent receive a new notification? | No new notification or automatic handoff policy is introduced. Durable Attention visibility cannot depend on a notification, CRM note or email succeeding. Technical problems need an owned support route, not a misleading invitation to change lead data. |
| Will the dashboard initially look worse? | It may show more held leads and fewer apparently healthy ones because existing failures are now visible. Counts must distinguish new failures, historical discoveries and unresolved incidents. |

“Nurture blocked — system error” is a business meaning, not a pre-approved new workflow enum or
table. Reuse the existing pause/review and operational-evidence contracts; approve exact reasons,
representation and recovery semantics at R1–R3. A system-error hold is not a new consent suppression
or permission to revoke otherwise authorized human follow-up.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — apparently active leads stranded by exhausted execution; confirm at publication |
| Source / delivery class | Production-state consistency Issue 10 / **Class A: failure visibility and safe recovery** |
| Components | Native activity failure boundary; durable workflow/hold/history outcome; independent backstop; same-journey operator recovery; scoped API/Attention/lead reads |
| Repositories | miller-schackman-api and miller-schackman-web; complete final failure → saved or independently discovered problem → operator correction → verified safe disposition journey |
| Sequence | Sixteenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A, 4-A, 5-A, 6-A, 7-A and 8-A. Draft order does not establish integration or release. |
| Required backstop integration | 7-A supplies independent discovery, exact engine/run observation and shared reconstruction. A confirmed exhausted business activity must be classified before sending recovery; a missing engine is not permission to bypass its failure hold. |
| Required duplicate protection | Integrate 17-A's committed send intent/claim and correct outcome ownership on every affected send route, including paused-search. An exception after provider I/O cannot be made safe merely by catching its final attempt. |
| Shared state and recovery integration | Reuse 1-A/5-A/6-A hold/wait and occurrence integrity, 2-A instruction identity and accepted/applied evidence, 3-A enrollment/start accounting and 4-A retained operational evidence. R1/R2 name the exact integrated dependencies or contained routes. |
| Protected behavior | Preserve 9-A unresolved-reply and deterministic STOP safety, 16-A durable opt-outs, current human control and 8-A's separately gated completion contract. This ticket does not resolve G1. |
| Adjacent ownership | 6-A handles returned cannot-proceed outcomes; 7-A handles independent missing-engine discovery; 15 owns general exhausted background-work queues. This ticket handles terminal activity failures at source and their integration, not three new recovery systems. |
| Not a prerequisite by itself | Releasing 13-B, 14-B or 17-B. Preserve the actual separately released consent, CRM-control and uncertainty baseline; never introduce an unshipped B rule or undo a released one. |
| Decision ownership | Name implementer, independent reviewer, engine/persistence owner, API/web owner and release/incident-response operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08; Temporal SDK locked to 1.30.0. No live production state was inspected; retrace the implementation branch. |
| Closure boundary | Terminal activity failure cannot remain an unowned healthy-looking journey: its durable outcome or independently recovered exception is visible, current protections remain intact, and the actual authorized recovery journey works. |

**Included:** standard and recurring paused-search scheduling/execution failures; the two native
uncertainty-timeout activities while present on the released baseline; failure-recording failure;
correlation, transactions, occurrence/send safety, independent detection, API/UI, tests and bounded
historical treatment. Shared send/instruction paths are integration boundaries, not permission to
rebuild the dispatch or recovery foundations here.

**Excluded:**
- Changed ordinary attempt limits, backoff or business-activity timeouts; unlimited retry, a new
  automatic resume-after-exhaustion rule, forced human handoff, or a new customer/agent alert policy.
- Reclassifying returned provider rejection as an engine exception, treating uncertainty as proof
  of failure/no-send, new fallback/contact rules or the separate 30-minute inbound-outage policy.
- A new campaign/enrollment, terminal re-entry, completion deadline, changed recurring limits,
  released send claims, reset AI/touch/start budgets or widened recovery/resume permissions.
- A general Workflow Task bug/nondeterminism repair framework, changing the SDK's global failure
  exception settings, treating deliberate cancellation as exhaustion, or a generic rules engine.
- Blind historical restarts, guessed failure/send times, production fault injection, real-customer
  test traffic, or editing any of the prior fifteen drafts.

**D7: Class A and Class B must not share a PR.** An integrated B rule remains the baseline to
protect, not an excuse to add another policy change inside this repair.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

LeadNurtureWorkflow awaits scheduling and execution activities without an activity-failure handler.
Standard and recurring names share the same helpers. Scheduling has a 30-second start-to-close
timeout; execution has a two-minute start-to-close timeout. Both retry policies allow three total
attempts, with a two-second initial interval, coefficient 2 and maximum interval 30 seconds.
These are per-activity attempt settings, not a universal three-retry or fixed outage-duration rule.

The uncertain-send branch waits up to 24 hours on the reviewed baseline, then invokes either
timeout-uncertain-paused-search-occurrence or timeout-uncertain-outbound-send. Both have 30-second
start-to-close timeouts and RetryPolicy(maximum_attempts=3), using the SDK's other defaults. The
surrounding built-in TimeoutError catch handles normal wait expiry; it does not catch failure of
those cleanup activities. If separately released 17-B removes these business waits, do not restore
them here or turn failure of an audit-only reporting sweep into a new nurture hold.

Temporal's Python SDK surfaces final activity failure to the workflow as ActivityError, with cause,
activity identity and retry_state. ActivityError inherits FailureError; unhandled it can fail the
Workflow Execution. It can also represent non-retryable failure or cancellation, so its type alone
does not prove three attempts were made. Ordinary workflow-code errors such as result-coercion
TypeError generally fail/retry a Workflow Task under the reviewed default settings instead; they
are not the same terminal execution failure. Worker shutdown, deliberate cancellation/termination
and normal timer expiry must not be labelled as exhausted customer work merely because they stop
or interrupt execution. Exact SDK behavior needs real-engine evidence at R2, not a broad catch-all.

The engine snapshot is in-memory/query state and records activity results only after success. The
initial snapshot does not copy input_.workflow_id, and the first failed scheduling call may leave
no successful workflow/step/occurrence result. Standard activity inputs lack an explicit business
workflow ID. A new recorder cannot rely only on the last successful snapshot or assume that the
latest workflow for a lead is the failed one.

Activities call application use cases in a database session, then commit before returning their
result. Errors can occur before a write, after committed dispatch intent, after external provider
I/O on a direct route, or after commit while returning the result. The retry-policy comment about
durable send-request replay does not establish that guarantee for paused-search's direct-send
bypass. Failure leaves the last committed business facts in place; it does not roll back a provider
effect or prove that every activity attempt did nothing.

The domain already has PAUSED, HUMAN_HANDOFF, HUMAN_OWNED and terminal states, but no dedicated
system-error state or activity-exhaustion reason in the reviewed enums. PAUSED preserves the cursor
and clears next_action_at. apply_workflow_state_transition loads the latest workflow for the lead,
writes state/history, and can return NO_WORKFLOW or SKIPPED. Its optional enrollment dependency
mirrors terminal outcomes only, not PAUSED. Its optional occurrence dependency cancels open
occurrences on PAUSED and other protected/terminal transitions. Neither passing those repositories
blindly nor adding the old workflow ID to metadata supplies safe same-run failure persistence.

The UI builds Attention from API data, not directly from Temporal execution failures. Admin and
assigned-agent helpers already project selected paused/human-control lead states; the admin helper
also reads reports, preflight and outbound-send exceptions. Those sources do not enumerate every
exhausted automation activity. A lead left ACTIVE_NURTURE after such failure can evade these lists.
Adding a pause alone would still leave generic copy, episode/recovery and protected-state gaps.
The admin helper also catches unavailable outbound-exception reads as an empty exception array;
new failure reads must not copy that pattern and advertise an outage as “nothing needs attention.”

Generic Resume checks existing role/assignment/reason/contact rules, then records ACTIVE_NURTURE
and queues a resume instruction; it returns REQUESTED, not proved engine application. Already
active/recovering states are not resumable. Specialized review-hold resolution also exists; do not
assume it accepts a new system-error reason or that a successful toast proves repaired execution.
There is no independently periodic failure inventory supplied by this workflow; 7-A remains an
integration requirement, not an implemented capability inferred from its draft.

The source incident described short Temporal history retention. That is historical context, not a
fresh live setting/count. 4-A owns verified retention and longer-lived application evidence.

### 3.2 Classify the failure without changing the business outcome

Approve this disposition matrix at R1. These are required meanings, not prescribed schema names.

| Observed situation | Required disposition |
| --- | --- |
| Required scheduling/execution activity still has allowed native retries | Preserve its existing policy and safety checks. Do not create a fresh unresolved review for each intermediate attempt. |
| Required activity has definitively exhausted attempts, timed out terminally or ended non-retryably | Record the actual final category and reason; establish the same-run system-error hold if no newer/protected disposition conflicts. No next automatic nurture action until the approved recovery releases that failure. |
| Activity returned a documented hold, review, rejected, failed, deferred, skipped or terminal business result | Follow its existing or integrated 1-A/5-A/6-A/8-A contract. A status string named failed is not an ActivityError; do not overwrite a provider/consent/configuration outcome with a generic system error. |
| Legacy uncertainty-timeout activity fails while the lead is already held/reconciling | Keep the original uncertain-send hold, claim and message truth; attach the failed timeout-processing obligation as related operational work. Do not cancel uncertainty, mark delivery failed, or replace the original restriction merely to store an error. |
| Already paused, response-processing, handed off, human-owned, terminal or superseded when the late failure is handled | Preserve current reason/authority and successor state. Record the relevant failed obligation separately, or an evidenced superseded/no-longer-applicable result; never demote protection or pretend the original work succeeded. |
| Normal timer expiry, cancellation/control flow, deliberate incident containment or a Workflow Task bug | Preserve the correct SDK/control semantics and owned operational route. No fabricated activity-attempt exhaustion, hidden cancellation swallowing, automatic reversal of containment or replacement of a running execution. |
| Failure cannot be recorded because storage or the recording activity is unavailable | Do not report a saved hold. Retain what execution/operational evidence is available, expose the recording outage and use the independent backstop after recovery, with no blind sending restart. |
| Identity, cause, engine health or prior provider side effects cannot be established | Show the known facts and explicit uncertainty with an owned remedy. Unknown is neither healthy nor permission to contact; do not invent a lead, enrollment, run or failure category. |

Failure handling blocks the failed automation obligation; it does not convert every incident into
contact suppression or take human work away from its owner. R1 identifies which committed existing
intents must be held and how already-started effects settle through 17-A. An irreversible send that
preceded the failure cannot be promised undone.

### 3.3 Persist one truthful failure against exactly the right journey

1. Correlate workspace, lead, business workflow/enrollment, pinned campaign and execution mode/track,
   engine workflow/run or generation, activity identity and available step/occurrence/request/message
   evidence. Distinguish business workflow identity from a reused Temporal workflow ID and individual
   engine executions. Approve a stable failure-episode key plus per-attempt evidence; retrying the
   recorder, replaying history or observing the same failure in 7-A must not create new incidents.
2. Capture the failing phase from the attempted call and authoritative input, not merely the last
   successful result. Resolve missing optional/legacy identity conservatively. Revalidate the exact
   current target under the approved lock/version boundary before mutation; a stale same-business-run
   engine must not re-pause a successfully recovered successor execution. No latest-by-lead fallback
   without proven correlation, and no new enrollment fabricated to make recording succeed.
3. Record a bounded, allowlisted technical category and business-readable reason, original failure
   observation time, recording time, evidenced retry state/count, failed phase and safe support
   reference. Unknown attempt count or original failure time stays unknown. ActivityError does not
   provide a universal attempt-count field, and maximum_attempts is not evidence of actual attempts.
   Do not copy raw exceptions, stack traces, prompts, customer messages, provider payloads, headers
   or credentials into application/UI history or new logs. Retained SDK history access also needs
   the 4-A privacy/access contract; this is not approval to broaden diagnostic access.
4. Use the sanctioned state transition and the integrated hold/history contract. For a currently
   eligible unprotected journey, persist non-sendable system-error meaning and clear misleading
   next-outbound scheduling, retaining its cursor, pinned versions and prior valid progress. The
   workflow, matching enrollment projection, required episode/history and any recovery instruction
   must agree in the approved transaction. A generic terminal-only enrollment mirror is insufficient.
5. Preserve prior admission/source, created/enrolled/started facts, logical-touch and AI budgets.
   Failure is not a completed touch, new start or campaign end. Reuse 3-A for accurate enrollment
   phase; do not stamp started_at during a scheduling failure or set ended_at merely to free an
   admission constraint. A protected state retains its matching enrollment meaning.
6. Approve occurrence handling for planned/scheduled/draft/dispatch-pending/in-flight/uncertain and
   already terminal records before wiring the generic pause helper. A blanket cancel_open_for_workflow
   can discard a live obligation. Preserve accepted/uncertain claims, settlement and accounting;
   a retained future occurrence's old due time must not authorize an unvalidated send. If approved
   cancellation is appropriate for unattempted work, retain its reason and one safe recovery path.
7. Re-read current state and pending replies/controls when failure recording races pause, handoff,
   suppression, business completion, authorized recovery or a new journey. Preserve newer authority
   and append the relevant incident/supersession evidence. PAUSED-to-PAUSED may be legal in the
   domain; legality alone does not permit replacing another hold reason or widening resume rights.
8. Distinguish committed recording, duplicate already-recorded, protected/superseded, missing-anchor
   and persistence-failed outcomes. NO_WORKFLOW, SKIPPED, zero-row writes or an ignored enrollment
   update are not successful coherent recording. A retry after commit-before-ack loss must find
   the existing outcome, not change the original timestamp or create another transition/review.
9. Keep failure truth independent of secondary notification/CRM writes. Required local evidence
   commits durably; already-authorized external updates use their existing durable work ownership.
   Their failure cannot unpause, re-send or erase the primary incident. Do not invent a new handoff,
   review notification product or second incident table where existing mechanisms can carry it.

### 3.4 Keep execution and independent recovery safe when recording also fails

1. Handle native terminal activity failure at the actual scheduling/execution/legacy-timeout
   boundaries, including failure before the first successful result. Preserve cancellation semantics
   and deterministic workflow execution. Database/provider I/O stays in activities/adapters; do not
   call repositories directly from workflow code or leak Temporal exceptions into the domain.
2. After a committed hold, establish its approved non-sending engine disposition. The recommended
   path parks the engine for an authorized resolution; a deliberately failed-after-recording engine
   requires the explicit recovery contract in §6. Neither disposition is campaign completion or a
   healthy engine-exit. Snapshot flags alone cannot enforce the hold across restart or other senders.
3. Normal close/pause/inbound processing must still work while blocked. Old resume, unblock,
   reschedule, timing or paused-search-configured signals cannot clear a newer system failure merely
   by flipping _send_blocked. Reuse 2-A's exact instruction identity/freshness and authoritative
   application revalidation. A permitted resolution releases only its applicable episode; other
   pending reply/contact/human/configuration controls remain effective.
4. Bound the failure-recording activity and its recovery behavior at R2. A secondary storage failure
   is not permission for an unlimited reporting loop over a still-active-looking journey. Retain
   the primary failure identity/category separately from the recording failure; do not replace the
   root incident with only “failed to record error.” If no durable outcome is possible, fail honestly
   into the approved independently observable disposition, rather than returning healthy success.
5. Pair the source handler with 7-A's independently running, monitored check. Once services return,
   a confirmed exhausted execution that missed recording must converge on the same episode/hold
   before any recovery that could send. Do not require a lead click, new webhook, queued instruction
   or recent next_action_at. Concurrent source/backstop recording must converge, not compete to
   restart or create two failure items. A paused failed engine stays excluded from automatic resume.
6. A running engine whose worker is unavailable, a failed inspection, an old closed execution in a
   live chain and a deliberately stopped execution are distinct. Use 7-A's scoped direct inspection,
   freshness/coverage and current-run rules. If reporting cannot finish while the engine is RUNNING,
   R2 must provide bounded observable escalation; a missing-engine-only sweep cannot discover an
   indefinitely parked, unrecorded failure. Do not restart a live engine or label unknown health as
   proven exhaustion. If history expired, record evidence limitations and contain unsafe recovery.
7. Preserve all prior send identities and claims through native retries, timeout, process failure,
   correction and restored execution. A timed-out activity can have made a provider call and can
   still finish late. Through integrated 17-A, a possibly accepted touch is never repeated or
   re-drafted as new; accepted/uncertain outcomes settle under their existing policy. A proven
   unattempted intent or definitely-unaccepted retry can proceed only after applicable protection
   is legitimately released, through the original bounded dispatch path with current send checks.
8. Late activity/dispatch/callback results may contribute their real message/occurrence evidence;
   they do not prove the failed automation has been repaired or authorize an old state transition.
   Revalidate authority at send/settlement boundaries, not just when writing a recovery receipt.
   Preserve actual 17-B audit-only callbacks where released; never add its continuation rule here.
9. Correction and explicit allowed resolution use 2-A/7-A's same-journey reconstruction, not another
   enrollment or replay of the original inbound/operator business action. Recover pinned mode,
   cursor, occurrences, pending dispatch/reply waits and original commands. Known-begun work is not
   charged a second start; never-begun work respects 3-A before its first real action. No catch-up
   burst, step-one reset or newly inferred final completion; preserve G1-dependent waits.
10. Record recovery pending, engine acceptance, restored safe disposition and any actual command
    application separately. A new engine run ID, process restart, transient RUNNING observation or
    successful recorder call cannot reset the incident/recovery budget or falsely resolve repeated
    exhaustion. R2 approves a verifiable recovery-success rule and bounded, auditable operator retry
    after correction; unresolved or recurrent failures stay discoverable with current age/evidence.

### 3.5 Complete the scoped operator journey

- **Discover:** fresh lead/Attention reads show the affected journey and the safe system-error
  reason, failed phase, first-observed age, evidence reference and current recovery status. Include
  relevant failures even where a newer protected state or absent lead anchor prevents a simple
  latest-workflow pause projection. Use the established workspace/support surface for unattachable
  work; never invent an owner/lead or expose another tenant's details to create a convenient link.
- **Explain the action:** distinguish a correctable lead/configuration issue from a database,
  provider/LLM service or code problem needing support. Give an actionable permitted destination
  and reference. Agents must not be told to retag, change consent, repeatedly press Resume or edit
  the database to fix a system outage. Visibility is required even when no self-service fix exists.
- **Correct, then resolve:** reuse a suitable existing hold-resolution/manual-resume path after
  verifying its reason, permissions and transaction behavior. If a scoped operational retry action
  is needed, approve it at R3; do not presume an endpoint exists. Require actor/reason, exact episode
  and current eligibility on submission. Do not dismiss unrelated rejected drafts, reply holds,
  handoffs or send exceptions as collateral damage from resolving this failure.
- **Separate authorities:** technical engine restoration and business permission to resume are
  different. Restoring a paused engine cannot release its hold. An explicit permitted business
  resolution must still obey current role, assignment, consent, human ownership and workspace
  controls. Neither support visibility nor a reason string grants human hand-back, terminal re-entry
  or force-send permission. Assigned-agent versus wider-role scope must match existing enforcement.
- **Verify the result:** the UI shows requested/pending until the applicable saved/reconstructed/
  applied evidence exists, not “resumed from step one” or “fixed” from a queued signal. Refresh
  preserves the result, and a still-blocked recovery names the remaining blocker. Duplicate actions,
  lost responses and concurrent recovery return a stable reference or truthful superseded outcome.
- **Keep counts and seen state honest:** distinguish affected leads from failure episodes/attempts
  and historical discoveries. Correlate source/backstop and related instruction/send problems
  without deleting their independent obligations or double-counting the same episode. Seen is not
  resolved; legitimate resolution retains history, and recurrence/new work is discoverable under
  the approved episode/version rule. Normal retries do not flood the queue with duplicate items.
- **Scope before pagination:** complete traversal, counts and action authorization use workspace
  and current lead ownership before limits. Reassignment changes the permitted viewer, not the
  failure's identity or nurture policy. Managers use an existing authorized destination, not an
  admin-only settings link or newly invented manager/team authority. Unowned work stays with an
  authorized workspace operator, not a fabricated assigned-agent queue.
- **Distinguish unavailable from empty:** loading, genuine empty, stale, partial and failed reads
  have explicit meanings. Unavailable failure or acknowledgment data cannot hide an incident or
  assert healthy automation. Older resolved/superseded episodes remain reachable under 4-A's
  history/access contract; latest-only state or a first-page result is not a complete incident list.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Failure identity, classification and business state | Approve the terminal/cancel/task/returned-outcome matrix; same-run/generation/episode identity including first-call and legacy inputs; safe reason/time/attempt metadata; protected-state precedence; enrollment/occurrence/accounting semantics and exact adjacent A/B baseline. | Domain/application failure-contract implementation |
| R2 — Durable recording, execution and backstop | Approve claim/lock/version/commit/duplicate and missing-anchor semantics; deterministic source handler and engine disposition; recording retry/secondary failure bounds; independent 7-A observation-before-recovery integration; 17-A send/late-settlement guarantees; instruction/reconstruction and recurrence-success rules; worker wiring, old inputs/history replay and test seams. | Persistence/engine/recording/recovery implementation and integrated safety acceptance |
| R3 — Operator and scoped-read contract | Approve API/UI fields/copy, cause-correction/support destination, exact reasoned recovery/resume authorities, accepted-versus-applied evidence, counts/episode/seen/history, scope-before-pagination and unavailable/absent-anchor handling. | API/web/operator-recovery implementation |
| R4 — Historical cohort, rollout and operations | Approve evidence-based inventory and separately authorized correction/containment; compatible worker/schema/reader ordering; exact cohort, rates and operational monitoring thresholds; independent recording/backstop liveness and incident owner; canary stop criteria and evidence-preserving rollback. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. This draft does not choose
a new business state, recording retry duration, recovery budget or historical treatment by fixture
default. An integrated dependency is required evidence, not a link to another draft with open gates.

## 4. Business acceptance scenarios — for approval

Each changed behavior requires a demonstrated meaningful failing test before its implementation.
Use synthetic leads, controlled failure injection and recording provider fakes at external ports.
**These are not passing tests.** Before testing each scenario, fill its exact categories, thresholds,
states and permitted action outcomes from the applicable gates in §3.6; R4's rollout decisions do
not block unrelated baseline reproduction.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Run standard scheduling through its real native retry policy and fail all three allowed attempts with an infrastructure/application error. | One durable same-run system-error hold/reason/history outcome, coherent enrollment/read projection and approved non-sending engine disposition; Attention identifies the affected lead without an operator wake-up. | Engine FAILED while the application alone remains healthy, only a log/snapshot, invented start/end time, or a fourth business attempt from an outer retry loop. |
| AC-02 | Schedule a valid standard step, then exhaust execution before any provider submission, including an LLM drafting dependency that repeatedly raises. | Correct execution phase and evidenced final cause/attempts; preserved step/budgets and a usable review/recovery path with no later automatic touch. | Diagnose it as missing configuration or provider rejection without evidence, consume the step, advance to the next one or silently close successfully. |
| AC-03 | Exhaust schedule and execution separately in recurring paused-search mode, with pinned track and prior completed occurrences. | Same failure contract with exact mode/track/workflow/occurrence lineage; prior touches remain counted once and next-action meaning is truthful. | Standard-only fix, new track/campaign substitution, reset recurring limits or new occurrence for already-owned work. |
| AC-04 | On a baseline retaining the uncertain wait, exhaust each of the occurrence and standard reconciliation timeout activities; separately exercise a released audit-only expiry path. | Preserve original uncertainty/hold/claim; related timeout-processing failure is visible and owned. An audit-only failure does not create a new nurture hold; actual released B behavior stays intact. | Wait expiry itself means failure, a cleanup exception proves non-delivery, overwrite the original hold or reintroduce removed 17-B waiting behavior. |
| AC-05 | Fail an activity transiently, then succeed on its second or third allowed attempt; include valid due and future actions. | Native retries recover normally, one legitimate eligible action occurs at its proper time and no unresolved terminal-failure episode remains. | Hold on the first exception, all sends disabled, extra provider call/transition on retry or changed retry/backoff settings. |
| AC-06 | Exercise terminal activity timeout and an existing non-retryable activity failure before the maximum count. | Classify actual retry_state/cause and evidenced attempts correctly, preserving possible external effects; both reach the approved actionable terminal disposition. | Claim every ActivityError means three attempts, invent an attempt count or infer no send from a timeout/non-retryable label. |
| AC-07 | Exercise normal timer expiry, requested cancellation, activity cancellation, worker shutdown, deliberate termination and a workflow result-coercion/task error; inspect current engine status. | Real history/status and fresh business reads evidence each R1-approved outcome: normal timer expiry progresses its permitted path, cancellation propagates, and worker return services the same execution where it remains RUNNING. No false exhausted-activity category or reversal of containment; a running task-failing engine is not replaced as absent. | Broad Exception/FailureError catch swallows cancellation, global SDK failure settings changed, or every stopped worker produces a paused lead. |
| AC-08 | Return normal business hold/review/rejected/failed/deferred/skipped/terminal outcomes and a valid final-response wait without throwing. | Preserve their existing or integrated 1-A/5-A/6-A/8-A meanings, legitimate waits and provider/consent reasons; no duplicate generic system incident. | Every non-sent status treated as engine exhaustion, completion inferred from no step, or existing review reason overwritten. |
| AC-09 | Fail the first schedule before any successful result; include optional/legacy missing workflow ID, absent lead/enrollment and conflicting workspace/campaign/engine linkage. | Correlate safely from authoritative input/execution facts where possible; otherwise create the approved scoped operational exception with explicit missing anchor, not guessed business mutation. | Last successful snapshot required to detect the incident, latest-by-lead chosen blindly, invented workflow/lead or cross-tenant attachment. |
| AC-10 | Duplicate the failure recorder, replay the same execution history, and lose the recording activity acknowledgment after commit. | One stable episode and required state/history/enrollment effect; original valid observation/recording facts remain, duplicate returns truthful prior outcome. | New incident, transition, start/touch debit or first-failure time on every attempt/replay. |
| AC-11 | Fail before/after workflow, enrollment, occurrence, episode/history and required outbox commit boundaries, including zero-row writes and invalid/protected transitions. | Independent database sessions prove the approved atomic result or explicit recoverable non-success; NO_WORKFLOW/SKIPPED is not misreported as saved coherent hold. | Workflow paused while promised enrollment/evidence silently diverges, uncommitted instruction treated as durable, or error handler reports success over a rollback. |
| AC-12 | Exhaust a required activity while the database is unavailable; also exhaust recording, then restore services and run the actual independent 7-A path with no user signal. | Honest recording outage followed by same-journey classification/visible hold or explicit evidence-poor containment before sending recovery. Discovery does not depend on next_action_at or outbox presence. | Claim the unavailable database saved an audit, leave a healthy-looking orphan indefinitely, or automatically replay the failed send before classifying its failure. |
| AC-13 | The primary activity and its recorder both fail repeatedly; restart workers and allow further scans, including a recording-pending engine still RUNNING. | Primary and secondary evidence remain distinguishable; approved bounds and independent liveness/escalation prevent silent parked failures or unlimited churn. No new business attempts without permitted recovery. | Only the recorder error survives, missing-engine sweep claimed to cover every running stall, or new process/engine IDs reset exhaustion endlessly. |
| AC-14 | Source recording, the backstop and duplicate operator submissions compete for the same incident using independent transactions. | One authoritative episode/hold and applicable bounded recovery ownership; duplicate/superseded outcomes remain truthful and unrelated incidents stay separate. | Process-local fake counters used as concurrency proof, duplicate review items, competing restart owners or swallowed required instruction. |
| AC-15 | Deliver a delayed failure from an old engine after authorized recovery of the same business run, and after a genuinely new enrollment/track; vary engine generation and workspace. | Old failure remains attributable to its own obligation; no re-pause or mutation of newer successful execution, successor workflow or unrelated tenant. | Business workflow ID or reused Temporal workflow ID alone authorizes a late write; latest state is overwritten. |
| AC-16 | Race failure recording with pause, pending inbound receipt/processing, handoff/human ownership, suppression, completion and successor creation; exercise both commit orders. | Current protection/reason/authority wins under the approved serialization rule; relevant failure evidence remains without demoting protected outcomes or fabricating resolution. | PAUSED-to-PAUSED legality used to erase another reason, handoff demoted, STOP undone, terminal enrollment reopened or pending reply released. |
| AC-17 | Deliver old/duplicate resume, unblock, inbound-continue, reschedule, timing and configured-mode signals while the system-error hold is current; then deliver a genuinely permitted resolution. | Stale/unrelated instructions cannot clear the failure; correct same-episode resolution is applied through current checks, while independent holds remain. Normal close/control behavior remains responsive. | _send_blocked=False bypasses persisted protection, every signal is discarded, or valid operator resolution cannot wake the held engine. |
| AC-18 | Let a provider possibly accept a touch, then crash/fail before local result/acknowledgment; repeat native activity attempts and later authorized recovery on each affected send route. | Integrated 17-A retains the original request/message/occurrence claim and truthful acceptance/uncertainty; no second submission of that possibly accepted touch or duplicate journey consumption. | Exception/timeout or absent provider ID proves no contact, new idempotency key/re-draft after recovery, or terminal catch claimed to repair duplicates from earlier attempts. |
| AC-19 | Hold a proven unattempted committed send intent and a documented definitely-unaccepted retryable attempt; correct and legitimately release the applicable protection. | Original intent can make its first allowed dispatch or existing bounded retry with current safety/timing checks; no new campaign/claim or unresolved-hold bypass. | Every pending request permanently blocked to pass no-resend tests, raw PENDING/FAILED label accepted as proof, or dispatch begins before allowed resolution. |
| AC-20 | Inject failure/late outcome around planned, draft-review, dispatching, uncertain and terminal paused-search occurrences; let an already-started activity settle after the hold. | Approved occurrence/claim lifecycle retains real effects, one accounting outcome and current protection; retained old schedule is revalidated before future sending. | Blanket cancellation loses in-flight/uncertain work, stale settlement resumes nurture, duplicate occurrence/touch or old due time bypasses the hold. |
| AC-21 | Discover a recorded failure on a parked engine, correct its cause and submit the approved existing or R3-approved resolution with reason; repeat and refresh. | Usable scoped action, stable reference and pending/accepted/applied evidence; same journey resumes only as permitted, preserving future timing, progress and remaining controls. | UI-only success, repeated generic Resume is the remedy, “restart from step one,” unrelated draft/reply reviews dismissed or forced handoff. |
| AC-22 | Resolve a supported incident whose engine failed/closed after recording; separately restore a paused engine technically without authorizing business resume. | Shared 2-A/7-A reconstruction retains original commands and same-run context. Only the authorized business action releases its applicable hold; terminal or unsafe/unreconstructable cases remain protected and owned. | Technical restoration grants sending rights, new enrollment evades the hold, accepted start equals applied resolution or broken active-only Resume is the only support route. |
| AC-23 | Read incidents/counts and request recovery as assigned agent, unrelated agent, permitted wider role, inactive member and another workspace; include reassigned and unowned leads. | Fresh list/detail/count reads contain only authorized workspace and assignment scope, enforced before pagination; unauthorized recovery cannot change business/recovery state. Valid role-specific destinations and owned unassigned/support work. Reassignment changes permitted visibility, not incident identity or workspace. | Broader role rights to make a button work, admin-only dead-end for managers, cross-tenant reference/count leakage or a reason alone grants force-resume. |
| AC-24 | Produce a real saved failure and read through API/client into lead detail and both relevant Attention builders, including a newer protected business state. | Consistent same-run safe cause/phase/time/reference and recovery status; incident remains discoverable without relying solely on latest PAUSED state or outbound-send exceptions. | Proposed fields only exist in web fixtures, engine internals are the only discovery path, or protected-state preservation makes the failure disappear. |
| AC-25 | Mark an episode seen, request recovery, observe acceptance without reconstruction, resolve it, then cause renewed exhaustion; include an independent failed instruction/send obligation. | Seen/requested/accepted/restored/resolved are distinct; stable counts and version/recurrence evidence keep new and independent work discoverable while retaining history. | Old seen marker hides recurrence, accepted start marks incident fixed, alert per native retry or linked obligations all deleted as duplicates. |
| AC-26 | Traverse failures/older episodes past a full page of unrelated leads; fail or stale a failure/history/acknowledgment read and include missing/expired history. | Scope-before-pagination and declared complete coverage; loading/empty/partial/stale/error are truthful, known incidents persist and evidence gaps are explicit. | Repeated first-100 list, current latest workflow replaces all history, error becomes empty healthy queue or unknown original failure time is invented. |
| AC-27 | After failure recording, make an already-authorized CRM update/notification fail and retry; include no configured notification destination. | Local hold/incident remains durable and discoverable, secondary delivery has its own truthful outcome and no repeated lead send. A new notification dependency is not required. | Review exists only if email/CRM succeeds, cause is silently overwritten, no destination means no incident, or A creates a new notification/escalation policy. |
| AC-28 | Stop the application activity worker, failure recorder or independent recovery runtime; make Temporal inspection unavailable and later recover it. | Operational evidence distinguishes running-but-unserviced, recording unavailable, check unavailable and confirmed exhausted work; an observation path independent of the failed worker detects stale coverage under the mechanism/thresholds agreed at R4, without blanket lead mutation or duplicate starts. | Recorder/sweeper self-success counters are the only liveness proof, silence means health, unknown is NOT_FOUND or unavailable checks trigger bulk resume. |
| AC-29 | Inventory synthetic historic failed/closed runs, expired history, already held/terminal/superseded journeys, uncertain sends and conflicting or absent anchors. | Evidence-strength and exact authorized correction/containment matrix; only proven same-run failures are projected as such, with original versus discovered/corrected time distinct. | All closed/old ACTIVE rows labelled three-attempt exhaustion, missing history proves never-sent, guessed times or automatic backlog replay. |
| AC-30 | Rehearse compatible canary and rollback across old/new schema, workers, activities, source recording, 7-A, dispatch and readers; replay representative Temporal histories. | Approved cohorts only, registered/wired failure handling and containment of incompatible paths; rollback preserves holds, claims, evidence and usable recovery/read access. | Reset customer engines to avoid replay issues, remove readers under persisted new reasons, bulk clear holds or enable old direct-send replay windows. |
| AC-31 | Demonstrate synthetic ordinary work → real activity exhaustion → committed failure → fresh API/UI → authorized correction/resolution → verified next safe disposition; also run storage-outage/backstop recovery without a chance signal. | Complete traced journey using real Postgres/Temporal at claimed boundaries and recording fakes at external provider ports per §5, including one legitimate post-resolution action and no repeated prior touch. | Manually inserted PAUSED fixture, mocked recorder success or fake engine close plus screenshot offered as complete proof. |
| AC-32 | Run normal enrollment/cadence, paused-search, AI replies, operator/draft sends, final-response waits, holds, handoffs, STOP/DNC, workspace controls and the declared A/B baseline beside failure handling. | Working eligible sends and every independent protection remain; no new completion, consent/fallback, tag, uncertainty, notification or automatic recovery policy is hidden in A. | All outreach disabled to pass negatives, new start/touch/AI debit on recovery, changed human authority or Class B behavior inside the repair PR. |

AC-29–30 authorize synthetic rehearsals only, not production reads/changes. Already-correct
positive/protected controls may pass on the baseline; changed behavior still needs meaningful red.
Required skipped integrations remain missing evidence, never a green acceptance result.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Native activity failure → application outcome → read:** actual standard/recurring workflows
  and registered activities, native final failure classification, committed hold/evidence and fresh
  public lead/Attention reads. Include first-call failure, transient recovery and real returned
  business outcomes, not just a new exception-normalization helper (AC-01–09/24/31–32).
- **Durable failure recording:** approved repository/transaction contracts on real migrated Postgres
  with independent sessions for exact identity, atomic state/enrollment/occurrence/evidence and
  protected-state/source/backstop races. Direct storage assertions are appropriate at this approved
  persistence seam; operator correctness still needs public reads (AC-09–16/20/23/26).
- **Execution, signals and independent backstop:** real Temporal test environment for attempt
  limits, terminal/cancel/task semantics, timeout, replay, parked/failed disposition, recording
  failure and restored same-run execution. Run the actual periodic entry point with no synthetic
  signal that accidentally provides recovery (AC-01–07/10–17/21–22/28–31).
- **Send/settlement safety:** actual application activity → integrated durable dispatch and outcome
  ownership with recording fakes at external provider ports; late activity completion, acceptance/lost
  response, crash, uncertainty, positive first-dispatch and bounded definitely-unaccepted retry.
  Pair no-resend assertions with a legitimate future/due send after permitted resolution (AC-18–20/32).
- **Operator correction → submission → verified result:** approved API/client/route boundaries for
  permissions, reason/episode validation, pending versus applied copy, history/count/seen/pagination
  and partial/unavailable reads. A support-owned correction can be an explicitly approved procedure;
  it cannot be only an unusable settings link or a fixture-only proposed endpoint (AC-21–27/31).

**Allowed fakes:** fixed clocks and hand-written recording CRM/LLM/messaging/notification/engine
transport fakes at external ports; repository fakes for narrow application semantics. Existing
Temporal monkeypatch tests help isolate control flow, but cannot prove native retries, cancellation,
history replay, transaction durability or concurrent ownership. Use the real integration for each
such claim; do not fake the state, duplicate protection, recovery or outcome decision under test.
Expected states/counts/times come from approved cases, not another call to the production helper.
A fake provider count proves calls to that fake, not provider-wide exactly-once delivery.

1. Agree R1–R3 and the test seams, then begin AC-01 or AC-02 on the unchanged baseline: exhaust the
   real bounded activity and demonstrate the absent durable business failure outcome through the
   chosen public seam. Observing an engine failure alone is setup, not the fix's expected result.
2. If the new failure-recording/backstop seam does not exist, add only the smallest non-working
   boundary needed to express the approved scenario and distinguish that from baseline reproduction.
   Import errors, a missing proposed enum/field or a fake programmed to return PAUSED are not
   meaningful red evidence. Do not write the handler before recording the behavioral failure.
3. Implement one minimal vertical slice to green, then the next failing case: transient success,
   first-call identity, recorder failure, protected-state race or send-claim retention as appropriate.
   Do not bulk-write speculative private-helper tests and implement toward their assumptions.
4. Run the smallest test, its file/package and affected safety regressions. Keep useful existing
   workflow/occurrence/command assertions, but a mocked retry-policy argument is not proof that the
   actual engine stops after the allowed attempts or preserves cancellation. Add real evidence for
   commits, concurrency, temporal failure semantics and API-to-UI behavior as those slices claim it.
5. Demonstrate critical sensitivity: locally remove the terminal-failure handler, same-run/state
   guard, source/backstop dedupe, retained claim or applied-evidence check and show the relevant test
   fails. Pair protections with genuine allowed retries, ordinary sends and permitted recovery.
6. Have an independent reviewer check expectations against source, R1–R4 and actual released A/B
   behavior. Attach revisions, exact commands, meaningful red/green, pass/fail/skip counts and
   integration limitations. No new dependency, browser project, provider contact or production
   fault injection is authorized by this draft. Review unrelated refactoring separately.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Fill during implementation | Not run in this draft | Required before the change | Required | Required where applicable | Explicit, never hidden as pass |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. A dedicated system-error
reason/episode, failure recorder and general incident recovery API are proposed contracts, not
claimed existing symbols. Inventory actual producers, consumers and optional dependencies first.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — native failure boundaries, inputs, signals and registration | app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/worker.py; app/interfaces/workers/temporal_worker.py |
| API — sanctioned transitions and lifecycle | app/domain/workflows/models.py; app/domain/campaigns/enrollment.py; app/application/use_cases/apply_workflow_state_transition.py |
| API — persistence and occurrence integrity | app/infrastructure/persistence/postgres/workflow_repository.py; app/infrastructure/persistence/postgres/campaign_enrollment_repository.py; app/infrastructure/persistence/postgres/paused_search_occurrence_repository.py |
| API — standard/paused-search execution and existing holds | app/application/use_cases/campaign_cadence_execution.py; app/application/use_cases/schedule_next_paused_search_action.py; app/application/use_cases/lead_review_hold_resolution.py |
| API — original command delivery and restart | app/application/use_cases/dispatch_temporal_signals.py; app/application/ports/temporal.py; app/infrastructure/workflows/temporal/starter.py; app/application/use_cases/lead_resume.py |
| API — durable sends and legacy uncertainty handling | app/application/use_cases/dispatch_outbound_send_requests.py; app/application/use_cases/process_provider_delivery_callback.py; app/application/use_cases/timeout_uncertain_outbound_send.py; app/application/use_cases/timeout_uncertain_paused_search_occurrence.py |
| API — scoped lead/history and action transport | app/application/use_cases/lead_read.py; app/interfaces/api/schemas/leads.py; app/interfaces/api/v1/leads.py; app/infrastructure/persistence/postgres/reporting_repository.py |
| Web — discovery, episode version and presentation | src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/attentionVersions.ts; src/lib/presentation/operations.ts |
| Web — actual operator routes and clients | src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx; src/lib/api/leads.ts; src/lib/api/attention.ts; src/app/router.tsx |

**Two engineering approaches to review before coding:**
- **Recommended: record through one small application contract, then park the native workflow.**
  Explicitly catch/classify final activity failure, invoke an idempotent recording activity and wait
  for the permitted resolution while retaining current control handling. Reuses existing native
  signals and minimizes normal recovery latency and extra engine starts. Costs: correct per-phase
  identity, replay-compatible commands, signal freshness and a bounded recorder-failure escape into
  7-A are essential; an in-memory blocked flag is not the durable business contract.
- **Alternative: record the same durable hold, then deliberately fail the engine with correlated
  evidence.** The explicit approved operator resolution later uses 2-A/7-A to reconstruct the same
  journey. Avoids a long-lived blocked engine, but adds start/reconstruction latency and more
  recovery work; the backstop must never automatically turn that held execution into outreach.
  A technical FAILED execution over a coherent visible hold is not business completion. This
  option is unacceptable without integrated duplicate-safe reconstruction and an actionable owner.

Both require source-side capture plus an independent backstop when recording fails. Choose at R2;
do not introduce automatic handoff or a new contact policy to distinguish these engineering
options. Reuse approved hold/episode, transition, command and recovery mechanisms; no generic
workflow wrapper, second polling recovery system or global catch-all exception policy is approved.

**Existing test starting points, not claimed new coverage:**
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/test_temporal_worker.py
- tests/interfaces/test_temporal_worker.py
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_dispatch_outbound_send_requests.py
- tests/application/use_cases/test_dispatch_temporal_signals.py
- tests/application/use_cases/test_lead_resume.py
- tests/application/use_cases/test_lead_review_hold_resolution.py
- tests/application/use_cases/test_lead_read.py
- tests/domain/workflows/test_workflow_transitions.py
- tests/infrastructure/persistence/postgres/test_workflow_repository.py
- tests/infrastructure/persistence/postgres/test_campaign_enrollment_repository.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/interfaces/api/v1/test_lead_review_hold_resolutions.py
- Web: src/app/LeadsRoutes.test.tsx; src/components/operations/operations.test.tsx

The current Temporal file includes real long-wait tests and numerous monkeypatched control-flow
tests; no final activity-failure recorder is established by those existing cases. Use approved
SDK/server-compatible tests for actual failure/cancellation semantics and replay. Locate any newly
integrated 7-A/17-A and Attention/client coverage on the implementation branch before adding tests.

## 7. Historical inventory and bounded correction

Production reads/changes require separately approved scope and access. Rehearse on synthetic data.

- Inventory exact workspace/lead/workflow/enrollment, pinned mode/version, execution/run lineage,
  last known successful business action, closure/failure evidence, current protected/successor
  state, send/occurrence claims and pending instructions. Do not inspect raw payloads or credentials
  when allowlisted metadata suffices. No production failure count is asserted by this draft.
- Separate evidenced terminal activity failures, normal completed/closed runs, deliberate stops,
  running-but-unserviced/task-failing executions, existing holds, superseded incidents and unknown
  or expired histories. Old ACTIVE state plus no next action does not establish a specific cause.
- Classify a discovered confirmed exhausted obligation through the same source/backstop contract,
  subject to current authority. Preserve stronger protection and link prior evidence; do not
  auto-start it first to see whether the problem is gone. A later successful authorized recovery
  must not be undone by late historical recording of an already superseded failure.
- Record original observed failure time only when evidenced, plus actual discovered/corrected
  time, actor and reason. Unknown original attempt count, start/send facts or deleted history remain
  explicit. 4-A cannot reconstruct what no usable copy retained, and absence of a message receipt
  is not proof that a provider never received it.
- R4 names the exact approved cohort, dry-run output, batch/rate limits, owner and stop criteria.
  Apply only conditional same-run projections/repairs; unsupported or unsafe cases receive visible
  containment and an owned investigation. Restoring service or deploying the handler is not blanket
  authorization to replay historic activities, clear claims, release every hold or create new runs.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test gates with owners and actual A/B dependency
   versions. Verify deployed SDK/server, namespace/task queue, worker registration and source/
   recorder/backstop wiring. No new numeric thresholds or hidden automatic recovery policy.
2. **Safe rehearsal:** demonstrate AC-31 and primary-plus-recorder failure, transient-success
   control, same-run/successor/protected-state races, possible prior provider acceptance, unavailable
   inspection and recurrent exhaustion. Use real integrations at their claimed boundary and
   recording providers; no deliberately broken production service or real-customer test message.
3. **Compatible cutover:** stage approved additive persistence/reason/read support, registered
   recording activity, source handling, backstop/command integration and operator actions. Prove
   old inputs and representative histories replay safely; contain old writers that can bypass
   current holds, misattribute failures or repeat direct sends. Do not reset engines to evade replay.
4. **Bounded activation:** enable only the approved synthetic/canary cohort, then verify committed
   same-run failure visibility, non-sending disposition, independent post-outage discovery and one
   permitted corrected recovery. Historical inventory/projection and any resume are separately
   scoped operations, not side effects of turning on the backstop.
5. **Operator acceptance:** show the safe reason/reference, a support-owned cause, a protected-state
   incident, pending versus applied recovery and a genuine still-blocked case. Explain increased
   visibility, no step-one reset, seen versus fixed, and why a possible prior send is not retried.
6. **Monitor and respond:** track terminal activity failures by supported category, recording
   failures/pending age, unprojected discovered incidents, stale backstop coverage, recurrence/
   bounded recovery outcomes, state/enrollment mismatch, unresolved instruction/send obligations,
   stale-identity rejections and normal legitimate outreach. Name an independent liveness/incident
   response owner; counters emitted only by the failed component cannot establish its health.

**Rollback:** stop unsafe new mutation/recovery through the approved scoped control and contain
incompatible workers. Preserve committed holds, protected/terminal states, episode/history and
send/instruction claims; keep compatible readers and a usable operator/support path. Do not clear
system-error reasons or resume all leads to make the dashboard green, roll back durable dispatch
under possible prior sends, or restore healthy-success copy over lost evidence. Already-started
external effects may settle and cannot be undone; a forward-compatible repair may be safer than
reverting a worker that cannot understand persisted failure/recovery state. Retain independent
coverage of contained/unrecorded failures and explicit follow-up for unresolved cohorts.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact, unchanged behavior and Class A boundary; applicable
  R1–R4/test gates close with exact decisions and owners before their implementation/release.
- [ ] Every supported required native activity's terminal failure has a truthful same-run durable
  outcome or independently recovered/contained exception; native retries and cancellation/task
  semantics remain correct. Recording failure cannot silently erase the primary incident.
- [ ] Workflow/enrollment/occurrence/evidence and engine disposition agree under real commit,
  duplicate and concurrency tests, preserving stronger protection, successor authority and history.
- [ ] Native retry, timeout, late settlement and authorized recovery retain all possible prior send
  claims and real accounting; a permitted positive recovery works without new enrollment or resets.
- [ ] Actual scoped API/UI supports discovery, safe explanation, cause correction/escalation and
  authorized resolution with truthful pending/applied evidence, history, counts, seen and errors.
- [ ] Meaningful red-first, green, critical sensitivity and unchanged positive/safety controls are
  attached; real Postgres/Temporal/replay/backstop/API-to-UI evidence supports the claims instead
  of fixture-only holds, fake retry results or skipped integrations.
- [ ] Historical treatment/containment, compatible canary, independent monitoring and safe rollback
  are rehearsed and separately authorized where production access/actions are involved.
- [ ] Independent product and technical reviewers accept the implemented journey; merged and
  accepted-live evidence remain separate. This draft checks none of those implementation boxes.

## 10. Related records and draft review record

- [Source Issue 10 — the engine can fail while the lead stays live](../production-state-consistency-issues.md#issue-10--the-engine-can-fail-outright-while-the-lead-stays-live)
- [Business-impact contract — exhausted failures and independent recovery](../production-state-consistency-issues.md#10--turn-exhausted-engine-failures-into-operator-visible-problems)
- [D1–D7 consensus and separate ship classes](../production-state-consistency-review-consensus.md)
- [7-A — independent discovery and same-journey reconstruction](issue-7-a-missing-engine-recovery.md)
- [17-A — committed send claims and durable outcome ownership](issue-17-a-durable-outbound-dispatch.md)
- [2-A — original instructions and truthful accepted/applied evidence](issue-2-a-reliable-instruction-delivery.md)
- [1-A — scheduling hold and operator recovery](issue-1-a-visible-scheduling-holds.md)
- [5-A — send-time hold and occurrence integrity](issue-5-a-durable-send-time-holds.md)
- [6-A — explicit returned cannot-proceed outcomes](issue-6-a-visible-cannot-proceed-outcomes.md)
- [3-A — enrollment phase and first-action accounting](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [4-A — retained, scoped operational evidence](issue-4-a-retained-operational-evidence.md)
- [8-A — separate completion and unresolved G1 reply lifecycle](issue-8-a-completion-lifecycle.md)
- [9-A — unprocessed-reply and deterministic STOP safety](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [16-A — durable contact restrictions through refresh](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [17-B — separately released uncertainty accounting, not an A default](issue-17-b-continue-cadence-after-uncertain-send.md)
- [Temporal Python SDK — failure versus task/cancellation semantics](https://github.com/temporalio/sdk-python#exceptions)
- [Temporal Python error handling — native activity failure, retries and sensitive diagnostics](https://docs.temporal.io/develop/python/best-practices/error-handling)
- [Temporal ActivityError API — identity, retry_state and inherited cause](https://python.temporal.io/temporalio.exceptions.ActivityError.html)

Draft source trace completed against API a761c1b and web 04d4361 on 2026-09-08. It distinguishes
native activity exhaustion from returned business failure and Workflow Task/cancellation behavior;
last committed business state from in-memory results; direct-send risk from documented durable
intent; and source recording from the independently required 7-A backstop. Public SDK references
explain semantics, not a tested claim about the deployed runtime.

Independent product-reader, technical/source and test-contract reviews completed with source-based
adjudication. Refinements clarify per-scenario gate sequencing, observable cancellation/control
and scoped-read checks, independent liveness observation and recording provider fakes. Suggestions
premised on nonexistent acceptance subcases/lock wording, a fabricated inbound-close signal or a
prescribed partial-incident schema were not adopted. Open R1–R4 decisions are not assumed resolved.

A final reader check found no remaining material drafting contradiction; it is not product approval.
Documentation validation passed (exit code 0): ten ordered sections, 32 acceptance rows, 50 unique
source/test file references, 20 unique local links across ticket/index including heading fragments,
index consistency and the unchanged prior-fifteen aggregate. API a761c1b and web 04d4361 source
worktrees remain clean. These checks validate documentation, not Temporal or production behavior.

Stakeholder review and R1–R4 remain open. No application code or prior ticket draft was changed;
no behavioral tests, production access, Jira publication, implementation or release was performed
for this draft.