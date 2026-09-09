# Issue 17-B — Continue the cadence after an uncertain send without sending that step again

**Status: DRAFT — business, test-contract and engineering-readiness review required.**
This is the seventh proposed Jira description, not a published issue or permission to implement.
It implements the recorded **Class B uncertain-send policy**. Issue 17-A owns durable-dispatch
mechanics; its separate draft and the five earlier drafts remain unchanged. The policy is decided;
the implementation contract and individual owner release sign-off are not yet complete.

## 1. Business impact — read this first

**The promise:** A missing or ambiguous provider answer must not freeze an otherwise eligible lead.
Count that outreach attempt once for the journey, continue on its configured schedule, and never
send the uncertain step again. Keep the delivery record honest: counting a touch is not proof that
the provider accepted it or that the lead received it.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | Uncertain cadence and AI-send outcomes can pause the stored workflow. Temporal waits for resolution, then can wait indefinitely after 24 hours. A callback can wake the engine without removing the database pause, leaving a lead dark even after delivery is confirmed. Paused-search has additional occurrence timeout and manual-resolution behavior. |
| What changes? | Once the original attempt is durably classified as uncertain, it consumes the applicable step, occurrence or AI turn once. The eligible journey continues as its normal sent counterpart would, without waiting for a delivery callback, timeout or operator resolution. |
| Does uncertain mean delivered? | No. Provider acceptance itself may be unknown. The timeline says delivery is uncertain and the attempt counted for cadence; it must not manufacture a provider ID, sent/received timestamp or successful-delivery claim. |
| What if the provider never sent it? | That touch can be missed. The system will not replace it or send a second copy to eliminate doubt. Subsequent configured touches still proceed when allowed. This is the accepted continuity-versus-certainty trade-off. |
| Could messages reach the lead close together? | Yes. A delayed uncertain message might arrive near the next scheduled touch. The platform cannot control that provider delay. Application sending hours and applicable spacing rules still apply; this policy does not authorize an immediate next message or catch-up burst. |
| What if a later callback says failed? | Correct the delivery record. Do not pause the lead, refund its touch/AI budget, rewind the track, resend the failed-now-but-originally-uncertain step, or send an alternate-channel replacement. |
| What if no callback ever arrives? | Background reporting marks the unresolved reconciliation timed out; the cadence does not depend on that reporting job. Operators can inspect uncertainty without being required to resolve it to keep nurture running. |
| Can other conditions still stop outreach? | Yes. Current consent, global do-not-contact, human controls, unresolved replies, configuration, timing, caps and legitimate review/terminal rules remain decisive. A consumed touch may reach a configured limit; that is not an uncertainty hold. |
| What about Send now and Approve and send? | After 17-A's durable queue acknowledgment, an uncertain outcome completes the applicable journey accounting once, while the action/review and delivery states remain distinct. Neither “sent immediately” nor another approval/retry is the answer to uncertainty. |
| Does a handoff acknowledgment restart nurture? | No. Its existing handoff purpose remains authoritative. An uncertain acknowledgment is not resent and does not clear human ownership or become a cadence touch. |
| Does this fix all sending reliability? | No. It consumes the separately implemented 17-A durability and non-redispatch contract. It promises neither provider-wide exactly-once delivery nor eventual confirmation of every uncertain message. |
| Will existing held leads restart automatically? | Not simply because the code is deployed. An authorized, bounded recovery plan must identify uncertainty-only holds, preserve other restrictions and account for what already progressed. Historical uncertainty is not permission for bulk resume or resend. |

**Unchanged:** approved content, channel/consent policy, authorized human controls, original run/track
identity, normal send acceptance, definite-failure handling, configured cadence/occurrence/AI limits
and completion/re-entry policy. The change removes uncertainty as a reason to stop; it does not
remove every reason a lead can be stopped.

## 2. Ticket identity, scope and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — recorded contact-policy change; confirm at publication |
| Source / delivery class | Production-state consistency Issue 17 / **Class B: uncertain-as-sent for cadence, not delivery** |
| Repositories / components | miller-schackman-api: outcome completion, cadence/AI/occurrence accounting, Temporal, callbacks, report sweep, operator APIs and reads; miller-schackman-web: affected action/status/health presentation |
| Sequence | Seventh draft after 16-A, 9-A, 11-A, 14-B, 13-B and 17-A. Draft order is not evidence that any implementation shipped. |
| Required foundation | Identify the integrated 17-A revisions and D6/G6-sized journey coverage: durable original intent/claim, uncertainty classification, non-redispatch, occurrence/purpose linkage and recoverable completion. A draft alone is not this prerequisite. |
| Safety integration | Preserve 16-A opt-out durability/recovery, 9-A deterministic STOP and unresolved-reply protections, 11-A ownership projection, and the actual released consent/CRM-control contracts. Record integrated revisions. |
| Separate policy / lifecycle | 13-B owns consent fallback; 12-B owns carrier-opt-out handling; 14-B owns CRM tag controls; 9-B owns the reply-escalation window. Issue 8/G1 owns standard completion/late replies; 2/7/10/15 own broader signal/engine/failure recovery. |
| Owners | Name implementer, independent reviewer, product/release owner and recovery/reporting operator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; retrace the actual post-17-A branch before code |
| Readiness | Close §3.7's applicable R1–R4 stages and D7/G7 release requirements. No new vote on whether uncertain should pause is required. |

**Included:** uncertainty-driven once-only progression on every relevant journey; truthful separate
delivery evidence; audit-only delivery reconciliation and reporting expiry; removal of uncertainty
waits and unsafe resolution side effects; affected API/UI/accounting readers; test-first proof;
compatible Temporal cutover and a scoped plan for legacy records.

**Excluded:** building 17-A's missing dispatch foundations in this PR, new retry/channel/consent
rules, provider replacement, generic workflow/reconciliation platforms, blanket removal of review
signals, new notification policy, arbitrary retention/spacing values, automatic re-entry, and bulk
historical repair. Policy-specific schema/contract changes belong here if justified; independent
mechanical defects need separately scoped A work, not a mixed PR.

**D7:** A and B must not share a PR. B can build on accepted A interfaces, but cannot be accepted
while a production bypass can repeat its uncertain touch. If staged, name complete B-only journey
slices and an explicit activation boundary; do not advertise “every journey” with partial coverage.

