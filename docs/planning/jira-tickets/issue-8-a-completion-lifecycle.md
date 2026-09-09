# Issue 8-A — Complete the campaign without losing replies to its final message

**Status: DRAFT — stakeholder, G1 lifecycle, design and test-contract review required.**
This is the fifteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not authorize production access, historical correction, sends or release.
**G1 is unresolved. Do not build or enable the terminal transition before its reply contract is agreed.**

## 1. Business impact — read this first

**The promise:** A silent lead whose standard campaign has genuinely finished eventually has a
recorded completion, a consistent enrollment and an engine that no longer waits forever. Replies
to the final message still receive their explicitly agreed handling. An authorized operator can
later start a new eligible journey with a recorded reason; completion itself never starts one.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | After the final standard-cadence send, the workflow stays “waiting for response” without a completion deadline. Its engine normally waits for a close instruction, and its still-open workflow/enrollment blocks ordinary future enrollment. |
| What changes for agents? | Lead detail and the relevant lists/reports distinguish a valid final-response wait, recorded campaign completion, and an unresolved operational or reply-processing problem. The completion reason and time belong to the correct run. |
| Does “completed” mean the lead converted or read every message? | No. It records the agreed end of this nurture run, not a sale, handoff, provider delivery or read receipt. Existing completed outcomes can also mean “not interested”; the reason matters. |
| When exactly does it complete? | **Not decided: G1.** Choose an explicit response window or completion with explicit post-completion reply handling. No duration, clock-reset rule or immediate-close default is authorized by this draft. |
| What if the lead replies to the last message? | Ordinary replies, buying/selling interest, requests for a person, non-opt-out “not interested” replies and opt-outs must follow their approved routes before and after completion. Saving a reply or skipping an invalid state transition is not, by itself, a complete response journey. |
| Can a reply or handoff be closed by an old completion timer? | No. Processing, human control and newer authoritative decisions must be respected. G1 must define how an ongoing conversation affects the completion boundary; the implementation cannot guess. |
| Will STOP still work after completion? | Yes: the recorded contact restriction must remain effective even when the old run is terminal or its engine has closed. This ticket does not introduce channel fallback or erase completion history to record a new opt-out. |
| Can anyone press Resume to reuse the finished run? | No. Completion is terminal. Existing authorized manual re-entry creates a new enrollment/workflow with a reason; assigned-agent visibility alone does not grant terminal re-entry rights. |
| Does completion automatically enroll the lead again? | No. Dormant selection still excludes leads with prior workflows. Issue 14-B's separate tag-removal/re-add exception is not general permission to restart completed campaigns. |
| Will old completion totals immediately become correct? | Only where evidence supports the approved historical correction. Missing history or timestamps stay unknown, not estimated from an empty cursor or deployment date. |
| Is this only a new status label? | No. Workflow, enrollment, history, engine disposition, replies and manual re-entry must agree. A green UI badge over a still-open enrollment or a lost reply does not satisfy the ticket. |

**G1 is a release-critical product choice, not a harmless technical timeout.** Ending a run too early
can remove AI continuation that currently works while waiting. Leaving every final response window
unbounded merely preserves the defect. This draft defines the safeguards, not the missing decision.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — indefinite final waits, misleading lifecycle and blocked controlled re-entry; confirm at publication |
| Source / delivery class | Production-state consistency Issue 8 / **Class A: explicit completion without automatic re-entry, subject to G1** |
| Components | Standard-cadence end accounting; workflow/enrollment/history consistency; engine completion; final/late inbound routing; scoped lifecycle reads and existing manual enrollment |
| Repositories | miller-schackman-api and miller-schackman-web; complete final action → response/completion → visible outcome → controlled future enrollment journey |
| Sequence | Fifteenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A, 4-A, 5-A, 6-A and 7-A. Draft order does not establish integration or release. |
| Blocking product dependency | G1 must record completion timing, ongoing-conversation behavior and ordinary/interested/opt-out reply routes after the final action and after completion. Any changed contact/reply entitlement needs its explicit D7 classification and approval, not a hidden A change. |
| State/accounting integration | Reuse 3-A's enrollment and first-action facts, 4-A's retained same-run history, and 6-A's distinction between a valid end and “cannot proceed.” No second enrollment lifecycle or generic completion framework. |
| Safety and execution integration | Integrate 9-A unresolved-reply/STOP safety, 16-A durable opt-outs, 17-A durable send/accounting identities and 2-A/7-A instruction/recovery contracts where these boundaries intersect. R1/R2 identify exact release blockers and contained routes. |
| Not a prerequisite by itself | Releasing 13-B, 14-B or 17-B. Preserve the actual separately released consent, CRM-control and uncertain-send baseline; do not introduce an unshipped B behavior or undo a released one. |
| D2 status | The earlier automatic-volume-surge/joint-release premise is withdrawn. Completion restores controlled manual re-entry, not automatic dormant selection; 3-A remains an accounting dependency where used, not the old D2 volume gate. |
| Decision ownership | Name product/lifecycle owner, implementer, independent reviewer, persistence/engine owner, inbound/API/web owner and release/historical-correction operator. G1 and R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No live production state was inspected; retrace the implementation branch. |
| Closure boundary | An eligible silent standard run completes under the agreed contract, replies remain handled, state layers and engine agree, and authorized future enrollment works without reopening the old run. |

**Included:** standard-cadence final-action lifecycle through scheduled execution, durable dispatch
settlement/retry and the existing deferred-send-now/draft-approval paths that advance that cadence;
post-final/post-completion inbound handling; same-run evidence, engine convergence, API/UI, existing
manual re-entry, tests and bounded historical correction. Shared paused-search paths are protected
regressions, not permission to replace their separate configured end rules.

**Excluded:**
- Automatic re-enrollment, terminal Resume, new CRM tag semantics, widened role permissions,
  changed paused-search limits, new AI-turn budgets or forced human hand-back.
- New consent/fallback, carrier-error, uncertain-as-sent or classifier retry/notification policy.
  A response window is not Issue 9's separate 30-minute processing-outage policy.
- Invented completion/start/send times, treating provider uncertainty as delivery, new conversion
  KPIs, blanket historical terminalization, or real-customer messages used as test traffic.
- A new rules engine, parallel history/command system, generic workflow refactor, or an operator
  “force complete” button used instead of a reliable lifecycle.
- Editing the prior fourteen drafts or treating their remaining gates as closed.

**D7: Class A and Class B must not share a PR.** If resolving G1 requires a changed reply policy,
record and separately scope that behavior. Integrate the required approved route before enabling
completion for affected leads; “the late-reply ticket will follow” is not safe partial acceptance.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

The normal standard send path calls advance_workflow_after_outbound_send for SENT and ALREADY_SENT.
It records WAITING_FOR_RESPONSE, finds the next configured step, clears next_action_at, and clears
current_step_id when none remains. It returns has_more_steps=False without a completion transition.
The same advancement helper is called by rejected-draft approval and deferred-send-now; repairing
only the Temporal loop would miss these producers. A standalone AI reply or acknowledgment is not
automatically a final cadence step merely because the cadence cursor is empty.

