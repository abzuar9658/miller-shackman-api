# Issue 7-A — Recover missing automation engines without restarting the business journey

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the fourteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not approve production access, historical recovery, sends or release.

## 1. Business impact — read this first

**The promise:** An eligible lead must not lose its automation indefinitely just because no new
reply or operator instruction arrives. A periodic check finds a missing engine and safely restores
the existing journey from its saved progress. If recovery cannot proceed, the problem and next
permitted action remain visible. Restoring an engine is not enrolling the lead again.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | An enrollment is saved but its engine never starts, or an engine later ends while the business workflow remains live. No independent check finds it; recovery depends on a later queued instruction happening to encounter the missing engine. |
| What changes for agents? | Eligible missing executions are discovered without a new webhook, retag or Pause/Resume toggle. Lead detail distinguishes engine recovery pending, restored execution, and recovery needing support from the business phase and any existing hold. |
| Will the lead start again from step one? | No. Keep the same enrollment, business workflow, pinned campaign/track, progress, touch budgets and message identities. A replacement engine execution is not a fresh marketing journey. |
| Will recovery send immediately? | Not necessarily. It restores the correct future timer, response wait, dispatch wait or other current disposition. A genuinely due, permitted touch may proceed through ordinary send safeguards; no catch-up burst or recovery message is added. |
| What if the lead is paused or with a human? | Preserve the pause, handoff or human ownership. This ticket does not widen automatic restart eligibility or automatically resume their outreach. An undeliverable instruction can still need attention while the lead remains safely protected. |
| What if the engine is running but quiet? | Leave it running. A future timer, response wait, stopped worker or delayed task is not proof of a missing execution. In particular, Issue 8's still-waiting final-cadence engine is not repaired by restarting it. |
| What if the engine service cannot be checked? | Show an unavailable or stale observation, not “engine missing” or “healthy.” Retry the check within approved operational bounds; do not create duplicate engines or blanket-change every lead's business state. |
| Does an accepted start mean recovery worked? | No. Recovery requested, start accepted, execution reconstructed and instruction applied are separate facts. “Engine restored; still held for review” may be correct. None means a message was delivered. |
| Can a failed start count as another daily start? | No for an enrollment already proven to have begun. A never-begun enrollment must still obtain valid first-start capacity under 3-A; an unknown historical start is not assumed unused. |
| Can support recover an already-active lead? | Through an approved, narrowly scoped engine-recovery path, not by weakening Resume permissions or manufacturing a pause. Some cases need configuration repair or explicit human hand-back first. |
| Are outreach policies or notifications changing? | No new contact permission, fallback rule, reply deadline, SMS/email/push alert or re-entry right. Preserve the separately released consent, CRM-control and uncertain-send policy. |
| Will deployment revive the whole historical backlog? | No. Approve the initial cohort, evidence, recovery rate and safeguards first. Existing stranded or evidence-poor records need separately authorized recovery or explicit containment. |

**A recurring job or a green “start succeeded” counter is not enough.** The check must cover its
declared population, restoration must be safe and evidenced, and unresolved cases must be usable by
operators. Recovery may restore previously lost outreach volume; do not disguise that release impact.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — silent stranded enrollments and nurture; confirm at publication |
| Source / delivery class | Production-state consistency Issue 7 / **Class A: independent missing-engine detection and same-journey recovery** |
| Components | Periodic reconciliation; engine inspection/start adapter; guarded shared recovery; durable evidence and bounds; scoped lead/attention reads and operator recovery |
| Repositories | miller-schackman-api and miller-schackman-web; complete detection → recovery → visible outcome journey |
| Sequence | Fourteenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A, 4-A, 5-A and 6-A. Draft order does not establish integration or release. |
| Instruction integration | Share 2-A's same-workflow restart, instruction identity/freshness and queued/accepted/applied evidence. A new sweep must not retain the existing start-then-discard-instruction defect or create a second recovery implementation. |
| Execution and send integration | Reuse 1-A/5-A/6-A wait/hold reconstruction, 3-A first-action/cap accounting, 4-A durable evidence and 17-A committed send identities where those paths intersect. Preserve 16-A opt-outs and 9-A unresolved-reply safety. Name exact release blockers at R1/R2. |
| Safety dependency, not an optional enhancement | Automatic sending recovery cannot ship for a route whose progress/waits cannot be reconstructed or whose possible prior sends lack the required durable duplicate protection. Integrate the approved A contract or contain that route explicitly; do not claim its recovery accepted. |
| Adjacent ownership | Issues 5/6 prevent silent returned-outcome exits; Issue 10 handles exhausted engine/activity failures at source; Issue 8 owns completion/late replies; Issue 15 owns general background-work dead letters. This ticket supplies the independent backstop, not all their policies. |
| Not a prerequisite | Shipping 13-B, 14-B or 17-B. Preserve the actual separately released baseline; never introduce an unshipped B behavior or roll a released one back under this A repair. |
| Decision ownership | Name implementer, independent reviewer, engine/persistence owner, API/web owner and release/recovery operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No live production state was inspected; retrace the implementation branch. |
| Closure boundary | Bounded periodic discovery of eligible missing executions, one safe same-journey restoration, retained instructions and honest scoped visibility/recovery; no dependence on a chance instruction. |

**Included:** initial engine-start failures after enrollment commit; later missing/closed engines;
standard and paused-search execution modes; independent candidate traversal, safe inspection and
recovery; shared reactive-restart integration; operational evidence, API/UI, tests and rollout.

**Excluded:**
- New enrollments, automatic terminal re-entry, track changes, cadence resets, inferred completion,
  catch-up schedules or automatic human hand-back. No widened restart/resume permissions.
- Terminating, resetting or duplicating a running execution because it is slow. The check must
  distinguish worker availability and legitimate waits from missing engines.
- New consent/channel fallback, carrier-error, tag-only control, reply-window or uncertain-as-sent
  policy. **D7: Class A and Class B must not share a PR.**
- A generic incident/rules/command framework, universal worker monitoring, rebuilding deleted
  history or entities, bulk replay, or real-customer traffic used as a recovery test.
- Editing the prior thirteen drafts or treating their open gates as approved.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

The signal dispatcher is reactive. It first tries an outbox instruction; only a
TemporalWorkflowNotFoundError triggers _restart_missing_workflow. That helper requires the latest
locked workflow's business ID to match the entry, permits QUEUED, ACTIVE_NURTURE,
WAITING_FOR_RESPONSE and RESPONSE_PROCESSING, and requires a matching active enrollment. It does
not independently compare the entry's Temporal target with the workflow's stored Temporal ID.
It starts using the workflow's stored Temporal/business IDs and the enrollment's campaign version.
A pinned paused-search track selects PAUSED_SEARCH_RECURRING; otherwise it selects STANDARD_CADENCE.

