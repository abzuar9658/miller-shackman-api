# Issue 5-A — Keep send-time holds visible and safely recoverable

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the twelfth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not approve production access, historical repair, sends or release.

## 1. Business impact — read this first

**The promise:** If a paused-search contact was scheduled legitimately but the final check finds
that it cannot proceed, keep the lead visibly held and recoverable. “Cannot send yet” must not
quietly become “automation finished.” Correcting the cause must lead to a safe, permitted next
action on the same journey, not a fresh enrollment or a duplicate contact.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | Required timing information or the usable track can disappear after scheduling. The sender reports “no next step,” the engine exits, and the lead can still look actively nurtured. There is no running wait left to receive a later correction. |
| How is this different from Issue 1? | Issue 1 covers a hold found while deciding the schedule; the engine already waits. This ticket covers a hold discovered when executing an already-scheduled action and must prevent that engine from ending. Both use the same durable hold/recovery concept. |
| What will the agent see? | “Contact held — the final timing check needs review,” with the specific missing/invalid input, hold-start time, affected track and permitted next step. Not healthy nurture, completed work or a message awaiting approval when no draft exists. |
| Will the blocked message be sent? | Not if this hold is found before provider dispatch. No touch is consumed. A separate send already attempted or accepted must retain its real evidence and original identity; a later hold is not proof it never happened. |
| Does moving a valid contact into the future also end the engine? | No. That result already asks the engine to reschedule. Preserve it as a normal timed wait, with no new review requirement. An existing occurrence must not reuse an obsolete earlier time. |
| How does an operator recover the lead? | Correct the actual cause, then explicitly request the permitted revalidation/resume. The system checks current inputs and safeguards, recomputes the schedule and keeps recovery discoverable until its outcome is known. |
| Does correcting a date send immediately? | No. The existing track, progress, timezone, quiet hours and final send rules still decide. A future action waits; an otherwise allowed due action proceeds once through the normal sender. |
| Can “Approve,” “Skip” or “Mark seen” bypass the problem? | No. Seen is acknowledgement. A timing hold is not message approval; a generic skip must not consume an unsent touch to make the warning disappear. Existing legitimate occurrence actions stay separately permission-checked. |
| Are terminal limits or human controls changing? | No. Published occurrence/touch/duration limits keep their configured outcome. Manual pauses, unresolved replies, handoff, suppression and other independent protections cannot be overwritten by this repair. |
| Are new notifications included? | No email, SMS, push or escalation timer. The required notification is durable in-product attention/review visibility, matching lead status/history and a usable owned-lead recovery path. |
| Will this revive leads whose engine already ended? | Not automatically. Deployment prevents new failures; existing stranded leads need an evidence-based inventory and separately authorized recovery under the established instruction/missing-engine contract. |
| Is outreach policy changing? | No. This is Class A lifecycle consistency. No new timing fallback, contact permission, CRM control, uncertain-send rule, completion policy or automatic re-entry. |

**A returned “review” label alone is not the fix.** The business hold must commit durably, the
engine must remain in a recoverable wait, the old timer must be harmless, and an authorized person
must be able to find and resolve the cause without losing progress.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — silent loss of scheduled nurture and recovery; confirm at publication |
| Source / delivery class | Production-state consistency Issue 5 / **Class A: durable send-time holds** |
| Components | Paused-search execution revalidation; workflow/transition/review and occurrence persistence; Temporal activity results/waits/signals; scoped operator reads and revalidation |
| Repositories | miller-schackman-api and miller-schackman-web; complete operator journey, not a sender-only enum change |
| Sequence | Twelfth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A and 4-A. Draft order does not mean predecessors shipped. |
| Shared foundation | Integrate/reuse 1-A's approved hold episode, persistence, visibility and correction contract; extend it with send-time origin and existing-occurrence handling. Do not create a competing send-time review system. |
| Other integration dependencies | Declare the actual baseline. Reuse 2-A command identity/delivery truth, 3-A lifecycle projection, 4-A durable decision evidence and 17-A dispatch identity/commit guarantees where integrated. Preserve 16-A opt-out and 9-A reply safety. |
| Adjacent scope | Issue 6 owns general cannot-proceed/engine-state reconciliation; Issue 7 owns general missing-engine recovery; Issue 8 owns general completion. This ticket must still prove its own live hold → correction → recovery path end to end. |
| Not a prerequisite | Shipping 13-B, 14-B or 17-B. Preserve a separately released B policy on the actual baseline; do not import an unshipped policy into this repair. |
| Decision ownership | Name implementer, independent reviewer, workflow/persistence owner, API/web owner and release/recovery operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No production state was inspected for this draft; retrace the implementation branch. |
| Closure boundary | Durable, visible and recoverable in-scope send-time holds; safe current-identity rescheduling without a consumed or duplicate touch; truthful terminal outcomes and bounded historical guidance. |

**Included:** nonterminal timing/readiness outcomes from paused-search execution revalidation,
including required timing data becoming unavailable and an identifiable current workflow losing
its usable pinned track; applicable early operational gates; existing occurrence/cursor integrity;
correct propagation of configured terminal results reached at this boundary; wait/recovery,
authorized visibility, tests and rollout for this journey.

**Excluded:**
- New missing-date/default-interval policy, maintenance permissions, timezone/quiet-hour rules,
  track-selection/migration policy or automatic feature/pilot enablement.
- Broadly turning every NO_CADENCE_STEP, missing entity or dependency exception into review; all
  unrelated campaign/workspace/engine failures remain with their owner tickets. No invented lead,
  workflow, track, message or occurrence to make a hold record fit.
- New consent/fallback, carrier-failure, CRM tag-control, reply deadline, uncertain-as-sent or callback
  policy. **D7: Class A and Class B must not share a PR.**