## 3. Current behavior and contract to approve

### 3.1 Verified starting point — distinguish source, prerequisites and target

- The durable dispatcher records UNCERTAIN for ambiguous provider outcomes and stale in-flight
  claims, retains reconciliation and appends a reschedule instruction. That is not itself proof
  that the original journey advances. Ordinary accepted dispatch already has a completion path
  without waiting for a delivered callback.
- Cadence completion accepts SENT/ALREADY_SENT; UNCERTAIN instead reaches the block/pause path.
  AI continuation also pauses on uncertainty; its successful branch charges ai_interaction_count
  only for SENT. Merely returning a successful-looking status would hide the wrong accounting.
- Temporal's uncertain branch sets its send block, waits up to 24 hours and then waits without a
  deadline. With no occurrence/reconciliation identity it can wait indefinitely from the outset.
  Removing the wait alone does not fix the stored pause, cursor or consumed-touch record.
- Paused-search scheduling includes UNCERTAIN in its open-occurrence set, not its slot-consuming
  set. PostgreSQL occurrence updates increment logical_touch_count only for SENT; the workflow
  count follows that persisted result. Uncertain does **not** already count as one in this baseline.
- The callback handler can queue BLOCKED_REVIEW_COMPLETED, and a formerly uncertain occurrence
  confirmed SENT can increment the workflow touch count. It does not transition the paused database
  workflow back to a sendable state. These are existing effects to replace, not audit-only behavior.
- The plain reconciliation timeout use case only marks TIMED_OUT, but is invoked by the blocking
  Temporal activity. No independent reporting sweep is established by that helper. The paused-search
  timeout additionally marks the occurrence failed, pauses/signals and can notify for review.
- Manual paused-search resolution currently sets SENT/FAILED/SKIPPED; its repository sets the touch
  count to one/zero, and the use case resumes on SENT or closes otherwise, with a workflow signal.
  Making this action “optional” without changing those effects is insufficient for 17-B.
- Current Send now and rejected-draft approval map non-success uncertainty to failure results;
  their normal completion happens after the sent-only branch. The web Send now success toast assumes
  immediate sending and cadence advancement. Rebase on 17-A's asynchronous contracts, not this toast.
- Provider evidence, request exception views, occurrence health and timing history are distinct
  read paths. The cross-channel history reader currently filters SENT/sent_at; later status changes
  must not erase an already consumed attempt or move its timing anchor.

The direct-path and transport-classification repairs in 17-A are prerequisites, not current behavior
silently attributed to this ticket. Existing guards already block some re-sends after a commit;
neither those guards nor synthetic provider tests prove every crash window safe.

### 3.2 One consumed attempt; delivery truth stays separate

1. A durably classified uncertain attempt has two independent facts: **delivery unresolved** and
   **consumed for the applicable journey**. Keep its original workspace, run/purpose, message,
   occurrence/turn and attempt identity. Record why and when the policy consumed it; do not write
   SENT/DELIVERED merely to make existing sent-only readers advance.
2. Apply the same applicable state/cursor/schedule/count result as the normal sent counterpart,
   once. Do not introduce an uncertainty-only pause, review requirement or extra waiting period.
   When another valid control already blocks or terminates the run, retain the attempt's consumption
   without clearing that control or waking a successor. A permitted later resume must not replay it.
3. Pending/queued, provably unattempted, deferred or policy-rejected work is not uncertain merely
   because it lacks a provider ID. Do not count it on enqueue. Conversely, a stale claim that 17-A
   conservatively classifies UNCERTAIN is consumed even if nobody can prove a provider call occurred;
   the possible missed touch is explicit, not a reason to resend or invent acceptance.
4. Use the existing durable outcome/completion obligations to make consumption and required next
   action recoverable. The database count, original cursor and required execution instruction must
   commit coherently or retain an idempotent recovery obligation. An outbox append is not delivery
   to Temporal. A failed bookkeeping/signal operation must not silently strand a healthy-looking lead.
5. Replays, repeated operator actions, callbacks, stale worker returns and recovery all observe the
   same once-only consumption. No duplicate charge, step skip, new message version/key, re-draft or
   alternate-channel replacement may escape it. Delivery changing to FAILED later does not make the
   original attempt retryable or available for a fresh occurrence.
6. Freeze the scheduling/accounting anchor from the original attempt/outcome under R1. The next
   action follows the configured track and applicable application-level timing limits, not callback
   arrival or reporting expiry. Do not reset its due time on each completion replay. Retain the
   consumed-attempt history needed for spacing even if delivery is later recorded FAILED.

This is **once-only application accounting**, not a guarantee of exactly one delivered copy.
Uncertainty is not a delivered metric, and a callback's delivery time is not the cadence's clock.

### 3.3 Complete each purpose without turning every message into a cadence step

| Purpose | Required uncertainty outcome |
| --- | --- |
| Standard cadence | Consume the original step once and preserve the normal next-step schedule. The eligible workflow takes the same state progression as accepted sending; there is no uncertainty-specific database pause or engine wait. |
| Paused-search single-fire and recurring outreach | Consume the original logical touch and occurrence slot once, with the correct occurrence number, phase, pinned track, caps and next action. It is no longer an open/sendable uncertain occurrence. Delivery evidence can still be uncertain or later corrected; a later FAILED record cannot reopen the slot. |
| AI continuation after a handled inbound | Consume one AI interaction on the original run and complete its response lifecycle as a successful counterpart would. Keep the original inbound/thread/content identity; do not increment a separate cadence step merely because both use the dispatcher. Do not clear other unresolved replies. |
| Deferred Send now | Complete that original message's existing step/occurrence obligations once. Keep the authorized actor/reason and existing timing override only. A repeated action returns the existing truthful outcome rather than sending again. |
| Rejected-draft Approve and send | Preserve approval of the actual content/version and finalize the applicable review/journey without requiring another approval because delivery is unknown. Distinguish approved-and-consumed from confirmed sent; no false APPROVED_SENT semantics or hidden open review that still blocks nurture. |
| Existing lead-facing handoff acknowledgment | Retain uncertainty and no-resend protection for its original purpose. Preserve handoff/human ownership and staff obligations; do not advance a cadence cursor, charge an unrelated turn or resume nurture. |