The durable standard dispatch path first returns DISPATCH_PENDING, which is not a send or completion.
The dispatcher later records its outcome and queues rescheduling; the engine can revisit the same
message as ALREADY_SENT. That result is a message-level idempotency short-circuit also available
after direct sends, not proof of which producer sent it. Provider acceptance, delivery callback,
journey accounting and business completion are distinct boundaries. 17-A owns durable dispatch
integration; its draft is not proof that every existing direct-send caller has those guarantees.

After SENT/ALREADY_SENT with no more steps, LeadNurtureWorkflow waits on _closed rather than normally
exiting. Its close signal only changes an in-memory flag; it does not persist completion. A later
scheduling pass may return “no remaining cadence steps,” leading to the distinct Issue 6 exit.
No remaining step is not a sufficient completion test: missing configuration, invalid cursor and
final-step skips can also produce empty/no-step results. Existing paused-search terminal outcomes
have their own scheduling rules and must not be folded into this standard-cadence repair.

COMPLETED, SUPPRESSED and CLOSED are terminal in the domain. The generic transition helper writes
workflow/history and mirrors a terminal outcome to the workflow's enrollment only when its optional
enrollment repository is supplied. mark_terminal targets that exact enrollment, updates active
statuses and preserves an existing ended_at. The standard advancement helper does not pass that
dependency or accept it in its current signature; none of its scheduled, deferred-send-now or
draft-approval callers mirrors enrollment through that helper today. A repository supplied to
pinned-config lookup elsewhere is not completion mirroring. The generic transition helper also
resolves the latest workflow for a lead, so old-run metadata alone cannot guard a successor.

There is an existing COMPLETED state, but no dedicated standard-cadence-completed reason in the
reviewed reason enum. Other paths already produce COMPLETED, including a not-interested inbound
decision. “No code ever completes a workflow” and “completed always means all messages succeeded”
would therefore be wrong. The standard enrollment's still-QUEUED/missing-start evidence is the
related Issue 3 defect, not a reason to stamp a start time at completion.

Inbound processing is an application journey, not merely a signal to the parked engine. It records
and classifies messages, can persist suppression and handoffs, and queues inbound-processed when a
workflow is present. AI continuation explicitly requires WAITING_FOR_RESPONSE; a null cursor alone
does not block it, because a nonempty cadence supplies its first step as drafting context. That is
not a new cadence enrollment. Terminal transitions are rejected by the domain and caught as SKIPPED;
a handoff can still be created when that transition was skipped. This proves a missing explicit
terminal-reply contract, not that every terminal reply is dropped or raises an uncaught exception.
Saving a message before classification also does not, without its real caller's commit evidence,
prove that receipt survives a later rollback.

Queued terminal-target signals are not simply “silently discarded by Temporal”: the dispatcher has
retry and terminal-failure handling and its not-found recovery excludes terminal business states.
Those mechanisms do not supply a post-completion reply route. Nor does the existing dispatcher
expose a close outbox kind merely because the workflow has a close signal.

Read surfaces already recognize completed state: lead narrative/history, Finished outcomes and
workflow/enrollment reporting counts. Exhausted progress/no next action can be diagnostic clues,
but are not an authoritative completion. “Not enrolled” means no workflow history, not completed.
The latest-workflow history view also stops showing the preceding run after re-entry; the recorded
manual re-entry reason is not in the current UI metadata allowlist. Reuse 4-A's historical access
contract rather than assuming those facts are already available in the operator journey.

Handoff detail already offers permission-checked acknowledgment/reassignment and lead-level Resume
readiness. Acknowledgment marks the handoff as seen; it does not resolve the business conversation.
Those controls do not prove an end-to-end disposition for a late handoff on a terminal run. G1/R3
must name the usable human follow-up route without treating terminal Resume as the solution.

### 3.2 G1 — decide completion timing and reply handling before implementation

Neither option is selected. This is an owner decision, not an inference from the last delay_hours.

| G1 option | Required business definition | Benefit / risk to review |
| --- | --- | --- |
| Explicit final-response window | Record its exact duration and scope, the event/time that starts it, ongoing-reply/AI-turn reset or extension rules, and the route for replies received after it. A silent run completes when the approved boundary is satisfied. | Keeps a deliberate final waiting phase; needs a durable recoverable deadline and cannot be an indefinite wait disguised as a window. A window alone still does not settle post-completion replies. |
| Completion at the approved final-action boundary | Explicitly route ordinary, interested and opt-out replies after completion, including with no running engine. Define whether any permitted conversation continuation uses a separate context and how its existing budget/ownership is preserved. | Ends cadence bookkeeping promptly; the current WAITING_FOR_RESPONSE-only AI path cannot just be left unchanged. No silent terminal reopening or automatic new marketing enrollment. |

Record the following in G1 before translating §4 into exact expected states and times:

1. **What ends this run?** Final-send/journey evidence, treatment of an approved final skip or
   separately released uncertain-as-sent accounting, and any window's precise duration/scope. A
   rejected, deferred, pending or unknown final attempt is not silently promoted to “sent.”
2. **Which clock and boundary?** The authoritative business timestamp, receipt-versus-processing
   ordering, equality at the deadline, delayed/out-of-order webhook handling and untrusted/missing
   timestamps. Keep provider event time, platform receipt, accounting and completion-recorded time
   distinguishable. Processing lag must not silently decide which replies receive attention.
3. **What happens to each reply?** Explicit ordinary, interested/request-for-person, non-opt-out
   “not interested,” opt-out and unclassifiable routes after the final action, during any window,
   and after declared completion. A decline has its existing distinct meaning/end reason; do not
   silently group it with ordinary AI continuation or fabricate a channel opt-out. Specify permitted
   AI/human handling and visible unresolved outcomes, not merely “do not drop.”
4. **What happens to an ongoing conversation?** Whether a reply changes the completion boundary,
   what follows a permitted AI response, and how pending classification, AI limits, review, handoff
   and explicit human ownership affect it. No hidden endless deadline extension or timer that
   completes a live human conversation. Preserve the separately approved processing-outage policy.
5. **Which run owns a late reply?** Define attribution when a new enrollment already exists and
   provider/thread evidence identifies the old run, the current run or neither reliably. Choose the
   customer-handling route explicitly; ambiguity is not permission to mutate whichever run is latest.
6. **What are the release and historical boundaries?** Record the decision owner/version, affected
   cohorts, operator copy and any separately classified policy dependency. Decide how pre-existing
   final waits are treated; never apply a guessed retroactive window to all old leads.

No G1 value is pre-approved here. R1/R2 cover durable representation and race handling; R3 covers
operator/read contracts. Any chosen route requiring changed contact rights or customer notification
must be disclosed and classified separately under D7, not smuggled into the completion repair.

### 3.3 Complete exactly the right journey, once, from durable evidence