- Universal engine restart, bulk signal replay, replay of an uncertain send, automatic historical
  repair, fresh enrollment/step-one reset on resume, or a generic hold/rules/notification framework.
- Editing the previous eleven drafts or treating their unresolved implementation/release gates as closed.

## 3. Current behavior and contract to approve

### 3.1 The precise failure, including the already-working branch

The execution gate calls schedule_next_paused_search_action again before the paused-search step
proceeds. The original valid schedule is therefore not authority to contact the lead. At this
baseline, the gate collapses **every non-SCHEDULED result to NO_CADENCE_STEP**. It does not report
these holds as SKIPPED. Temporal has no waiting branch for NO_CADENCE_STEP and returns its snapshot.

In contrast, a changed step or a valid next_action_at later than now returns **SKIPPED**, which
Temporal handles by scheduling again. The source issue explicitly corrected the earlier claim
that future deferral caused the exit. Keep that correction; do not “fix” a normal wait by adding
manual review. Whether a stored occurrence still carries an obsolete time needs its own regression.

| Traced boundary | Existing behavior / relevant gap |
| --- | --- |
| Send-time gate | _revalidate_paused_search_execution_gate maps HOLD, missing-track/profile, not-sendable and terminal/review results alike to NO_CADENCE_STEP. It needs classification, not a blanket rename of that generic result across all callers. |
| Scheduler persistence | Nonterminal _save_hold clears the paused-search step and next_action_at without a state transition/review. The early recurring-disabled/pilot-excluded HOLD bypasses that save. 1-A owns the shared durable representation. |
| Terminal propagation | The outer executor receives workflow_transition_repository, but the execution gate does not forward it to the scheduler. _save_terminal_or_hold requires it for configured occurrence/touch/duration terminal transitions; without it, it falls back to clearing the schedule. This is not a claim that opt-outs are track-limit terminal reasons. |
| Engine waiting | Scheduling HOLD/REVIEW waits on close, unblock or reschedule. Execution REVIEW waits only on close/unblock; reschedule_requested alone does not satisfy that predicate. Returning REVIEW alone therefore does not prove timing-update recovery. |
| Existing occurrence | When the plan is scheduled, the scheduler can reuse an open occurrence's scheduled_for. A newly computed later time is not automatically an update of that row. Revalidate the actual due time and identity used at dispatch. |
| Cancellation and progress | apply_workflow_state_transition can cancel open occurrences for PAUSED when that repository is supplied. CANCELLED/SKIPPED count as slot-consuming in the scheduler. Blindly wiring cancellation into a recoverable hold can discard the unsent touch. |
| Activity wiring | execute-paused-search-occurrence delegates to execute-campaign-cadence-step. Both activity entry points, result coercion/snapshots and both supported execution modes must carry the agreed meaning; a new dataclass flag alone proves nothing. |
| Review identity | PausedSearchReview supports POLICY and optional occurrence/message references, but Postgres create_or_get requires an occurrence and deduplicates workspace/occurrence/kind. Workflow-level holds and later episodes on the same occurrence need the integrated 1-A identity contract. |
| Operator recovery | Policy review resolution accepts resume_after_revalidation and delegates to generic resume, which is not proof of a valid paused-search timing plan. Inner commit points can precede saving the resolved review. The UI says the workflow “was signaled”; that is not evidence the hold was resolved or the schedule applied. |
| Operator access | Review listing limits workspace rows before filtering lead/ownership; the global review route has a wider-role gate than own-lead operations. Reuse 1-A's scoped discovery and recovery fixes, not merely a row that an assigned agent cannot reach. |

Paused-search currently bypasses the durable request path by withholding send-request/reconciliation/
provider-failure dependencies inside the executor. 17-A owns that repair. Retrace the integrated
sender/dispatcher boundary before claiming this hold also fences a queued request or survives
post-provider crashes; “repositories were constructed in the activity” is not proof of use.

### 3.2 Classify the current outcome without changing its policy

Approve the branch/reason matrix at R1, including early returns and both phase/occurrence planners.
The same existing decision must mean the same thing whether found while scheduling or executing.

| Current situation at revalidation | Required outcome |
| --- | --- |
| Missing required timing data under HOLD_FOR_REVIEW; no actionable phase or invalid pinned-track cursor | Durable nonterminal hold with the actual explanation and permitted correction, not an engine completion, guessed date or cursor reset. |
| Current workflow exists but its pinned track is missing/disabled or required profile data is unusable | Identify the actual missing/invalid input and appropriate data/admin remedy; preserve a recoverable hold where the existing outcome is nonterminal. Distinguish this from an intentionally inactive profile or nonexistent lead/workflow. |
| Applicable recurring enablement/pilot gate blocks the same live journey | Preserve the operational block and its administrator-facing cause. Do not mislabel it a missing date or change flags/allowlists. |
| Valid default-interval fallback, valid future action, quiet-hour adjustment or different currently due step | Use the existing permitted schedule/recompute behavior; no send under the stale action/time and no new manual-review requirement merely for rescheduling. |
| Known future reactivation with no permitted maintenance action | Follow the actual planner outcome; a future date alone does not make every track sendable. Preserve an existing hold rather than inventing interim contact. |
| Configured occurrence/touch/duration limit | Persist and propagate the published completed, closed or terminal-pause-for-review outcome with its original reason. Preserve appropriate enrollment/occurrence projection and waiting/ending semantics; do not substitute the new recoverable timing hold. |
| Profile deliberately deactivated, independent manual/reply/handoff block, suppression, terminal state or successor workflow | Respect current authority and reason. A stale send cannot reinstate paused search, overwrite protection, resolve a newer hold or reopen terminal work. Only a genuinely terminal outcome ends the business journey. |
| Missing lead/workflow, unrelated missing campaign/workspace, or infrastructure failure outside this boundary | No provider call or manufactured replacement state. Preserve explicit failure/absence handling and record any general consistency gap under Issue 6/7; do not claim this ticket reconciles every cannot-proceed result. |
| The same persisted hold is evaluated again | Stay held on the same episode, without replacing its explanation with generic WORKFLOW_NOT_SENDABLE, repeatedly consuming slots, exiting or busy-looping. |

