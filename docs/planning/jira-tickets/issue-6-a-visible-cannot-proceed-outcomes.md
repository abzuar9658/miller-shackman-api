# Issue 6-A — Make cannot-proceed outcomes visible instead of silently ending nurture

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the thirteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not approve production access, historical repair, sends or release.

## 1. Business impact — read this first

**The promise:** When automation cannot find the configuration or current action it needs, it must
say what is wrong and remain safely recoverable. It must not quietly finish while the product still
shows a lead in nurture. A genuinely finished journey, a human-controlled pause and a configuration
problem are different outcomes and must remain different.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | Scheduling or execution returns “cannot proceed,” and the engine treats that as successful completion without a matching business-state change. The lead can remain queued, active or waiting for a reply even though no engine is listening. |
| What will an affected agent see? | An explicit “Automation held — configuration needs attention” explanation for a new recoverable configuration problem, with the actual cause, discovery time and permitted remedy. An existing human pause or handoff keeps its own state and explanation. |
| Does “no next step” prove nurture finished? | No. It can mean an empty or inconsistent configuration, an obsolete instruction, an unavailable track, an already-protected lead or a legitimate response wait. The system must distinguish them before deciding what to do. |
| Is the last standard-cadence send currently an engine exit? | No. That engine waits for close while the lead remains waiting for a reply. Issue 8 owns completion and its late-reply contract. This ticket prevents a later scheduling pass or restart from mistaking that nonterminal wait for permission to exit or send again. |
| Is a blocked contact sent or counted as a touch? | No, when this defect is detected before dispatch. Preserve the same journey and unconsumed work. Any separate send already attempted keeps its real claim and evidence; the new hold cannot undo it. |
| How does recovery work? | Correct the actual cause through a permitted data/admin/support action, then explicitly request revalidation and continuation. A valid recovery continues from preserved progress on the permitted schedule, not from step one. |
| Can every agent fix the configuration? | No. The agent can discover the problem and identify the required remedy; some corrections require an administrator or engineering operator. This ticket adds no configuration permissions and does not permit editing an immutable published version in place. |
| Does saving a correction, marking seen or delivering a signal mean recovered? | No. Correction saved, recovery requested, engine accepted and authoritative recovery applied are separate facts. Unresolved work stays discoverable. |
| What if the lead, workflow or workspace is genuinely unavailable? | Do not manufacture records or offer a fictional Resume action. Use an explicit, scoped operational exception with a named support route when a normal lead hold cannot be recorded. A database outage is not a missing user setting. |
| Are notifications or outreach rules changing? | No new email, SMS, push or escalation timer. Require durable in-product attention for identifiable leads and an approved operational destination for unattachable failures. Preserve contact, consent, human-control, provider and timing policy. |
| Will deployment revive old stranded leads? | Not automatically. Inventory and classify them using evidence, then obtain separate approval for any recovery. General missing-engine reconciliation remains Issue 7. |

**A new status string is not enough.** The business outcome, persisted reason, engine behavior and
operator journey must agree. Neither “pause everything” nor “mark everything completed” fixes the
classification defect.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — silent loss of nurture and recovery; confirm at publication |
| Source / delivery class | Production-state consistency Issue 6 / **Class A: visible cannot-proceed outcomes** |
| Components | Schedule/execute short-circuits; workflow and decision persistence; activity/result contracts; Temporal waits; scoped attention and permission-checked recovery |
| Repositories | miller-schackman-api and miller-schackman-web; complete product journey, not an engine-only conditional |
| Sequence | Thirteenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A, 4-A and 5-A. Draft order does not mean predecessors shipped. |
| Shared hold foundation | Integrate/reuse the approved 1-A/5-A hold identity, persistence, occurrence protection, discovery and correction contracts. Extend them for general configuration/structural causes rather than creating a competing queue or review model. |
| Other integration dependencies | Declare the actual baseline. Reuse 2-A instruction identity and delivery truth, 3-A enrollment projection, 4-A decision evidence and 17-A send identity/commit guarantees where integrated. Preserve 16-A opt-out and 9-A reply safety. |
| Adjacent ownership | Issue 7: independent missing-engine reconciliation. Issue 8: completion/late replies, not a new completion rule here. Issue 10: exhausted engine/activity failures. Issue 15: background-work dead letters. This ticket must still deliver its own live hold-to-recovery journey. |
| Not a prerequisite | Shipping 13-B, 14-B or 17-B. Preserve the separately released policy on the actual baseline; do not import an unshipped B behavior. |
| Decision ownership | Name implementer, independent reviewer, workflow/persistence owner, API/web owner and release/recovery operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No production state was inspected; retrace the implementation branch. |
| Closure boundary | Every in-scope returned cannot-proceed result has an explicit business/engine disposition; repairable live journeys remain visibly held and recoverable; protected waits and real terminal outcomes are preserved. |

**Included:** configuration and structural short-circuits at scheduling/execution; missing or
inconsistent current action references; paused-search result flattening not already repaired by
1-A/5-A; preservation of stored human-control and response waits; absence/error classification;
complete activity-result propagation, scoped discovery, recovery, tests and bounded rollout.

**Excluded:**
- Redesigning schedule-time/send-time timing holds already owned by 1-A/5-A. Shared branches must
  have one implementation and integration tests, not competing ownership or a second hold episode.
- Choosing a new completion deadline, late-reply behavior, re-entry permission, default date,
  replacement track/template or migration policy. Issue 8/G1 remains separate.
- New consent/fallback, carrier-error, tag-only CRM control, reply retry/notification or uncertain-send
  policy. **D7: Class A and Class B must not share a PR.**
- Universal engine/job failure handling, a new generic rules/incident framework, automatic repair
  of missing entities, bulk restart/replay, or sending real customer traffic to demonstrate recovery.
- Editing the previous twelve drafts or treating their open implementation/release gates as closed.

## 3. Current behavior and contract to approve

### 3.1 The source-confirmed failure is result flattening, not lack of a status enum

Temporal continues only for explicitly handled results. Scheduling that is neither scheduled,
hold/review nor terminal returns the snapshot and completes the run. Execution also returns for
unrecognized results outside its wait/continue/send branches. None of those generic returns proves
that the same business workflow is terminal.

