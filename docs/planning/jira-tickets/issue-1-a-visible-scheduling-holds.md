# Issue 1-A — Make scheduling holds visible and safely recoverable

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the eighth proposed Jira description, not a published issue or permission to implement.
Approval to continue drafting does not approve implementation, production repair or release.

## 1. Business impact — read this first

**The promise:** If the platform cannot schedule a paused-search lead under the existing track
rules, it must say so, explain what needs attention, and provide a permitted route back to a valid
schedule. A lead must not look actively nurtured merely because nobody recorded its scheduling hold.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | A missing re-engagement date on a hold-configured track clears the next action without recording a paused state, workflow transition or review item. The engine waits, while operators can still see a lead that looks active. The source incident remained unnoticed for nine days. |
| What changes? | That existing scheduling decision becomes a durable, nonterminal scheduling review: outreach is held, the reason and history are saved, and authorized operators can discover it from attention and lead views. |
| Does this add a new reason not to contact someone? | No. The track already says not to proceed. This records and exposes the decision; it does not change missing-date rules, maintenance permissions, operational enablement or timing calculations. |
| What will the agent see? | A plain-language explanation such as “Scheduling needs review — the track requires a re-engagement date,” the affected track, when the hold began, and an appropriate correction/recovery action. Not “healthy nurture,” “message awaiting approval,” or a promised send time that does not exist. |
| What does the operator do next? | Correct the underlying data or permitted configuration, then use a permission-checked revalidate/resume action. If the inputs are still invalid, the hold remains actionable. A saved correction or queued instruction is not proof that scheduling succeeded. |
| Does correcting the date send immediately? | No. Successful recovery recomputes the next action using the existing track, progress, workspace timezone and quiet hours. A future action waits; a due action proceeds only through the normal protected send path. |
| Can “Mark seen” or “Skip” get around a missing date? | No. Seen is an acknowledgement, not resolution. A workflow-level hold with no occurrence has no message to approve or skip; those controls must not manufacture progress or bypass timing. |
| What happens to prior progress? | The same enrollment, pinned track, completed touches and send identities remain. Recovery is not a new enrollment or a restart from step one, and creating a hold does not consume a touch. |
| Who can act? | Existing owner/role and workspace permissions apply. Assigned agents need a usable own-lead path; wider workspace operators retain their existing access. Administrative enablement or track changes stay restricted to their current roles. |
| Will dashboards change? | Healthy-active counts can fall and paused/review counts rise as hidden stalls become visible. This exposes existing blocked work, not a new contact restriction or evidence that previously sent messages disappeared. |
| Are new notifications included? | No email, SMS, push or escalation timer is introduced. The required notification is the durable, discoverable in-product attention/review item and matching lead status/history. |
| What is not fixed here? | Holds first discovered during sending, unrelated cannot-proceed/engine-exit defects, general missing-engine recovery, and Class B consent/CRM/uncertain-send policies remain separate tickets. |

**Deployment is not historical repair.** An old engine already waiting silently might never run
the new scheduler until it receives an instruction. Inventory affected records and approve any
bounded repair separately; do not bulk resume every active lead with an empty next-action field.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — silent loss of nurture and operator visibility; confirm at publication |
| Source / delivery class | Production-state consistency Issue 1 / **Class A: schedule-time hold visibility and recovery** |
| Components | Paused-search scheduling; workflow/history and review persistence; schedule-result consumers; scoped attention/list/detail reads; permitted correction/revalidation |
| Repositories | miller-schackman-api and miller-schackman-web; one complete operator journey, not backend-only status plumbing |
| Sequence | Eighth draft, after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A and 17-B. Drafting order does not prove any predecessor is implemented or released. |
| Integration dependencies | Preserve 16-A's opt-out/refresh protection and 9-A's independent reply safety. Coordinate occurrence/send identity with separately integrated 17-A where those paths are touched. Verify the actual release baseline rather than assuming earlier drafts have shipped. |
| Not a prerequisite | Shipping 14-B, 13-B or 17-B. This A fix can expose existing scheduling holds without changing those policies. |
| Related boundaries | Issues 2/7 own general signal-delivery/missing-engine repairs; Issues 5/6 own send-time and other cannot-proceed outcomes; Issue 8 owns general completion. The new hold's own wait/revalidation path must still work end to end. |
| Owners | Name implementer, independent reviewer, API/web contract owner and release/recovery operator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; retrace the implementation branch |
| Closure boundary | Durable, discoverable schedule-time review and safe correction/rescheduling, with bounded recovery guidance; not a universal dead-letter or workflow reconciler |

**Included:** missing required timing data under a hold-configured track; other existing
nonterminal timing holds reached through the same scheduler; legitimate operational scheduling
gates with the appropriate explanation and authorized next step; repeat scheduling/wake-up safety;
occurrence-less review lifecycle; API/UI visibility, scoping, pagination and resolution; tests and
rollout guidance for this complete journey.

**Excluded:**
- Inventing a re-engagement date, changing fallback intervals, enabling maintenance outreach,
  bypassing the recurring feature flag/pilot allowlist, or changing pinned-track selection rules.
- New consent/fallback outcomes, CRM tag-control rules, reply-hold deadlines, provider failure
  routing, uncertain-as-sent accounting or callback policy. Preserve the baseline actually released.
- Treating every null next-action timestamp or every non-SCHEDULED result as this defect. Missing
  workflow/track/profile, inactive profiles, genuine completion and independent human holds have
  distinct outcomes; this ticket must not silently redefine them.