Do not classify by an empty next_action_at or status string alone. Domain reason, current business
state, pinned track, episode and actual action identity all matter. A backend error is not a user's
missing date. Decisions already superseded by newer protection must not be made authoritative again.

### 3.3 Persist the hold without losing the scheduled touch

1. Extend the shared 1-A hold concept: validated nonterminal PAUSED state, stable reason, bounded
   actionable detail, transition/history and discoverable review. Record **discovered at send time**,
   original planner reason and decision time, workspace/lead/business workflow, pinned track/version,
   prior step/phase and scheduled time. Link the actual occurrence/message/request only when present.
   No new state/enum/table name is pre-approved; Postgres remains the business source of truth.
2. Commit the protective state, invalidation of the executable stale schedule, required transition/
   decision evidence and review consistently. Existing unsent work must remain non-consumed and
   non-dispatchable while held. Persistence failure is a recoverable failure, never successful HOLD
   with partial state or a provider call anyway. Use the actual unit of work and lock order.
3. Preserve logical touch counts, occurrence numbers, prior successful sends, campaign enrollment,
   pinned version and send/idempotency claims. Do not cancel/skip an unsent occurrence if that would
   consume its slot; do not replace it with another occurrence to hide the error. Approve the exact
   held-occurrence representation and pending-message/request treatment at R1, reusing 17-A where needed.
4. Use a database-safe identity for one hold episode, shared across scheduling and execution retries.
   An unchanged cause retains its original start time and acknowledgement; distinct cause changes
   remain auditable/actionable. Recovery and later recurrence must not overwrite an old resolved
   review or become invisible behind workspace/occurrence/kind uniqueness. Null occurrence cases
   still need a real create/read/dedupe contract, not a dummy occurrence.
5. Keep original decision evidence after correction, later successful send or terminal supersession.
   A hold is not a sent/failed message and does not fabricate provider evidence. Reuse 4-A's evidence
   approach; store allowlisted facts, not raw CRM/provider payloads, message bodies or secret-bearing errors.
6. Fence stale work against the **current business workflow and hold episode**, not just whichever
   workflow is latest for the lead. Validate step, occurrence, pinned version and command/review
   identity where applicable. An old activity, duplicated signal or old browser tab cannot act on a
   successor journey. Preserve existing independent safety decisions under concurrent writes.
7. If 17-A has introduced queued dispatch, enforce the approved final revalidation/fencing boundary
   there as well. A confirmed pre-dispatch hold prevents the queued send; a provider call already
   possibly accepted retains its claim and honest uncertainty. Do not claim cancellation can recall
   an in-flight message, mint a new send key, or change 17-B policy to complete this A fix.
8. No timer expires the hold into approval, automatic resume or a consumed touch. A permitted
   terminal/profile/human-control outcome can supersede it explicitly, retaining history and making
   old actions ineffective. A later callback follows the separately released policy for its own send.

### 3.4 Keep the engine waiting and make recovery authoritative

1. Propagate a typed/explicit hold outcome through application results, both activity names and
   coercion/snapshot consumers into a durable Temporal wait. Choose the smallest compatible contract
   at R2. Do not interpret has_more_steps=False, “no next step” or a missing timestamp as completion
   when the current outcome is this hold. A boolean flip or endless SKIPPED loop is not waiting.
2. Approve which existing signals trigger re-evaluation and which authorize recovery. A timing-update
   or reschedule signal can wake evaluation without waiving review or independent protection. Ensure
   the actual wait predicate consumes the intended wake-up; execution REVIEW currently differs from
   scheduling HOLD. Duplicate, early or late signals must neither be lost nor bypass the hold.
3. Save authorized corrections, then require the explicit permitted recovery action/reason under the
   shared 1-A contract. At action time verify tenant, current owner/role, current workflow, hold/review
   identity and any applicable administrative permissions. A correction save is not permission to send.
4. Revalidate current profile, pinned track/overrides, operational gates, existing resume/send
   safeguards and actual remaining progress. Evaluate the eligible candidate state safely: passing
   PAUSED straight into a planner that always returns WORKFLOW_NOT_SENDABLE is not successful
   revalidation, and committing ACTIVE first to work around that guard is not an acceptable bypass.
5. If still blocked, remain held with an accurate actionable reason. If independently protected or
   terminal, preserve that outcome and explain why recovery is unavailable. Generic Resume, timing
   update, message Approve, send-now or policy Skip must not evade an unresolved timing hold on the
   same journey. Do not remove unrelated valid message/occurrence actions.
6. On successful revalidation, recompute from preserved progress under existing timing rules. Make
   the current next action and persisted occurrence agree; never restore the original activity's old
   scheduled_for as authority. A future action waits until its independently expected due time; a
   legitimate due action uses the same non-consumed touch and normal protected dispatch identity.
7. Make workflow/schedule changes, review resolution and any outbox instruction recoverable across
   the existing inner commits, duplicate actions and lost responses. Reuse 2-A identity/delivery
   evidence. Distinguish correction saved, recovery requested, engine accepted and authoritative
   schedule applied. Keep unresolved recovery discoverable; do not close the review merely because
   generic resume returned success or the signal entered an outbox.
8. Prove the live engine waits without retry storms, accepts permitted recovery and returns to the
   correct schedule across activity retries, worker restart and replay. The next send rechecks current
   rules again. A newly changed cause can create a new hold without duplicating or consuming the touch.