The execution fallthrough is shared by MISSING_CAMPAIGN_CONFIG, MISSING_WORKSPACE, NO_WORKFLOW,
NO_CADENCE_STEP and ALREADY_WAITING_FOR_RESPONSE. Fixing only the last one leaves the other exits
intact; the R1 matrix and engine tests must cover each applicable producer through that boundary.

| Traced boundary | Existing behavior / relevant gap |
| --- | --- |
| Missing campaign configuration | Both schedule and execute look up configuration before loading the workflow. MISSING_CAMPAIGN_CONFIG therefore returns without a workflow object even if a live row exists. Missing identity in that result is not evidence that the workflow is absent. |
| Standard schedule has no selected step | An empty cadence or a current_step_id absent from that cadence produces NO_CADENCE_STEP without the already-loaded workflow in the result. It is not an audited completion transition. |
| Generic no-step result | Terminal-state and WAITING_FOR_RESPONSE/no-cursor/no-next-action guard variants carry the workflow in their NO_CADENCE_STEP result, unlike the empty/unmatched-step variant. The waiting guard can also encounter unavailable paused-search dependencies/version or a touch limit; its shape alone does not prove legitimate standard exhaustion. |
| Paused-search schedule mapping | _paused_search_schedule_result forwards SCHEDULED, NO_WORKFLOW, TERMINAL, REVIEW and HOLD, but flattens remaining outcomes such as NO_TRACK, NO_PROFILE and WORKFLOW_NOT_SENDABLE to NO_CADENCE_STEP. A paused/handed-off recurring journey can therefore lose its engine. |
| Profile terminology | NO_PROFILE is returned when the lead lookup returns None, but carries the already-loaded workflow. A present lead without a paused-search profile is instead represented as inactive profile data. Neither automatically means a missing re-engagement date or permission to reactivate; a carried workflow does not prove an attached hold is legally writable after deletion. |
| Execution structural guards | Missing requested step, unavailable pinned track, missing immutable template binding and a reminder lacking its required planned occurrence can return NO_CADENCE_STEP. Distinguish a broken current action from a stale action against valid newer progress. 5-A owns the timing revalidation gate itself. |
| Missing workspace | Workspace lookup returning None yields MISSING_WORKSPACE without a matching hold transition. A thrown database/network error is a different path, not this returned business result. |
| Existing response wait | ALREADY_WAITING_FOR_RESPONSE is returned by execution but is not handled by the engine's send/wait branches. Separately, SENT/ALREADY_SENT with has_more_steps=False already waits for close. The latter is Issue 8, not evidence of this engine-exit defect. |
| Standard human-control protection | With otherwise valid configuration, standard execution returns SKIPPED for paused/handoff/human-owned states and the engine schedules again. Preserve no-send and recovery behavior; do not claim this branch currently exits or blanket-convert every SKIPPED into review. |
| Activity and engine contracts | activities.py explicitly constructs result objects; lead_nurture.py separately coerces mappings and records snapshots. Defaults such as has_more_steps=False and missing scheduled_for cannot supply the missing business meaning. Both execution modes and delegated activity entry points matter. |
| Operator discovery and recovery | Admin attention derives lead items from paused/human_handoff rows; agent attention also includes human_owned. Admin attention already includes outbound-send exceptions, but these are not configuration holds. Generic resume checks permissions/contactability and changes state before queuing an instruction; it does not prove configuration revalidation or applied engine recovery. |

Published paused-search occurrence/touch/duration outcomes already transition through the scheduler
when correctly wired: complete, close or pause for configured review. Preserve that policy and
original reason. 5-A separately addresses its send-time dependency-forwarding gap; a configured
review is nonterminal, not a completed enrollment.

The phase planner reaches _hold_result, which emits WORKFLOW_NOT_SENDABLE before the outer mapping;
the occurrence planner also has its own result adapter. R1 chooses one state-aware classification
seam and covers the full public path. Do not indiscriminately reuse _terminal_schedule_status:
that helper returns REVIEW for PAUSED and TERMINAL for every other state under its configured-limit
assumption. It is not a general terminal-state predicate; handoff and human ownership are nonterminal.

Flattened meaning is not universal identity loss. The paused-search mapper preserves its workflow,
including NO_PROFILE, and activity converters forward workflow_id when that workflow is present.
Preserve usable identity and verify current authority/constraints where required; do not mandate an
extra database read when the safely loaded current object already suffices. Missing identity in an
early result still needs the R1/R2 resolution contract, never a guess about the latest lead workflow.

### 3.2 Approve an explicit outcome matrix before changing the engine

Classify by **current business identity, state, reason and action evidence**, not status text alone.
R1 must inventory each early return and its exact producer, including branches shared with 1-A/5-A.