- General automatic engine restarts, all-campaign lifecycle reconciliation, reporting redesign,
  new delivery guarantees, and a generic hold/rules/notification framework.
- Automatic historical repair, unapproved production data writes, fresh enrollments on recovery,
  or enabling an obsolete “skip/approve” control for a review that has no occurrence.

**D7:** A and B must not share a PR. A scheduling-visibility fix must neither introduce a Class B
rule nor revert a separately approved B rule that is already present on its integration baseline.

## 3. Current behavior and contract to approve

### 3.1 What the code does today

The timing planner already returns HOLD_FOR_REVIEW for cases including no actionable phase and a
step cursor outside the pinned track. A missing re-engagement date plus the published HOLD_FOR_REVIEW
fallback is the incident's trigger. Other planner reasons distinguish absent steps, inactive
profiles, future schedules and configured terminal limits; they are not interchangeable.

The scheduling use case locks the latest workflow. Its nonterminal _save_hold path clears the
step cursor and next action, but leaves workflow state unchanged and writes no transition/review.
Its early recurring-disabled/pilot-excluded branch also returns HOLD_FOR_REVIEW, without using that
save path. Updating only _save_hold would leave that early branch unrecorded.

The scheduler's REVIEW status is already used for terminal behavior configured as pause-for-review;
it is not evidence that schedule-time holds have a durable review record. The next-cadence adapter
and Temporal loop recognize scheduling HOLD as waiting. Persisting PAUSED without adjusting the
affected consumers is insufficient: the next planner invocation can return WORKFLOW_NOT_SENDABLE,
and an unrecognized scheduling outcome can make the engine return instead of keep waiting.

Existing workflow state, pause_reason and transition history provide the durable business state.
PausedSearchReview already has POLICY and nullable occurrence/message references. However,
PostgresPausedSearchReviewRepository.create_or_get asserts a non-null occurrence and deduplicates
using workspace/occurrence/kind. PostgreSQL's existing nullable occurrence constraint does not
deduplicate workflow-level null-occurrence reviews. A nullable schema is not a complete creation,
identity or resolution contract; no “no migration required” claim is justified before design review.

Existing attention helpers recognize paused workflows, but that alone does not prove complete
visibility. Agent/admin attention composition, lead status presentation, review reads and their
limits must agree. Review listing currently limits workspace rows before application-level lead/
ownership filtering. An authorized lead's review can therefore be missed behind unrelated rows.
The global review-queue route has a wider-role gate than the own-lead operations permission.

Policy review actions already accept resume_after_revalidation, skip and terminalize, but generic
resume does not itself establish a valid paused-search timing plan. The policy action can call a
resume path that commits before the review is saved. Profile updates already enqueue rescheduling;
neither this signal nor a successful generic resume response proves that the held cause is fixed.
The existing UI's generic “workflow was signaled” copy must not be reused as evidence of recovery.

### 3.2 Classify outcomes without changing scheduling policy

Approve a concrete reason-to-outcome table at R1; cover phase-level and occurrence-level returns,
including early returns. The following boundaries are mandatory, not permission to add new holds:

| Existing situation | Required treatment in this ticket |
| --- | --- |
| Missing required date under the hold fallback; no actionable timing phase; stale cursor outside pinned track | Persist a nonterminal scheduling hold with its specific explanation. Never substitute a date, silently reset to step one, or send anyway. |
| NO_STEP_IN_PHASE or another nonterminal timing result which actually leaves this paused-search journey waiting with no valid next action | Make that existing scheduling hold visible, distinguish its cause, and direct it to authorized data/track correction. Do not call it track completion or invent a step. |
| Recurring feature disabled or workspace outside the pilot allowlist on an applicable paused-search workflow | Keep the operational block; expose the real cause and administrator action. Do not ask an agent to supply a date, enable the feature, or change the allowlist automatically. |
| A valid future schedule, quiet-hours roll-forward, or maintenance exhausted while waiting for a known reactivation window | Keep the scheduled wait and correct next action. No review item merely because no send is due now. |
| A configured default-interval fallback yields a valid schedule | Preserve that permitted fallback. Do not impose a required date on tracks that do not require it. |
| Occurrence/touch/duration limits with a published terminal behavior | Preserve that behavior, including existing terminal pause-for-review semantics. Do not classify genuine completion as a new scheduling defect or reopen it. |
| No workflow, no usable track/profile, inactive profile, or a workflow already protected for another reason | Do not manufacture this scheduling review from a generic result/null field. Preserve independent state/reason and record broader defects under Issues 5/6/7 as appropriate. |
| This ticket's own persisted scheduling hold is encountered again | Keep its durable waiting/review semantics; do not replace its reason with generic WORKFLOW_NOT_SENDABLE, complete the engine, or create another review. |

Operational branches must check the actual workflow/hold context before changing it. A flag check
that runs before the planner is not permission to overwrite a handoff, manual pause or terminal state.
A future date alone does not guarantee a valid schedule: before its reactivation window, a track
that does not permit maintenance outreach can still legitimately hold. Preserve that distinction.

### 3.3 Persist one durable, nonterminal hold episode

1. Use the existing validated workflow transition mechanism to record PAUSED with a stable,
   scheduling-specific reason and structured timing context. Record original planner reason,
   actionable detail, workflow/enrollment and pinned track/version; retain relevant cursor/phase
   evidence even if an unsafe pending schedule is cleared. Any new reason identifier is proposed
   implementation work, not an already-existing enum promised by this draft.