On accepted restart, the dispatcher currently marks the original instruction SENT without
dispatching it again. On disallowed/missing recovery dependencies it records TERMINAL_FAILURE;
failed restart attempts follow its retry path. Those are outbox outcomes, not independent engine
health observations. 2-A owns their delivery repair; 7-A must integrate, not copy, that contract.

The worker runs dispatch_temporal_signals and commits after the batch. It has no scan of live
workflows without outbox entries. Existing repository workspace lists are limited/latest-oriented,
not a complete checkpointed reconciliation population. No independent engine-inspection port or
periodic missing-engine recovery process was found in the traced production paths.

The shared enrollment starter saves enrollment, workflow and transition, then invokes its optional
commit callback before calling Temporal. With production commit wiring, a failed start leaves the
rows committed and returns FAILED to the caller. Existing application tests assert both the retained
rows and commit-before-start order. Re-running enrollment is not the recovery contract: admission
still sees an existing journey. Trace each actual caller's commit boundary, including paused-search
initialization and track reassignment, rather than treating the optional callback as universal proof.

TemporalClientWorkflowStarter._signal obtains a handle and awaits its signal RPC; it translates
RPCStatusCode.NOT_FOUND there. Merely obtaining a handle is not a liveness check. The start adapter
sets no explicit completed-ID reuse restriction. The source issue already corrected the claim that
completed IDs cannot restart; do not reintroduce it. A proactive read must distinguish missing,
closed, running and unavailable rather than infer them from signal-outbox status.

LeadNurtureWorkflow starts by scheduling against application state. The standard schedule/execute
inputs lack the explicit workflow ID carried by recurring schedule input; the top-level optional
workflow ID alone does not prove every activity is fenced to that business run. In-memory flags and
snapshot fields are not a complete persisted recovery plan. Final SENT/ALREADY_SENT with no more
steps waits for close; unhandled cannot-proceed returns can instead end the engine. Reconstructing
those waits safely needs the 1-A/5-A/6-A contracts, not “start again and hope.”

Manual resume checks business state and permissions, persists ACTIVE_NURTURE and queues an
instruction; it does not inspect or restart the engine. Already-active/recovering states are refused
as already active. The web's “restarted from step 1” branch is not evidence of such a server recovery
path. Lead detail and attention do not currently show correlated missing-engine recovery evidence.
Admin attention already has provider/integration exceptions; do not claim all operational visibility
is absent or confuse those records with signal delivery or execution health.

### 3.2 Detect the right population and distinguish evidence from assumptions

Approve the following matrix at R1. These are required meanings, not pre-approved enum/table names.
Postgres remains business truth; Temporal supplies execution observations. An observation needs its
identity and time, not a new competing source of truth for send permission.

| Current facts | Required detection/recovery disposition |
| --- | --- |
| Eligible same-run QUEUED enrollment committed; its initial engine never started | Include independently of outbox entries, started_at or next_action_at. After the approved startup grace and verified absence, restore the existing engine intent subject to current first-start capacity and other controls. |
| Current restart-eligible workflow has a confirmed absent or closed execution and trustworthy reconstruction evidence | Qualify for bounded same-workflow recovery. Absence alone is not permission: validate current lineage, controls, existing sends and the closure disposition before starting. |
| Current execution is RUNNING, including a future timer, response wait or blocked activity | Do not restart or terminate it. A running execution does not prove its worker is healthy or its business work is progressing; show limited observation truth and route an independently established operational failure appropriately. |
| An older execution is closed/continued-as-new while the current execution chain is running | Inspect the authoritative current target/chain. Do not mistake the old run for missing automation or address old instructions to an unrelated new business journey. |
| Inspection times out, is unauthorized/unavailable, uses unverified deployment/namespace context, or only lacks a visibility-list/search result | Health is unknown, not confirmed absence. No automatic new start on that evidence; bounded probe retry and service-level attention without blanket business-state mutation. |
| PAUSED, HUMAN_HANDOFF or HUMAN_OWNED, whether the engine is running or missing | Preserve control state, reason, cursor and authority. Do not auto-start an active engine or resume sending. Record relevant observed loss/undeliverable control separately; later explicit authorized hand-back is not performed by the sweep. |
| COMPLETED, SUPPRESSED or CLOSED business workflow, or a superseded enrollment | No automatic recovery or enrollment. Preserve terminal/successor lineage and historical evidence; obsolete engine work has no authority over the current run. |
| ELIGIBLE-only candidate, missing enrollment/workflow linkage, conflicting pinned mode/version, or overlapping authoritative runs | Do not turn a candidate into an enrollment or guess which journey to run. Use a scoped operational exception/remedy; resolve exact identity before automatic recovery. |
| Engine was deliberately cancelled/terminated for incident containment, or closure intent is uncertain | Do not blindly undo the operator's stop. R1/R4 must define how containment is represented and checked. Retained closure evidence informs disposition; a technical status alone does not authorize revival. |
| Engine history has expired but durable same-run state and send evidence remain | History absence neither proves “never ran” nor requires inventing history. Classify reconstructability; approved evidence-sufficient cases can recover, otherwise retain an explicit unknown/held outcome and support route. |
| Current control/configuration/send/reply facts prohibit the intended work | Preserve their existing hold/wait policy. Restoring execution must not clear them or re-run the business action that produced an instruction. Missing-engine recovery is not a sendability override. |

1. Define the expected-engine population by durable business workflow/enrollment and current
   authority, not CRM lead status or the broad is_sendable_workflow_state helper. Its inverse is
   not the restart allowlist, and no engine is implied by ELIGIBLE alone.
2. Scan all approved candidates, including queued failed starts, future timers and null-next-action
   cases with no pending signal. Define protected-state observation versus automatic-action scope;
   a safely intentional pause is not an overdue marketing send merely because no engine is running.
3. Use complete, stable pagination/checkpointing with workspace scope applied before limits.
   Repeated first-100 scans are not complete coverage. Changing rows, one poison candidate, a failed
   workspace or an outage must not silently starve other candidates or erase the unfinished scan.
4. Approve cadence, startup grace, observation freshness, batch/concurrency limits, rate/backoff and
   operational attention thresholds. These govern checking/recovery, not new customer-contact
   deadlines. Expose last successful sweep/coverage and unavailable checks; silence is not health.
5. Confirm absence through the approved direct execution-inspection contract in the correct
   environment/namespace. Test supported SDK/server meanings, current-run selection and retention
   limits. Do not send pause/resume/reschedule as a “harmless” health probe.

### 3.3 Restore one existing journey, with current-state and side-effect protection