| Evidence / current disposition | Completion contract |
| --- | --- |
| A standard run has a supported final-action outcome, its G1 boundary is satisfied and no newer protected disposition conflicts | Commit one explicit cadence-completion outcome, matching enrollment end and audit evidence for that same run; arrange engine convergence without another lead message. |
| More legitimate cadence work remains, or an approved final-response window is still open | Preserve the existing next action or explicit response wait. No early completion, reset to step one, or cap/budget change. A response deadline is not a scheduled outbound touch. |
| Final intent is merely queued/dispatching, deferred, definitely failed, or uncertain under the pre-17-B baseline | Preserve its actual dispatch/wait/hold/reconciliation contract. Neither an empty cursor nor estimated end time supplies missing outcome evidence. |
| Separately released 17-B has consumed an uncertain final touch for journey accounting | Apply that integrated accounting plus G1 without resending or waiting for delivery as a new condition. Message uncertainty remains visible; do not fabricate provider acceptance or implement 17-B here. |
| Empty configuration, missing/invalid step, ambiguous skip or insufficient final-action evidence | Use the approved 6-A cannot-proceed/exception route. An explicitly supported final skip needs its own agreed evidence/end treatment, not a fabricated last send. |
| PAUSED, HUMAN_HANDOFF, HUMAN_OWNED, unresolved inbound processing, or a newer applicable control | Preserve its reason, ownership and protected outcome. Do not overwrite it with cadence completion to free enrollment admission; apply G1's explicitly agreed ongoing-conversation disposition. |
| Already COMPLETED/SUPPRESSED/CLOSED, superseded, or a different journey/mode | Respect the existing terminal reason and lineage. Duplicate completion is a truthful no-op; old work cannot complete, reopen or reschedule the successor. |

1. Correlate workspace, lead, business workflow, enrollment, pinned campaign version, execution
   mode/track, final step and relevant message/request or occurrence. Carry enough identity through
   timers, activities, dispatch settlements and external final-send producers to reject stale work.
   Neither lead ID nor “latest workflow” is sufficient authorization for a delayed completion.
2. Use durable authoritative final-action and G1 facts. Approve any new deadline/outcome fields
   only after inspecting existing state/evidence models. Repeated scheduling, provider callbacks,
   restarts and ALREADY_SENT retries must not re-arm the window from the current clock or consume
   another step, AI turn, daily-start slot or completion.
3. Revalidate the same-run state and relevant pending replies/controls at the completion commit
   boundary, with concurrency protection shared by inbound and other state writers. Define the
   winner when finalization races receipt, processing, suppression, handoff or manual re-entry;
   an earlier eligibility snapshot is not permanent authority.
4. Persist the workflow transition, matching enrollment status/end and required durable completion
   evidence/engine instruction in one approved transaction. Use the sanctioned domain transition
   and a meaningful end reason; do not use OUTBOUND_MESSAGE_SENT as the only completion explanation
   or write state directly to bypass terminal/human-control guards. A failed or zero-row enrollment
   mirror must not be silently reported as coherent success.
5. Preserve original enrollment/source/start facts, accepted-send evidence and pinned versions.
   Define business completion time versus recorded-at time explicitly; retain the first valid end
   on duplicate processing. Historical uncertainty cannot be repaired by invented timestamps.
6. Only a committed terminal business outcome authorizes successful engine lifecycle completion.
   If business completion commits but the engine acknowledgment/close fails, keep the non-sendable
   terminal truth and an owned convergence problem. Retry/reconcile safely through the shared
   instruction/recovery contracts; do not reopen or resend to make the engine catch up.
7. If G1 selects a window, persist/reconstruct its original deadline and response disposition.
   Native timers, downtime recovery, duplicate wake-ups and lost notifications must eventually
   converge without a chance reply or manual close. If finalization cannot run, show the problem;
   no clean engine exit over a nonterminal supposedly completed run.
8. Every actual final-cadence producer uses the same lifecycle contract. Integrate 17-A's final
   outcome ownership rather than calling the provider again after a completion failure. A final
   deferred send or draft approval must wake the correct waiting engine or otherwise converge
   durably; changing only a workflow's in-memory has_more_steps branch is insufficient.
9. Do not reinterpret an AI continuation, handoff acknowledgment, unrelated operator message or
   configured paused-search terminalization as standard final-step completion. Preserve their
   accounting, ownership and end reasons; explicitly inventory legacy/shared callers at R1/R2.

### 3.4 Keep replies and protection effective across the completion boundary

- **Receipt is not completion of handling.** Preserve durable inbound receipt, deduplication,
  classification/route evidence and any unresolved attention through 9-A/4-A. An old completion
  timer cannot erase a processing hold, hide exhausted work or declare a reply handled because its
  workflow transition returned SKIPPED. The same rule applies when persistence/AI/CRM is unavailable.
- **Run the agreed route without relying on a live old engine.** Before sending, creating/reusing
  handoff or claiming a final disposition, recheck relevant run, current contact controls and human
  ownership. A deliberate no-AI route must have its approved visible handling, not a generic error.
  Do not weaken terminal guards or silently create a new enrollment to satisfy the old AI helper.
- **Interested replies must remain actionable.** Preserve existing open handoff ownership and
  deduplication. A new or reused handoff, its conversation and its history must tell a coherent story
  even when the cadence is already complete. Prove the permitted owner can acknowledge/reassign
  where authorized and carry out the G1-approved human follow-up/disposition through the actual
  operator journey, with persisted evidence. “Seen” alone is not “resolved”; an unusable Resume-only
  destination does not satisfy this requirement. Inventory existing controls first and keep any
  missing disposition explicit in G1/R3, without assuming a new endpoint or widening terminal
  Resume. Do not blanket-handoff ordinary late replies as an allegedly policy-free workaround.
- **STOP and global DNC are independent of engine liveness.** Use the integrated deterministic
  opt-out path and durable suppression preservation. A later STOP can add current contact-restriction
  evidence while the old completed run remains completed historically; no terminal-to-SUPPRESSED
  transition is required merely to record the restriction. Current eligible work must respect it.
  Preserve the actual A/B workflow/channel outcome; no added courtesy send or cross-channel fallback.
- **Receipt and completion races need a proved contract.** Apply G1's exact time/ordering rule when
  a message arrives before the boundary but processing finishes later, or when a delayed provider
  event arrives after completion. Preserve original evidence and current protection; retry cannot
  select a different route simply because wall time advanced. A timestamp alone cannot bypass an
  explicit newer pause, suppression or human handoff.
- **Later enrollment does not erase earlier conversations.** Use the approved correlation rule for
  old-thread/current-thread/ambiguous replies. Do not attach old timers, budget consumption, CRM
  snapshots or command outcomes to a successor by accident. Lead-level opt-out protection still
  applies even when journey attribution is unresolved.
- **Control delivery is not reply routing.** Use 2-A for relevant instruction identity and delivery
  evidence, including explicit supersession/no-longer-applicable outcomes. A closed terminal engine
  must not be restarted to process a business reply, and a failed obsolete signal must not create
  an endless restart/review loop. Do not drop still-required handoff/reply work with that signal.