2. Commit the state, cleared actionable schedule, transition/history and pending review together.
   A crash or failure must not commit “active with no next action,” a paused lead without its review,
   or a review while the old schedule remains executable. Do not turn persistence failure into a
   successful HOLD return. Use existing failure/retry machinery without changing retry budgets.
3. Reuse the existing review concept, preferably a scheduling-specific POLICY review with
   occurrence_id and outbound-message references absent when none exist. Do not create a dummy
   occurrence/message, another workflow state machine, or a second source of truth for sendability.
   Existing message, terminal and unrelated policy reviews remain distinguishable and unaffected.
4. Define a stable, workspace/workflow-scoped scheduling-hold identity with database-enforced
   concurrency safety and a supported occurrence-less create/read path. Repeated scheduler calls,
   activity retries and concurrent delivery converge on one pending episode and one entry transition.
   The current nullable occurrence uniqueness is not sufficient. Approve any migration at R1.
5. Preserve the original hold-start time and acknowledgement version on unchanged retries. A
   substantive cause/context change must become visible and auditable, not masquerade as the old
   acknowledged item. Resolution retains history; a later distinct hold becomes a new actionable
   episode. Do not reopen/overwrite a resolved historical review or deduplicate all future holds away.
6. A scheduling hold does not send, consume a logical touch/occurrence, reset counters, replace the
   pinned track, close enrollment or create a fresh run. Preserve existing send/idempotency claims.
   The generic transition helper can cancel open occurrences when passed that repository, and
   CANCELLED currently consumes a slot: wiring it blindly would skip an unsent touch. Design the
   affected hold path so invalid schedules cannot execute without consuming or recreating progress.
7. A workflow-level scheduling review has no implicit message-review expiry. Do not auto-approve,
   auto-resume, skip a touch or disappear after a borrowed message-review timeout. It remains visible
   until valid resolution or an explicitly audited superseding business outcome.
8. Persisted state wins over stale wake-ups. Recheck the same current workflow/episode under the
   existing locking discipline. Never let a late scheduling result overwrite a manual pause,
   unresolved-reply protection, handoff, suppression, terminal decision or newer track/workflow.

### 3.4 Make the complete operator journey visible

- Lead list/detail, status narrative, relevant dashboard/workflow-status counts and attention must
  agree on “held for scheduling review.” Show the specific reason, hold-start time, affected track
  and permitted next step; do not imply a message was drafted, sent, delivered or awaiting approval.
- The assigned agent must discover the owned lead and reach its permitted correction/resolution
  flow. Do not send that agent to a role-forbidden global review page or grant wider workspace access
  as a shortcut. Authorized managers/admins retain their existing scope, including ownership gaps.
- Reuse the attention surface and review history; correlate projections of the same scheduling
  episode so it is not counted twice as both a generic paused-lead alert and a separate review item
  in one queue. Independent issues on the same lead must not be suppressed by this deduplication.
- Scope and filter before applying the relevant page limit. Provide a complete way to traverse
  applicable hold results, including those beyond the first page of leads or reviews. Do not claim
  completeness from increasing a hard-coded limit or from an empty filtered subset of workspace rows.
  Counts must have explicit matching semantics; broader pagination/reporting redesign is not required.
- Preserve acknowledgement semantics: seen/unseen affects presentation, not review status, workflow
  state, eligibility or progress. An unresolved seen hold remains discoverable using the existing
  all/seen views; a substantively changed or later episode must not inherit stale acknowledgement.
- Distinguish loading, empty, failed reads, rejected actions, queued recovery and successful
  scheduling. On API/read failure do not show “nothing needs attention.” After mutations, refresh
  affected status/review/attention queries; no new live-push or background polling contract is implied.

### 3.5 Correct, revalidate and resume without a bypass

1. Save authorized corrections using existing profile/track controls and their audit history.
   A data save or reschedule signal alone does not waive a pending scheduling review, consent rule or
   human control. The flow must clearly distinguish “correction saved” from “recovery requested.”
2. Require an explicit authorized recovery action and reason for this hold. Check current actor
   permissions, workspace, lead, workflow, review identity and current hold context at action time;
   an old tab/review must not resume a successor workflow or resolve a newer hold.
3. Revalidate the current timing inputs, effective pinned track/overrides, applicable operational
   gates and existing independent send/resume safeguards. A paused workflow cannot simply be passed
   through a planner guard that always returns WORKFLOW_NOT_SENDABLE and called revalidated. Approve
   a bounded way to evaluate the eligible candidate state without first committing an unsafe resume.
4. If the cause remains, keep the hold pending with an accurate explanation and no progress/send.
   A missing date cannot be solved by generic Resume, message Approve, Skip, a timing-update signal,
   or operator send-now. Enforce this on backend entry points as well as in UI controls; do not
   disable unrelated, valid occurrence-level review/skip behavior.
5. On successful recovery, recompute using existing progress and clocks, and arrange the resulting
   schedule and durable engine instruction consistently. Treat a queued instruction as queued, not
   applied. Keep the hold/recovery work discoverable until an authoritative successful scheduling
   outcome exists; do not permanently close its review merely because generic resume returned OK.
   The R2 design must make review resolution, workflow/schedule and any outbox effects recoverable
   across the existing inner commit points and lost responses.