1. Share one guarded recovery contract between periodic reconciliation, reactive not-found handling
   and the approved support action. It must not call new-enrollment or tag/re-entry machinery.
   The automatic business-state allowlist remains the four existing restartable states; all other
   safeguards still apply. A human resume must first pass its own existing permission/reason checks.
2. Correlate workspace, lead, business workflow, enrollment, pinned campaign version, paused-search
   track/mode and Temporal execution identity. Preserve original enrollment/source/start evidence,
   cursor, next-action intent, occurrence identity, logical-touch and AI budgets. A new execution
   may have a new run ID; it must not obtain a new business identity or default to step one.
3. Resolve mode from authoritative stored lineage, including standard and recurring paths and
   historical mode ambiguity. Do not substitute the newest published campaign/track, infer a track
   from a lead badge or silently convert an older journey because one input is missing.
4. Inspect execution outside long-held business locks, then revalidate and durably own the proposed
   recovery under the approved transaction/version contract. A scan snapshot or expired claim is
   not lasting authority. Avoid network I/O under broad campaign/workspace locks.
5. Coordinate competing initial starts, sweepers, signal dispatchers and support retries. Use an
   explicit verified Temporal conflict/reuse strategy plus durable business-level ownership, so at
   most one current intended execution can act. “Already running” requires matching lineage; it is
   neither unconditional failure nor proof that recovery/instructions were applied.
6. A start timeout can follow real acceptance. Reconcile the same intended execution before another
   start; never choose a fresh random engine ID to escape uncertainty. Fence stale claimants and
   outcome writes. Start acceptance before a DB result commit must remain recoverable, not lost.
7. Protect the probe → claim → start → first activity race. Re-read authoritative state at execution
   bootstrap and every relevant application/send boundary. A newer pause, handoff, terminal state,
   track reassignment or successor must win even if a stale external start was already accepted.
   Inventory legacy inputs without workflow identity; do not mutate whichever run is latest.
8. Reconstruct the intended safe disposition from durable progress, occurrences, dispatch and
   instruction evidence before allowing outbound effects. Preserve future due times, quiet hours,
   response/processing waits and shared holds. Revalidate stale schedules normally; do not move
   all overdue work to “now,” invent a next step or mistake no remaining step for new enrollment.
9. A known-begun enrollment retains its first-start evidence and consumes no extra daily slot.
   Never-begun work follows 3-A's actual first-action/day/claim contract; unresolved historical
   accounting cannot fail open. A new engine receipt is not started_at or provider delivery.
10. Existing accepted, uncertain, dispatch-pending or in-flight work retains its original message/
    request/occurrence identity and claim evidence. A missing/terminated engine does not prove a
    previously executing activity made no provider call. Recovery must not recreate the send,
    release a possibly used claim, consume it twice or replay its originating inbound/operator
    action. A provably unattempted pending intent can still take its first legitimate dispatch;
    a documented definitely-unaccepted attempt retains only its already-authorized bounded retry.
    Both use the same 17-A dispatch path and current safety checks, not a fresh recovery send.
    A PENDING/FAILED label or missing provider ID alone is not proof of non-attempt. Apply integrated
    17-A guarantees and separately released uncertainty policy, not 17-B by implication.
11. Keep each still-relevant original instruction available through 2-A, with its payload, actor,
    identity and freshness semantics. Do not mark it SENT because an engine started or substitute a
    generic reschedule for pause, resume, inbound, unblock or timing work. Deliver/reconcile it to
    the legitimate target and preserve acceptance versus application evidence. Initialization,
    first scheduling and in-flight/duplicate/stale signals must not lose or undo its effects.
12. If safe reconstruction is impossible, persist a precise operational hold/exception through the
    shared mechanisms, preserving any stronger existing reason. Name the permitted remedy rather
    than creating an engine that immediately exits again. Correcting infrastructure/configuration
    does not itself authorize human hand-back, contact, or historical bulk recovery.

### 3.4 Make recovery durable, bounded and truthfully verifiable

Use one minimal durable recovery/observation contract; first inspect the existing instruction,
hold and operational evidence models. New schema, fields, states, endpoints and worker topology
need R1/R2 approval. The table describes observable semantics, not a parallel workflow state machine.

| Recovery stage | Evidence / required meaning |
| --- | --- |
| Observed / check unavailable | Exact target, checked-at time, execution observation and its limitations. Absence first observed now does not prove when the engine stopped. Retain last verified observation separately from a failed later check. |
| Recovery pending / retry scheduled | Same-run intent and durable attempt ownership or approved reconstructable equivalent, next eligible attempt and reason. The system has not yet proved an active reconstructed execution. |
| Start accepted / reconstruction pending | Correctly correlated external acceptance. Record or reconcile lost-response uncertainty; a RUNNING status alone does not prove application activities restored the intended wait or schedule. |
| Engine restored | Matching execution has completed authoritative reconstruction and evidenced its next safe disposition as of a stated time. A legitimate wait or newly discovered hold is explicit; do not label held work “healthy sending.” |
| Instruction pending / applied | Use 2-A's separate command evidence. Engine restoration alone cannot clear an unresolved instruction or claim its handler ran. |
| Recovery blocked / exhausted / unknown | Safe reason, retained identity/evidence, attempt/age, current protections and an owned next action. No silent dropped candidate, endless restart churn or false success. |
| Superseded / no recovery required | Evidence of a legitimate current engine, newer business journey or protected/terminal disposition. Keep the prior incident history; do not rewrite it as successful restoration. |

1. Record meaningful detection/recovery outcomes durably, with stable episode/attempt identity and
   observation/start/reconstruction times. Reuse 4-A's retention/privacy contract. No raw workflow
   payload, message content, credentials, headers or uncontrolled exception text in UI/logs.
2. Approve real commit boundaries for claims, attempts, safe reconstruction and result evidence.
   Crash/retry cannot reset the budget, erase earlier batch results or let stale workers overwrite
   newer success/protection. Independent DB sessions must see the promised committed facts.
3. Bound probe retries and restart attempts separately. Persist budget/backoff across process
   restarts and repeated successful starts that immediately close. A new scan, new engine run ID or
   one transient RUNNING observation must not reset a failing episode indefinitely. Approve a
   verifiable recovery-success/reset rule and an explicit scoped operator retry after correction.
4. At exhaustion or unsafe reconstruction, retain discoverable attention and the approved protective
   hold/exception. Do not clear an unrelated business hold to fit a recovery status. If persistence
   is unavailable, fail honestly and surface worker/service failure; do not manufacture a saved
   review, missing-user-data diagnosis or successful empty scan.
5. Start accepted with no working application worker remains reconstruction-pending and becomes
   operationally overdue under the agreed threshold. Do not create another engine because its
   worker is unavailable. Verify reconciliation worker liveness independently of its own success
   counters, including when Temporal is unavailable; name the monitoring/response owner at R4.