For paused-search, all consumers must agree on consumption: scheduler open/closed tests, occurrence
caps and retries, phase selection, workflow logical-touch total, review/edit/skip/cancel, timing
updates, track migration and terminalization. Re-labeling one status or changing one counter is not
enough. A consumed occurrence cannot be made unattempted by any of these operations.

At a last step, touch/AI limit or configured track end, match the approved sent-counterpart outcome.
Do not add a new touch, restart step one or auto-enroll. Standard completion/late-reply defects remain
Issue 8/G1; name any dependency needed for the claimed acceptance instead of silently building that
A change here or claiming the existing final-step wait is fixed by 17-B.

**Fallback boundary:** after an uncertain attempt, neither primary nor alternate channel may repeat
that touch. A separately authorized fallback that began before uncertainty remains the same logical
touch; if that alternate attempt is uncertain, consume it once. Definitive primary rejections retain
the integrated 13-B/12-B and signed G3 configured paused-search fallback rules, not a new blanket rule.

### 3.4 Delivery callbacks and reporting expiry are audit-only

Keep authenticated, tenant-correct correlation to the original message/request/reconciliation and
occurrence. Supported ACCEPTED/DELIVERED or failure evidence corrects the delivery view; retain event
deduplication, ordering/precedence and useful timeout history. Do not guess correlation from content,
destination or timing. Missing provider support/IDs may leave uncertainty unresolved indefinitely.

**Delivery reconciliation must not:** pause/resume/close a workflow; change its cursor, next due time,
touch/AI count or enrollment; create a replacement send; queue a workflow-control or advancement
signal; or clear a human/reply/review hold. This applies even if the callback beats consumption
bookkeeping, arrives after a successor enrollment, or later reports a hard delivery failure.

Initial outcome completion and recovery may still publish the instruction needed to progress the
original journey. Those are not later delivery callbacks. Preserve normal accepted-send completion
and legitimate operator/reply/control signals; do not globally delete BLOCKED_REVIEW_COMPLETED.
R1/R2 must make an early callback race safe without relying on that callback to perform progression.

Replace the blocking confirmation timeout with a **required background reporting sweep** over actual
unresolved uncertain attempts. Do not sweep every PENDING reconciliation: one may have been created
at enqueue before any attempt. Define threshold/clock, interval, bounded batches, retry/idempotency,
owner and observable lag under R3. Existing 24-hour waiting is not an implicit approval of a new job's
parameters. The sweep records TIMED_OUT for reporting only; it does not turn unknown into proven
failure, refund a touch, send a review-to-resume instruction or become a prerequisite for the next send.

Later trusted evidence must still correct a timed-out record's effective delivery view while retaining
the timeout trail. “Terminal timeout means ignore all later callbacks” does not satisfy this contract.
Sweep/callback/late-dispatch races must not downgrade stronger evidence or change consumed progress.

An independently valid opt-out, unsubscribe, human-control or inbound event remains subject to its
own safety rule, even if received near a delivery callback. Audit-only delivery handling is not
permission to discard consent evidence. A newly recorded channel restriction affects future eligible
work under its separate contract; it does not manufacture a replacement for the consumed old touch.

### 3.5 Legacy waits, manual resolution and independent controls

No new uncertainty-only workflow wait may be installed. Existing persisted histories may contain
the old 24-hour timer, indefinite wait, timeout activity or already-queued unblock signal. The rollout
must explicitly handle them without nondeterministic replay or a stale instruction clearing a newer
pause. Removing an activity registration without a compatible history/build plan is not sufficient.

Manual uncertainty resolution must no longer be needed for progress. R2 chooses whether the existing
API is retained as a permission-checked audit correction or retired with a safe client response. In
either case, old SENT/FAILED/SKIPPED requests must not resume/close a workflow, refund/recount a touch
or make the original attempt sendable. Retained corrections need actor/reason, original-run attribution
and evidence provenance; an operator assertion must not masquerade as a provider-confirmed fact.

Explicit human pause/resume/close remains separate, authorized and audited. If such a control or STOP,
global DNC, a newer unresolved reply, tag removal under the integrated 14-B policy, or a terminal state
wins a race, uncertainty completion/reconciliation cannot override it. Final checks for the next send
still apply. Do not adopt an unimplemented future policy simply because a target rule document says it.

### 3.6 Truthful API, UI, history and operations

Fresh authorized reads must distinguish:
- queued/not attempted and unfinished completion work;
- consumed step/occurrence or AI turn with delivery uncertain, including reporting timeout;
- uncertain handoff acknowledgment with human ownership unchanged and no cadence/AI charge;
- provider acceptance versus confirmed delivery;
- later delivery failure on an already consumed touch versus a definite send-time failure/real hold.

Show the actual next action or independent hold/terminal reason. For cadence/occurrence messages,
explain “delivery uncertain; counted for cadence.” For AI replies, show that one AI interaction
counted; for a handoff acknowledgment, show uncertain delivery with handoff unchanged and no cadence/AI
charge. Never describe uncertainty as “accepted provisionally,” “delivered,” or “resolve to resume.”
Do not expose retry/approve-again controls that can repeat the consumed attempt. Approval/action
responses, lead timeline, occurrence health and request-exception views must agree; a stale request-status
filter must not turn reconciled evidence into a fresh resendable failure or an alleged nurture hold.

Keep uncertain/failed delivery totals separate from actual sent/delivered metrics while retaining
their contribution to cadence/touch/AI limits. Existing CRM notes/snapshots or other completion outputs
must also remain truthful; do not call the confirmed-send helper blindly if it fabricates send evidence.
No new CRM write or staff-notification policy is introduced just to report uncertainty.

Non-blocking uncertainty must remain inspectable. Report-sweep/completion failures have named owners,
thresholds and supported recovery, distinct from an agent task to resume a lead. Missing expected
execution is a visible operational failure, not proof that the cadence continued. Preserve loading,
empty and error states and current role/ownership/tenant restrictions.

### 3.7 Remaining gates — required before the affected implementation/release