9. If the exact engine run is already closed/missing, an ordinary signal cannot wake it. Use only a
   separately supported same-business-workflow recovery contract or report an actionable pending/
   failed recovery with its Issue 2/7 dependency. Never silently start at step one, claim application
   success from an unavailable engine, or advertise this ticket as a universal restart reconciler.

### 3.5 Complete the authorized operator journey

- The affected lead's status, next-action narrative, history, relevant counts and attention/review
  views must agree. Show the actual cause, when it was detected, affected track and permitted remedy;
  do not present an obsolete due time, healthy nurture, completed work or fabricated message approval.
- Reuse 1-A discovery/scoping. Assigned agents need an own-lead path that does not route them into
  a forbidden global queue; wider roles keep their existing access, including ownership gaps.
  Apply current workspace/membership/role/ownership checks before filtering, pagination and counts.
- Support complete bounded traversal beyond unrelated first-page rows. Correlate the same hold
  episode across status and queue projections rather than double-counting it; do not hide independent
  problems on the same lead. Seen is presentation only; unresolved seen work remains discoverable.
- Distinguish timing/readiness review from message approval, configured terminal review and provider
  uncertainty. Keep original cause/history after recovery, and make a substantively changed or new
  episode visible instead of inheriting stale acknowledgement or a previously resolved status.
- Show loading, no holds, read failure, permission denial, stale/conflicting action, invalid correction,
  queued recovery and applied schedule distinctly. API failure is not “nothing needs attention.”
  After a mutation, refresh affected status/history/review/attention queries; no live-push requirement.
- Explain why a remedy requires an administrator or why another protection still blocks recovery.
  Do not grant additional permissions, claim a scheduled touch was delivered, or use “workflow was
  signaled” as the final success message. No new external notification or escalation policy.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Outcome, episode and occurrence contract | Approve every in-scope branch/reason and terminal mapping, 1-A shared hold identity/fields/migration, episode recurrence and acknowledgement, current-workflow fencing, lock/transaction boundaries and non-consuming occurrence/message/request treatment. Distinguish absent entity, inactive profile and actual recoverable readiness failure. | Application/persistence implementation |