- **External effects follow current truth.** Keep CRM snapshots, existing notifications and any
  already-authorized acknowledgments consistent with the agreed reply disposition, consent and
  handoff. Reuse existing completion/idempotency records. No new notification product or resend on
  a CRM failure; stale final-send snapshots must not overwrite newer completion/handoff evidence.

### 3.5 Make completion, reporting and future enrollment usable by operators

1. **See the lifecycle:** lead detail, authorized lead lists and existing aggregate surfaces show
   valid response wait versus completed versus held/processing outcomes from durable API facts.
   Include the approved completion reason/time and any window deadline as distinct concepts. Do
   not reuse next-outbound copy for a response deadline or show “Not enrolled” for a historical run.
2. **Distinguish facts:** completion committed, engine convergence pending, inbound processing and
   provider outcome are different facts. A missing/failed/stale read cannot appear as no history,
   zero completions or a healthy wait. Refetch persisted facts rather than relying on a toast.
3. **Report honestly:** reuse existing completed counts, with their declared units: workspace
   latest-workflow counts, campaign-filtered workflow counts and historical enrollment counts are
   not interchangeable. Re-entry can change a lead's current-workflow bucket while leaving its old
   completed enrollment intact. No conversion/success rate or time-to-complete from missing starts,
   latest-transition timestamps or conflated end reasons; no new analytics dashboard is required.
4. **Inspect after re-entry:** the preceding completion, late-reply outcome and new-run re-entry
   reason remain reachable through the approved 4-A history/read route with explicit run identity.
   Do not advertise current latest-only workflow history as a complete cross-run record. Correct
   completion evidence must remain usable after the exact action this ticket restores.
5. **Start a new permitted journey:** reuse manual-enrollment-options and manual-enrollments, not
   Resume or a new bypass endpoint. Recheck active published configuration, current admission,
   contact/workspace controls, source/role and reason on submission. Existing MANUAL_ADMIN-source
   permissions include authorized wider roles such as managers; assigned agents cannot terminally
   re-enter merely by entering a reason. Bring displayed actions into line with backend permission.
6. **Preserve the old run:** accepted manual re-entry creates new workflow/enrollment/message
   identities and its own normal budgets, with actor/reason and linkage to prior history. It does
   not modify old completion, release claimed old sends, inherit old timers or bypass 3-A's genuine
   new-start capacity. Duplicate/concurrent submission or a lost start response cannot create
   repeated journeys; a failed engine start uses 7-A recovery of the new run, not another enrollment.
7. **Keep authority scoped:** use existing own-assigned-lead versus workspace permissions; authorize
   actions separately from reads. Campaign UI routes are admin-only today even though managers have
   backend reporting rights. Do not grant broader access or invent a team scope to make a new link
   work. Apply scope before pagination/counts and provide a permitted destination for each role.
8. **Explain limitations:** completion is not new consent, tag re-add eligibility, automatic dormant
   re-entry or confirmation that a reply has been handled. Operational inconsistencies have a scoped
   correction/support route with actor/reason/evidence, not retagging, bulk Resume or direct DB edits
   offered as the normal user journey. No new unsolicited customer notifications are required.

### 3.6 Remaining implementation and release gates

**G1 in §3.2 remains a prerequisite to completion implementation, not merely release paperwork.**
Its decision and exact expected reply outcomes must be attached alongside the following gates.

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Completion evidence and lifecycle contract | Approve G1 translation into the final-action/skip/uncertainty matrix, same-run/pinned-version/mode identity across republication or reassignment, authoritative boundary and timestamp meanings, reason/status/enrollment consistency, protected dispositions and exact adjacent A/B dependencies. | Domain/application completion-contract implementation |
| R2 — Durable finalization, inbound and engine contract | Approve all producer wiring, transaction/zero-row/duplicate semantics, reply-versus-finalization ordering and concurrency, timer/recovery persistence, closed-engine late routing, stale activity/signal/callback protection, engine convergence, old inputs/history compatibility and test seams. | Persistence/engine/inbound implementation and integrated lifecycle acceptance |
| R3 — Operator, reporting and re-entry contract | Approve API/UI status/time/reason copy, current versus historical count semantics, prior-run/reply/re-entry-reason access, terminal-handoff human follow-up/disposition and action/role alignment, pagination/freshness/error behavior and usable permission-checked new enrollment after completion. | API/web/reporting/operator implementation |
| R4 — Historical treatment, rollout and operations | Approve evidence-based inventory, exact historical G1 treatment and separately authorized corrections/containment, migration/worker order, cohort/canary, monitoring/response owner, stop criteria and rollback that preserves post-completion reply handling. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. No unresolved duration,
reply entitlement, historical policy or action permission may be supplied by a test fixture default.
An integrated dependency is required evidence, not a link to an earlier draft with open gates.

## 4. Business acceptance scenarios — for approval