| Gate | Required artifact / boundary | Who closes it |
| --- | --- | --- |
| 17-A / D6/G6 prerequisite | Record accepted A revisions and full in-scope durable intent, purpose/occurrence linkage, claim classification, non-redispatch and completion evidence. Name any unbuilt mechanical dependency and keep it in an A-only PR. A passing standard-cadence test is not all-journey coverage. | Engineering owner + independent reviewer, before B integration/activation claims; scope before estimate |
| R1 — Consumption and scheduling contract | Specify the existing durable authority for once-only consumption, per-purpose effects, original-run ownership, atomic/recoverable next-action obligation and all status/counter readers. Choose the immutable attempt/progression time, including stale-claim recovery and clock-limited legacy records; supply literal timing/cap examples. Preserve applicable spacing without inventing a frequency engine or treating delivery timestamps as cadence clocks. Compare §6 approaches before code. | Engineering/workflow owner + independent reviewer; product owner accepts boundary examples, before affected code |
| R2 — Audit, manual action and public contract | Specify early/late/reordered callback precedence, evidence after TIMED_OUT, no callback progress effects, occurrence correction without reopening/refund, and exact API/review/UI/metric outputs. Retain manual resolution as audit-only or retire it safely; name stale-client behavior and provenance. Identify actual supported 17-A correlation limits, not assumed provider features. | Product + API/UI/integration reviewers, before affected code; tested consumer compatibility before release |
| R3 — Reporting sweep and operational bounds | Name uncertainty-only eligibility, age source/threshold, interval, batching, retry/idempotency, actual runner and supported investigation/recovery surfaces. Supply owner, measurable lag/error thresholds and response. No per-lead workflow wait or cadence dependence; no invented existing worker/feature flag/notification route. | Engineering + operations, design before code; configured values and run evidence before release |
| R4 — Existing runs, rollout and rollback | Inventory uncertainty-only versus mixed/ambiguous holds, consumed/unconsumed outcomes, old timeout/manual effects, old signals and Temporal histories/builds. Name per-cohort compatible conversion/containment, supported dry-run and recovery actions, verified dispatch-stop controls and no-burst/no-resend verification. Preserve other holds and successor runs; no bulk resume by reason substring. | Release/recovery owner + reviewer; compatibility/recovery design before code, bounded cohort authorization before writes |
| D7/G7 — Individual B release approval | Record owner's explicit yes for this policy release, accepted missed-touch/late-delivery trade-off, test-first and integration evidence, prerequisite revisions, operator briefing and monitoring owner. The earlier “looks good” on a draft is not deployment authorization. | Product/release owner, before activation |