6. Restoration must survive fresh API reads, process restart and duplicate observations. Losing
   evidence cannot be treated as proof nothing happened. If the engine ends again, retain a linked
   unresolved/recurrent episode instead of a permanent green badge from an old acceptance.

### 3.5 Complete the operator journey without changing human-control permissions

- **Discover:** affected authorized leads appear in existing attention/lead workflows with “engine
  recovery pending” or “automation recovery needs attention,” separately from queued/active/paused
  business phase. Normal brief startup/probe work need not alert on every pass. Do not overwrite a
  pause/handoff explanation, count each retry as a new incident or hide another unresolved problem.
- **Inspect:** expose cause, observation freshness, relevant business run, preserved progress,
  recovery stage, last attempt, safe next step and original instruction status where applicable.
  Prior-run evidence stays distinguishable. A successful start count or old next_action_at must
  not be presented as verified future execution; do not fabricate downtime or historical receipt.
- **Act:** approve a narrow “recheck/recover this engine” action or a documented authorized operator
  procedure with a durable reference, actor/reason and visible result. Already-active/queued leads
  need this route without an artificial pause/resume. Viewing an incident is not permission to
  start engines, edit configuration, lift suppression or reclaim human ownership.
- **Recover after correction:** recheck current authority, engine status, eligibility, lineage,
  mode, budgets and in-flight sends. Retry the same bounded recovery, not enrollment or the
  originating inbound/send action. Repeated requests and a lost HTTP/CLI response must not mint
  independent recoveries. Stale pages/commands cannot override later restrictions or a successor.
- **Protected lead:** show its existing pause/handoff reason and any genuinely unresolved engine
  instruction. Explain the permitted support or explicit hand-back route; do not offer “force
  recover” to clear it. Engine repair and business resume remain separate operations.
- **Scope:** reuse actual own-assigned-lead and wider reporting permissions, including unowned leads
  for already-permitted roles. Authorize recovery separately; do not invent a manager-team scope or
  grant workspace reporting to make an agent link work. Scope fields, counts and action responses.
- **Read reliability:** filter before pagination and traverse all affected records. Define count,
  acknowledgment and refresh semantics; “seen” is not resolved. An error/unavailable check remains
  distinguishable from no incidents and cannot erase the last known unresolved case.
- **Response/copy:** recovery requested → start accepted → engine restored/current hold are distinct.
  Refetch persisted evidence rather than relying on a toast. Do not reuse “restarted from step 1”
  or claim a queued instruction was received. Coordinate shared 2-A client corrections once.
- **Unattachable case:** if no valid lead/tenant anchor exists, do not fabricate one or expose a
  service-role query publicly. Use the approved scoped operational destination and support owner.
  No new customer notification channel or generic observability product is required.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Population, evidence and recovery eligibility | Approve expected-engine versus protected-observation populations; complete traversal; exact inspection/namespace/run-chain contract; startup grace/freshness; closed/absent/unknown and deliberate-stop disposition; lineage/mode reconstruction matrix and related A dependencies. No widened restart policy. | Candidate/inspection/reconstruction-contract implementation |
| R2 — Durable recovery, execution and test contract | Approve shared recovery seam, runtime owner, claim/commit/fencing and SDK conflict/reuse semantics; ambiguous starts; bootstrap/activity identity and state races; wait/progress/send/instruction reconstruction; positive restored-evidence rule; durable probe/restart/churn budgets, reset and exhaustion; old histories/inputs and exact integration blockers. | Worker/adapter/engine/persistence implementation and integrated recovery acceptance |
| R3 — Operator and scoped-read contract | Approve status/reference/copy, same-run lead/attention reads, permissions for viewing versus technical recovery versus human resume, absent-anchor handling, paging/count/seen/freshness and usable correction → bounded retry → evidenced outcome. | API/web/operator-recovery implementation |
| R4 — Historical cohort, rollout and operations | Approve evidence-based inventory, separately authorized historical recovery/containment, initial cohort and recovery rate, actual deployment/namespace/worker wiring, migration/version ordering, sweep monitoring/response owner, canary stop criteria and evidence-preserving rollback. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. Numeric operational limits
and unresolved historical classifications are decisions to record, not defaults to guess. An A/B
baseline and dependency table must say what is actually integrated, not merely drafted.

## 4. Business acceptance scenarios — for approval