6. A future schedule waits, and an otherwise allowed due touch proceeds once through the normal
   sender. A stale timer or duplicate recovery command must not use the old time or mint another
   occurrence/dispatch identity. Subsequent sending still rechecks current send-time safeguards.
   Changes first discovered at send time remain Issue 5; this ticket does not implement that repair.
7. An independently authorized terminal/profile-clear/human-control outcome may supersede the
   scheduling problem, but must preserve its history and explain the new state without reporting
   nurture resumed. Do not make old scheduling actions effective against it. A genuinely terminal
   choice remains explicit and audited; “End track” is not a disguised timing override.
8. Exercise the new hold through the next-cadence adapter and Temporal wait/signal loop, including
   repeated recomputation while still held. It must remain waiting rather than exit or busy-loop.
   Prove existing live-run correction/resumption; if a missing engine needs Issue 2/7 work, leave an
   honest actionable recovery failure and named dependency rather than claiming this ticket built a
   universal restart mechanism. Compatibility for already-running histories is a release gate.

### 3.6 Remaining implementation and release gates

These are unresolved design/verification gates, not a reopening of the settled missing-date policy.

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Outcome and durable identity | Approve the exact branch/reason matrix, episode identity and structured fields; workflow-level review creation/uniqueness and migration; lock/transaction boundaries; cursor/occurrence treatment without consuming a touch; unchanged- versus changed-cause acknowledgement behavior. | Persistence/scheduler implementation |
| R2 — Correction and recovery contract | Approve permitted entry points/actions, candidate-state timing revalidation, old-review rejection, superseding outcomes, queued-versus-applied results, review-closure timing, transaction/outbox ordering and live-run Temporal wait/replay compatibility. Identify any actual Issue 2/7 blocker, not a presumed repair. | Resolution/engine implementation and integrated acceptance |
| R3 — Operator/read contract | Agree on own-agent versus wider-role access, human-readable causes/actions, queue projection/deduplication, pagination/filter/count semantics and required UI states; keep administrative permissions unchanged. | API/UI implementation |
| R4 — Release and existing stalls | Name operator, compatible API/web/worker/migration order, historical inventory and separately authorized containment/repair, regression commands and rollback that retains holds/history/progress. Brief operators on newly visible stalls and changed counts. | Production rollout/live acceptance |