| R2 — Engine and recovery contract | Approve result/serialization and signal/wait semantics in both modes, candidate-state revalidation, authorized actions, stale-command rejection, authoritative rescheduling including stored occurrence time, review/outbox commit ordering and queued-versus-applied evidence; prove restart/replay compatibility and identify any real 2-A/7/17-A dependency. | Engine/resolution implementation and integrated acceptance |
| R3 — Operator/read contract | Agree on own-agent/wider-role paths, causes/actions, shared queue projection, scoping/paging/counts/acknowledgement and correction/requested/applied/error UI states, without wider permissions or a second queue. | API/web/read implementation |
| R4 — Cutover and stranded leads | Name owners, exact integrated baseline, compatible schema/API/web/activity/worker order, Temporal history strategy, synthetic regression evidence, scoped historical inventory and separately approved containment/recovery, monitoring and safe rollback. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. These are engineering and
verification gates, not an invitation to reopen settled contact policy. Partial shared plumbing
does not close the complete send-time hold journey.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic leads, fixed clocks,
independently worked literal times and recording providers. The original schedule must really be
valid; then change the relevant inputs before execution rather than seeding an already-held result.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Schedule a valid paused-search action under a hold-configured track; remove its required timing input before executing at the original due time, before provider I/O. | Same workflow commits a nonterminal hold with specific send-time reason/history and one pending episode; no executable stale schedule or provider call. Fresh authorized detail/attention show it. | NO_CADENCE_STEP presented as finished, active-looking stall, transient reason only, guessed date or a send. |
| AC-02 | Exercise AC-01 through each supported Temporal activity/mode with actual application revalidation. | Engine remains open in a durable non-spinning wait after the activity; persisted state and activity/snapshot meaning agree. | Merely renaming a result, returning a completed engine snapshot, manipulating has_more_steps or repeatedly scheduling without a wait. |
| AC-03 | Same identifiable current journey loses its usable pinned track or required profile input after scheduling; include disabled track and applicable early operational gates. | R1-specific hold/cause and authorized data/admin remedy; no stale send. Independently inactive/absent-entity/protected cases follow their distinct R1 treatment. | Every case labeled missing date, invented replacement track/entity, automatic enablement, or broader cannot-proceed repair claimed without coverage. |
| AC-04 | Re-evaluate an unchanged held journey repeatedly from scheduler, execution and duplicate activity delivery. | One shared pending episode and entry transition; original hold time/acknowledgement preserved, zero sends/consumption, engine stays waiting. | Schedule/send duplicates, generic not-sendable reason replacing the cause, new review on every retry or an engine exit. |
| AC-05 | Fail between required hold/workflow/schedule/review writes or at commit; inspect after retry and process restart. | Approved local atomicity, explicit recoverable failure and no dispatch; one complete durable hold after success. | Partial-success HOLD, executable old schedule alongside resolved/review state, or logs/memory as sole evidence. |
| AC-06 | Independent database sessions process the same hold decision concurrently; later change the cause and create a distinct episode after resolution. | Database-backed convergence for duplicates; preserved original history and actionable changed/new episode, including the same existing occurrence. | Process-local dedupe, overwritten resolved review, duplicate progress, or uniqueness silently suppressing every future hold. |
| AC-07 | Enter/retry/recover the hold with an open unsent occurrence; separately test a supported occurrence-less path. | Occurrence identity/number, logical touch count, pinned version and send claims remain correct; no touch consumed by the hold. Absent links remain absent. | PAUSED cancellation consumes a slot, skip-to-clear, replacement occurrence/message, counter reset or fresh enrollment. |
| AC-08 | During the hold, deliver the old timer/activity, duplicate wake-up and an already-queued but not dispatched request where 17-A is integrated. | Current hold/identity is rechecked at the real send boundary; no provider call under the obsolete schedule. | Old scheduled_for authorizes contact, timing hold reroutes channels, or an alternate entry point bypasses it. |
| AC-09 | Restore valid inputs but perform only a correction save, reschedule/timing-update signal or seen acknowledgement. | Evaluation may wake; the explicit recovery requirement and independent protections remain. UI distinguishes saved/seen from resumed. | Implicit approval/send, lost wake-up causing an unobservable stall, or acknowledgement resolving the hold. |
| AC-10 | Authorized operator requests recovery while the timing cause remains; attempt generic Resume, Approve, send-now or policy Skip against that same hold. | Hold remains actionable with accurate validation result and zero progress/send; backend enforces the boundary. | UI-only protection, ACTIVE committed before validation, or a skipped/approved occurrence used to bypass missing timing. |
| AC-11 | Correct the cause and explicitly recover when the preserved next touch is legitimately due. | Authoritative schedule/recovery succeeds; same touch proceeds once through normal send checks, history retained, no reset; truthful provider evidence. | Never sending as a way to pass hold tests, duplicate contact, lost completed progress or claiming queued means delivered. |
| AC-12 | Correct the cause and explicitly recover to a known future action; open occurrence still carries its original past due time. | Literal newly expected due time is persisted/used consistently, engine waits until then and the touch proceeds once when otherwise allowed. | Reuse the old occurrence time, send immediately, invent a delay, create a second occurrence or demand an extra review solely for a future date. |
| AC-13 | With no review-worthy cause, change timing to a valid future date or a different due step before execution; also test permitted default-interval fallback and quiet-hours adjustment. | Existing SKIPPED/recompute semantics continue with the correct actual due time/step; no unnecessary review, legitimate later traffic preserved. | Claim this was the engine-exit bug, turn every non-send into hold, use stale action/time or consume the wrong touch. |
| AC-14 | After valid recovery, change the inputs again before the next provider dispatch. | Final current-rule check blocks/defers again as appropriate; new reason/episode is visible and no duplicate touch occurs. | Treat prior approval or engine wake-up as permanent send permission. |
| AC-15 | Resume/revalidate concurrently; lose the response before/after commit; fail review saving or instruction delivery across existing inner commits. | One effective action with stable identity; consistent recoverable state, no lost review/instruction, honest pending/applied distinction on refresh. | Review disappears on enqueue, acknowledged delivery assumed applied, multiple engine starts or duplicate sends on retry. |
| AC-16 | Send an old review action/activity/signal after a newer hold, pinned-track change or successor business workflow. | Current identity/lineage is verified; stale work is rejected or safely ignored with no change to the new state/claims. | Acting on whichever workflow is latest, reviving the old track or attributing recovery to the wrong episode. |
| AC-17 | Race this hold/recovery against manual pause, unresolved reply, handoff/human ownership, global DNC or a terminal decision; include current platform opt-out evidence after CRM refresh. | Existing protection and actual released channel rules win; no overwrite or unauthorized resume. Only the appropriate independently authorized action can resolve them. | Reclassify every channel block as global terminal, clear durable opt-out, erase human reason or import unshipped B behavior. |
| AC-18 | A published occurrence/touch/duration limit becomes effective between scheduling and execution; parameterize configured complete, close and pause-for-review. | Committed workflow is COMPLETED/CLOSED with its existing terminal enrollment projection, or PAUSED with nonterminal enrollment for configured review. Matching transition/history retains the original limit reason; occurrence handling follows that outcome. Engine ends only for true terminal outcomes and waits for configured review. | Missing transition repository silently clears schedule, active-looking engine completion, terminalizing a review enrollment, new generic timing hold, changed limit policy or automatic re-entry. |
| AC-19 | Independently deactivate the profile or terminalize the journey during the hold; then deliver the old correction/resume. | Superseding state/reason and prior hold history remain; old action cannot resume it. | Automatic reactivation, new enrollment, silent review deletion or falsely reporting nurture resumed. |
| AC-20 | Restart the worker, retry an activity and replay representative existing and new engine histories while held, during a timer and during recovery. | Deterministic compatible behavior; durable wait/progress survive and permitted signals cause the intended re-evaluation once. | In-memory hold, lost early signal, replay nondeterminism, stale execution-review predicate or restart from step one. |
| AC-21 | The exact business journey has a closed/missing engine when recovery is requested; include delayed instruction delivery and a later successor. | Supported same-workflow recovery only, or discoverable pending/failed recovery with named dependency; state/claims and successor protected. | Ordinary signal claimed to wake a closed run, false recovery success, generic automatic restart or new-business-run reset. |
| AC-22 | List/filter/page/read/act as assigned agent, unrelated agent, wider authorized role, inactive member and another workspace; include unowned leads and holds beyond 100 unrelated rows. | Correct current scope before paging/counts, complete bounded traversal and reachable own-lead remedy without wider access. | First-page false emptiness, cross-tenant/count leakage or a forbidden global queue as the only recovery route. |
| AC-23 | Show the same episode in lead status, attention and review; mark seen, change cause, resolve and later hold again. | Consistent explanation/counts, no duplicate projection of one issue, unresolved seen work discoverable and changed/new episodes actionable. | Seen clears hold, stale acknowledgement hides new cause, or deduplication hides unrelated lead problems. |
| AC-24 | Exercise loading, empty, failed reads, permission/stale-action denial, invalid correction, queued recovery and applied future/due schedule. | Honest distinct UI/API states, permitted remedy and refreshed affected queries; original hold history remains readable. | “Nothing needs attention” on error, “workflow was signaled” as proof of recovery, or scheduled/accepted means delivered. |
| AC-25 | Use synthetic sensitive error/payload content in a hold cause and read its history as permitted roles. | Allowlisted bounded evidence and safe explanation with correct identity/time; no raw credentials, payloads or message content in new generic metadata. | Free-form secret-bearing errors stored or exposed, UI-only redaction, or a second sendability source. |
| AC-26 | A separate provider call may already have succeeded before a crash or concurrent later hold; retry recovery or receive a callback. | Preserve 17-A's integrated claim/evidence and the separately released uncertainty/callback policy; no new-key resend. | Claim the hold proves no contact occurred, recall an in-flight message, fabricate delivery or ship 17-B inside this A ticket. |
| AC-27 | Inventory legacy active-looking/no-next-action leads with an exact known hold exit, a valid future wait, human/terminal protection, uncertainty, successor workflow and missing evidence. | Dry-run separates cases; only separately authorized, identity-verified recovery is proposed, preserving progress and unknowns. | Null timestamp or engine NotFound alone proves this defect; bulk resume/reset or invented historical cause. |
| AC-28 | Rehearse additive migration, compatible mixed API/web/activity/worker versions and rollback on synthetic held leads. | Held state, episode history, touch/send identities and scoped reads survive; incompatible workers are contained. | Old worker treats new hold as finished, unknown result silently coerces to completion or rollback clears holds/claims. |
| AC-29 | Run unchanged standard cadence, valid paused-search maintenance/reactivation, existing message/terminal review and applicable dispatch-pending/uncertain flows on the declared baseline. | Legitimate due traffic and existing safeguards/progress behave as before outside the intended hold repair. | Blanket no-send success, changes to 13-B/14-B/17-B policy or general completion/re-entry work smuggled in. |
| AC-30 | Demonstrate valid schedule → changed input → real send-time hold → scoped agent discovery → correction/revalidation → authoritative future wait → one due touch using actual application activities and persistence. | Coherent durable product/engine journey with literal timing, original progress/history and recording-provider evidence; pending integration gaps explicitly named. | Unit/fake status alone presented as end-to-end proof, manually fixing rows during the demo or real-customer test traffic. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Execute → observable hold:** existing schedule/execute use cases, then fresh authorized lead/
  attention/review reads. Change real timing/profile inputs between schedule and execution; do not
  replace the planner/gate/transition logic with a fabricated HOLD result (AC-01/03–04/07–14/17–19).