Each changed behavior requires a demonstrated meaningful failing test before its implementation.
Use synthetic leads, controlled clocks and recording providers. **These are not passing tests.**
Replace every G1-dependent expectation with its approved literal route/time before writing that test.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A silent standard run completes its actual final action through the supported send path, then reaches the approved G1 boundary without a new inbound event or operator signal. | One committed cadence-completion reason/history entry, matching completed enrollment/end time and eventual engine completion; fresh reads show the same run and no further cadence touch. | Indefinite waiting, a UI-only badge, terminal workflow with active enrollment, manual close required, or an extra final message. |
| AC-02 | Complete a nonfinal step with a configured later step; repeat with an open approved final-response window and ordinary future scheduling. | Existing legitimate next step or explicit response wait remains; finalization occurs only when its own approved boundary is satisfied. | Every successful send ends the campaign, a response deadline becomes an outbound send, or all sends disabled to satisfy AC-01. |
| AC-03 | Advance immediately before, exactly at and after the approved boundary; restart/replay while waiting and delay worker availability. | Literal G1 clock/equality rules; original durable deadline/disposition survives, eventual finalization is evidenced and overdue inability remains visible. | Guessed duration, processing time substituted for receipt, restart extends the window, or a fake close substitutes for real expiry. |
| AC-04 | The final standard send is DISPATCH_PENDING, then durably settles and is revisited as ALREADY_SENT; delay/duplicate provider callbacks. | Pending is not completed/sent. The correct supported outcome establishes end accounting once; completion uses G1 independently of delivery reporting. | Complete on queue insertion, send the final message twice, require a new callback without policy basis, or label acceptance as delivery. |
| AC-05 | Retry the final action/finalization and duplicate the relevant outcome after a lost response or already committed completion. | One business completion with the original valid end time, retained message/request claim and no duplicate step/AI/start debit. Duplicate is a truthful same-run no-op. | New transition/time on every retry, rejected-terminal error reported as a new incident indefinitely, or released send identity. |
| AC-06 | Use deferred/rejected/failed/uncertain final work, missing/empty configuration, invalid cursor and a final skip; separately exercise any integrated 17-B final accounting. | Apply the approved R1 matrix and actual released baseline. Unsupported/unknown evidence stays owned and visible; an approved skip has its real reason, and uncertain-as-sent never means delivery. | has_more_steps=False or null cursor alone proves completion; fabricate a final send, silently add 17-B, or wait for delivery contrary to a released 17-B contract. |
| AC-07 | Finish the actual standard cadence through scheduled execution, deferred-send-now and draft approval; compare with a standalone AI reply, acknowledgment and paused-search end. | All standard final producers reach the same G1 lifecycle and correct engine disposition. Other journey types keep their own accounting/ownership/end contract. | Fix only the Temporal send loop, finish on an unrelated outbound, lose an operator-produced final outcome or replace paused-search limits. |
| AC-08 | An allowed AI conversation continues after the last cadence action and crosses the old boundary; include the existing turn cap and repeated callbacks/recovery. | G1's explicitly chosen extension/end rule, original run/budget and current processing/human protections hold. No silent infinite extension or lost finalization after conversation handling. | Old timer ends a live conversation, each retry resets the budget/window, or a fresh enrollment is created to get AI permission. |
| AC-09 | Receive ordinary SMS and email replies after the final send but before any declared completion; separately exercise a non-opt-out “not interested” reply. | Durable receipt and each explicit G1 route: expected ordinary AI/visible outcome and distinct decline meaning/end reason, with correct run and existing safety/budget checks. | Message saved but route abandoned, decline treated as ordinary continuation or a fabricated opt-out, new cadence from step one, or silent loss of a supported reply route. |
| AC-10 | Receive buying/selling interest or an explicit request for a person after the final send but before completion, including an existing open handoff. | Approved human route remains actionable; handoff/conversation ownership and deduplication are preserved, and obsolete finalization cannot replace that outcome. | Complete over the handoff, duplicate ownership/task or automatic hand-back to AI. |
| AC-11 | Receive ordinary SMS/email replies after recorded completion, with the old engine running-to-close, fully closed or unavailable; separately exercise a non-opt-out “not interested” reply. | Each explicit post-completion route succeeds or leaves its approved owned unresolved outcome independently of old-engine liveness. Distinct decline evidence, old terminal history and current safeguards remain intact. | Generic state-mismatch SKIPPED presented as handled, drop the message, rewrite cadence completion as a later decline, fabricate an opt-out, restart the completed engine or silently create a new marketing run. |
| AC-12 | Receive an interested/request-for-person reply after completion; repeat webhook delivery, include an existing open handoff, then exercise the authorized owner's actual action journey. | Coherent reply/handoff/conversation evidence and correct duplicate/reuse behavior; permitted acknowledgment/reassignment and G1-approved human follow-up/disposition work through API/UI with persisted results, without needing a terminal transition. | Orphan/duplicate or merely visible handoff with no usable follow-up, “acknowledged” presented as resolved, terminal Resume used as a bypass, or blanket-handoff of every ordinary reply. |
| AC-13 | Receive STOP after the final send and after completion while classification raises; follow with CRM refresh and a current/new-run send attempt. | Integrated 9-A/16-A safety records the restriction without AI and preserves it; current sending obeys the released channel/DNC rule. Old completed history need not be rewritten. | Terminal state/closed engine prevents opt-out, refresh clears it, completion grants new consent, or A adds fallback/courtesy contact. |
| AC-14 | Receive before the deadline but process afterwards; also deliver a delayed/duplicate/out-of-order provider event after completion, with missing/untrusted time and exact-boundary cases. | Explicit G1 receipt/ordering/attribution rule and durable original evidence determine handling; current protection always applies. Retry does not change entitlement merely because time passed. | Whichever clock or lock is easiest decides silently, backdate completion from a guessed event, or discard late events. |
| AC-15 | A reply is durably pending, classification fails/exhausts, or its approved route needs review while completion becomes due. | G1/9-A disposition preserves processing evidence and a visible owned unresolved path; finalization cannot erase it or release prohibited outreach. | Declare the lead silent, auto-complete to hide a stuck reply, clear the hold, or introduce the separate 30-minute policy. |
| AC-16 | Compete finalization with inbound receipt, classification result, AI dispatch and handoff using independent transactions; exercise both winning orders. | Approved serialization/fencing and current-state rechecks produce one coherent route/end outcome, no duplicate effect and no lost reply. | Fake sequential calls offered as concurrency proof, stale eligibility overrides receipt, or only result writes are fenced while an unauthorized send proceeds. |
| AC-17 | Apply pause, human ownership/handoff, suppression, workspace/campaign stop or newer applicable control during finalization; separately start from already terminal outcomes. | Respect each approved disposition/reason and authority; completion does not overwrite stronger/current protection or relabel a distinct terminal reason as cadence exhaustion. | Free enrollment uniqueness by completing a held lead, resume a human-owned conversation or bypass global DNC. |
| AC-18 | Deliver an old final activity, timer, dispatch result, engine signal or CRM completion retry after a successor enrollment/track exists; vary workspace/campaign/run identity. | Exact old-run correlation; successor state, timers, budgets and snapshots cannot be overwritten or closed. Retained send evidence remains attributable to its original run. | Latest-by-lead mutation, newest campaign substitution, stale close/reschedule reaches successor, or old callback reopens a terminal workflow. |
| AC-19 | A later enrollment exists when an old-thread reply arrives; repeat with current-thread and ambiguous attribution, plus STOP. | Apply the explicit G1 ownership/route matrix; show unresolved attribution where required, without silently stealing a new run's AI budget. Lead-level contact protection applies regardless. | All replies assumed old or latest solely by arrival order, dropped STOP, or invented thread linkage. |
| AC-20 | Crash before/after finalization commit, fail enrollment mirroring or instruction commit, lose engine-close acknowledgment, and make storage unavailable. | Independent reads prove the approved atomic business outcome and retained recoverable convergence. No false coherent success; retries preserve original claims/times and durable reply evidence. | Workflow complete/enrollment active accepted as done, close engine before required persistence, partial outbox success, or resend after DB/CRM failure. |
| AC-21 | Lose/restart the engine during the final wait or after committed business completion; repeat with delayed/duplicate/stale instructions. | 2-A/7-A integration restores only the permitted same-run wait or converges terminal execution. Original deadline/commands are retained or explicitly superseded; terminal runs never auto-recover into outreach. | Restart resets cadence/window, start accepted means completion applied, or missing-engine sweep revives a completed lead. |
| AC-22 | Compare full-cadence completion, not-interested completion, suppression, handoff and re-entry in reporting, including unknown started_at and corrected historical end evidence. | Correct declared workflow/enrollment counting units and end reasons; completion time differs from send/start/recorded-at as specified. Unknown durations stay unknown and new enrollment does not erase old completion. | Completed count advertised as conversions/deliveries, latest workflow totals equated to enrollment history, or fabricated zero-duration successes. |
| AC-23 | Read legitimate final wait, completion, engine-convergence failure and pending late reply through real API/client contracts and relevant lead/home/campaign surfaces. | Truthful status/reason/time, separate reply/provider/engine facts and correct scoped navigation; loading, empty, stale and error outcomes differ. | Fixture-only proposed fields, error renders zero/healthy, “Not enrolled” for completed, or a response deadline labelled next outbound. |
| AC-24 | After real completion/mirroring, get options and submit manual re-entry as an authorized wider role with a reason; try missing/blank reason and assigned-agent terminal re-entry. | Existing permitted new-enrollment route works with fresh identity/history and normal capacity/contact checks; forbidden submissions and misleading action affordances are blocked/explained. | Resume the completed run, stale active enrollment blocks legitimate options, reason alone grants agent permission, or bypassed start cap. |
| AC-25 | Submit re-entry concurrently/repeatedly, lose its HTTP or engine-start response, or race a new human/contact restriction. | At most one new authoritative journey under current checks; committed failed engine start uses same-new-run recovery. Old completion evidence remains unchanged. | Retrying creates another enrollment, optimistic toast is proof of start, or late old completion mutates the new run. |
| AC-26 | Run dormant selection, automatic/tag enrollment and missing-engine recovery after completion; include the actual separately released 14-B tag-ended exception where applicable. | No generic automatic re-entry or terminal restart. Distinct tag-ended exception/track reassignment retains only its existing approved scope. | Completion adds the lead to dormant selection, tag remains present so every completed run restarts, or unbuilt 14-B behavior is assumed current. |
| AC-27 | Read history/counts and attempt actions as assigned agent, unrelated agent, permitted manager/admin, inactive member and another workspace; include unowned leads. | Existing scoped read/action permissions hold end to end, with valid role-specific destinations and server-side enforcement. | Cross-tenant history/count leakage, new manager-team assumptions, admin-only route exposed to managers without a usable alternative, or broad access to fix one link. |
| AC-28 | Complete, handle a late reply, re-enroll and retrieve the prior end plus new re-entry reason beyond the first page; include unavailable/expired history. | Approved 4-A route preserves navigable run-specific evidence and safe pagination. Missing data is explicit; refresh/new workflow does not erase the prior result. | Latest-only history marketed as complete, reason persisted but inaccessible, limit-before-scope or invented expired evidence. |
| AC-29 | Inventory synthetic old final waits, partially mirrored terminal rows, active conversations, skipped/uncertain final outcomes and evidence-poor/superseded records. | Exact G1/R4 historical treatment, evidence strength and scoped corrective/contained disposition; only proven approved records qualify. Original and correction times remain distinct. | Complete all empty-cursor leads, backdate from last_transition_at, auto-enroll after correction or treat missing history as no prior contact/reply. |
| AC-30 | Rehearse canary cutover and rollback with old/new schemas, final producers, inbound handlers, recovery workers and representative Temporal histories. | Only approved cohorts finalize; old incompatible writers are contained. Rollback stops unsafe new completions while retaining handling for replies to already-completed runs and preserving claims/history. | Roll back the late-reply handler under terminal leads, mass-reopen runs, reset engines instead of replay validation, or silently apply a retroactive window to the backlog. |
| AC-31 | Demonstrate synthetic actual final action → approved boundary → committed completion → engine convergence → fresh API/UI → permitted manual re-entry; separately demonstrate ordinary/interested/STOP late replies. | Complete journey using real Postgres/Temporal where claimed and recording external providers, with correct old/new lineage, scoped operator outcome and no customer test traffic. | Manually fabricated terminal fixtures or fake close plus screenshot offered as the complete proof. |
| AC-32 | Run ordinary cadence, paused-search limits, AI replies, existing handoff acknowledgments, holds, opt-outs/DNC, workspace controls and the declared A/B baseline beside completion. | Existing legitimate sends and every independent safeguard remain. No new timing/contact/fallback/tag/uncertainty rule, AI budget or re-entry right hides in A. | All messaging disabled to pass protection tests, changed configured end policy or Class B behavior included in the completion PR. |