These gates settle implementation and operations, not the already-recorded uncertain-as-sent policy.
New material conflicts go to the owner; no reopening the closed multi-reviewer consensus by default.

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Parameterize applicable cases across SMS/email and §3.3's
purposes. Use synthetic contacts and controlled clocks. Compare against a normal sent counterpart
with literal expected cursor/count/due-time values; do not calculate the oracle using the code under
test. Close the relevant §3.7 contract before a test whose expected outcome depends on it.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Execute a permitted non-final standard step and durably record an ambiguous provider outcome; deliver no callback. | Original step consumed once; eligible database workflow and actual Temporal execution proceed to the correct configured next action. Message remains uncertain and claim remains protected. | PAUSED/cadence_step_blocked, a resolution wait, fake SENT evidence or a second call for that step. |
| AC-02 | Observe queued/provably unattempted work; separately recover a stale in-flight claim that 17-A classifies uncertain. | Queue alone consumes nothing. Recovered uncertainty consumes once under R1's timestamp and original identity without redispatch; possible missed touch remains disclosed. | Queue equals sent, every missing ID equals uncertain, or a fresh key used to force the stale attempt through. |
| AC-03 | Record ordinary provider acceptance with no later delivery callback; also queue two distinct legitimate intents. | Existing accepted-send completion still works once without waiting for delivered/opened. Both distinct intents can proceed under normal controls. | Global removal of completion signals, disabling legitimate sends or treating all sent messages as uncertain. |
| AC-04 | Retry original activities/events/actions while the attempt is uncertain and after its delivery later becomes failed; include replanning/version/channel changes. | Original consumed identity is retained across every applicable producer; no extra dispatch, new version/key, replacement content or alternate-channel copy. | Deduplication based only on current UNCERTAIN status or original idempotency key while a new key escapes it. |
| AC-05 | Fail between uncertainty persistence, count/cursor update and required execution instruction; retry and race independent completion workers in real Postgres. | Durable recovery completes the original obligation once, preserves count/due time and reaches the correct execution when available. Other legitimate intents still progress. | Partial commits silently losing progression, double count, skipped step or provider I/O used to repair bookkeeping. |
| AC-06 | After uncertainty is durably established, deliver success/failure evidence before consumption bookkeeping finishes; also race a callback with local outcome commit. | Correct evidence precedence; the independent original completion obligation yields one policy-consistent consumption. Callback itself makes no workflow/count/schedule/signal change. | Lost advancement because the message now reads FAILED/SENT, callback-owned completion, or two progression owners charging twice. |
| AC-07 | Replay duplicate/reordered delivery events and delayed dispatcher results after the next step is scheduled or sent. | Evidence converges under the signed precedence rules; original touch/count/next time remain fixed and no delivery callback queues workflow instructions. | Delivered evidence downgraded, uncertainty re-opened, extra signal/charge, cursor rewind or due-time reset. |
| AC-08 | Later callback proves the originally uncertain message failed/bounced/was undelivered. | Failure is visible for audit; previously consumed slot/AI charge remains consumed and the current journey continues subject to its own safeguards. | Provider-failure hold for that old attempt, refund, reopening FAILED occurrence, fresh draft/version or fallback resend. |
| AC-09 | A subsequent configured step becomes due before provider confirmation, outside/inside applicable allowed hours and spacing. | Normal scheduled progression and final checks govern; no callback wait, immediate extra message, shifted anchor or catch-up burst. | Uncertainty blocks step N+1 indefinitely or “continue” bypasses its independent timing restrictions. |
| AC-10 | No callback arrives before or long after the old 24-hour resolution deadline. | Eligible next steps progress independently; no uncertainty-only hold, timeout failure notification requiring resume, or unbounded workflow wait. Unresolved evidence stays inspectable. | Replacing the 24-hour wait with another blocking confirmation deadline or silently hiding the unknown send. |
| AC-11 | Run the reporting sweep on before/at/after-threshold uncertain records, normal queued PENDING reconciliations and resolved records; run overlapping/repeated batches. | Only eligible unresolved uncertainty expires for reporting, idempotently and in bounded batches, with no workflow/count/timer/signal/provider side effects. | Expiring all queued work, proving failure from missing callback, touching another tenant or cadence progress depending on sweep success. |
| AC-12 | Stop/fail the sweep or a batch commit, then recover through the supported runner. | Reporting lag/error is observable to its owner; safe idempotent catch-up corrects reports without extra contact or blocking normal cadence. | Unowned stale reporting, endless silent retries, a fabricated existing runner or bulk per-lead resume. |
| AC-13 | Deliver supported success/failure evidence after TIMED_OUT; race the sweep, callback and late worker outcome. | Effective delivery view corrects with timeout history retained; progress and original consumption timestamp do not change. | Ignoring all later evidence because timeout is terminal, losing stronger evidence, recounting or restarting the lead. |
| AC-14 | Execute uncertain paused-search single-fire and recurring multi-occurrence sends with no callback; retry scheduling/completion. | Original occurrence slot and one logical touch are consumed; workflow total, phase, occurrence number and next configured action agree. Uncertain evidence remains honest. | UNCERTAIN left as open/sendable work, counter-only fix with stalled planner, two touches or skipped occurrence. |
| AC-15 | Consume the last allowed occurrence/touch/AI turn or last step; compare confirmed-send control under the same pinned configuration. | Same applicable cap/track-end/last-step outcome, no extra message or auto-enrollment. Document Issue 8/G1's separate completion dependency where relevant. | Uncertainty evades a cap, invents a new terminal policy, restarts step one or is advertised as fixing all completion defects. |
| AC-16 | Change paused-search timing, review/approval, skip/cancel, track migration or terminalization while uncertainty/completion is pending. | Original consumption cannot become unattempted; valid controls remain, replacement tracks cannot resend it and later evidence stays with the original occurrence/run. | New occurrence/key used to repeat the touch, count refund, premature phase change or resurrection of a terminal run. |
| AC-17 | An otherwise permitted AI reply produces uncertainty after its inbound was handled; retry the original inbound/completion. | One AI interaction consumed on the original run; correct response lifecycle with no uncertainty pause, correct thread/message identity and no unrelated cadence-cursor advance. | ai_continuation_send_uncertain hold, no budget charge, duplicate AI reply or success/delivery invented to unblock. |
| AC-18 | Follow AC-17 with a genuinely new reply, another unresolved reply and a turn-cap boundary. | New input routes under normal rules, unresolved input still blocks stale outreach and the consumed uncertain turn counts toward the existing cap. | Blanket clearing of reply holds, pretending any new inbound is already handled or refunding the turn after a failed callback. |
| AC-19 | Authorized Send now is queued then uncertain; lose the action response and repeat before/after completion. | Same original message/step/occurrence; once-only completion and truthful queued/uncertain/current-next-action API/UI. Existing override only. | “Sent immediately” on queue/uncertainty, SEND_FAILED implying safe retry, duplicate send or a new safety bypass. |
| AC-20 | Approve a rejected draft whose dispatch becomes uncertain; repeat approval and race later correction/edit/dismiss. | Approved content/version remains authoritative; review no longer blocks solely for uncertainty, consumption once and delivery shown separately under R2. | False APPROVED_SENT, stale open review requiring another send, changed content inheriting approval or double advancement. |
| AC-21 | An existing configured handoff acknowledgment becomes uncertain; replay its inbound and deliver later success/failure. | Acknowledgment is not resent; handoff/human-owned state and staff obligations remain intact without cadence/AI charge for the acknowledgment. | Shared success path resumes nurture, creates unconfigured acknowledgments or uses delivery failure to end/undo handoff. |
| AC-22 | Commit STOP/channel restriction, global DNC, explicit human control, a new unresolved reply, workspace/campaign stop or integrated tag removal during completion or before the next dispatch. | Applicable latest-state protections win. Consumed attempt stays consumed; no forbidden send and no callback/sweep clearing the independent control. Independently valid consent evidence is still processed. | Uncertainty policy as blanket permission, dropped opt-out evidence, same-step replacement triggered by a later channel block or hidden 9-B/12-B/13-B/14-B changes. |
| AC-23 | Return a definitely-unaccepted temporary rejection, exhausted/permanent failure, a pre-send block and unavailable required safety data; contrast true ambiguity. | Integrated bounded retry/hold/defer rules remain with correct reasons. Only actual classified ambiguity gets 17-B consumption/continuation. | Every error relabeled uncertain to avoid holds, ignored known rejection, infinite retries or unavailable safety data treated as unknown consent. |
| AC-24 | Exercise permitted consent/configured fallback before any ambiguous attempt; separately make the primary or its already-authorized alternate uncertain. | Signed separate fallback rules remain; one logical touch across permitted attempts. Once any attempt is uncertain no replacement on either channel follows. | General provider-failure fallback, lost legitimate fallback, two counted touches or uncertainty used to justify another-channel copy. |
| AC-25 | Query/validate next-message spacing and cadence timing after uncertainty, completion replay and later SENT/FAILED/delivered-at correction. | R1's literal time examples hold; already consumed attempt remains in applicable spacing history, next due time is not recomputed from callback time, and delivery metrics remain distinct. | SENT-only filter erases prior attempt, fake sent_at enables timing, late evidence resets the schedule or required spacing is silently removed. |
| AC-26 | Call existing manual uncertainty resolution with SENT/FAILED/SKIPPED from authorized and stale clients, including consumed/old-run records. | Signed audit-only correction or safe retired response; no workflow signal/state change, no count refund/recharge or reopen. Retained human evidence has actor/reason/provenance. | Old resolution endpoint resumes/closes nurture, operator claim shown as provider confirmation or resolution required for progress. |
| AC-27 | Old uncertainty timers, timeout activities and queued unblock instructions execute after cutover and after an independent hold was added. | Versioned/compatible handling makes them harmless for progressed work and preserves the hold. Explicit legitimate resume/review controls still function separately. | Old timeout re-pauses/fails/refunds the occurrence or stale BLOCKED_REVIEW_COMPLETED releases a newer human/reply hold. |
| AC-28 | Resolve/recover old uncertainty after a new enrollment, with a missing old execution, wrong workspace/provider identity or uncorrelatable callback. | Evidence and any recovery stay scoped to the original purpose/run; successor unaffected. Unsupported correlation stays honestly unresolved with a named limitation. | Borrowing latest workflow, guessed correlation, fabricated Temporal/provider ID or cross-tenant changes. |
| AC-29 | Fetch actual APIs and fresh UI for queued, consumed-uncertain, timed-out, later-confirmed, later-failed and independently held records; inspect completion history/CRM output where applicable. | Action/review, timeline, next action, exception and health views agree; uncertainty is not a delivery success or automatic review hold. Existing completion outputs are truthful; no resend action. | Green delivered metric for uncertainty, “resolve to resume” when progressing, fake sent CRM note or unresolved work hidden by a success toast. |
| AC-30 | Use assigned/authorized operator, unrelated agent and other workspace across reads, correction/recovery and direct API calls. | Existing capabilities, ownership, tenant isolation and callback authentication/correlation remain; scoped diagnostics avoid contact bodies/destinations and credentials. | New audit/sweep path bypasses permissions, protected data leakage or UI-only authorization. |
| AC-31 | Dry-run recovery over uncertainty-only holds, generic/mixed pauses, old timeout-created FAILED rows, already-counted work, handoffs and successor runs. | Evidence-backed cohort plan identifies consumed versus owed work and real controls; only approved recoverable rows convert/continue once at an allowed schedule, without replaying the old send. Others remain visibly contained. | Bulk resume from pause_reason alone, assumed zero counts, arbitrary old timestamps, refund/resend of failed-now uncertainty or catch-up burst. |
| AC-32 | Rehearse compatible API/UI, dispatch/inbound worker and Temporal rollout against old histories, in-flight outcomes and mixed versions. | No supported post-activation journey installs the old uncertainty hold or bypasses no-resend/accounting. Existing waiting cohorts follow their reviewed compatible migration/containment plan. | Delete the timer/activity and hope replay works, old callback/manual handler retains progress effects, or all-journey claim while a live bypass remains. |
| AC-33 | Rehearse rollback after uncertain touches were consumed and later steps became due/sent. | Contain affected dispatch with verified controls; retain claims, consumption/counters, schedules, consent and audit. Compatible consumers or safe containment prevent replay and explain limitations to operators. | Reverting code rewinds progress, deletes evidence, bulk resumes, resends uncertain touches or pretends external contact was undone. |
| AC-34 | Completion/signal delivery exhausts retries or the original expected execution is missing after uncertainty. | Durable obligation and visible scoped operational failure with owner/recovery action; once infrastructure recovers, eligible original progress completes once without provider replay. | “No uncertainty holds” hides broken execution, reports outbox enqueue as delivered, or restarts a successor/terminal run. |
| AC-35 | Run protected-state and legitimate-send controls alongside uncertainty: normal channels, separate approved policies, authorized review/resume and fresh distinct messages. | All permitted flows still work and all independent protections remain; no global signal suppression or disabling providers to make non-resend tests green. | Passing by disabling nurture, retaining uncertainty-only holds, broad body-based deduplication or bypassing unrelated policy. |
| AC-36 | Run a synthetic standard, recurring and migrated inbound/operator journey through durable uncertain outcome → consumption → actual next-action execution → late callback/sweep → fresh API/UI reads. | Provider-call ledger, persisted states/counts/times, Temporal behavior and visible history support each specific claim. Next-step call occurs only when allowed; original call is not repeated. | Helper-only green, skipped integration labeled pass, real-customer outreach or a provider-wide exactly-once guarantee. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — agree before implementation:**
- **Journey entry → durable outcome → consumption → next action:** real cadence, recurring, inbound
  and operator use cases/APIs consuming 17-A's intent/dispatch boundary. Observe original identity,
  provider calls, public results, approved persistence evidence, count and concrete next due time.