| Situation confirmed at the current boundary | Required disposition |
| --- | --- |
| Same business workflow is already COMPLETED, SUPPRESSED or CLOSED | Preserve its committed state/reason and existing enrollment projection; the matching engine can end. No duplicate transition, new hold, reopening or success claim based only on an input signal. |
| Same workflow is PAUSED, HUMAN_HANDOFF or HUMAN_OWNED | Preserve its original controlling state, reason and authority; remain in a non-sending recoverable wait. Do not replace a human-control reason with generic configuration failure or let reschedule alone resume it. |
| Existing nonterminal response wait, including confirmed exhaustion after a standard final send | Preserve the no-send response wait on schedule re-entry and ALREADY_WAITING_FOR_RESPONSE. If an approved Issue 8 completion contract is integrated, follow that separately tested contract. Otherwise do not invent completion, review, re-entry or another first step. |
| Identifiable live workflow cannot load required campaign/track configuration or its current step/template/required action reference is invalid | Record the shared durable nonterminal operational hold with a precise cause and permitted data/admin/support remedy. Invalidate the obsolete executable schedule without consuming progress; keep the engine recoverable. |
| Requested step/version belongs to an obsolete activity or a superseded workflow | Fence the stale instruction. Re-evaluate only the legitimate current journey as its existing contract permits; do not hold, reset or overwrite a healthy successor because an old instruction is invalid. |
| Returned missing lead/workspace/workflow leaves enough trustworthy current context to attach a safe hold | Use that verified identity and the approved absence-specific disposition; no provider call. Recheck deletion, tenant context and referential constraints rather than assuming a missing-row simulation is a legal production state. |
| No valid same-workflow/tenant anchor remains, or an orphaned execution is verified | Record an explicit operational disposition through the R1/R3 destination and contain the execution. A verified obsolete/orphaned run may be closed as such, not recorded as completed nurture for an existing live lead. Never create replacement tenant/lead/workflow rows to satisfy a foreign key. |
| A repository raises an infrastructure error rather than returning an absent record | Preserve explicit retry/failure semantics; no dispatch or fabricated “configuration missing” success. Exhaustion visibility belongs to Issue 10. A dependency outage cannot be proved fixed by a user pressing Resume. |
| Legitimate scheduled future action, deferral, quiet-hour adjustment or stale-step recomputation | Preserve the existing safe timer/recompute path and due-send positive control. No extra review solely because no message is due now. |
| Existing 1-A/5-A hold, message review, dispatch-pending or provider/uncertainty result | Preserve the appropriate integrated hold/wait/dispatch policy and evidence. Do not merge these into a universal configuration pause or import 17-B. |
| Unknown status or internally inconsistent scheduled/execution payload | No implicit successful completion or provider call. Produce a controlled, observable contract failure with a recoverable disposition under R2; do not guess completion from an omitted boolean/time or spin indefinitely. |

Absence of configuration must not overwrite a newer terminal or human-control decision. Conversely,
an existing 6-A hold must retain its real cause when re-evaluation encounters “not sendable.” R1
defines precedence and supplemental evidence when independent problems coexist; it does not erase
one problem merely to display another.

### 3.3 Commit a truthful business outcome and preserve the journey

1. Reuse the 1-A/5-A nonterminal hold contract: validated state transition, stable cause, bounded
   actionable detail, decision/transition history and discoverable episode. Include origin
   (schedule or execution), detection time, workspace/lead/business workflow and the relevant pinned
   campaign/track, action and engine identities. Link an occurrence/message/request only if it exists.
   No new state, field, table, endpoint or framework is pre-approved by this draft.
2. Resolve the intended workflow even when configuration lookup returned first. Validate the engine
   input against the actual business workflow, enrollment and version lineage; “latest for lead” is
   not sufficient authority to mutate a successor. Approve how older inputs lacking an explicit
   workflow ID are safely resolved or rejected, including the standard-cadence activity contract.
3. Commit the protective state, invalidation of stale executable work, required evidence and hold
   episode consistently through the actual unit of work. Respect existing lock ordering. If the
   write/commit fails, return an explicit recoverable failure, not a successful hold with partial
   state or a provider call anyway. An engine-only snapshot or log line is not the durable hold.
4. Preserve enrollment identity, completed progress, logical touches, occurrence number, pinned
   versions and send/idempotency claims. Reuse 1-A/5-A non-consuming occurrence handling: a PAUSED
   transition must not accidentally cancel a slot that the scheduler counts as consumed. No skipped
   touch, dummy occurrence, counter reset or invented first-action time. Terminal enrollment changes
   require the actual terminal business outcome, not merely an engine return.
5. Use database-backed episode/deduplication rules shared across schedule/execution retries. An
   unchanged cause retains its original detection time; a changed cause remains explainable, and a
   later episode remains actionable after resolution. Do not overwrite a resolved review or let
   occurrence-level uniqueness/old acknowledgement hide recurrence. Keep history after recovery.
6. For absence without a usable tenant/lead anchor, R1/R3 must name the durable operational evidence
   destination, authorized reader, owner and next action. Record only trustworthy opaque identifiers,
   attempted boundary, detection time and disposition. Do not bypass tenant isolation or create an
   impossible lead-level review. If no existing destination can satisfy this, its smallest justified
   extension is an explicit acceptance prerequisite, not an assumed capability or a new general queue.
7. Keep unavailable storage distinct from a committed operational record. Surface explicit failure
   through approved operational health/error handling; do not claim evidence was saved during an
   outage. Generic exhausted-retry escalation is Issue 10, not a hidden retry/notification policy here.
8. Use allowlisted reason categories and bounded details, not raw exceptions, CRM payloads, message
   bodies or credentials. Reuse 4-A evidence/read contracts. Original cause/time is not rewritten
   from today's configuration, and a successful later send does not erase the hold.
9. A confirmed pre-dispatch hold fences stale timers and any queued request at the integrated final
   send boundary. Where 17-A is integrated, preserve its claim and completion guarantees. If a call
   may already have reached a provider, retain its actual evidence and separately released policy;
   no recall promise, new-key resend or fabricated delivery. Do not reimplement durable dispatch here.

### 3.4 Keep waits real and make recovery authoritative

1. Carry the approved disposition through use-case results, explicit activity conversions, serialized
   mappings, snapshots and both execution modes. Keep business decisions in domain/application code
   behind ports; Temporal owns timers/signals, not a second business-state authority. A status rename,
   has_more_steps=True workaround or endless SKIPPED loop is not the fix.
2. Newly held and already human-controlled journeys remain in a durable, non-spinning wait. Preserve
   the existing response-wait meaning separately. R2 must name the signals that wake evaluation and
   the actions that authorize recovery; a wake-up does not waive a hold, unresolved reply or handoff.
   An early/duplicate/late instruction cannot be lost or made authoritative against a newer episode.
3. Expose correction through an existing permitted configuration/data action or a concrete support
   route. Restoring availability is not permission to pick an arbitrary newer version, edit immutable
   published content, reactivate an intentionally inactive profile or start a fresh enrollment.
4. Require explicit permission-checked recovery for a new operational hold, with current tenant,
   membership/ownership, workflow/enrollment/version, episode and actor/reason validation. Existing
   human-control and terminal states keep their own rules; no additional manager/agent capabilities.