Approve the applicable gates and §4–5 test boundaries before implementation. No unanswered gate
may be silently decided by weakening an acceptance assertion to fit the code.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic leads, fixed clocks,
literal expected dates and recording transports. Include both supported planner modes where the
behavior is shared; a happy-path fake result does not prove transaction or Temporal behavior.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Enroll an otherwise eligible paused-search lead with no required re-engagement date and a hold-configured track; run scheduling and commit. | Same workflow becomes nonterminal scheduling review; no next executable action, specific missing-date explanation, one history transition and pending review; zero provider calls. Fresh detail/attention expose it. | Active-looking lead with no explanation, guessed date, dummy message/occurrence, or a send. |
| AC-02 | Reach the same hold after earlier real touches, with a pinned track and recorded cursor/occurrence/dispatch history. | Hold preserves enrollment, track and completed progress/claims; retains diagnostic cursor context and consumes no new slot. Recovery later continues from correct progress. | Restart from step one, new enrollment, erased send evidence or a cancelled unsent occurrence counted as a completed touch. |
| AC-03 | Parameterize the approved nonterminal reason matrix: no actionable phase, stale pinned-track cursor, and no-step/occurrence-planner holds without a valid future action. | Each existing hold becomes one correctly explained scheduling review with the relevant correction action; no invented steps or completion. | Fixing only the incident branch, generic missing-date copy for every cause, or treating all non-SCHEDULED outcomes alike. |
| AC-04 | Disable recurring scheduling or exclude an applicable workspace from the pilot; repeat with a manual pause, handoff and terminal workflow. | Active applicable journey exposes its unchanged administrative block; protected workflows keep their state/reason and cannot be resumed by that gate. | Early HOLD bypasses persistence; flag/allowlist enabled automatically; an agent gets administrative controls; human state is overwritten. |
| AC-05 | Healthy controls: a planner-valid future schedule under existing track/maintenance permissions, quiet-hours roll-forward, and exhausted maintenance with a known future reactivation window. | Literal next-action times remain correct and the existing wait is scheduled; no new scheduling review or premature send. At a permitted due time the positive-control touch can send once. | “No message now” classified as a defect, all nurture paused, or a future date treated as permission to send now. |
| AC-06 | Missing date where the configured fallback produces a valid schedule; parameterize USE_DEFAULT_PAUSE_DURATION and USE_MAINTENANCE_INTERVAL with valid track/maintenance settings. | Each existing fallback schedule and allowed journey remain unchanged. | This fix imposes a universal date requirement, changes the fallback interval, or bypasses maintenance permissions. |
| AC-07 | Reach published occurrence/touch/duration limits under each supported terminal behavior. | Existing completion/closed/terminal-review outcome and enrollment treatment remain; no added scheduling-hold episode or reopened journey. | Genuine completion becomes an indefinite scheduling review, or terminal pause-for-review is mistaken for successful resumption. |
| AC-08 | No workflow, missing pinned track/profile, inactive profile, independent manual/reply hold, handoff/human ownership, and suppressed/closed/completed controls. | No manufactured scheduling review or new outreach; existing protected states/reasons remain. Record any separate cannot-proceed defect under its own ticket. | Inferring this hold from any null timestamp, false positive review on an unrelated lead, or sweeping broader Issue 6 behavior into this PR. |
| AC-09 | Repeat the same hold computation, replay an activity, and race two scheduling attempts using real persistence. | One pending episode and one entry transition; stable start time and unchanged seen-version; no duplicated occurrence or outbox effect. | Null-occurrence uniqueness admits duplicates, retries continually reset age, or duplicate history/notifications. |
| AC-10 | Fail each hold write/commit boundary and retry from an independent session. | No partially committed workflow/schedule/history/review tuple and no send; failure is recorded honestly and retry can produce the complete hold. | Fake-only rollback proof, successful HOLD with lost evidence, or review saved while the stale next action can execute. |
| AC-11 | A planned/deferred unsent occurrence exists when a scheduling hold is discovered; later correct and recover it. | Old due work cannot execute while held; unattempted slot/progress is retained and the valid next action uses coherent existing identity. | Blind transition cancellation consumes the slot, recovery skips the touch, or schedule-time correction resurrects a claimed/uncertain send. |
| AC-12 | After durable PAUSED is saved, deliver harmless reschedule/timing-update and duplicate wake-ups before correcting anything. | Adapter and real Temporal loop remain waiting on the same visible hold without send, engine exit, duplicate episode or busy-loop. | WORKFLOW_NOT_SENDABLE interpreted as finished work or a signal alone clears the hold. |
| AC-13 | Replay representative running histories and execute the hold/correct/recover path in standard and recurring execution modes that reach this scheduler. | Compatible result/signal handling, one live journey and preserved progress; actual Temporal evidence supports the release plan. | Compatibility claimed from mocked activities alone, incompatible result changes, or a second engine created to hide a wait bug. |
| AC-14 | Read as owning agent, unrelated agent, permitted manager/admin, inactive member and another workspace; include an unowned lead for wider-role operators. | Allowed list/detail/attention/review data and counts agree; own-agent correction is reachable without a forbidden route; disallowed reads/actions stay denied. | Cross-tenant access, broadening roles to fix navigation, or manager visibility used as proof that the assigned agent can act. |
| AC-15 | Put an owned held lead/review after more than the existing page limit of unrelated rows; traverse supported views and lead-scoped review reads. | Scope/filter-before-limit and pagination allow discovery; counts match their declared scope; a hold is not double-counted in one queue. | Empty first subset reported as no work, bigger hard-coded limit presented as completeness, or duplicates across generic-paused/review projections. |
| AC-16 | Mark the hold seen, refresh, retry unchanged scheduling, then materially change its cause; later resolve and create a distinct new episode. | Seen never resolves/resumes; unresolved item remains in all/seen views; unchanged retry stays stable; changed/new episode becomes actionable/unseen with retained history. | Acknowledgement releases outreach, a new hold inherits old seen state, or every heartbeat becomes a new alert. |
| AC-17 | Save a corrected date without requesting resume; separately request recovery while date remains absent/invalid or an operational gate still blocks. | Save is accurately reported; no implicit resume. Failed revalidation leaves actionable current hold with specific reason and zero provider calls. | Profile-save signal or generic “resume requested” clears review despite invalid timing. |
| AC-18 | Correct the data and explicitly request permitted recovery with a future valid next action. | Current inputs/track/progress are revalidated; authoritative scheduling resolves the matching review with actor/reason/history; future action is shown and awaited. Queued work is labelled queued until applied. | Review disappears before valid scheduling, past timer reused, controls silently change the track, or response claims a message was sent. |
| AC-19 | Recover with an otherwise eligible due action; retry the command after a lost response and deliver duplicate wake-ups. | Exactly one intended test-provider submission for the unattempted touch under the existing send-identity contract; no extra occurrence, consumed slot or enrollment. Later legitimate progress still works. | Lost response triggers another send, idempotency key reset, duplicated accounting, or every recovery blocked to make the zero-send cases pass. |
| AC-20 | Attempt generic Resume, Approve, Skip, direct policy-resolution API calls and operator send-now against the unresolved occurrence-less hold. | Backend and UI prevent bypass or fictional progress; approved revalidation is the only resume route. Existing valid occurrence-level message review/skip controls still work. | Hidden button is the only protection, dummy occurrence manufactured, skip resolves missing data, or all policy reviews lose valid actions. |
| AC-21 | Act from an old review/tab after resolution, track/workflow replacement or a later hold episode; repeat a successful action's idempotency key. | No-op/already-resolved/stale result as appropriate, with current state unchanged; original audit retained and no extra signal/send. | Old review resumes the latest workflow by lead ID alone or resolves a newer cause. |
| AC-22 | While held, apply an independently authorized profile-clear, terminal outcome, manual pause, handoff or suppression; then deliver stale recovery work. | New independent outcome remains authoritative; scheduling review is retained or audited as superseded with accurate current actionability, never “nurture resumed.” | Hold correction removes independent safeguards, resurrects a closed enrollment or leaves a misleading pending Resume for an obsolete run. |
| AC-23 | Interleave schedule/resolve with date or track changes, reply protection, manual control and suppression using independent DB sessions. | Revalidate current state/identity under the approved locking contract; stale computation cannot overwrite the newer guard or commit an invalid executable schedule. | Last stale writer wins, cross-workflow updates, or real concurrency claimed from serialized fakes. |
| AC-24 | Lose the action response; fail before/after recovery-intent commit; delay/fail the wake-up; include a missing engine. | Idempotent recoverable work, honest queued/failed state and discoverable unresolved recovery. Live-engine retry can converge; any missing-engine dependency is explicit, never a fabricated delivery success. | Review closes permanently with no schedule/engine, blanket automatic restart, or Issue 2's general repair claimed delivered without evidence. |
| AC-25 | Existing message, terminal and unrelated policy review controls, expiry, list/history and null message fields are exercised alongside the new hold. | Existing valid behavior remains; scheduling review renders without a message and does not expire into automatic send/skip or steal another review's identity. | New uniqueness collides with unrelated reviews, UI requires a message body, or existing message approvals are broken. |
| AC-26 | Dry-run inventory of synthetic historical stalls alongside healthy waits, terminal/manual/handoff cases and missing-engine cases; rerun an approved scoped hold-recording rehearsal. | Only evidenced schedule-time stalls are classified for repair; rerun is idempotent, records current discovery honestly and sends/resumes nothing. Ambiguous cases remain explicit. | Bulk mutation from next_action_at IS NULL, fabricated original timestamps, live CRM replay, or production repair without separate approval. |
| AC-27 | In integrated API/UI flow, fail/load the review and lead reads, reject a correction, queue recovery, then complete valid scheduling and refetch. | Correct loading/error/empty distinctions, truthful action feedback, refreshed matching lead/attention/review state and accessible correction links. | Fixture-only UI pass accepted as end-to-end proof, failed query shows healthy/empty state, or a queued request is toasted as applied. |
| AC-28 | Run existing safety and ordinary-nurture controls on the declared integration baseline, including opt-outs, unresolved replies, human control and already-claimed/uncertain sends. | Hold discovery/acknowledgement/correction creates no new outreach; successful eligible recovery uses that baseline's safeguards and accounting. No Class B policy changes. | CRM refresh erases restrictions, held lead gains a send bypass, an uncertain touch is retried, or new consent/CRM/callback policy ships in this A PR. |