- **Consumption and reconciliation persistence:** real local/disposable Postgres with independent
  sessions and transactions for duplicate completion, callback/sweep races, rollback and original-run
  isolation. Existing hand-written repository fakes are not proof of SQL locking or atomicity.
- **Temporal execution:** actual workflow scheduling, timer/replay and signal consumption, including
  old uncertainty histories. A unit assertion that a signal was appended does not prove progress.
- **Callback / sweep / manual APIs:** real normalization, correlation, eligibility and permissions
  within the agreed seam; audit changes must leave workflow/count/timing unchanged. Inject synthetic
  provider events; inherit verified 17-A provider limits instead of claiming fake key echo is real.
- **API/UI and operations:** focused real response/presentation/permission mapping and a synthetic
  integrated demonstration of next action, uncertain history and supported recovery.

CRM/LLM/provider/notification transports and clocks may be hand-written fakes. Keep policy, original
identity, state transitions, occurrence scheduling and accounting real inside each approved boundary.
For a kill/rollback continuation test, the recording transport ledger must survive the killed process.
Use the agreed persistence seam for durable evidence rather than private-method assertions.

1. Start with one meaningful failing case on the integrated A baseline: an otherwise eligible
   non-final uncertain send does not pause and schedules the literal next step without a callback.
   Run the unchanged behavior, capture the wrong state/wait/count assertion, then implement the
   smallest complete slice and rerun green. Repeat one scenario at a time, not all code then tests.
2. Add a recurring consumption red and AI-turn red at their actual public seams. Test late FAILED
   reconciliation and no-callback progression before calling the policy complete. Migrated operator
   approval and asynchronous completion need behavioral coverage, not merely an enum or mock return.
3. A missing import/dependency, bad fixture, unavailable Postgres/Temporal, empty collection or skipped
   test is not policy-failure evidence. Minimal interface scaffolding may make a test runnable;
   record it separately. Any mechanical foundation discovered missing goes to the named A dependency.
4. Preserve already-green non-redispatch, normal acceptance and protected-state controls. Where a
   current protection is green, demonstrate sensitivity with an isolated mutation rather than inventing
   a failure or weakening the expectation to match implementation.