AC-29–30 authorize synthetic rehearsals only, not production reads/changes. Already-correct positive
and protected controls may pass on the baseline; changed behavior still needs meaningful red first.
Required skipped integrations remain missing evidence, never a green acceptance result.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve after G1 and before implementation:**
- **Actual final action → lifecycle → read:** scheduled, durable-settlement, deferred-send-now and
  draft-approval entry points through approved boundary evaluation and fresh public state/history/
  enrollment reads. Include nonfinal/failed/skip controls, not just the advancement helper (AC-01–07).
- **Inbound receipt → route → visible disposition:** real inbound application/worker transaction
  boundary, actual continuation/handoff/suppression and their persisted/public outcomes before and
  after completion, including older/ambiguous threads and ongoing conversation (AC-08–19).
- **Persistence and concurrency:** approved repository/transaction contracts on real migrated
  Postgres with independent sessions, state/enrollment/transition consistency, duplicate/lost
  outcomes, competing inbound/finalization/re-entry and scoped history/reporting (AC-05/16–20/22–29).
- **Engine lifecycle and recovery:** real Temporal test environment plus application activities,
  durable dispatch and original instructions; time advance, restart, unavailable worker, completion
  convergence and representative old/new history replay. Fake wait_condition calling close is not
  proof of autonomous persisted completion (AC-01–04/07–08/18/20–21/30–31).
- **Operator journey:** actual API/client contracts and existing route tests for lifecycle copy,
  history, counts, role-specific navigation, options/POST reason/permission and error handling,
  including the approved terminal-handoff owner action/disposition. Demonstrate the synthetic data
  journey through API to UI, not only fixtures (AC-12/22–28/31).
- **Runtime and rollback:** deployed producer/timer/worker wiring, approved cohort treatment and
  preservation of already-required post-completion handling when disabling new finalization
  (AC-20–21/29–31). This is later authorized validation, not a production operation in this draft.

**Allowed fakes:** fixed clocks and hand-written repository/CRM/LLM/messaging/engine-port fakes for
fast application tests. Do not fake the completion, G1 route, state, authority, suppression or
deduplication decision under test. Expected literal times/states/counts come from the approved
scenario, not another call to its production helper. A fake provider count proves submissions to
that fake, not global provider delivery exactly once.

1. After G1/test-boundary approval, begin with AC-01 on the unchanged baseline: run the real final
   action, pass the agreed boundary and demonstrate the missing recorded completion/enrollment/end
   disposition through the approved public seam. Preserve useful existing send/cursor assertions.
   Today's test explicitly expecting WAITING_FOR_RESPONSE is setup evidence, not a passing fix.
2. For a genuinely new expiry/evaluation seam, add only the smallest non-working boundary needed
   to express the approved behavior and distinguish it from baseline reproduction. An import error,
   missing proposed field, or mock preprogrammed to return COMPLETED is not meaningful red evidence.
3. Implement one smallest vertical slice to green, then the next failing case: nonfinal protection,
   legitimate final reply, enrollment consistency or duplicate settlement as appropriate. Do not
   bulk-write speculative tests/private-helper contracts and then implement to their assumptions.