AC-26 is a safe rehearsal requirement for the recovery runbook, not approval to run a repair in
production. AC-19's once-only assertion is for the identified test touch and known local failures;
it is not a provider-wide exactly-once-delivery guarantee.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Scheduling → fresh state/review reads:** existing scheduling use case and cadence activity
  adapter, actual planner/transition rules, persisted list/detail/review results (AC-01–11).
- **Correction/recovery commands → scheduling:** real profile update, review action and alternate
  resume/send entry points with current permission checks; observe schedule/progress/provider call
  counts and action results, not a helper-call count (AC-17–24/28).
- **Persistence:** local/disposable real PostgreSQL, migrations and independent sessions for
  null-occurrence uniqueness, atomic writes, row locking, lifecycle, stale actions and scoped paging.
  Read through supported repositories/APIs; database assertions are appropriate for explicitly
  agreed persistence invariants, not an unapproved side channel (AC-09–11/14–16/21–26).
- **Durable execution:** actual Temporal test environment/replay for held wake-ups, correction,
  duplicate signals, retry and result compatibility; run the real business activities where the
  claim depends on them. A fabricated HOLD result cannot prove the saved-PAUSED cycle (AC-12–13/18–24).
- **Operator experience:** frontend API/route/helper tests and a synthetic real API-to-UI acceptance
  demonstration covering permissions, queue completeness, acknowledgement and failure/recovery
  feedback. Use the existing test tooling; do not add a browser/dependency project (AC-14–18/25/27).
- **Existing business flow:** recording CRM/LLM/send transports plus unchanged cadence, profile,
  terminal/review behavior and earlier safety regressions; include a permitted due-send positive
  control, not only zero-send assertions (AC-02/05–08/11/19–20/25/28).

**Allowed fakes:** external transport ports, fixed clocks and hand-written repository fakes for
fast application cases. Do not mock the timing decision, permission check, state transition or
review lifecycle being tested. Fake transactions and a mock Temporal client are not evidence of
real atomicity, concurrency, signal handling or replay compatibility. Use literal independently
worked expected dates/states; do not obtain expectations by running the production planner again.

1. Approve one scenario and boundary. Write and run its behavioral test against unchanged code,
   record the meaningful failure, implement the smallest complete repair, and rerun the same test.
   Continue one vertical slice at a time; do not write all implementation first and retrofit tests.
2. Start with AC-01: scheduling the missing-date fixture must fail on saved state/history/review
   visibility, not just on an expected new enum/import. Minimal no-op interface scaffolding may
   make the seam runnable, but record it separately; setup errors, skips and missing services are
   not red evidence.
3. Baseline controls may already pass. If the first fix makes another defect scenario pass,
   demonstrate sensitivity against baseline or an isolated mutation instead of inventing a red.
4. Independently remove hold persistence; remove the workflow-level uniqueness; make PAUSED map
   to engine exit; accept generic resume without timing validation; restore limit-before-scope;
   consume a slot on hold; close review at request-only success. Each relevant protection test must
   fail for its intended business reason. Restore the implementation and rerun; no mutation ships.
5. Have an independent reviewer check expected dates, state/action semantics, no-send boundaries
   and positive controls. Do not change assertions merely to accept a partial status-label repair.
6. Record exact commands, revision, pass/fail/skip counts and integration limitations. Escalate a
   genuinely ambiguous failing expectation rather than silently changing policy to make it green.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills every applicable case | Reproducible invocation | Business assertion, not setup failure | Revision, exit code and counts | Observed protection failure or justified unchanged control | Named remaining limitation |

## 6. Engineering starting points — navigation, not a prescribed design