Each changed behavior requires a demonstrated meaningful failing test before its implementation.
Use synthetic leads and recording providers. These are requirements, not passing test results.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Commit an eligible enrollment/workflow, fail its initial Temporal start and queue no instruction. Advance beyond approved startup grace and run the periodic check; repeat it. | One same-journey engine is restored without a webhook/retag/operator toggle; existing enrollment identity and first-start accounting remain correct. Fresh reads show the actual recovery stages. | A helper-only test that never executes the periodic entry point, another enrollment, endless queued lead or duplicate execution/touch. |
| AC-02 | A previously begun standard or recurring journey loses its engine while waiting for a future timer; repeat with a genuinely due action and no signal. | Independently discovered; same pinned mode/version, cursor, occurrence and budgets are restored. Future work waits; the due permitted touch uses ordinary safeguards once. | Reset to step one/new track, contact at restart time regardless of schedule, or recovery only when a signal is injected. |
| AC-03 | Inspect a running future timer, response wait, hold/dispatch wait, final-standard-send wait and execution with no worker polling. | No replacement/reset. Observation truth distinguishes RUNNING from confirmed application progress; worker failure is not engine absence. Issue 8's completion defect is not claimed fixed. | Age, null next_action_at, empty worker queue or lack of recent sends interpreted as missing execution. |
| AC-04 | Inspection times out, is unavailable/unauthorized or has unverified namespace/environment; separately omit a running execution from visibility-search results. | Unknown/stale observation and bounded probe behavior; no new engine or blanket state change. Existing unresolved evidence remains visible. | Treat every exception/list absence as NOT_FOUND, show healthy empty results, or contact another environment. |
| AC-05 | Inspect completed, failed, cancelled, terminated and timed-out old executions, a continued-as-new/current live chain, and an intentionally contained run. | Apply the approved current-target/closure-intent matrix. Only verified eligible recoveries start; live-chain and deliberate-stop cases remain protected/owned. | Completed-ID refusal assumed, old closed run prompts a duplicate, or automatic recovery reverses incident containment. |
| AC-06 | Candidates include queued/null-start/null-next-action, future-timer and signal-free rows beyond a full first page, across permitted workspaces; some rows change or fail mid-scan. | Stable complete traversal/checkpointing and measured coverage; one poison row/workspace cannot starve others. No dependence solely on due timestamps, enrollment phase or outbox availability. | Repeated first-100 scans, limit-before-scope, skipped failed-start population or silent loss of unfinished work. |
| AC-07 | Probe a mismatched workspace/lead/enrollment/campaign linkage, an instruction with the correct business ID but wrong Temporal target, reused engine identity, superseded workflow, overlapping runs or ELIGIBLE-only candidate. | Explicit safe non-recovery/exception; no unproved target mutation or fabricated enrollment. A legitimate successor remains untouched. | Matching only the business ID or using “latest lead workflow” as universal authority, newest campaign substitution or treating every nonterminal enum as restart permission. |
| AC-08 | Scan PAUSED, HUMAN_HANDOFF and HUMAN_OWNED with missing engines and undeliverable controls; also scan COMPLETED, SUPPRESSED and CLOSED. | No widened automatic start/resume/re-entry. Original state/reason/progress and independent instruction attention remain correct; protected absence is not automatically a failed marketing send. | Clear a pause to restart, demote handoff, free uniqueness by completing it, or advertise a suppressed lead as recoverable outreach. |
| AC-09 | After AC-08, an authorized actor explicitly resumes a permitted paused/human-controlled lead; an unauthorized actor also tries. | Existing permission/reason/contact checks govern the business action. Once legitimately restart-eligible, shared recovery restores that same run and retains its resume instruction. | Sweep performs hand-back, every viewer gains recovery/resume rights, or re-enrollment is used to evade protection. |
| AC-10 | Pause, suppress, hand off, change ownership, terminalize or reassign to a successor between probe, claim, start acceptance and first activity; deliver an old activity afterwards. | Latest authoritative restrictions/identity win at every irreversible boundary. Any already-accepted stale physical start cannot send or mutate the successor. | Probe-time eligibility authorizes later contact; fencing only result writes; standard/legacy activities silently target the latest run. |
| AC-11 | Recover each supported mode with prior sends, distinct original timestamps/source, pinned campaign/track, current occurrence, logical-touch and AI budgets; include ambiguous historical mode. | Preserve all same-journey lineage/progress. Unknown reconstruction is explicit and contained, not guessed. No extra start debit for known-begun work. | Default STANDARD_CADENCE or newest track, reset counters/created_at/started_at, or fresh occurrence for already-owned work. |
| AC-12 | Restore stale/future/due schedules, quiet hours, a reply-processing hold, dispatch wait and shared 1-A/5-A/6-A configuration hold. | Reconstruct/revalidate the approved disposition without skipping the blocker or moving every old timer to now. A new real blocker is visible as such. | Burst catch-up, invented date, reschedule clears human/reply hold, or always-pausing implementation hides a broken positive path. |
| AC-13 | A missing engine belongs to an exhausted standard cadence still nonterminal; separately use a genuinely terminal configured paused-search outcome. | Preserve the approved response wait or separately integrated Issue 8 completion contract; preserve actual terminal evidence. No step-one reset or repeated start/clean-exit loop. | Infer completion from no remaining step, reopen terminal work, or count start acceptance as restored while the engine immediately disappears again. |
| AC-14 | Prior work is dispatch-pending, accepted, uncertain or in flight when the engine ends; include an old activity returning after replacement starts, a provably unattempted pending control and a documented definitely-unaccepted retryable attempt. | Keep exact message/request/occurrence identity and claims; consume progress only under existing durable completion rules. No repeat possibly accepted send or replayed originating action. The proven pending control can dispatch once and the definitely-unaccepted control retains its ordinary bounded retry through 17-A with current checks. Uncertainty policy is unchanged. | NOT_FOUND, a PENDING/FAILED label or missing provider ID proves no prior call; clear ambiguous claims, re-draft a claimed touch, block every pending first dispatch or silently enable 17-B. |
| AC-15 | Recover with each of the five original outbox instruction kinds and applicable mode-specific payloads; interrupt delivery after accepted start. | Original identity/meaning survives; actual delivery/application or unresolved/superseded status is evidenced through 2-A. Initialization cannot lose required wake-up/control effects. | Start alone marks SENT, generic reschedule replaces inbound/resume/unblock semantics, or pending instruction disappears. |
| AC-16 | Reorder/duplicate older pause, resume, unblock and inbound instructions around reconstruction and a newer control decision. | Per-kind freshness and original identity prevent stale control or duplicate side effects; necessary wake-ups are retained or explicitly superseded with evidence. | Last-arrival-wins flags, age-only blanket dropping, or reconstructing the DB state counted as a command receipt. |
| AC-17 | Two sweepers, an initial enrollment starter, reactive dispatcher and approved support retry compete for the same intended execution. | Real independent ownership and verified Temporal conflict handling permit at most one current intended actor; already-running must match lineage and does not discard instructions. | Process-local lock/fake counter proof, random replacement IDs or duplicated active business runs. |
| AC-18 | Temporal accepts a start but its response is lost; repeat after DB outcome commit failure and with delayed worker initialization. | Same target is reconciled without an independent start; acceptance/unknown and reconstruction-pending are accurate until applied evidence exists. | Blind retry with a fresh ID, false definite failure or “restored” from an accepted RPC alone. |
| AC-19 | Crash before/after recovery claim commit, before/after external start, during reconstruction and before/after result commit. | Independent DB sessions and real engine tests demonstrate the approved recoverable boundaries, retained attempts/evidence and safe stale work. | Rolled-back claim treated as durable, lost earlier batch outcomes, or external action authorized only by uncommitted state. |
| AC-20 | A claim expires, another owner proceeds, and the old owner later attempts a start or writes success/failure; repeat with a newer pause/successor. | Stale-start/bootstrap and outcome fencing prevent effects on current work; retained evidence is monotonic and belongs to the right attempt/run. | Lease expiry grants two senders, only the DB receipt is fenced, or late failure erases verified restoration. |
| AC-21 | Probes/start attempts fail repeatedly or accepted replacements immediately exit; restart the recovery worker and run further scans. | Persisted separate retry/churn bounds, accurate next attempt and final owned attention/hold. A new scan/run ID or transient RUNNING observation cannot reset exhaustion. | Infinite daily resurrection, unbounded inner loop, attempt counter reset on crash or invisible exhausted candidate. |
| AC-22 | Start is accepted while the application worker is down, then reconstruction fails or later succeeds; separately stop the reconciler itself. | Start accepted remains distinct from restored; overdue reconstruction and stale scan coverage are observable through the approved independent operational check. Existing running work is not duplicated. | Self-reported success counter treated as worker-health proof, permanent green badge or another start to repair worker availability. |
| AC-23 | Persistence/accounting is unavailable; separately process a bad candidate alongside valid ones and recover after the outage. | Honest operational failure, no false saved hold/empty scan/zero-usage result; required committed evidence and unrelated safe work are preserved. | Treat DB failure as missing user configuration, fail-open start capacity or one bad item silently loses every batch result. |
| AC-24 | Recover known-begun prior-day, known-never-begun and unknown-start enrollments, including a delayed first action crossing the approved day boundary. | Known-begun is not charged again; never-begun respects 3-A's current valid capacity/day; unknown follows approved evidence/containment. No new enrollment or timestamp rewrite. | Every restart bypasses the cap, every resume consumes a new slot, or null started_at is universal unused capacity. |
| AC-25 | After correcting an operational cause, request scoped engine recovery for an already-active/queued lead; repeat the request, lose the response and race a new restriction. | Usable permission-checked path without fake pause/retag; stable recovery reference, actor/reason, bounded attempts and current-state validation. Fresh reads show actual outcome. | Unconditional status reset, force-resume endpoint, repeat business action or recovery available only by creating another enrollment. |
| AC-26 | Read/act as assigned agent, unrelated agent, permitted wider role, inactive member and another workspace; include unowned and missing-anchor cases. | Existing visibility plus separately approved action rights hold across detail, counts, references and operator procedures. Unattachable failures reach scoped support without fabricated records. | Cross-tenant leakage, service-role API exposure, manager-scope invention or granting broader permissions to fix navigation. |
| AC-27 | Read recovery pending, accepted, restored-in-wait, restored-but-held, blocked and stale/unavailable evidence through actual API/client contracts. | Business phase, engine evidence and instruction state remain distinct with honest times/copy; loading, empty and error states are different and refresh retains results. | Fixture-only new fields, “from step 1,” accepted equals applied, stale next_action_at implies scheduled or error renders healthy. |
| AC-28 | Page beyond unrelated first-page rows, mark an episode seen, retry it, resolve it, then observe renewed loss or a separate instruction failure. | Scope-before-pagination, complete traversal, declared counts and stable episode identity. Seen never resolves; new/unrelated unresolved work remains actionable. | Alert per sweep/attempt, double-counted engine/instruction projections or acknowledged incidents disappear as solved. |
| AC-29 | Inventory synthetic historical failed starts, expired histories, false-SENT instructions, uncertain sends, deliberate stops and conflicting/insufficient lineage. | Evidence strength and current reconstructability are explicit; only approved evidence-sufficient cases qualify, unknowns remain visible. No fabricated lost history/start/stop times. | Treat expired history as never-ran, trust every old SENT, bulk replay all commands or infer no provider side effect from no receipt. |
| AC-30 | Rehearse canary cutover, historical containment, recovery-rate limits and rollback with old/new workers, schemas, inputs and representative Temporal history replay. | Only the approved cohort can auto-recover; stale incompatible writers are contained, old histories remain compatible or explicitly owned, rollback stops reactivation without erasing evidence/claims. | Deployment drains the backlog, forced engine resets substitute for replay, or old dispatcher restores false SENT/restart churn. |
| AC-31 | Demonstrate synthetic enrollment → committed failed start → independent scheduled check → actual reconstruction → fresh API/UI evidence → permitted due action, plus blocked/support-recovery case. | Complete journey with real Postgres/Temporal where claimed and recording providers. One intended due submission, retained future waits/instructions, usable owned failure and no manual trigger needed for eligible discovery. | Mocked starter plus static screenshot used as end-to-end proof, manual run_once only used as production scheduling proof or real-customer test sends. |
| AC-32 | Run normal enrollment, ordinary nurture, replies, holds, handoffs, opt-outs/DNC, workspace controls and declared A/B baseline regressions alongside recovery. | Working eligible sends and every independent safeguard remain; no new contact/fallback/tag/reply/uncertainty policy, completion rule or re-entry right. | All nurture disabled to pass negative tests or a Class B behavior hidden in a Class A recovery PR. |