- **Persistence/recovery contract:** migrated real Postgres repositories and actual unit of work,
  independent sessions, concurrent writers and commit-boundary faults. Repository contracts are
  approved seams for atomicity/identity/occurrence invariants, not SQL-text tests or hidden side
  channels replacing the public business assertions (AC-05–08/12/15–19/22/25–28).
- **Engine and dispatch boundary:** real Temporal test/replay environment with production activity
  wiring and recording external transports. Verify execution stays open, actual wait/signal handling,
  retries and allowed resumption; integrate the declared 17-A path (AC-02/08–09/14–16/20–21/26/28–30).
- **Operator journey:** existing API permission/contract and frontend route/component tests, plus
  the synthetic API-to-UI flow for discovery/correction/pending-versus-applied feedback (AC-22–24/30).
  No new browser/dependency project or live production exercise is authorized by this draft.

**Allowed fakes:** hand-written external CRM/LLM/provider transports, fixed clocks and repositories
for fast application tests. The CRM fixture must reflect the changed inputs so refresh does not
undo the test setup. Do not fake the timing verdict, hold persistence, authorization, dedupe or
resume decision under test. Fake wait/execute_activity tests are useful controls, not proof that
the real engine remains alive or an actual transaction commits safely.

AC-07 must exercise the actual activity dependency wiring with a real open occurrence and inspect
committed identity/progress through the approved persistence seam. AC-01 passing alone does not
prove non-consumption. The cancellation sensitivity check must fail when an unsent slot is consumed;
do not omit production dependencies just to keep the fixture green or prescribe a private-helper
call as the business test. The approved design may safely change how those dependencies are used.

1. Begin with AC-01 after seam approval: legitimately schedule, remove required timing data, run
   the existing executor and assert the positive business expectation of a persisted PAUSED hold
   with its reason through the agreed fresh read boundary, and zero provider calls. On unchanged
   code, the active/cleared-schedule result must fail that expectation. Do not import a proposed enum,
   add a no-op seam solely to manufacture red, or assert the broken NO_CADENCE_STEP result as success.
2. Follow with the engine-exit slice at AC-02: real activities produce the hold and a bounded test
   verifies the execution is still running/waiting, then drives permitted recovery. Do not simply
   await workflow completion forever, read private _send_blocked as end-to-end proof, or stub the
   execution activity to return a hold the application never produced.
3. One scenario → meaningful red → minimal complete fix → same test green. Work vertically, not
   all implementation then retrofitted tests or all imagined tests then one large implementation.
   Record minimal test-seam scaffolding separately from a business-assertion failure.
4. Protect unchanged positive controls: ordinary future/stale-step rescheduling, default fallback,
   one legitimate due send, terminal limits and independent safeguards. Use independently worked
   literal times/counts/reasons; never derive expected dates with the production planner under test.
5. Independently bypass the hold write; restore NO_CADENCE_STEP mapping; keep the old execution
   wait predicate; cancel/consume the occurrence; reuse its old time; drop current-episode checks;
   resolve on enqueue; bypass a send/permission guard; or reset progress on recovery. Each critical
   test must fail for the intended protection. Restore and rerun; no sensitivity mutation ships.
6. Independently review expectations against §4 and the actual integrated A/B baseline. Incidentally
   fixed cases need sensitivity evidence; already-working controls need a justified baseline pass,
   not an artificial defect. Never weaken assertions to accommodate an unresolved R1–R4 decision.