5. Revalidate the actual root cause and all current resume/send safeguards before declaring recovery.
   When evaluating a held candidate, use the approved candidate-state seam: passing PAUSED directly
   to a planner that always returns WORKFLOW_NOT_SENDABLE is not useful validation, and committing
   ACTIVE first to get past that guard is unsafe. Still blocked means still discoverable with a reason.
6. Generic Resume, message approval, send-now or an occurrence skip must not bypass an unresolved
   same-journey structural hold. Preserve unrelated, legitimately authorized human actions; this
   ticket neither blocks inbound safety processing nor grants a new route around its protections.
7. Successful recovery recomputes from preserved progress under the existing timing rules. Keep
   the actual step/occurrence and scheduled time consistent. Future work waits; an otherwise valid
   due action proceeds once through normal dispatch. Never restore an old activity's time as authority.
8. Make state/schedule/episode resolution and any outbox instruction recoverable across commit
   boundaries, response loss and duplicate requests, reusing 2-A. A queued or accepted signal is not
   proof the root cause was resolved or a schedule applied. Keep unresolved recovery visible until
   authoritative outcome evidence exists; never resolve on enqueue alone.
9. Test the real engine's wait, permitted wake-up and next action across activity replay and worker
   restart. An unfamiliar result or an obsolete worker must not complete silently. Do not merely
   replace successful engine completion with an invisible failed execution; state/error handling and
   the applicable Issue 10 boundary must be explicit.
10. If the exact engine is already closed/missing, ordinary signaling cannot wake it. Use only a
    separately supported same-business-workflow recovery contract, or show actionable pending/failed
    recovery with its 2-A/7 dependency. This exception does not waive the live-engine recovery proof
    required here or authorize a generic reconciler, step-one restart or bulk signal replay.

### 3.5 Complete the scoped operator journey

- Fresh lead status, next-action narrative, history and attention/review counts must tell the same
  story: configuration hold, human-controlled wait, awaiting response, actually terminal, or a named
  operational exception. No obsolete due date presented as planned contact and no fake draft approval.
- Show the actual cause, origin/time, affected configuration and role-permitted correction or named
  administrator/support action. Reuse 1-A/5-A surfaces. Agents need a reachable own-lead route, not a
  forbidden global queue; preserve existing wider-role scope, including unowned/unmapped cases.
  Do not invent a manager-only-team restriction absent from the current permission contract.
- Apply tenant/current-ownership checks and hold filters before pagination/counting. The attention
  helpers currently read a default lead page and filter it; one page is not a complete hold inventory.
  Provide complete bounded traversal without fetching every lead into the browser.
- Correlate one episode across lead and queue projections, without hiding independent handoff,
  provider or reply problems. Seen is acknowledgement only; unresolved seen work remains findable.
  Changed causes/new episodes must not inherit stale acknowledgement or resolved-review state.
- Distinguish loading, genuinely empty, failed read, denied access, stale/conflicting action, invalid
  correction, correction saved, recovery requested and applied recovery. Refresh affected queries
  after actions. No live-push requirement; no “was signaled” copy as final proof of success.
- A deleted/unavailable tenant may make the ordinary application view impossible. Its R1/R3
  operational destination must still support safe investigation and disposition, without widening
  customer visibility or falsely promising that an assigned agent can repair a missing workspace.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Outcome, identity and persistence | Approve the complete producer/branch/reason matrix, protection precedence, exhausted-wait distinction, shared 1-A/5-A episode identity, exact-workflow resolution, lock/transaction boundaries and non-consuming progress. Specify real absence/orphan constraints and the evidence disposition when no tenant/lead hold can be attached. | Application/persistence implementation |