4. Exercise the G1-selected branch and approved post-completion routes, not both hypothetical product
   options as though both must ship. Keep unselected policy explicitly out of the implementation.
   Replace vague “handled” assertions with approved saved/queued/applied/human-owned outcomes.
5. Prove real commits, races, engine timers/replay and API-to-UI contracts at their claimed boundary;
   run the smallest test then its file/package and affected safety regressions. No new dependency,
   browser project, production access or provider sends are authorized by this draft.
6. Demonstrate critical test sensitivity by locally removing the final-action/state/run guard,
   inbound protection, enrollment mirror or stale-timer fence and observing the matching failure.
   Pair no-duplicate/no-send cases with legitimate ordinary sends and agreed positive reply routes.
7. An independent reviewer checks expectations against G1, R1–R4, source and actual released A/B
   contracts. Attach commands, revisions, meaningful red/green, pass/fail/skip counts and integration
   limitations; unresolved integration is not relabelled acceptance. Review broader refactoring
   separately rather than expanding the initial red-to-green slice.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Fill after G1 during implementation | Not run in this draft | Required before the change | Required | Required where applicable | Explicit, never hidden as pass |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. Deadline fields, a dedicated
cadence-end reason and post-completion routing are proposed contracts, not claimed existing APIs.
Inventory production callers and commit points before changing a shared/optional interface.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — standard final action and shared producers | app/application/use_cases/campaign_cadence_execution.py; app/application/use_cases/lead_draft_review.py; app/application/use_cases/send_deferred_outbound_message_now.py |
| API — durable dispatch and outcome signals | app/application/use_cases/dispatch_outbound_send_requests.py; app/application/use_cases/process_provider_delivery_callback.py; app/application/use_cases/dispatch_temporal_signals.py |
| API — terminal state, audit and enrollment | app/domain/workflows/models.py; app/domain/campaigns/enrollment.py; app/application/use_cases/apply_workflow_state_transition.py; app/infrastructure/persistence/postgres/workflow_repository.py; app/infrastructure/persistence/postgres/campaign_enrollment_repository.py |
| API — engine and separate paused-search endings | app/application/ports/temporal.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/activities.py; app/application/use_cases/schedule_next_paused_search_action.py |
| API — inbound, continuation and handoff integration | app/application/use_cases/process_inbound_message_event.py; app/application/use_cases/apply_inbound_workflow_transition.py; app/application/use_cases/continue_ai_conversation_after_inbound.py; app/application/use_cases/complete_handoff.py |
| API — existing human action controls, not a presumed terminal-resolution endpoint | app/application/use_cases/handoff_actions.py; app/interfaces/api/v1/handoffs.py; app/application/use_cases/lead_resume.py |
| API — admission and existing manual re-entry | app/domain/campaigns/enrollment_admission.py; app/application/services/campaign_enrollment_starter.py; app/application/use_cases/lead_manual_enrollment.py; app/infrastructure/persistence/postgres/dormant_candidate_selector.py |
| API — lifecycle reads, counts and transport | app/application/use_cases/lead_read.py; app/application/services/lead_cadence_progress.py; app/infrastructure/persistence/postgres/reporting_repository.py; app/interfaces/api/schemas/leads.py; app/interfaces/api/v1/leads.py |
| Web — operator lifecycle, historical display and clients | src/pages/LeadDetailPage.tsx; src/pages/HandoffDetailPage.tsx; src/pages/HomePage.tsx; src/pages/CampaignDetailPage.tsx; src/lib/journey/leadJourney.ts; src/lib/api/leads.ts; src/app/router.tsx |

**Two engineering approaches to review after G1, before coding:**
- **Recommended: one small application completion contract, driven by existing final-outcome
  producers and native Temporal timing.** Persist same-run end eligibility/deadline as required by
  G1; application transactions own terminal state/enrollment/history, and a durable notification or
  reconstructable activity result makes the engine converge. Reuses existing execution ownership
  and minimizes parallel policy logic. Cost: final actions outside the engine, changed timers and
  old Temporal histories need explicit durable wiring/replay; in-memory close alone is inadequate.
- **Alternative: a bounded application finalization worker using the same durable end contract.**
  Scan eligible due boundaries with stable scope/pagination and atomically finalize, then converge
  the engine. Can recover missed external final-action wake-ups independently of a parked engine;
  costs an additional runtime responsibility, scan load and bounded completion latency. Must not
  duplicate the decision in a second state machine or treat all null cursors as expired windows.

These are engineering alternatives, not a selection between G1's business options. Choose the
smallest complete design once timing/routing are known. Reuse existing transition, outbox, history
and admission mechanisms, preserve constraints, and keep vendor/SQL details behind their current
ports/adapters. No approval to add a generic orchestrator or to weaken terminal-state validation.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_process_inbound_message_event.py — includes AI continuation and run-budget cases
- tests/application/use_cases/test_dispatch_temporal_signals.py
- tests/application/use_cases/test_lead_read.py
- tests/domain/workflows/test_workflow_transitions.py
- tests/domain/campaigns/test_enrollment_admission.py
- tests/interfaces/api/v1/test_lead_manual_enrollments.py
- tests/infrastructure/persistence/postgres/test_campaign_enrollment_repository.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- Web: src/app/LeadsRoutes.test.tsx

The final-step application test currently asserts the indefinite waiting shape. The all-steps
Temporal test supplies close from its fake wait; neither establishes autonomous completion. Reuse
their useful setup but add actual final-outcome/expiry/reply evidence. Locate producer-specific,
worker and client coverage on the implementation branch before adding tests at those seams.

## 7. Historical inventory and bounded correction

Production reads/changes require separately approved scope and access. Rehearse on synthetic data.

- Inventory exact workspace/workflow/enrollment, pinned mode/version, final action/skip evidence,
  provider/request claims, original timestamps, pending/late replies, conversation/handoff state,
  engine disposition and any successor. Empty cursor, old last_transition_at or a closed engine
  is not independently proof that the run finished silently.
- Separate proven silent exhausted standard runs, existing terminal rows with missing enrollment
  mirroring, legitimate final waits, active conversations, human-controlled/held runs, unresolved
  sends, other journey modes, superseded rows and evidence-poor cases. Keep their reasons distinct.
- G1/R4 must choose treatment of pre-existing final waits explicitly: eligibility, original boundary
  evidence, handling of later replies and correction time. Do not silently infer a retroactive window
  or label deployment time as when every campaign actually completed.
- Apply only an authorized same-run conditional repair with retained original evidence plus actor,
  reason and correction time. Respect existing terminal end times and newer states; no recreated
  final sends, lost claimed keys, reset budgets, automatic re-entry or changed published versions.
- Unknown completion/start/receipt facts stay unknown with scoped review/containment and an owned
  support route. 4-A cannot recreate deleted engine history; message progress can be a clue, not
  sufficient evidence for every lifecycle fact or successful provider delivery.