7. Record exact commands/revisions, meaningful failing assertions, exit codes and pass/fail/skip
   counts. Mark absent real Postgres/Temporal/replay/API-to-UI evidence as an open integration gap,
   not success. Keep live access, historical writes and release approval separate from test execution.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each applicable case | Reproducible invocation | Business assertion and revision | Revision, exit code and counts | Intended protection failure or justified baseline pass | Named limitation and owner |

## 6. Engineering starting points — navigation, not a prescribed design

Paths below are relative to the explicitly named repository at the reviewed baseline. Reuse the
integrated 1-A design and retrace all actual writers/consumers before choosing fields or changing
activity results. These are existing navigation targets, not new tests or APIs claimed to exist.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — timing and occurrence decisions | app/domain/campaigns/paused_search_timing.py; app/application/use_cases/schedule_next_paused_search_action.py; app/application/use_cases/campaign_cadence_execution.py |
| API — state, progress and persistence | app/domain/workflows/models.py; app/application/use_cases/apply_workflow_state_transition.py; app/infrastructure/persistence/postgres/workflow_repository.py; app/infrastructure/persistence/postgres/paused_search_occurrence_repository.py |
| API — review identity and recovery | app/domain/campaigns/paused_search_reviews.py; app/infrastructure/persistence/postgres/paused_search_review_repository.py; app/application/use_cases/paused_search_operations.py; app/application/use_cases/lead_resume.py; app/application/use_cases/lead_paused_search.py; app/application/use_cases/lead_workflow_overrides.py |
| API — activity, wait and signal integration | app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/starter.py |
| API — final send and current-state reads | app/application/use_cases/send_outbound_message.py; app/application/use_cases/dispatch_outbound_send_requests.py; app/application/use_cases/lead_read.py |
| Web — discovery, action and contract | src/pages/ReviewQueuePage.tsx; src/pages/LeadDetailPage.tsx; src/app/router.tsx; src/lib/api/pausedSearchOperations.ts |

In activities.py, inspect _execution_outcome_to_result as well as the two activity entry points.
It explicitly constructs the engine result: status is already forwarded, while any newly approved
hold evidence must survive this conversion and subsequent serialization/coercion. Test the complete
activity result contract rather than assuming adding a field to either dataclass transmits it.

**Compare two narrow approaches at R1/R2:**
- **Recommended starting point:** extend the shared 1-A business hold and use an explicit execution
  hold/result contract handled by the same durable wait/revalidation semantics. Clear separation
  from message review/terminal outcomes; requires serialization and existing-history compatibility.
- **Alternative:** reuse an existing execution REVIEW result but preserve a typed cause/episode and
  deliberately align the wait/signal/recovery contract. Potentially less result-schema change, but
  higher risk of confusing timing review with message approval or borrowing the wrong expiry/action.

Neither option authorizes another hold table/queue by default. A blanket NO_CADENCE_STEP → REVIEW
replacement, has_more_steps=True workaround or infinite SKIPPED loop is not an acceptable design.
Keep domain decisions/application transactions behind current ports; Temporal/SQLAlchemy stay in
adapters. Wire required dependencies through the actual execution gate, not merely its caller.

**Existing test starting points, not claimed complete coverage:**
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_schedule_next_paused_search_action.py
- tests/application/use_cases/test_paused_search_operations.py
- tests/application/use_cases/test_lead_resume.py; tests/application/use_cases/test_lead_paused_search.py
- tests/application/use_cases/test_lead_workflow_overrides.py
- tests/application/use_cases/test_lead_read.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/test_temporal_paused_search_track_matrix.py
- tests/infrastructure/persistence/postgres/test_paused_search_review_notification_repositories.py
- tests/infrastructure/persistence/postgres/test_paused_search_timing_postgres_e2e.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/interfaces/api/v1/test_attention.py
- Web: src/pages/ReviewQueuePage.test.tsx; src/app/LeadsRoutes.test.tsx
- Web: src/lib/api/pausedSearchOperations.test.ts

The existing hold_wakes_on_reschedule_signal test covers **scheduling** HOLD with monkeypatched
engine calls, not this send-time defect. Existing missing-date E2E coverage starts from scheduling;
the new regression must mutate the valid schedule before execution. Inspect fixtures rather than
claiming an infrastructure filename proves real persistence or engine integration.

Run the smallest approved pytest node/file first using Python 3.12/uv, then relevant application,
Postgres and Temporal suites plus make lint, make typecheck and make test. For web changes use
focused Vitest, then pnpm test, pnpm typecheck and pnpm lint. Record exact commands and unavailable
services; do not bring up or alter production infrastructure to make a test pass.

## 7. Existing stranded leads and bounded recovery

- Prepare a read-only scoped inventory using current business workflow/enrollment, retained timing/
  decision history, pinned track/occurrence and send/request/provider evidence, plus exact engine
  identity/status when available. Counts and approved opaque references suffice; no raw payload dump.
- Separate newly recorded holds, old schedule-time waits, confirmed send-time exits, valid future
  waits, independent protection, already-terminal/superseded journeys and unknown cases. An empty
  next-action field, engine NotFound or missing Temporal history alone is not a diagnosis.
- No missing historical reason/timestamp may be invented from today's profile. If original evidence
  is unavailable, record “prior cause unknown” and any current evaluation with its own time/provenance.
  4-A retention cannot restore deleted evidence. Do not replay old activities to manufacture it.
- For a proposed recovery, recheck current identity/permissions/protection, valid timing and actual
  touch/send claims. Retain progress and use the supported same-business-workflow engine recovery
  contract; otherwise leave an actionable blocked case with an Issue 2/7 owner. No generic reset.