| R2 — Engine and recovery contract | Approve result/input conversion and compatibility, wait/signal behavior in both modes, current-identity fencing, root-cause/candidate-state validation, authorized correction/recovery, authoritative schedule and queued-versus-applied evidence. Name actual 2-A/7/8/10/17-A integration dependencies; no implicit new lifecycle or retry policy. | Workflow/recovery implementation and integrated acceptance |
| R3 — Operator/read contract | Agree on cause/action vocabulary, reachable own-lead and existing wider-role paths, scoped filters/paging/counts/acknowledgement, mutation/error states and the exact controlled destination/owner for unattachable operational exceptions. | API/web/read implementation |
| R4 — Cutover and historical cases | Name owners and baseline, compatible schema/API/web/activity/worker order, Temporal history/version strategy, real integration evidence, scoped dry-run inventory, separately approved recovery/containment, monitoring and safe rollback. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. These are engineering and
verification decisions, not permission to reopen settled contact policy or call partial plumbing done.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic records, fixed clocks,
independently expected times/counts and recording providers. Return real absence from an approved
repository boundary where needed; do not fabricate the hold/result that the application must produce.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A verified, otherwise eligible current live workflow exists but required campaign configuration is unavailable; exercise scheduling and execution separately. | Same journey commits the R1 configuration hold with reason/time/history and a discoverable episode; engine remains recoverable, no dispatch. Missing workflow field in the old result does not lose identity. | Active-looking successful engine exit, assuming NO_WORKFLOW from absent result identity, replacement configuration or send. |
| AC-02 | Current standard cadence is empty or current_step_id is absent from it; separately execute a genuinely missing current step. | Specific structural hold, preserved progress and permitted remedy. A fresh read shows the cause, not completed nurture. | Empty configuration treated as legitimate exhaustion, cursor reset to first step, generic transient error only or message counted as sent. |
| AC-03 | Paused-search scheduling encounters NO_TRACK, NO_PROFILE or deliberately inactive profile; test pinned/unpinned and present/absent lead distinctions. | Each follows its approved R1 disposition and shared 1-A/5-A ownership; identifiable failures stay recoverable, real absence is operationally visible and deliberate controls remain intact. | Everything called missing date, fabricated lead/profile, automatic pin/reactivation or silent NO_CADENCE_STEP completion. |
| AC-04 | A current action loses an immutable template binding or its required planned occurrence; compare an obsolete activity referring to an old valid action. | Current structural failure is held/escalated with real identity; stale work cannot damage valid current progress. | Dummy occurrence/template, skip to clear, arbitrary version replacement, or holding a healthy successor solely because an old action is invalid. |
| AC-05 | Workspace lookup returns None; separately raise a repository outage, and model a verified deletion where a tenant-level hold cannot legally be saved. | Returned absence, infrastructure failure and unattached anomaly follow distinct R1 dispositions, with no send, explicit operational owner/evidence and no false saved-state claim. | Exception swallowed as absent config, retry storm, impossible foreign-key hold, tenant recreation, cross-tenant fallback or healthy-success report. |
| AC-06 | The exact workflow is absent, superseded or cannot be safely resolved from legacy input; include MISSING_CAMPAIGN_CONFIG with an existing workflow as a contrasting case. | No mutation of an arbitrary latest workflow. Verified orphan/stale disposition is observable; unresolved identity stays contained with named next action. | No-op completion labeled completed nurture, invented workflow, step-one restart, or treating missing config-result identity as proof of deletion. |
| AC-07 | Paused-search scheduling or execution sees an existing manual PAUSED, HUMAN_HANDOFF or HUMAN_OWNED state, including after worker restart and without a newly delivered pause signal. | Original state/reason/owner preserved; engine stays in a non-sending recoverable wait; only its existing authorized recovery can unblock it. | Generic config reason overwrites human control, engine exits on not-sendable, reschedule silently resumes, or nonterminal enrollment is terminalized. |
| AC-08 | Same workflow is already COMPLETED/CLOSED/SUPPRESSED; separately reach a published paused-search limit configured to complete, close or pause for review. Also lose configuration after a controlling state has committed. | Matching committed state/transition reason and existing enrollment projection win; terminal engines can end. Configured review remains PAUSED/nonterminal with its limit reason and a recoverable wait. | New generic hold over terminal state, duplicate transition, suppression invented as a track-limit outcome, changed limit policy, paused review counted as completed or unshipped consent behavior. |
| AC-09 | Run a standard final send, then separately start a scheduling pass against its established WAITING_FOR_RESPONSE/no-cursor state. | Existing final-send wait remains a positive control; schedule re-entry also preserves a no-send wait, or follows a separately integrated approved Issue 8 contract. | Claim the original final send currently exits; new completion/late-reply deadline, automatic re-entry, review invented solely from exhaustion or resending step one. |
| AC-10 | Actual execution produces ALREADY_WAITING_FOR_RESPONSE for the current touch. | Engine preserves the legitimate non-sending response wait with accurate stored/read state. | Unrecognized-status successful exit, duplicate send, forced review or has_more_steps manipulation. |
| AC-11 | Exercise shared 1-A/5-A hold cases and unchanged future/quiet-hour/stale-step deferrals, standard human-control skips and applicable dispatch/provider waits. | One consistent outcome contract without duplicate holds; existing legitimate waits and due traffic survive on the declared A/B baseline. | Turning every skip into review, hiding a wait as finished, duplicate queue model or shipping unrelated provider/CRM/consent policy. |
| AC-12 | Re-evaluate an unchanged 6-A hold from scheduler, execution and repeated signals; later change the cause or resolve and encounter it again. | Stable episode/original time and preserved explanation for duplicates; changed/new episodes remain auditable/actionable, including occurrence-less cases. | Generic not-sendable replaces root cause, a new entry on every retry or old review uniqueness/acknowledgement hides recurrence. |
| AC-13 | Fail required hold/evidence/schedule writes and commit boundaries, then retry after process restart. | Approved atomicity, explicit recoverable failure, no dispatch and one complete outcome after successful commit. | Success with partial state, executable old schedule alongside held/resolved review or memory/logging as sole business evidence. |
| AC-14 | Independent database sessions concurrently discover the same cause or race correction against a newer hold. | Database-backed convergence and current-episode checks preserve one effective decision and full history. | Process-local dedupe, overwriting the newer cause, duplicate transition/progress or success from a rolled-back write. |
| AC-15 | Hold/retry/recover with prior sends and an open unsent occurrence; separately exercise supported no-occurrence standard cadence. | Same enrollment, pinned version, progress and send claims; hold does not consume/cancel a counted slot or fabricate action/start evidence. | Lost completed progress, skipped unsent touch, dummy occurrence, re-enrollment or new send key. |
| AC-16 | Deliver a delayed activity/result/recovery action against a later workflow, different pinned version or newer protection; include missing-config early returns. | Exact business identity/lineage is verified before change; stale work is rejected or safely ignored without changing the successor or its claims. | Mutating whichever row is latest for the lead or reviving obsolete work. |
| AC-17 | Deliver unknown result status or inconsistent scheduled payload lacking its required time/step through the activity contract. | Controlled observable contract failure, no send and an explicit recoverable/operational disposition; compatibility behavior follows R2. | Default fields imply completed work, status silently ignored, invisible failed engine substituted for invisible completed engine or endless looping. |
| AC-18 | Restore configuration availability but only save the correction, mark seen or send a reschedule/timing-update instruction. | Evaluation may wake, but explicit hold recovery and other protections remain; UI distinguishes saved/seen from applied recovery. | Automatic approval, send, lost instruction or review resolution on acknowledgement. |
| AC-19 | Explicitly request recovery while the root cause persists; attempt generic Resume, approval, send-now or skip on the same unresolved journey. | Backend revalidation leaves an actionable hold without transiently making it sendable. Wrong-role corrections are denied with a usable escalation explanation. | UI-only guard, commit ACTIVE before validation, unauthorized immutable config edit or bypass through a second entry point. |
| AC-20 | Correct the cause through a sanctioned action and recover when the preserved next action is legitimately due. | One authoritative continuation and one protected due action; original identity, completed progress and history remain. | Never-send implementation passes, step-one reset, duplicate contact or signal accepted described as delivered message. |
| AC-21 | Correct/recover to an independently expected future time while old activity/occurrence data contains an earlier time. | Current schedule/occurrence agree, real engine waits until the expected time and one otherwise permitted touch proceeds. | Stale scheduled_for authorizes contact, immediate send, invented timing fallback or a second occurrence. |
| AC-22 | Concurrent recovery requests, lost API response and failed instruction delivery cross existing inner commits. | Stable command/episode identity and recoverable state; requested, accepted and applied are distinguishable on fresh reads. | Resolve on enqueue, lost review/instruction, duplicate engine starts or duplicate sends. |
| AC-23 | Race hold/recovery with manual pause, unresolved inbound reply, handoff, global DNC, channel opt-out/CRM refresh or terminal supersession; deliver early/duplicate/late signals. | Current authority, 9-A inbound safety and integrated consent policy remain; no lost wake-up or unauthorized recovery, no cleared opt-out. | Hold blocks safety processing, ordinary reschedule overrides a human decision, every channel block becomes global terminal or unshipped B policy is imported. |
| AC-24 | Use real Temporal activities/waits, then restart workers and replay representative old/new histories while held and during recovery. | Engine remains open without busy-looping, persisted outcome/progress survives, and permitted current-identity signals drive the intended action. | Private flag/fake wait treated as proof, replay nondeterminism, lost early signal or restart from step one. |
| AC-25 | Recovery targets a closed/missing exact engine, with delayed instruction and possible successor. | Only supported same-workflow recovery or discoverable pending/failed recovery with an explicit 2-A/7 dependency. Live-engine recovery is still proven separately. | Ordinary signal claimed to wake a closed run, silent restart/reset or generic automatic reconciler smuggled in. |
| AC-26 | List/count/page/read/act as own agent, unrelated agent, existing wider role, inactive member and another workspace; include unowned leads and holds beyond 100 unrelated rows. | Current scope/filter before paging/counting, complete bounded traversal and reachable permitted remedy. Unattachable cases use the approved controlled operator route. | First-page false emptiness, tenant/count leakage, invented manager scope or forbidden global queue as the only agent path. |
| AC-27 | Project one episode across status/history/attention/review; mark seen, change cause, recover and hold again. | Consistent counts/reasons; unresolved seen cases remain discoverable, changed/new episodes actionable and independent problems visible. | Seen resolves hold, double-count one episode or dedupe hides independent handoff/provider/reply work. |
| AC-28 | Exercise loading, empty, read failure, denied/stale action, invalid correction, correction saved, pending instruction and applied future/due action; include synthetic sensitive error text. | Honest distinct UI/API states, refreshed affected queries and bounded allowlisted evidence. Role-limited remedies explain who can act. | Error rendered as empty, “was signaled” treated as final recovery, secret-bearing/raw payload evidence or scheduled/accepted called delivered. |
| AC-29 | Old timer or queued request reaches final dispatch after hold; separately a provider call may already have succeeded before a crash or concurrent hold. | Pre-dispatch hold prevents the old send; possible prior acceptance retains its integrated 17-A claim/evidence and separately released uncertainty/callback policy. | Recall promise, new-key resend, fabricated delivery or 17-B implemented inside this A ticket. |
| AC-30 | Dry-run legacy inventory includes confirmed early exits, final-response waits, valid future waits, human/terminal states, absent entities, uncertain sends and missing evidence. | Distinct evidence-based categories, unknowns retained and exact current identity/progress for any separately proposed recovery. | Null next-action or engine NotFound alone proves 6-A; invented historical cause, bulk resume/reset or real-customer test traffic. |
| AC-31 | Rehearse migration and mixed API/web/activity/worker versions plus rollback using synthetic held, waiting, terminal and orphan cases. | Approved compatible rollout, preserved hold/history/claims and controlled handling by old versions; incompatible workers contained. | New status silently completes old worker, rollback drops protective data or schema compatibility mistaken for Temporal replay compatibility. |
| AC-32 | Demonstrate unavailable configuration → actual application hold → committed evidence → real engine wait → scoped agent discovery → permitted correction/recovery → authoritative future wait → one due action. | Coherent end-to-end product behavior, independently expected timing and recording-provider evidence; integration gaps named. | Pre-seeded hold result, manual row fix during demo or unit/mock success presented as complete integration proof. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Schedule/execute → fresh business reads:** real use cases and actual classification/transition
  behavior, observed through approved lead/attention/history interfaces. Repository absence may be
  supplied by a hand-written fake, but the decision to hold/wait/end must be real (AC-01–12/18–21).