Paths below are repository-relative at the reviewed baseline; they are navigation hints, not new
APIs or a claim that the target behavior exists. Retrace callers/composition roots before editing.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — timing and schedule persistence | app/domain/campaigns/paused_search_timing.py; app/application/use_cases/schedule_next_paused_search_action.py |
| API — workflow/history and transition side effects | app/domain/workflows/models.py; app/application/use_cases/apply_workflow_state_transition.py |
| API — cadence/engine boundary | app/application/use_cases/campaign_cadence_execution.py; app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/lead_nurture.py |
| API — review domain/creation/resolution | app/domain/campaigns/paused_search_reviews.py; app/application/use_cases/paused_search_message_review.py; app/application/use_cases/paused_search_operations.py |
| API — review/occurrence persistence | app/infrastructure/persistence/postgres/paused_search_review_repository.py; app/infrastructure/persistence/postgres/paused_search_occurrence_repository.py; app/infrastructure/persistence/postgres/models.py; alembic/versions/0063_add_paused_search_reviews_notifications.py |
| API — correction, resume and reschedule | app/application/use_cases/lead_paused_search.py; app/application/use_cases/lead_resume.py; app/application/services/lead_nurture_rescheduling.py |
| API — read contracts/authorization | app/application/use_cases/lead_read.py; app/domain/identity/permissions.py; app/interfaces/api/v1/leads.py; app/interfaces/api/v1/paused_search_tracks.py; app/interfaces/api/schemas/paused_search_tracks.py |
| Web — attention and lead presentation | src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/leadPresentation.ts; src/lib/presentation/operations.ts |
| Web — operator routes and detail | src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx; src/pages/ReviewQueuePage.tsx; src/pages/HomePage.tsx; src/app/router.tsx |
| Web — current read/action clients | src/lib/api/leads.ts; src/lib/api/pausedSearchOperations.ts |

**Compare at least two approaches before coding:**
- **Recommended: extend existing workflow/history plus POLICY review support for scheduling
  episodes.** Reuses current state/permissions/operator surfaces and avoids another truth source.
  Requires explicit occurrence-less uniqueness/creation, reason-specific actions and transaction/
  Temporal work; it is not a one-line _save_hold change. Scoped indexed reads should avoid full
  workspace scans, and no network I/O belongs under a long-held DB lock.
- **Alternative: a dedicated scheduling-review model and read/action surface.** Can enforce a
  separate schema cleanly, but duplicates lifecycle, scoping, queue and migration work and risks
  contradictory hold state. Justify that complexity only if the existing model cannot express the
  approved invariants safely. A generic review engine is not an acceptable V1 shortcut.

A badge derived solely from null next_action_at, or PAUSED without a durable review/recovery path,
is not a complete alternative. Obtain design approval for the smallest complete approach. Thread
required repositories through every enabled production caller; optional dependencies must not
silently preserve the old partial-write behavior. Keep SQL/Temporal vendor types in adapters.

**Existing test starting points, not claimed new coverage:**
- tests/domain/campaigns/test_paused_search_timing.py
- tests/domain/campaigns/test_paused_search_reviews_notifications.py
- tests/application/use_cases/test_schedule_next_paused_search_action.py
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_paused_search_operations.py
- tests/application/use_cases/test_lead_paused_search.py; tests/application/use_cases/test_lead_resume.py
- tests/application/use_cases/test_lead_read.py; tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_paused_search_review_notification_repositories.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- tests/interfaces/api/v1/test_leads.py; tests/interfaces/api/v1/test_paused_search_tracks_admin.py
- Web: src/lib/api/pausedSearchOperations.test.ts; src/pages/ReviewQueuePage.test.tsx;
  src/app/LeadsRoutes.test.tsx; src/app/AdminOperationsRoutes.test.tsx

Locate the current Temporal test/replay targets as part of R2 rather than treating an application
fake as their substitute. Use Python 3.12/uv: one exact pytest node, its file, related suites, then
make lint, make typecheck and make test. For web changes run focused Vitest tests, then pnpm test,
pnpm typecheck and pnpm lint. Record exact integration targets; local/disposable services only.
Skipped Postgres/Temporal tests remain missing evidence, not a pass. No real-customer sends.

## 7. Existing affected records and bounded recovery

- Deliver a dry-run inventory/runbook separating evidenced schedule-time stalls from healthy
  future waits, independent holds, completed journeys, missing inputs owned by Issue 6 and absent
  engines owned by Issue 7. A live-looking state plus null next action alone is not sufficient proof.
- Use current pinned track/profile/progress and available history to identify cause; do not infer
  permission to contact from an engine's presence or reconstruct missing dates from guesswork.
  Where no original hold event exists, record discovery time honestly rather than inventing a
  historical start/actor. Preserve evidence of uncertainty and unresolved classification.
- A bounded repair, if approved, records the same hold/review invariants idempotently and preserves
  all send claims and restrictions. It does not resume, send, restart enrollment or change track
  policy. No such command is claimed to exist; any new command needs its own approved test-first
  boundary, dry-run output and transaction/tenant/retry evidence before execution.
- Correct and recover a lead only through the permitted action and current safeguards. Apply
  Issue 16's approved evidence recovery before re-enabling affected sends when suppression history
  needs repair. Missing-engine recovery must identify its existing supported path or separate
  dependency; blanket restarts and webhook replay are not this ticket's recovery strategy.
- Production mutation requires separately approved environment/workspace/lead scope, operator,
  exact commands, limits and verification. Inventory work must not log raw CRM payloads, contact
  information, message content or secrets. Report safe counts and narrowly necessary identifiers.