- Any production inventory, containment or repair requires separately approved environment/workspace/
  workflow scope, operator, commands, batch limits and stop conditions. Rehearse a dry run on synthetic
  records; make repeated authorized actions idempotent. This draft authorizes no production writes,
  bulk resumes, new enrollments or real-customer sends.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test gates and declare integrated 1-A/2-A/17-A contracts
   plus the actual released B baseline. Name exact covered outcomes/routes, pending adjacent recovery
   dependencies and operators; do not label an incomplete hold journey done.
2. **Rehearse:** AC-30 using real Postgres and Temporal where required, recording providers and the
   scoped UI. Include a stored occurrence with a stale past time, duplicate/early signals, commit
   failures, terminal limits, safety races and representative old-history replay.
3. **Deploy compatibly:** additive schema/identity changes first where required, then compatible
   readers/API/web, activities and workers in the R4-approved order. Plan workflow patch/version or
   compatible worker routing for existing histories; do not restart/reset every run. Contain old
   workers that would consume a new result as completion or overwrite hold evidence.
4. **Handle old stalls separately:** execute only the separately approved §7 plan. Deploying a new
   wait branch does not revive a closed engine. Verify each recovered case's identity, preserved
   progress, readable reason and current schedule before removing its recovery attention.
5. **Verify live within approved synthetic scope:** show held state/history/attention after the final
   check, open non-spinning engine, denied invalid recovery, valid future rescheduling and one due
   touch. Record merged, deployed, integration-verified and accepted-live separately. A worker health
   check, HTTP 200, queued signal or unit test is not acceptance of the complete journey.
6. **Observe and brief:** monitor send-time hold causes/age, active-looking leads whose engine closed,
   duplicate episodes, pending/failed recoveries, stale-work rejections, occurrence-time divergence,
   retry/write/replay failures and queue/read errors. Explain that active counts may fall as existing
   stalls become visible; do not hide them by clearing reviews or disabling safeguards.

**Rollback:** use a compatible rollback or forward fix with affected sends/workers safely contained
under an approved plan. Preserve committed holds/reviews/history, workflow and occurrence identity,
progress, send claims and independent protection. Never drop evidence, set held leads active,
recreate occurrences, bulk-resume or replay sends to “undo” the deployment. If older workers cannot
understand the new hold contract, do not route those histories to them; retain actionable recovery
visibility until compatible handling is restored.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business outcome and Class A boundary; applicable R1–R4 and §4–5 test
  contracts close with named owners before implementation/release. No previous draft gate assumed closed.
- [ ] Every approved send-time timing/readiness branch persists/reuses the correct nonterminal hold;
  configured terminal outcomes persist their real reason/state instead of falling through silently.
- [ ] Both actual activity routes and supported modes keep the engine in a durable compatible wait;
  permitted recovery/replay works without lost signals, busy loops or false engine completion.
- [ ] Existing occurrence/time/cursor/progress/send claims survive holds and recovery; stale work
  cannot contact, consume a touch, act on a successor or override independent protection.
- [ ] Assigned agents and wider authorized operators can discover the hold, reach role-permitted
  corrections or identify the required administrator action, and observe requested versus applied
  recovery through complete scoped reads and truthful UI states. No additional permissions granted.
- [ ] Every applicable AC has meaningful red/green or justified unchanged-control/sensitivity
  evidence, exact commands/counts and real persistence/engine/API-to-UI evidence where required.
- [ ] Synthetic rollout/replay/rollback and evidence-limited historical inventory are rehearsed;
  any production repair has separate bounded approval. No invented cause, bulk replay or fresh-run reset.
- [ ] Independent review confirms shared 1-A/2-A/4-A/17-A reuse rather than competing machinery,
  no A/B policy mix and honest limitations. Merged/deployed/integration-verified/accepted-live differ.

## 10. Source references and review record

- [Main issue plan — Issue 5 and the future-deferral correction](../production-state-consistency-issues.md)
- [D1–D7 consensus — separate ship classes](../production-state-consistency-review-consensus.md)
- [Issue 1-A — shared durable hold and explicit recovery](issue-1-a-visible-scheduling-holds.md)
- [Issue 2-A — truthful instruction delivery and same-workflow recovery](issue-2-a-reliable-instruction-delivery.md)
- [Issue 3-A — lifecycle projection and preserved progress](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [Issue 4-A — durable reasons and honest historical limits](issue-4-a-retained-operational-evidence.md)
- [Issue 17-A — separate dispatch durability and send identity](issue-17-a-durable-outbound-dispatch.md)

**Draft preparation (2026-09-08):** The bounded source trace distinguishes non-scheduled
NO_CADENCE_STEP engine exits from legitimate SKIPPED future/stale-step rescheduling. It identifies
missing terminal-transition dependency forwarding, differing execution/scheduling wait predicates,
stored occurrence-time and slot-consumption hazards, shared review identity and operator recovery
gaps. Independent product-reader and technical/test-contract reviews completed. The draft clarifies
role-permitted correction, result conversion and non-consumption test sensitivity. Terminal-limit
acceptance names the committed workflow/enrollment/transition evidence; configured review stays
nonterminal, without new re-entry permission. No private-helper test or blanket terminal enrollment
requirement was adopted. Reference checks found 39 existing source/test paths and 21 per-document
local links; AC-01–30, ten numbered sections, R1–R4 and table/index consistency were checked.
The prior eleven drafts remain unchanged: aggregate SHA-256
e1775ea6897972603003719f876ea708630393c08b1155e2a9af31cbcb712f80.
Final documentation-only validation passed, exit code 0: references/links, numbering, tables/index,
whitespace/final newlines, prior-draft checksum and clean API/web source worktrees. No application
code changed or behavioral tests ran; no production access, Jira publication, implementation or release occurred.
R1–R4 and stakeholder review remain open.