- **Persistence and identity:** migrated real Postgres repository contracts and actual unit of work,
  independent sessions and faults around commits. These are explicit approved seams for atomicity,
  referential validity, episode identity and occurrence accounting, not private-helper or SQL-text
  tests replacing the product assertions (AC-05–06/12–16/22–23/26/29–31).
- **Engine/result/dispatch contract:** real Temporal test and replay environment with actual
  application activities, serialization and recording external transports. Verify execution remains
  running, wait/wake behavior, exact identity, no dispatch and legitimate recovery (AC-07–11/16–25/29/31–32).
- **Operator journey:** existing API permissions/read/action contracts and frontend route/component
  tests plus a synthetic API-to-UI flow, including the operational route for unattached failures
  (AC-05–06/18–23/25–28/32). This draft does not authorize a new browser/dependency project or live access.

**Allowed fakes:** hand-written CRM/LLM/provider transports, fixed clocks and repositories for fast
application tests. Do not fake classification, hold persistence, authorization, outcome conversion,
deduplication or resume decisions under test. Engine mapping tests with stubbed activity results
are useful unit coverage, not proof that production activities produce those results or actually wait.

AC-07 must cover actual planner → scheduler result → outer mapping → activity conversion → engine
behavior through the approved use-case/engine seams. Exercise both applicable planner paths and
execution modes; no private-helper test or prescribed helper edit substitutes for that integration.

Missing-record tests must identify their level. A port returning None is valid defensive contract
coverage; it does not prove that deleting a referenced workspace/version while retaining its lead
is legal in Postgres. Integration cases must respect actual constraints and model real deletion,
legacy input or fault boundaries without disabling integrity checks to manufacture a red test.

1. Start with AC-01 after seam approval: an identifiable live workflow and an unavailable required
   configuration at the existing repository boundary. Call the current schedule/execute use case;
   assert the **positive expected persisted hold and specific reason** through the agreed fresh read,
   plus zero provider calls. Unchanged code must fail that business assertion, not merely fail to
   import a proposed enum or endpoint. Missing result.workflow is the gap to fix, not the assertion.