AC-29–30 authorize synthetic rehearsals only, not production inspection or mutation. Fill exact
R1/R2 thresholds/dispositions before tests. Existing positive/protected controls may already pass;
required skipped integrations remain missing evidence, not a green acceptance result.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Enrollment/start → independent recovery → read:** run the actual committed-start-failure path,
  then the approved periodic reconciliation entry point with no signal. Observe same-run restoration
  and durable status through public application/API reads (AC-01–02/06/11–15/24/31).
- **Inspection adapter → evidence classification:** direct current execution inspection in a real
  Temporal test environment, closed/live-chain/not-found/unknown cases and correct deployment
  identity. Hand-written transport fakes can simulate outages but do not prove SDK/server semantics
  or retention behavior (AC-03–05/18/22/29).
- **Persistence and concurrency:** explicitly agreed repository/transaction contracts against real
  migrated Postgres with independent sessions, claims, lost commits, stale owners, complete scoped
  traversal, retry/churn persistence and first-start accounting (AC-06–11/17–24/28–30).
- **Execution reconstruction and instructions:** actual workflow test environment and application
  activities, including standard/recurring identity, restored timers/waits, startup races, send
  claims and retained instructions. Replay representative existing/new histories; engine stubs do
  not prove absence of duplicate effects (AC-02–05/10–21/30–32).
- **Operator journey:** approved API/action permissions and existing web route/API tests for
  discovery, detail, correction/retry, count/pagination/seen/error and truthful copy; demonstrate
  synthetic API-to-UI data, not fixture-only promises (AC-25–28/31).
- **Runtime and containment:** verify the actual deployed scheduling/worker entry point is wired,
  runs without outbox activity, resumes coverage after interruption and exposes stale-sweep failure.
  Rehearse operational bounds, controlled canary and rollback without customer sends (AC-06/21–23/30–31).

**Allowed fakes:** fixed clocks, recording CRM/LLM/messaging transports and hand-written repository/
engine-port fakes for fast application scenarios. Do not fake the identity, eligibility, authority,
reconstruction, permission or deduplication decision under test. Expected times, states and counts
come from approved literal scenarios, not another call to the production decision helper. An
integration-named file using fake sessions is not real persistence/Temporal evidence.

1. Begin with AC-01 after boundary approval: demonstrate on the unchanged baseline that a committed
   failed start remains stranded without an instruction. Observe persisted identity and the absent
   safe recovery through the agreed public boundary. Existing tests that merely expect FAILED or
   preserve rows are useful setup, not a red test of the missing periodic recovery.
2. If the agreed periodic entry point is new, use only the smallest non-working seam needed to
   exercise that behavior and record it separately from the unchanged-baseline reproduction. An
   import error, absent proposed enum/method or stub programmed to return the assertion is not the
   defect reproduction. No recovery algorithm is written before meaningful red evidence exists.