5. Critical sensitivity checks: restore the uncertainty wait; leave UNCERTAIN open in the scheduler;
   omit/increment twice/refund consumption; reopen a later FAILED touch; use callback time as the
   anchor; queue callback/manual unblock; expire queued PENDING work; target the latest run; display
   uncertainty as delivered. Restore mutations and rerun affected checks.
6. Independent review validates expected states, time examples and counts against this contract,
   including positive controls. Do not derive expected results from the same mapping under test.

| AC / purpose / race | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Remaining integration limit |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each variant | Exact invocation | Failing business assertion | Revision, exit code and pass/fail/skip counts | Actual protected behavior | Named unverified claim |

## 6. Engineering starting points and design review

Navigation only, repository-qualified and relative to that repository for Jira portability. Retrace
the integrated A branch; these are existing seams, not a prescribed new table, status or framework.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — initial send and durable outcome | app/application/use_cases/send_outbound_message.py; dispatch_outbound_send_requests.py; revalidate_outbound_send_request.py in that directory |
| API — cadence / recurring consumption | app/application/use_cases/campaign_cadence_execution.py; schedule_next_paused_search_action.py; paused_search_operations.py in that directory; app/domain/campaigns/paused_search_timing.py; paused_search_occurrences.py in that directory |
| API — purpose completion | app/application/use_cases/continue_ai_conversation_after_inbound.py; process_inbound_message_event.py; send_deferred_outbound_message_now.py; lead_draft_review.py; complete_outbound_message_crm_sync.py in that directory |
| API — evidence / manual / timeout | app/application/use_cases/process_provider_delivery_callback.py; timeout_uncertain_outbound_send.py; timeout_uncertain_paused_search_occurrence.py; resolve_uncertain_paused_search_occurrence.py in that directory; app/interfaces/api/v1/paused_search_tracks.py |
| API — stored counts / history | app/infrastructure/persistence/postgres/paused_search_occurrence_repository.py; outbound_message_repository.py; outbound_send_reconciliation_repository.py in that directory; app/application/services/pre_send_facts.py |
| API — execution / read surfaces | app/infrastructure/workflows/temporal/lead_nurture.py; activities.py in that directory; app/application/use_cases/outbound_send_exception_read.py; app/interfaces/api/v1/outbound_send_exceptions.py; app/interfaces/api/schemas/leads.py |
| Web — action / evidence / health | src/pages/LeadDetailPage.tsx; src/pages/HomePage.tsx; src/components/StatusBadge.tsx; src/lib/api/outboundSendExceptions.ts; src/lib/helpers/leadPresentation.ts; src/lib/presentation/operations.ts; src/lib/formatting.ts |

**Compare at least two implementation approaches before code:**
1. Extend the accepted 17-A original-intent completion boundary with an explicit cadence-consumption
   result independent of delivery state. Existing durable identity/recovery can guard the once-only
   charge centrally, but the boundary must retain purpose-specific effects rather than treating every
   send as a standard step. Readers still need migration; no blanket SENT alias.
2. Keep consumption in the existing journey use cases, using one shared outcome rule and the existing
   durable records to guard each original-purpose completion. This keeps scheduling and AI logic
   local, but every producer, replay and callback/sweep race must prove the same idempotent contract;
   duplicating uncertain handling in several sent-only branches is a maintenance risk.

Recommend the smallest extension of the actual A design that separates monotonic consumption from
mutable delivery evidence and can prove all readers agree. Compare maintainability, completion latency,
lock/transaction behavior, Temporal compatibility and migration scope. Reuse existing records/outboxes;
do not invent a parallel ledger or generic rules engine. Obtain design approval before implementation.

**Existing test starting points, not claimed coverage:**
- API domain/application: tests/domain/campaigns/test_pre_send.py; test_paused_search_timing.py in
  that directory; tests/application/use_cases/test_campaign_cadence_execution.py;
  test_schedule_next_paused_search_action.py; test_dispatch_outbound_send_requests.py;
  test_revalidate_outbound_send_request.py; test_send_deferred_outbound_message_now.py;
  test_process_inbound_message_event.py; test_process_queued_inbound_message_events.py;
  test_process_provider_delivery_callback.py; test_uncertain_paused_search_occurrence.py;
  test_paused_search_operations.py; test_outbound_send_exception_read.py; test_business_flow_harness.py
  in that directory. Do not assume standalone AI-continuation/report-sweep test files already exist.
- API persistence/execution: tests/infrastructure/persistence/postgres/test_business_flow_harness.py;
  test_paused_search_timing_postgres_e2e.py; test_temporal_paused_search_workflow_postgres_e2e.py in
  that directory; tests/infrastructure/test_temporal_lead_nurture_workflow.py.
- API/UI: tests/interfaces/api/v1/test_leads.py; test_outbound_send_exceptions.py in that directory;
  web src/app/LeadsRoutes.test.tsx; src/lib/api/outboundSendExceptions.test.ts. Add focused tests for
  the agreed audit-only manual API, reporting runner and changed health/status consumers as needed.

Use Python 3.12/uv: exact pytest node, its file, related suites, then make lint, make typecheck and
make test. For affected web behavior: focused Vitest targets, then pnpm test, pnpm typecheck and
pnpm lint. Verify local/disposable SQL/Temporal targets; record actual commands/exit codes/counts.
Skipped integrations remain gaps. This drafting task runs document checks only, not behavioral tests.

## 7. Existing records, cutover and safe recovery

1. **Inventory without mutation:** by workspace/original run/purpose, identify uncertain messages,
   original claims, reconciliation age/status, consumption/count/cursor/due-time evidence, reviews,
   timeout-created failed/skipped occurrences, old timers/signals, independent holds and actual
   engine state. A generic cadence_step_blocked reason alone cannot identify safe recovery.
2. **Classify owed versus already consumed work:** later SENT/FAILED/manual/timeout corrections may
   obscure the original uncertainty. Preserve provenance and counts; never infer missing history from
   current status alone. Some old records are unresolvable; retain them with a named owner rather than
   guessing acceptance, time, touch count or a sendable state.