2. Add its vertical engine slice: production activity logic produces the cannot-proceed result,
   and a bounded Temporal assertion proves the run stays open in the proper wait. Drive an explicit
   recovery to an independently expected future/due action. Do not await completion forever or read
   private _send_blocked as the acceptance evidence.
3. Work one scenario → meaningful red → minimal complete fix → same test green. No implementation
   first with retrofitted tests, all imagined tests first, or weakening assertions around open gates.
   Record necessary seam scaffolding separately from the business failure; public test APIs must be
   agreed, not invented solely to fail.
4. Preserve positive controls: normal due send, future deferral, standard human-control no-send,
   real terminal outcomes and the existing final-send response wait. Already-correct behavior needs
   a justified baseline pass, not an artificial red. Newly fixed incidental cases need sensitivity
   evidence if the original defect no longer reproduces after an earlier vertical slice.
5. Independently remove the hold write; restore generic result exit; conflate terminal with paused,
   handoff or human-owned; drop ALREADY_WAITING handling; lose workflow identity on missing config; bypass root-cause or
   permission checks; consume an occurrence; reuse its old time; resolve on enqueue; or drop a
   current-episode check. The corresponding critical test must fail for the intended protection.
   Restore and rerun each change; no sensitivity mutation ships.
6. Use actual activity dependency wiring for occurrence/progress, not a reduced fake path that omits
   cancellation or send-request repositories. Independently review literal expectations against §4
   and the declared integrated A/B baseline. Never derive expected times with the production planner.
7. Record exact commands/revisions, meaningful failing assertion, exit code and pass/fail/skip counts.
   Missing real Postgres, Temporal replay or API-to-UI evidence stays an owned integration gap.
   Do not describe this planning document or a passing status-mapping unit test as a working repair.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each applicable case | Reproducible invocation | Business assertion and revision | Revision, exit code and counts | Intended protection failure or justified baseline pass | Named limitation and owner |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. Retrace actual writers,
dependencies and consumers before changing a result or persistence contract.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — returned outcomes and selectors | app/application/use_cases/campaign_cadence_execution.py; app/application/use_cases/schedule_next_paused_search_action.py; app/domain/campaigns/paused_search_timing.py |
| API — authoritative state and transitions | app/domain/workflows/models.py; app/application/use_cases/apply_workflow_state_transition.py; app/infrastructure/persistence/postgres/workflow_repository.py |
| API — configuration and occurrence/review persistence | app/infrastructure/persistence/postgres/campaign_execution_repository.py; app/infrastructure/persistence/postgres/paused_search_occurrence_repository.py; app/infrastructure/persistence/postgres/paused_search_review_repository.py |
| API — engine input/result, conversion and recovery | app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/starter.py; app/application/use_cases/lead_resume.py; app/application/use_cases/paused_search_operations.py |
| API — current reads and final dispatch | app/application/use_cases/lead_read.py; app/application/services/lead_cadence_progress.py; app/interfaces/api/v1/leads.py; app/interfaces/api/v1/attention.py; app/application/use_cases/send_outbound_message.py; app/application/use_cases/dispatch_outbound_send_requests.py |
| Web — discovery, action and contracts | src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/attentionVersions.ts; src/lib/api/leads.ts |

In activities.py inspect both explicit outcome-to-result converters and delegated activity names.
In lead_nurture.py inspect coercion, snapshots, generic returns, both wait predicates and signals.
Preserving a field on one dataclass alone does not transmit or validate it across these boundaries.

**Compare two narrow approaches at R1/R2:**
- **Recommended starting point:** explicit application disposition alongside a bounded cause/identity
  contract, using the shared 1-A/5-A hold and existing Temporal wait/recovery seams. Clearer exhaustive
  handling and fewer ambiguous engine decisions; costs compatible result/input changes and replay
  verification. No generic rules framework or new queue needed by default.
- **Alternative:** preserve existing result types, enrich cause/identity evidence and centralize the
  small state-aware mapping at the existing application/activity boundary before the engine acts.
  Less contract churn, but generic NO_CADENCE_STEP remains easy to misuse and every producer/consumer
  must prove it cannot fall through. Neither option authorizes new contact or completion policy.

Do not infer terminality from a missing timestamp/step, blanket-map NO_CADENCE_STEP to review, set
has_more_steps merely to keep the loop alive, or add unbounded automatic polling. Keep vendor SDKs
in infrastructure/interfaces and business state in Postgres, not in a second engine-only ledger.

**Existing test starting points, not claimed complete coverage:**
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_schedule_next_paused_search_action.py
- tests/application/use_cases/test_lead_resume.py; tests/application/use_cases/test_lead_read.py
- tests/application/use_cases/test_attention_acknowledgements.py
- tests/domain/workflows/test_workflow_transitions.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/test_temporal_starter.py
- tests/infrastructure/persistence/postgres/test_workflow_repository.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_postgres_e2e.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/interfaces/api/v1/test_leads.py; tests/interfaces/api/v1/test_attention.py
- Web: src/app/LeadsRoutes.test.tsx; src/components/operations/operations.test.tsx

Inspect fixtures: an infrastructure/E2E filename does not prove real engine or persistence coverage.
Run the smallest approved pytest node/file with Python 3.12/uv, then relevant application, Postgres
and Temporal suites plus make lint, make typecheck and make test. For web changes run focused Vitest,
then pnpm test, pnpm typecheck and pnpm lint. Record unavailable services, not assumed passes.

## 7. Existing stranded leads and bounded recovery

- Prepare a separately authorized, scoped read-only inventory of exact workflow/enrollment and
  engine identities, current state/progress, retained decision/transition evidence, pinned versions,
  occurrences and send claims. Use approved opaque references/counts, not customer payload dumps.
- Separate confirmed 6-A exits, 1-A waits, 5-A exits, legitimate future/response waits, human/terminal
  protection, superseded/orphaned runs, infrastructure failures and unknowns. Null next-action,
  missing engine history or NotFound alone is not a diagnosis; Issue 8 usually has a waiting engine.