- Live acceptance needs either verified correction of the in-scope historical stalls or explicit
  containment with named operator follow-up. Do not claim deploy alone has surfaced engines which
  remain asleep in the old silent HOLD branch, or label a pending historical repair complete.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4 gates; name owners; inventory affected records and
   all scheduler/activity/API/web consumers. Record which earlier A/B changes are actually present.
   Demonstrate unchanged policy instead of importing approved-but-unreleased rules into this PR.
2. **Safe rehearsal:** synthetic missing-date hold → discover as own agent/manager → correct →
   revalidate → future wait/due positive-control send. Include duplicate wake-up, still-invalid
   correction, independent handoff/opt-out, paging beyond first page, persistence failure and replay.
   Use real local persistence/Temporal and recording transports, not production customers.
3. **Compatible deployment:** apply the approved additive schema/index changes before dependent
   writes where needed; coordinate API/web/worker capabilities and running-history compatibility.
   Old workers can still return silent HOLD or exit on a newly persisted pause. Retire/contain those
   versions before calling the feature live; no blanket run reset or progress rewrite.
4. **Historical handling:** run only approved inventory/repair steps from §7 and verify fresh scoped
   reads. Report counts for surfaced, still-ambiguous and separately blocked records. Do not bulk
   resume/send to demonstrate that the backlog moved.
5. **Operator acceptance:** show specific cause, audit entry, one actionable review, safe seen state,
   working own-lead navigation, and honest queued/applied recovery. Explain that review totals can
   rise as pre-existing stalls become visible; there is no new automatic notification or timing rule.
6. **Observe:** use safe metadata for new/repeated holds, age, cause, recovery requested/applied/
   rejected/failed, duplicate-episode detection and unexpected engine exits. Reconcile relevant
   healthy/paused/review counts without presenting queue length as message delivery statistics.

**Rollback:** contain incompatible scheduler/resolution workers before reverting. Preserve hold
state, review/transition history, pending recovery intent and occurrence/dispatch claims; do not
clear holds or restore an “active with no explanation” snapshot. An older build may not understand
occurrence-less reviews or the new wait semantics, so document a compatible rollback/forward-fix
path and retained operator access. Never drop evidence/uniqueness merely to make old code start.
Production rollback or repair requires explicit approval and verification; it is not authorized here.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4: same timing policy, visible nonterminal hold, explicit revalidation,
      no occurrence-less skip/send bypass and protected independent controls.
- [ ] R1/R2/R3 design and API/UI action/read contracts agreed; implementer/reviewer/baseline recorded.
- [ ] §5 public test boundaries and first meaningful failing missing-date test approved.
- [ ] Shared occurrence/dispatch/safety integration and any real Issue 2/7 blockers are explicit;
      no Class B delivery hidden in this A ticket.

### Ready to merge
- [ ] Every applicable AC/variant maps to actual test/command evidence, meaningful red/green and
      sensitivity/positive controls; expectations independently reviewed.
- [ ] Real Postgres proves occurrence-less identity, atomicity, locking, stale-action protection,
      tenant/owner scoping and paging; real Temporal proves the saved-PAUSED wait/recovery cycle.
- [ ] Current-state/history/review/schedule remain coherent; review actions, profile saves, generic
      resume, stale signals and operator send-now cannot bypass this hold or independent safeguards.
- [ ] API-to-UI own-agent and wider-role journeys work, including no-message reviews, seen state,
      queue completeness, correct counts and failed/queued/applied feedback.
- [ ] Existing timing, fallback, terminal, message-review, progress and consent/CRM/uncertainty
      baseline controls pass; no new dependency or broad rules/recovery framework slipped in.
- [ ] R4 runbook supplies compatible rollout/replay/rollback, historical limits, operator ownership
      and evidence gaps; neither a new command nor a production repair is falsely claimed executed.

### Production acceptance complete — not merely merged
- [ ] Approved schema/API/web/worker versions deployed with no remaining silent-hold writer in scope.
- [ ] Synthetic integrated hold/correct/revalidate/reschedule and protected-state demonstrations
      recorded with no customer contact or fake-only integration claim.
- [ ] Historical in-scope stalls surfaced/recovered as separately approved, or explicitly contained
      with named follow-up; ambiguous/missing-engine cases remain accurately labelled.
- [ ] Stakeholder accepts the visibility/count change and unchanged scheduling policy; separate
      Issues 2/5/6/7/8 and Class B tickets are not marked delivered by this release.

**Evidence status at drafting:** source/code trace and document/reference validation only. No
application implementation, behavioral test run, Jira publication, commit, deployment or data repair.

## 10. References and decision precedence

- [Source Issue 1 and business-impact/readiness appendix](../production-state-consistency-issues.md)
- [Consensus — D7 release classes and D5 visibility briefing](../production-state-consistency-review-consensus.md)
- [Issue 16-A — preservation/recovery safety](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — independent inbound safety](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 17-A — separately integrated durable-dispatch mechanics](issue-17-a-durable-outbound-dispatch.md)
- [Issue 17-B — separate uncertainty policy, not implemented here](issue-17-b-continue-cadence-after-uncertain-send.md)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product, layering and design gates.

The source plan supplies the wider target; this draft bounds the proposed schedule-time A slice.
Escalate newly discovered policy or broader lifecycle questions explicitly. A review draft is not
implementation or release approval, and a visible badge alone does not satisfy the promised journey.