3. **Approve bounded cohorts:** distinguish live uncertainty-only stalls from mixed/ambiguous pauses,
   handoffs, suppression/global DNC, terminal/superseded runs and work already progressed. For eligible
   rows, repair consumption and the original next action once without dispatching the old attempt.
   Re-evaluate current safety and allowed timing; no historical catch-up burst. Other cohorts remain
   safely contained with an explicit resolution path, not mislabeled healthy.
4. **Name the real operation:** R4 records environment, exact cohort, operator, supported command/API,
   dry-run diff/counts, approval and post-check. If no safe recovery tool exists, scope/review/test it
   before use. This draft authorizes no replay, database repair, CRM write, bulk restart, migration
   execution, provider send or deployment.
5. **Coordinate old and new consumers:** schema/contract expansion if needed, then compatible API/UI,
   callback/manual handlers, dispatch/inbound workers, reporting runner and Temporal builds/histories.
   Rehearse old signals and timeout activities before activation. Preserve audit-only late corrections
   and prevent old code from reintroducing a hold or reopening a consumed touch.
6. **Observe after authorized activation:** bounded synthetic journey evidence plus uncertainty volume,
   reporting lag, duplicate-consumption attempts, overdue completion/instructions and actual next-action
   health. Record owners and actions; do not confuse a high non-blocking uncertainty count with a queue
   of leads requiring resume. Use scoped identifiers/statuses, not broad exports of contact content.

## 8. Release, operator explanation and rollback

**Required operator explanation:**
> When delivery of a cadence message is uncertain, that attempt counts for the cadence and is not resent.
> The next configured touch proceeds when allowed; you do not need to resolve the old message to
> resume nurture. The old touch may never arrive, or may arrive late near the next one. History
> keeps that uncertainty and later provider evidence; it does not claim confirmed delivery.
> An uncertain AI reply consumes one AI interaction, not an extra cadence step. An uncertain handoff
> acknowledgment is not resent and leaves human ownership intact; it neither restarts nurture nor
> consumes a cadence touch or AI interaction.
> Independent consent, reply and human-control restrictions still apply. Use the supported explicit
> pause/stop control if needed, not a resend or delivery-correction action.

**D7/G7:** record the owner's individual yes for this B release, the accepted trade-off, prerequisite
revisions, R1–R4 closure at release, red/green and SQL/Temporal/API/UI evidence, legacy-cohort treatment,
provider limits and the applicable D5 change-management briefing. No blanket approval from 17-A,
the closed consensus or “looks good” on a draft authorizes production activation/data repair.

**Rollback:** stop/contain affected dispatch through verified controls first. New code may already
have consumed uncertain touches and sent later ones; reverting cannot undo contact. Preserve claims,
consumption/count/time/cursor evidence, approvals, consent and delivery history. Keep compatible
consumers or safely contain affected work; never rewind to the uncertain step, refund its slot, restore
direct sending, replay old unblock signals indiscriminately or reset reconciliations to resendable.
Rehearse mixed-version behavior and tell operators what is paused operationally and why.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Business outcomes and ACs accepted as the implementation contract, without reopening the policy.
- [ ] 17-A dependencies and B-only scope named; R1/R2 design and API/consumer contracts recorded.
- [ ] Test seams, first meaningful red, literal timing/count examples and independent review agreed.
- [ ] R3 sweep and R4 compatibility/recovery design are concrete, with no invented existing controls.

### Ready to merge
- [ ] Every included journey consumes uncertainty once with truthful delivery state, protected identity
      and recoverable original-purpose progression; no uncertainty-only wait or callback prerequisite.
- [ ] AC variants map to meaningful red/green or justified existing-control evidence; sensitivity,
      real SQL races/rollback and actual Temporal next-action/replay tests pass with skips disclosed.
- [ ] Delivery callbacks, reporting expiry and retained manual corrections are audit-only, including
      early/late races and evidence after timeout. No refund/reopen/resend or successor-run effect.
- [ ] Caps, timing history, review/approval, metrics, API/UI and existing completion outputs agree;
      no fabricated sent/delivered facts or agent instruction to resolve uncertainty to continue.
- [ ] Normal sends, legitimate signals and independent safeguards remain proven. No separate A repair
      or unrelated B policy is hidden in the PR; any completion/engine dependency is explicitly tracked.
- [ ] Compatible rollout/rollback, old-record cohorts, supported recovery/reporting operations and
      operational owners are reviewed. Current help/docs describe actual activated behavior.

### Production acceptance complete — not merely merged
- [ ] Owner has separately authorized this B activation and any scoped recovery writes; briefing delivered.
- [ ] Compatible workers/APIs/UI/Temporal histories and reporting runner are verified against the approved
      activation boundary; observed synthetic flows support no-resend, correct next action and audit-only evidence.
- [ ] Historical uncertainty-only stalls are recovered as authorized; ambiguous/protected cohorts remain
      safely contained with named follow-up, not silently resumed or forgotten.
- [ ] Reporting/completion health and the policy's missed-touch/late-arrival limitations have accountable
      ownership. No claim that all provider uncertainties resolve or all Issue 17 mechanics were built here.

**Evidence status at drafting:** code/source trace and document review only. No application changes,
new behavioral tests, runtime pass, Jira publication, commit, deployment or production data operation.

## 10. References and decision precedence

- [Issue 17-A — separate durable-dispatch prerequisite](issue-17-a-durable-outbound-dispatch.md)
- [Issue 16-A — opt-out preservation and recovery](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — STOP ordering and unresolved-reply protection](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 11-A — ownership projection](issue-11-a-project-crm-reassignment-immediately.md)
- [Issue 14-B — separate CRM-control policy](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [Issue 13-B — separate consent/fallback policy and G3](issue-13-b-consistent-consent-and-channel-fallback.md)
- [Source Issue 17 and business/readiness appendix, including G1/G6/G7](../production-state-consistency-issues.md)
- [D6 scope and D7 ship-class gate](../production-state-consistency-review-consensus.md)
- [Pre-send target, including uncertain-step and next-step distinction](../../business-rules/04-pre-send-safety-checks.md)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product and design-review rules.

Code describes the baseline; dated owner decisions describe the target; D7 governs release boundaries.
“As sent for cadence” never means “confirmed delivered,” “all failures are uncertain,” or “ignore a
new opt-out.” Escalate a material new conflict to the owner rather than silently choosing a new rule.