- Do not infer old causes or timestamps from present-day configuration. Record a current evaluation
  as current, with provenance, and leave unavailable historical evidence unknown. 4-A cannot restore
  deleted history. Replaying old activities is not a safe way to reconstruct what happened.
- For any proposed recovery, establish current authority, valid same-workflow configuration and
  actual unconsumed progress/send claims. Use the supported 2-A/7 recovery contract or report a named
  blocked case. Missing configuration is not authorization to create new records or repin a journey.
- Any production inventory, containment or repair requires approved environment/workspace/workflow
  scope, owner, commands, batch limit and stop conditions. Recovery can make overdue contacts due;
  that consequence must be reviewed. No automatic bulk resume, backfill of completed state or sends
  is authorized by this draft, and no existing waiting engine is reset merely to simplify rollout.

## 8. Deployment, monitoring and rollback

1. Record the exact integrated baseline and owners; resolve R1–R4 and applicable test gates. Reuse
   shared hold/recovery work rather than assuming earlier ticket drafts are implemented. New B
   behavior requires its own PR and owner release approval.
2. Rehearse additive persistence/read changes and compatible API/web/activity/worker rollout on
   synthetic data. Inventory live Temporal history shapes; choose the supported versioning/replay
   strategy. Extra optional fields do not make new status semantics safe for old workers.
3. Before enabling new producers, prove the intended workers understand each disposition. Prevent
   old workers from silently completing on new results; prove held/response-wait/terminal and
   unattached-exception cases. Do not terminate active runs or replay sends as a deployment shortcut.
4. Verify committed holds, exact engine waits, complete scoped discovery and correction-to-applied
   recovery with real persistence/Temporal and recording providers. Add the legitimate due-send
   positive control. A merged PR or passing fake suite is not an accepted-live product outcome.
5. Monitor new/aged unresolved causes, requested-but-unapplied recoveries, engine/business-state
   disagreements, unexpected result-contract failures and duplicates/progress anomalies, without
   secret-bearing labels. Distinguish newly exposed historical problems from fresh regressions;
   explain potentially higher visible attention counts without treating them as new failures by default.
6. Contain rollout on replay failures, silent exits, missing evidence, tenant-scope leakage, unexpected
   sends or progress changes. Use established operational controls; no invented blanket consent block.
   Keep hold/history/send claims and pending instructions through rollback. Old software that cannot
   preserve these protections must stay contained rather than clearing rows/claims to become compatible.

## 9. Definition of done

- [ ] R1–R4 decisions, owners, baseline and business/test seams are recorded and approved.
- [ ] All in-scope returned outcomes have explicit dispositions; no generic successful exit leaves
  the same live journey falsely healthy, and no unfamiliar contract becomes an invisible substitute failure.
- [ ] Recoverable configuration problems commit a shared, scoped, non-consuming hold with evidence;
  genuine absence and infrastructure failure remain distinct with a real operational destination.
- [ ] Existing terminal, human-control, final-response, timing, provider and inbound-safety behaviors
  are preserved; Issue 8 completion and unshipped Class B policy are not smuggled into this change.
- [ ] Assigned agents and existing wider roles can discover, understand and reach permitted remedies;
  queued/accepted/applied recovery, empty/error and seen/resolved states are truthful.
- [ ] Live engine wait → correction → revalidation → future/due action works through real activities
  and persistence, with identity/progress and legitimate-send controls. Closed-engine gaps are owned.
- [ ] Meaningful red-first, green, critical sensitivity, permission/concurrency and real integration/
  replay evidence are recorded; no essential case is hidden as a skip or mocked-success claim.
- [ ] Historical inventory, separately approved repair, compatible cutover, monitoring and rollback
  are rehearsed within approved scope. No fabricated history, bulk reset or real-customer test sends.
- [ ] Independent product and technical reviewers accept the implemented journey; release acceptance
  is evidenced separately from merging. This draft does not mark those implementation boxes complete.

## 10. Related records and draft review record

- [Source Issue 6 and corrected Issue 7/8 boundaries](../production-state-consistency-issues.md#issue-6--the-automation-can-finish-while-the-lead-is-still-in-nurture)
- [D1–D7 consensus and separate ship classes](../production-state-consistency-review-consensus.md)
- [1-A — shared scheduling hold and recovery](issue-1-a-visible-scheduling-holds.md)
- [5-A — shared send-time hold and occurrence safety](issue-5-a-durable-send-time-holds.md)
- [2-A — instruction identity and delivery truth](issue-2-a-reliable-instruction-delivery.md)
- [3-A — enrollment lifecycle and first-action evidence](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [4-A — durable investigation evidence](issue-4-a-retained-operational-evidence.md)
- [17-A — durable send and claim foundation](issue-17-a-durable-outbound-dispatch.md)

Draft source trace completed against API a761c1b and web 04d4361 on 2026-09-08. It distinguishes
early missing-config identity loss, overloaded no-step results, paused-search human-control exits,
unhandled already-waiting response and real absence from the original final-send wait and thrown
infrastructure failures. Existing admin provider-exception attention is not claimed missing, and
current wider-role permissions are not replaced with an assumed manager-team restriction.

Independent product-reader and technical/source reviews completed. The reader found no material
journey gaps. Technical suggestions were adjudicated against source: clarified the shared execution
fallthrough, producer-specific identity and full-path tests. Did not adopt blanket reuse of the
configured-terminal helper, a mandatory extra lookup, or the incorrect claim that every flattened
paused-search result loses workflow identity. Explicitly separated pre-existing suppression from
configured track-limit outcomes. No private-helper tests or additional product policy were prescribed.

Final documentation validation after the review clarifications passed, exit code 0: 41 existing
source/test paths, 23 per-document local links, AC-01–32, ten numbered sections, R1–R4, tables/index,
whitespace/final newlines and clean API/web source worktrees.
Prior twelve drafts' aggregate SHA-256 is unchanged:
29fd693a26c2047809c7041ae25db2b4057b8ba80066d70cbac857ba7a682dfd.
No application code changed or behavioral tests ran; no production access, Jira publication,
implementation or release occurred. R1–R4 and stakeholder review remain open.