3. Implement the smallest vertical slice, run it green, then add the next failing case: prior
   progress/future timer, unknown health, retained instruction or competing start as appropriate.
   Do not write a speculative suite of private-helper tests and then build toward its implementation.
4. Preserve existing restart tests' useful lineage/mode assertions while coordinating replacement
   of 2-A's false SENT expectation. Test actual instruction processing, not only a starter call.
   Do not double-own the same code fix across tickets or treat a previously green bug assertion as
   approval to drop the original command.
5. Add real transaction/Temporal tests at each claimed boundary before declaring durability,
   concurrency, run-chain, startup or replay behavior complete. Start with the smallest test, then
   its file/package and affected safety regressions. No dependency/browser project is authorized.
6. Prove critical tests are sensitive: remove the unknown-health guard, identity/state recheck,
   stale-owner protection or retained-claim check in a controlled local test mutation and show the
   corresponding test fails. Pair no-duplicate/no-send assertions with real due/future positive
   controls; do not weaken safeguards or disable the whole system to make tests green.
7. Have an independent reviewer check expectations against the source issue, R1–R4 and the actual
   released A/B policy. Attach commands, revisions, meaningful red/green, pass/fail/skip counts and
   integration limitations. A real blocker remains open rather than being relabeled success.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Fill during implementation | Not run in this draft | Required before the change | Required | Required where applicable | Explicit, never hidden as pass |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. A new liveness inspection,
reconciliation worker, recovery action or receipt model is not claimed to exist. Inventory all real
production callers/commit points before changing a shared interface or adding optional dependencies.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — committed enrollment and new-run boundary | app/application/services/campaign_enrollment_starter.py; app/application/services/paused_search_track_assignment.py; app/domain/campaigns/enrollment_admission.py |
| API — reactive recovery and runtime entry | app/application/use_cases/dispatch_temporal_signals.py; app/interfaces/workers/temporal_signal_dispatcher_worker.py; scripts/start_workers.py; Makefile |
| API — engine ports, adapter, execution and activities | app/application/ports/temporal.py; app/infrastructure/workflows/temporal/starter.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/worker.py |
| API — business state and stored lineage | app/domain/workflows/models.py; app/infrastructure/persistence/postgres/workflow_repository.py; app/infrastructure/persistence/postgres/campaign_enrollment_repository.py; app/infrastructure/persistence/postgres/temporal_signal_outbox_repository.py |
| API — schedule/reconstruction and current controls | app/application/use_cases/campaign_cadence_execution.py; app/application/use_cases/schedule_next_paused_search_action.py; app/application/services/workspace_automation_control.py; app/application/use_cases/lead_resume.py |
| API — operator reads and wiring | app/application/use_cases/lead_read.py; app/interfaces/api/v1/leads.py |
| Web — detail, attention and client | src/pages/LeadDetailPage.tsx; src/pages/AttentionPage.tsx; src/lib/api/leads.ts; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/agentAttentionItems.ts |

**Two approaches to review before coding:**
- **Recommended: a small periodic application worker sharing one guarded recovery contract with
  reactive delivery.** Explicit full-population traversal and independent retry/coverage make the
  missed-start gap easy to operate and test without fake signals. Adapter-only execution inspection
  preserves existing boundaries. Cost: another runtime responsibility and durable bounded progress
  to own; interval/batch sizing trades detection latency against database/Temporal load.
- **Alternative: add bounded independent reconciliation to an existing suitable worker/scheduler.**
  Reuse deployment and timing machinery, but scan regardless of pending signals and share the same
  recovery contract. Fewer processes may suit V1; coupling can starve scans or delivery and shares
  their failure domain. Prove scheduling fairness, independent stale-sweep monitoring and outage
  recovery. Merely improving the outbox not-found branch does not satisfy this option.

Choose the smallest approach that satisfies complete detection and recovery. Do not build a
generic orchestration layer or put the only detector behind the unavailable engine it must inspect
without an independently owned failure signal. Keep Temporal/SQL details in adapters, use approved
additive migrations and retain existing active-workflow/enrollment constraints. Recovery ownership
must not become a second independent enrollment or contact-permission system.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_start_selected_campaign_batch.py
- tests/application/use_cases/test_dispatch_temporal_signals.py
- tests/application/use_cases/test_lead_resume.py
- tests/application/use_cases/test_lead_read.py
- tests/application/use_cases/test_paused_search_track_assignment.py
- tests/infrastructure/persistence/postgres/test_workflow_repository.py
- tests/infrastructure/persistence/postgres/test_campaign_enrollment_repository.py
- tests/infrastructure/persistence/postgres/test_temporal_signal_outbox_repository.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/infrastructure/test_temporal_starter.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/test_temporal_paused_search_track_matrix.py
- tests/infrastructure/test_temporal_worker.py

Locate the existing web route/API tests and worker wiring tests on the implementation branch before
adding coverage. Do not cite a guessed new test path or an unused proposed worker as existing proof.

## 7. Historical inventory and bounded recovery

Production reads/changes need separately approved scope and access. Rehearse this on synthetic data.

- Inventory by exact workspace/business workflow/enrollment: expected engine, actual current
  execution observation, original start evidence, pinned mode/configuration, next disposition,
  controls, send claims, pending instructions and containment intent. Record evidence strength and
  last checked time, not an invented missing-since timestamp.
- Separate never-started, later-lost, still-running/waiting, intentional protected/terminal,
  superseded, deliberately stopped, conflicting and unknown cases. A failed initial response may
  hide an accepted start; expired engine history may hide prior sends. Do not infer either away.
- Include legacy false-SENT instruction records under 2-A's evidence contract. Neither trust all
  historical SENT nor replay every instruction. Reconcile still-relevant work by identity/current
  authority, retaining uncertainty when applied evidence is absent.
- For eligible evidence-sufficient cases, preserve existing progress and reconstruct only the safe
  next disposition. Never manufacture enrollment/start/end times, reopen terminal rows, reset
  touch/AI budgets, release send claims, overwrite published versions or run enrollment again.
- If old data cannot establish mode, first-start capacity, pending send outcome or correct linkage,
  contain that route and expose the reason/remedy. Do not default unknowns into automated contact
  or permanently hide them merely because they are not automatic-recovery candidates.
- Approve the exact recovery cohort, current safeguards, rate, dry-run output, operator, canary
  evidence and stop criteria before any historical reactivation. Recovery can restore previously
  absent traffic even though no new contact policy or enrollment was added. Do not drain the backlog
  as a validation exercise; do not revive intentionally stopped executions.
- Make authorized recovery idempotent, race-safe and auditable. Keep original evidence plus the
  correction/attempt actor, reason and result. Unrecoverable history remains explicitly unknown;
  4-A retention changes cannot recreate data already deleted.