- Approve exact cohort, dry-run output, batch/rate bounds, operator and stop criteria before any
  historical write. A successful future-path deployment is not proof the existing backlog was
  corrected; accepted-live names corrected cohorts and explicit remaining containment/follow-up.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close G1 and applicable R1–R4/test gates with named owners. Record the exact
   integrated A/B baseline, dependency versions, expected observable states/times and historical
   scope. No standalone terminalization release while its required reply route is absent.
2. **Safe rehearsal:** demonstrate AC-31 plus pending dispatch, final ordinary/interested/STOP
   replies, timing/receipt races, failed enrollment mirror, duplicate outcomes, old-run/successor
   fencing, protected controls and legitimate nonfinal sends using recording providers.
3. **Compatible cutover:** stage approved additive persistence/read support, inbound routing,
   completion producers, timer/engine changes and API/web presentation. Coordinate 2-A/7-A/17-A
   consumers and contain incompatible old writers. Verify representative Temporal history replay;
   do not reset customer engines to evade nondeterminism or missing identity.
4. **Bounded activation:** use the approved synthetic/canary scope before wider release. Confirm
   committed workflow/enrollment/history and engine convergence, correct final-response behavior,
   preserved consent/human control, and usable authorized new enrollment. Historical correction
   is separately authorized; enabling a worker must not silently drain old final waits.
5. **Operator acceptance:** show valid final wait versus completion, its reason/time, an actionable
   late reply and a blocked/unknown case, then retrieve old history after permitted re-entry. Brief
   operators that completion is not conversion, fresh consent or automatic return to selection.
6. **Monitor and own failures:** due/unfinalized age where applicable, workflow/enrollment mismatch,
   terminal-engine convergence backlog, late-reply processing/route failures, stale-run rejections,
   duplicate effects and permission errors. Compare counts by declared unit/cohort, not a fabricated
   single success total. Name the response owner; preserve privacy/tenant scope in operational data.

**Rollback:** stop unsafe new finalizations and contain incompatible writers through the approved
scoped control. Preserve completed business state, original times, audit, send claims and current
suppression/human ownership; do not mass-reopen terminal runs, reset engines or send again. Retain
a compatible post-completion reply route for already-completed leads even if the finalizer rolls
back. Keep unfinished windows and engine-convergence problems visible with owned follow-up. A
code rollback cannot undo customer contact or the new historical lifecycle facts; use an approved
forward-compatible repair where reverting readers/handlers would lose those facts or replies.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves the business outcome and Class A boundary; G1 and applicable R1–R4/test
  gates close with exact decisions and owners before their implementation/release.
- [ ] A silent standard run completes at the approved boundary without a chance signal, with one
  coherent workflow/enrollment/history outcome, meaningful reason/time and engine convergence.
- [ ] All standard final-action producers participate; pending/failed/unknown work, other journey
  ends, current protection and old-run/successor races cannot be mistaken for cadence completion.
- [ ] Ordinary/interested/opt-out replies before and after completion follow the exact approved
  routes, including ongoing/pending processing, closed engines and later enrollment. Receipt,
  contact restriction, handoff ownership and unresolved attention are not lost.
- [ ] Actual scoped API/UI/count/history and manual options/submission demonstrate truthful lifecycle,
  correct roles/reason, preserved prior completion and new-run identity/capacity without auto re-entry.
- [ ] Meaningful red-first, green, critical sensitivity and unchanged positive/safety controls are
  recorded; required real Postgres/Temporal/concurrency/replay/API-to-UI evidence passes rather than
  being replaced by fake close, invented terminal fixtures or skipped integrations.
- [ ] Historical treatment/containment, compatible canary and rollback retaining late-reply handling
  are rehearsed and separately authorized where production access/actions are involved.
- [ ] Independent product and technical reviewers accept the implemented journey; merged and
  accepted-live evidence remain separate. This draft checks none of those implementation boxes.

## 10. Related records and draft review record

- [Source Issue 8 — missing standard-cadence completion](../production-state-consistency-issues.md#issue-8--a-standard-cadence-lead-never-reaches-completed)
- [Business-impact contract — finish without losing the conversation](../production-state-consistency-issues.md#8--finish-a-campaign-without-losing-the-conversation)
- [G1 and remaining acceptance gates](../production-state-consistency-issues.md#readiness-conditions-that-remain--do-not-discover-these-during-manual-testing)
- [D1–D7 consensus and withdrawn D2 joint-release premise](../production-state-consistency-review-consensus.md)
- [3-A — enrollment lifecycle and actual start accounting](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [4-A — retained evidence and prior-run access](issue-4-a-retained-operational-evidence.md)
- [6-A — cannot-proceed versus genuine completion](issue-6-a-visible-cannot-proceed-outcomes.md)
- [7-A — same-journey engine recovery and protected terminal state](issue-7-a-missing-engine-recovery.md)
- [2-A — durable instructions and truthful engine effects](issue-2-a-reliable-instruction-delivery.md)
- [17-A — durable send claims and journey outcome ownership](issue-17-a-durable-outbound-dispatch.md)
- [9-A — deterministic STOP and unprocessed-reply protection](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [16-A — preserve recorded contact restrictions](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [17-B — separately released uncertain-touch accounting](issue-17-b-continue-cadence-after-uncertain-send.md)
- [14-B — separate tag-ended re-entry, not generic completion](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [13-B — separate consent and channel-fallback policy](issue-13-b-consistent-consent-and-channel-fallback.md)

Draft source trace completed against API a761c1b and web 04d4361 on 2026-09-08. It distinguishes
final send/accounting from business completion, the normally parked engine from an exited one,
caught terminal-transition skips from actual reply/handoff handling, conditional enrollment
mirroring, and existing controlled manual re-entry from automatic selection. No live production
count, runtime observation, reconstructed history or behavioral test result is claimed.

Independent product-reader and technical/source reviews completed with source-based adjudication.
Accepted refinements explicitly inventory non-opt-out declines and require a usable late-handoff
owner journey, not only message/handoff storage. Source rechecks distinguish the optional repository
on the generic transition helper from the advancement helper's actual signature, the null-cursor
AI-context fallback from cadence restart, and MANUAL_ADMIN enrollment source from an admin-only role.
Suggestions to fill G1 with permissive placeholder tests, ban all post-completion AI by default,
remove existing manager rights, prescribe unapproved timestamp fields or invent a resolution
endpoint were not adopted. Existing atomic/same-run/pending-inbound/rollback safeguards remain.

A final reader check found no remaining material drafting contradiction; it is not product approval.
Documentation validation passed (exit code 0): ten ordered sections, 32 acceptance rows, 49 unique
source/test file references, 20 unique local links across ticket/index including heading fragments,
index consistency and the unchanged prior-fourteen aggregate. Initial checks caught an incorrect
standalone continuation-test filename and stale G1 anchor; both were corrected and rechecked. API
a761c1b and web 04d4361 source worktrees remain clean.

G1, stakeholder review and R1–R4 remain open. No application code or prior ticket draft was changed;
no behavioral tests, production access, Jira publication, implementation or release was performed
for this draft.