- Deployment repairs the future path, not every old incident. Accepted-live requires verified
  treatment of the in-scope cohort or explicit containment with a named follow-up and usable support
  route. A count of “started” engines alone is not that evidence.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test gates and record exact A/B baseline, safety
   dependencies, approved cohort, bounds and owners. Verify the intended Temporal environment/
   namespace/task queue and actual worker/deployment wiring without exposing credentials.
2. **Safe rehearsal:** demonstrate AC-31 plus unknown inspection, concurrent/ambiguous starts,
   initial commit failure, repeated accepted-then-closed churn, protected-state/successor race,
   retained instructions/claims, genuine waits and due positive control using recording providers.
3. **Compatible cutover:** stage approved additive schema, identity/evidence readers, shared
   recovery/dispatcher, engine and API/web changes. Contain incompatible old paths that can bypass
   ownership, drop instructions or misstate recovery; replay old histories before enabling action.
4. **Observe before acting:** run the approved observation-only cohort and verify complete scope,
   unknown-versus-missing classification and operator presentation. Observation-only is a rollout
   stage, not fulfillment of automatic recovery. Authorize the canary action separately.
5. **Bounded activation:** enable recovery for the approved reconstructable cohort/rate; verify
   existing enrollments, progress, true engine reconstruction, future waits and one legitimate due
   touch. Keep historical unknowns, protected cases and intentionally stopped work contained.
6. **Operator acceptance:** show an eligible lost engine recovered without a new instruction,
   honest start-pending versus restored evidence, a blocked/unknown case, and scoped support retry
   after correction. Explain that a restored engine can still be held and never means step one.
7. **Monitor:** last successful sweep and full-coverage age; unknown checks; missing candidates;
   reconstruction-pending age; bounded recovery/churn/exhaustion; stale/duplicate rejections;
   instruction backlog; legitimate outreach and duplicate-request signals. Name who acts when
   scanning stops or a canary churns. Do not expose tenant data in global monitoring.

**Rollback:** first stop automatic recovery/start attempts through the approved scoped runtime
control, without deleting observations, claims, instructions or business history. Fence in-flight
stale attempts and contain incompatible workers; do not blindly terminate healthy already-restored
executions or undo their irreversible sends. Keep existing human/consent/reply holds and correctly
running work under a compatible forward-fix/rollback plan. Do not restore false-success badges,
clear uncertain claims, reset progress, drop required schema or mass replay to “try again.”
Rollback of the detector does not repair remaining missing engines: retain visible owned follow-up.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact, Class A scope and unchanged behavior; applicable
  R1–R4/test boundaries close with named owners before their implementation/release.
- [ ] A genuinely periodic production path finds failed initial starts and later lost executions
  without a chance instruction, with complete scoped traversal and truthful unavailable coverage.
- [ ] Exactly the approved eligible same journey is reconstructed under real conflict/transaction/
  race protection; paused/human-controlled/terminal/superseded and deliberately stopped work stays
  protected. Original mode, progress, first-start accounting and send/instruction identities survive.
- [ ] Recovery acceptance is distinct from reconstructed execution, instruction application and
  provider delivery. Attempts/churn are durably bounded and every unresolved outcome has a usable
  scoped operator route without new enrollment or weakened human-resume permissions.
- [ ] API/UI discovery, detail, actions, permissions, pagination/counts, seen/error/freshness and
  next-step copy are demonstrated with real contract data, including restored-but-held outcomes.
- [ ] Meaningful red-first, green, critical sensitivity and unchanged positive/safety evidence are
  recorded; required real Postgres/Temporal, replay, runtime and API-to-UI checks passed rather than
  being replaced by mocks, skipped tests or static screenshots.
- [ ] Historical scope/containment, compatible cutover, canary monitoring and evidence-preserving
  rollback are rehearsed and separately authorized where live access/actions are involved.
- [ ] Independent product and technical reviewers accept the implemented journey; merged and
  accepted-live are evidenced separately. This draft does not mark implementation boxes complete.

## 10. Related records and draft review record

- [Source Issue 7 — independent recovery and corrected restart facts](../production-state-consistency-issues.md#issue-7--a-live-lead-with-no-running-automation-is-only-ever-restarted-by-accident)
- [Business-impact contract — same campaign, not new enrollment](../production-state-consistency-issues.md#7--recover-a-missing-engine-without-restarting-the-business-campaign)
- [D1–D7 consensus and separate ship classes](../production-state-consistency-review-consensus.md)
- [2-A — shared restart and original instruction delivery](issue-2-a-reliable-instruction-delivery.md)
- [1-A — scheduling holds and safe recovery](issue-1-a-visible-scheduling-holds.md)
- [5-A — send-time holds and occurrence safety](issue-5-a-durable-send-time-holds.md)
- [6-A — explicit cannot-proceed outcomes and preserved waits](issue-6-a-visible-cannot-proceed-outcomes.md)
- [3-A — first-action evidence and daily-start capacity](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [4-A — durable evidence and historical limitations](issue-4-a-retained-operational-evidence.md)
- [17-A — committed send claims and same-touch safety](issue-17-a-durable-outbound-dispatch.md)
- [9-A — STOP and unprocessed-reply safeguards](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [16-A — preserve recorded opt-outs](issue-16-a-preserve-opt-outs-during-crm-refresh.md)

Draft source trace completed against API a761c1b and web 04d4361 on 2026-09-08. It distinguishes
reactive not-found restart from an independent periodic check, committed failed enrollment starts,
protected business states, running response waits, unknown health and instruction delivery evidence.
No production count, environment health, history reconstruction or behavioral test result is claimed.

Independent product-reader and technical/source reviews completed, with focused runtime/web source
checks and source-based adjudication. Product-reader review found no material contract ambiguity.
Final clarifications distinguish the existing business-ID guard from full execution correlation and
preserve a proven unattempted intent's first dispatch without permitting an ambiguous resend.
Manual resume remains distinct from reactive restart; retaining an outbox name is not proof of
instruction delivery. Paused-search durable dispatch remains required 17-A integration, not an
exclusion or a claim that it already works. No proposed acceptance scenario is reported as passed.

Documentation validation passed with exit code 0: ten ordered sections, 32 distinct acceptance
scenarios, four gate rows, table/whitespace checks, 40 existing source/test references and 18 unique
local links across this draft and index, including both source-heading targets. All fourteen drafts
are indexed; the prior thirteen match their recorded aggregate checksum. Both source worktrees
remain clean at the reviewed revisions. These are document checks, not behavioral acceptance.

R1–R4 and stakeholder review remain open. No application code or prior ticket draft was changed;
no behavioral tests, production access, Jira publication, implementation or release ran.