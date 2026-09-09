# Issue 17-A — Make every lead send durable before contacting the provider

**Status: DRAFT — business, test-contract and engineering-readiness review required.**
This is the sixth proposed Jira description, not a published issue or permission to implement.
It covers **Class A dispatch mechanics**, subject to D6/G6 sizing. The approved **17-B
uncertain-as-sent cadence policy requires its own implementation and release** and is not included.
Earlier drafts remain unchanged.

## 1. Business impact — read this first

**The promise:** Restarting a worker, retrying an inbound event or repeating an operator action must
not send a lead another copy merely because the first provider result was not saved. Save the send
intent first, remember what may already have happened, and finish the right journey without replaying
the message. Users must see whether it is queued, accepted for sending, uncertain or failed.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | Standard cadence has a durable dispatch path, but paused-search sends, inbound AI replies, operator send-now and rejected-draft approval bypass it. Existing lead-facing handoff acknowledgments also send directly. Provider acceptance followed by a crash or later transaction failure can leave nothing durable preventing another call. |
| What changes? | Every in-scope lead message uses committed intent and a durable claim before provider I/O. Retrying the original event/action reuses its send identity and outcome instead of creating another attempt that may duplicate an accepted message. |
| Does this guarantee exactly one delivered copy? | No. The enforceable promise is application-side protection against the specified duplicate-dispatch windows, with evidence for each journey. The platform and provider do not share one transaction; provider/SDK retry and deduplication behavior must be verified, not inferred from an internal key. |
| What if the outcome is unknown? | Preserve it as UNCERTAIN, retain the claim and reconcile supported provider evidence. Do not turn ambiguity into an ordinary retryable failure, send a replacement on another channel or call it confirmed delivery. |
| Could a touch be missed? | Yes. A lost worker may leave no proof whether it contacted the provider. Conservatively retaining that claim can prevent a send that never happened. Expose that uncertainty; a missing provider ID is not proof that retrying is safe. |
| Will this stop uncertain sends from pausing nurture? | **Not in 17-A.** Removing uncertainty holds, counting uncertain as sent for cadence progress, and making later callbacks audit-only are 17-B. The known uncertain-send lifecycle defects are not claimed solved by this durability migration alone. |
| What will Send now / Approve and send mean? | The authorized action durably requests dispatch. A successful queue acknowledgment is shown as queued, not “sent immediately” or “cadence advanced.” Final safety checks may still defer or reject it; worker availability affects latency. |
| Must an ordinary send wait for a delivery receipt? | No. A recorded provider acceptance remains the existing successful-send milestone. Durable completion must advance the applicable journey once without requiring a later delivered/opened callback. Acceptance is not proof of recipient delivery. |
| Can the queue bypass a pause, STOP or newer reply? | No. Revalidate current safety facts for the actual message purpose before dispatch. Existing operator/acknowledgment exceptions stay narrowly scoped; a queue entry is not standing permission to send. |
| What about paused-search timing and AI limits? | Keep the original occurrence, schedule, phase/cap and AI-turn identity. Queueing is not completion. Successful completion/accounting runs once even if signals or completion work retry. |
| Does this change channels, CRM controls or staff notifications? | No new policy. Consume separately integrated consent/fallback and CRM-control rules. Staff notifications, invitations, authentication emails and CRM notes are not lead outreach routed through this dispatcher. |
| Can old failed/pending messages simply be replayed? | No. Some old records may describe messages already accepted externally. Inventory and approve recovery separately; never use a fresh key/version to erase uncertainty or bulk resend historical work. |

**Unchanged:** normal content/approval rules, permissions, human handoff, unresolved-reply protection,
consent, applicable timing/frequency limits, track configuration and completion/re-entry policy.
This is not permission to send extra messages or disable legitimate sends to make duplicate tests pass.

## 2. Ticket identity, scope and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — prevent application retry duplicates; confirm at publication |
| Source / delivery class | Production-state consistency Issue 17 / **Class A: durable-dispatch mechanics only** |
| Repositories / components | miller-schackman-api: send producers, request/claim/revalidation, occurrence and AI/operator completion, callbacks, workers and reads; miller-schackman-web: operator outcomes and message/next-action presentation |
| Sequence | Sixth draft after 16-A, 9-A, 11-A, 14-B and 13-B. Draft order does not mean any implementation has shipped. |
| Safety integration | Preserve separately reviewed 16-A opt-out preservation/recovery and 9-A STOP/receipt/reply-hold protections. Keep 11-A ownership projection and the actual release's consent/CRM controls intact. Name integrated revisions rather than assuming these drafts are deployed. |
| Policy boundaries | 13-B owns consistent consent/fallback; 12-B owns carrier-opt-out recognition; 14-B owns tag-only CRM control; 17-B owns uncertain-as-sent/callback policy. The unresolved configured paused-search provider-fallback interaction remains G3, not an engineering guess. |
| Owners | Name implementer, independent reviewer, product/release owner and recovery operator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; retrace the actual implementation branch |
| Readiness | D6/G6 sizing plus R1–R4 in §3.7 must be closed at their stated stages. This draft supplies a contract, not an estimate, approved design or passing test evidence. |

**Included:** durable intent and claim across all lead-send producers; purpose-correct final checks;
crash/rollback/retry handling; non-redispatch of ambiguous attempts; recoverable completion and
reconciliation; paused-search occurrence linkage; truthful API/UI outcomes; tests and safe cutover.

**Excluded:** activating 17-B, new consent/channel/provider-failure rules, Issue 9-B's 30-minute
window, new opt-out lift routes, changes to staff-notification delivery policy, a replacement queue
platform or provider cache, generic messaging-framework work, bulk historical repair, and Issue 8/G1
completion/late-reply changes. Needed neighboring repairs must be named, scoped and reviewed separately.

**D7:** no PR may mix A and B. Do not add “uncertain means sent” while replacing direct sends, and
do not remove all callback workflow effects as a convenient dispatch refactor. If this is too large
for one implementation ticket, split into named **A-only, complete-journey slices** after D6 sizing;
the parent cannot be accepted as “every journey” while a production bypass remains.

## 3. Current behavior and contract to approve

### 3.1 Verified starting point — useful infrastructure, not a blanket safety proof

- send_outbound_message can enqueue an OutboundSendRequest and reconciliation, but the helper
  falls back to direct I/O when either repository or workflow/Temporal identifier is absent.
  Existing message status/key checks help after a successful commit; they do not close the lost-commit
  window. A pre-provider commit alone is not the durable claim/outcome lifecycle.
- The dispatcher commits DISPATCHING claims, refreshes CRM facts, revalidates under row locks,
  releases locks before external I/O and records the outcome. Stale claims are recovered as
  UNCERTAIN without redispatch. These mechanisms need real crash/concurrency evidence when extended.
- Revalidation currently resolves a pinned campaign and matches its cadence step/channel. Merely
  passing repositories into AI replies, paused-search, approvals or acknowledgments will not give
  them correct validation, lifecycle completion or operational recovery.
- Paused-search explicitly withholds request/reconciliation/provider-failure repositories and
  workflow identifiers on primary and configured fallback sends. Recurring occurrences already
  exist; do not invent a second occurrence ledger. The current DISPATCH_PENDING return precedes
  inline occurrence-outcome recording, which is an explicit integration hazard.
- AI continuation sends during inbound processing, then performs workflow/AI-budget and optional
  CRM completion work. The queued inbound processor commits after its processor returns. External
  acceptance cannot be undone by a later database rollback. Handoff acknowledgments also use this
  direct lead-send boundary; they are distinct from notifying the assigned agent.
- Standard Temporal execution already waits on a completion/reschedule instruction for
  dispatch_pending. Dispatcher acceptance can produce that instruction without a delivery callback.
  The current uncertain branch has different waits/timeout handling; its policy replacement is 17-B.
- Twilio's inspected create call does not transmit the application's idempotency key. SendGrid's
  Message-ID/thread headers are not verified send deduplication. Neither adapter inspection nor a
  fake provider proves provider-wide exactly-once delivery or callback correlation after a lost ID.
- The direct helper can label a raw transport exception UNCERTAIN internally but persist ordinary
  failure through reconcile_as_uncertain=False. The durable dispatcher instead records ambiguous
  provider exceptions as uncertain. Preserve that distinction from proven pre-I/O failure.
- Operator responses and UI assume synchronous sending; Send now's toast says the cadence advanced.
  Existing signal_queued refers to Temporal outbox work, not an outbound queue acknowledgment.
  Existing pending/status-detail and delivery fields should be reused where sufficient.

### 3.2 One durable intent, one authorized dispatch history

The following is the required end state, not a claim that today's direct-send producers already
satisfy it.

1. Bind each send to its workspace/lead, original run or purpose, source event/action, logical step /
   occurrence/AI turn/acknowledgment, message version and selected channel/payload. Persist the intent
   and required source-to-intent linkage before any provider call. No dispatch may depend on a
   producer transaction that can later roll back its only duplicate-prevention evidence.
2. Make the local producer outcome atomic: required message/intent/linkage and event-processing or
   operator-approval progress either commit consistently or remain retryable without external I/O.
   Processing an inbound event or accepting an approval can complete before message delivery, but
   only once its required send/completion obligations are durably represented. Do not hold the
   originating HTTP request or inbound unit of work open across lead-provider I/O.
3. Repeated API requests, lost HTTP responses, inbound retries and activity replay find the same
   persisted intent/outcome. A pending request is not a new message; a sent/uncertain request does
   not become pending through retry, re-drafting, version bump or alternate-channel selection.
   Reuse the existing identities; no new client idempotency mechanism without a demonstrated gap.
4. Claim due work durably and exclusively before dispatch. Persist claim ownership/state so two
   workers cannot legitimately dispatch the same attempt. Release long-lived locks before external
   calls; current-state locks are not a transaction shared with the provider. Prove competing claims,
   slow workers, stale recovery and conditional outcome updates in independent database sessions.
5. Distinguish **provably not attempted**, **definitely rejected**, **accepted**, and **possibly
   accepted**. Only outcomes proven safe to retry use the existing bounded retry/backoff rules.
   A timeout, dropped connection, ambiguous provider response or missing acceptance ID is not proof
   of rejection. A stale in-flight claim remains uncertain unless trusted evidence resolves it.
6. Once an attempt may have been accepted, retries of the original work must not call the provider
   again. Retry outcome persistence, reconciliation and remaining completion work instead. Preserve
   this protection when completion/CRM/notification persistence fails after acceptance; do not
   extend it into an unverified exactly-once guarantee for those other external systems.
7. Prevent stale saves from overwriting a newer reconciled outcome, reopening a claim or replacing
   delivered/failed delivery evidence with a late generic acceptance. Outcome/required outbox writes
   must be atomic or have a durable, idempotent recovery obligation. A returned provider result is
   not sufficient if its record and completion obligation can both disappear.
8. A missing production dependency or unsupported message purpose must leave a visible non-sendable
   outcome, never select the old direct path. Keep test/sink composition explicit. Non-lead emails
   are separately inventoried exclusions, not a reason to claim all provider calls must disappear.

### 3.3 Revalidate the real purpose; preserve its complete journey

Every queued send must refresh/reload and validate current applicable consent, destination,
configuration, workspace/run controls, message/version/content, human/reply restrictions, timing and
frequency before provider release. Use the integrated policy version; do not import the standard
checker's path-specific consent behavior as a new rule for formerly direct journeys. Required data
unavailability is not permission. A control committed before final validation must take effect;
document the remaining race after external release rather than promising recall.

| Journey / original identity | Required durable completion and preserved behavior |
| --- | --- |
| Standard cadence / run + step + message | Remains the reference path. Queueing does not advance the step. Recorded acceptance and retried completion advance once under the existing lifecycle, without waiting for a delivery receipt. Preserve pinned configuration, scheduling and caps. |
| Paused-search step / track + step, and recurring occurrence where applicable | Link the existing occurrence, request, message, reconciliation and original workflow/execution identity. Preserve due time, occurrence number, phase, logical-touch cap and cursor. Record in-flight state without leaving a sendable PLANNED occurrence or advancing it as sent. D6/G6 covers both primary and permitted fallback. |
| AI continuation / handled inbound + original run/turn | Persist the reply intent independently of later inbound-worker retries. Retain reply subject/thread context and approved content. Bind the authorization to the inbound being handled; another unresolved/newer reply still blocks stale content. Successful completion updates the correct run's AI count and lifecycle once, not at queue acknowledgment. |
| Deferred Send now / original message + authorized action | Persist actor/reason and only the currently supported timing override. Final checks remain decisive. Keep the existing step/occurrence identity and explicit queued result; refresh the UI and finish the journey once on actual completion. |
| Rejected-draft Approve and send / review + approved message/version | Persist approval separately from sent completion. A queued approval is not APPROVED_SENT. Prevent repeated approval, edit/dismiss or worker races from dispatching unapproved or duplicate content. Retain the actual review's permitted state transition and completion signal. |
| Configured lead handoff acknowledgment / handoff + inbound + intended channel | Persist the existing acknowledgment identity/content and validate its purpose-specific settings/exceptions. Do not require an invented cadence step or move HUMAN_HANDOFF to active nurture to satisfy the checker. Preserve human ownership and staff-notification obligations regardless of acknowledgment outcome. Deliberately enabled messages on two channels remain distinct, not accidental duplicates or newly enabled fallback. |

No Temporal identifier may be fabricated and no unrelated/latest run may be borrowed to satisfy a
request schema. R1 must cover valid purposes without a live cadence execution: either a supported
durable completion path or an honest non-sendable/recovery outcome, without disabling a currently
supported journey. Missing expected engine state is not silently treated as a valid no-engine purpose.

**Paused-search control races:** carry occurrence ownership through review/edit/approval, timing
updates, skip/cancel, terminalization and track migration. Unattempted superseded work must not send;
already released/ambiguous work must not be recreated under a new occurrence/key. Preserve existing
schedule and cap semantics; no catch-up burst, extra occurrence or cap consumption on queueing.

**Fallback:** consume the separately approved 13-B contract and signed G3 behavior actually integrated.
Asynchronous primary failure cannot silently drop an authorized configured fallback that used to run
inline. Conversely, migration cannot enable general provider-failure fallback. Track the same logical
touch and its attempts so completion is counted once. Never switch channels to retry an ambiguous
primary. Changes to the policy itself belong in the applicable B release, not this A PR.

### 3.4 Completion and callbacks are different events

Persist and retry the completion obligation appropriate to the original purpose: cadence advance,
occurrence update, AI-turn accounting, review finalization, CRM completion and required execution
instruction. Reuse existing completion/outbox patterns; no provider call belongs in “finish bookkeeping.”
Duplicate completion signals or worker crashes must not increment twice, skip a step or lose the next
authorized action. Delivery to an outbox and delivery to Temporal are different milestones.

A normal recorded provider acceptance is enough to enter the existing successful-send completion
path. Later delivered/failed callbacks improve delivery evidence; do not hold all ordinary sends
until a callback arrives. If completion cannot reach its original execution, expose/retry or safely
contain it through the agreed recovery path; never target a successor run to make the work disappear.

For ambiguous attempts, create/retain reconciliation and correlate supported callbacks to the
original workspace, provider, message/request and occurrence. Cover a callback arriving before the
dispatch result commits, duplicate/reordered callbacks and late worker writes. A payload containing
an internal key in a fake test does not establish that the real webhook supplies that key. R2 must
verify actual adapter/webhook capabilities, authentication and tenant attribution.

If correlation is impossible after a lost acceptance ID, do not match by body, destination or timing,
invent success, or resend. Retain honest unresolved evidence and an actionable recovery limitation.
Any capture/reprocessing needed for initially unmatched callbacks must be explicit and tested; do
not silently discard evidence and promise eventual recovery. No retention duration is invented here.

**17-B boundary:** A records uncertainty and prevents redispatch; it does not count uncertainty as
successful cadence progress, remove uncertainty waits/timeouts, or make every callback audit-only.
Document the exact A-release uncertainty lifecycle under R3. Existing allowed reconciliation effects
must be safe for the original run and independent holds, but this is not authorization to implement
the B policy. The known permanently-dark uncertain-lead problem remains a named follow-up, not a
reason to label A complete for all of Issue 17. B is already decided; it needs its own implementation
and owner release sign-off, not another policy vote.

### 3.5 Provider boundary — verify capabilities, do not invent guarantees

- Record each actual provider/SDK's retry behavior, acceptance/error classification, supported
  correlation mechanism and any documented deduplication scope/window. Inspect the adapter's real
  serialized request and webhook normalization using synthetic data, not just the message object.
- Use native deduplication only where the actual endpoint supports it and tests substantiate the
  contract. An arbitrary Idempotency-Key header, SendGrid Message-ID or local cache does not make a
  non-idempotent provider exactly-once. The existing durable request is the application authority.
- Verify hidden transport/SDK retries cannot replay possibly accepted sends outside the dispatch
  lifecycle. Classify raw transport exceptions consistently as uncertain where acceptance is unknown;
  preserve definite pre-I/O/configuration errors and known rejections as distinct outcomes.
- Unsupported native deduplication/correlation is a documented limit, not automatic failure of A
  or permission to retry. Release requires demonstrated non-redispatch and approved unresolved-outcome
  handling, not a promise that every uncertainty will resolve. Vendor sandbox sends require separate
  authorization; no real-lead outreach to prove this ticket.

### 3.6 User-visible status and operations

Return a distinct dispatch_pending/queued result only after durable acceptance of the intent. Retain
message/request identity so a repeated action can report the existing pending, sent or uncertain
outcome. Agree exact API types and consumers under R3; do not reinterpret sent or signal_queued to
mean queued. HTTP success alone must not trigger a “sent immediately / cadence advanced” toast.

Fresh authorized reads must distinguish queued/not attempted, retry/deferred, accepted for sending,
uncertain and failed/rejected, including the relevant reason and permitted next action. Reuse current
status-detail, provider status and timeline fields where sufficient. An operator must not be offered
an unsafe retry for a claimed uncertain message. Approval can be accepted while dispatch is pending;
the review and send status must both be truthful. Preserve loading, empty and error states.

Expose queue age, stale/uncertain claims, failed completion/signals and blocked requests through
verified existing operational surfaces, with a named recovery owner. A worker outage is queued work,
not silent success or an excuse to fall back to inline sending. R4 defines thresholds and actual
actions; this is not a broad new dashboard/notification project or an unspecified “will retry” claim.

### 3.7 Remaining gates — required before the affected implementation/release

| Gate | Required artifact / boundary | Who closes it |
| --- | --- | --- |
| D6/G6 — Scope and sizing | Inventory every production lead-send producer and its normal/retry/operator/fallback variants. Size occurrence linkage, purpose-correct validation, completion, API/UI, callback/claim races and migration tests. If split, name A-only complete-journey slices, dependencies and the final all-journey acceptance gate; no estimate based on passing a repository argument. | Engineering owner + independent reviewer, before assignment/estimate and implementation design approval |
| R1 — Identity, validation and completion design | Specify original-purpose/run/source linkage, authorized payload/version, real no-Temporal purposes, claim/outcome transition ownership, once-only completion/accounting and inbound/approval commit boundaries. Compare the two approaches in §6 and choose the smallest complete extension of existing seams. Cover paused-search review/control and AI/handoff exceptions without weakening ordinary safety. | Engineering owner + reviewer; product owner confirms operator/purpose outcomes, before code |
| R2 — Provider evidence and reconciliation limits | Document actual Twilio/SendGrid endpoint/SDK retries and dedup/correlation capabilities, authenticated callback mapping when acceptance ID is lost, early/unmatched callback handling and late-result precedence. Name unresolvable cases and safe non-resend recovery. No assumed header support, cache-based exactly-once claim or synthetic callback advertised as vendor proof. | Integration owner + reviewer; capability/design evidence before relying on it, operational limits accepted before release |
| R3 — A-only lifecycle and public contract | Record per-purpose queued, accepted, rejected, failed and uncertain API/review/workflow outcomes and consumers. Keep normal acceptance independent of delivery callbacks; preserve the A/17-B boundary with explicit regression expectations and a named 17-B follow-up. Record integrated 13-B/14-B revisions and G3's signed configured-fallback outcome for affected tracks. Do not use this gate to reopen D1 or the decided 17-B policy. | Product owner + API/UI/workflow reviewers, before affected implementation; separate B owners close any B dependencies |
| R4 — Cutover, observability and recovery | Name compatible API/worker/Temporal rollout, bounded queue-age/claim/completion alerts, operator-visible states, real retry/containment actions, legacy cohorts, supported dry-run/recovery commands and rollback. Prove current controls stop actual dispatch and that recovery cannot recreate a sent/uncertain intent. No invented feature flag or unbuilt recovery route. | Release owner + operations + reviewer; recovery design before code, cohort/activation authorization before release |

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Parameterize applicable cases across SMS/email and the
journeys in §3.3. Use synthetic contacts, controlled clocks and a recording transport whose acceptance
ledger survives a killed application process. Queue-only/unit-fake evidence is not crash or SQL proof.
Close the applicable §3.7 contract before implementing a case whose expected outcome depends on it.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Request an otherwise permitted message through every §3.3 producer, including paused-search primary/fallback and handoff acknowledgment. Inspect state from an independent connection before running dispatch. | Committed intent/message/source linkage precedes provider I/O; producer makes zero lead-provider calls. Dispatch later performs the actual send and correct purpose completion. | A direct bypass, optional-dependency fallthrough, uncommitted queue acknowledgment or a helper-only proof. |
| AC-02 | Fail producer persistence before/between required message, request, occurrence/source and processed/approval writes. Retry the original action. | Atomic durable producer outcome; no provider call from rolled-back work. Retry reconstructs the same authorized intent without a processed marker hiding missing obligations. | Partially accepted review/event, orphan sendable work, or an external send assumed undone by rollback. |
| AC-03 | Commit enqueue, then lose the HTTP/activity response or retry the inbound event; repeat while pending, sent and uncertain. | Same original intent and real status; no extra provider call or new version/key merely because the response was lost. | Duplicate send, duplicate approval or re-drafting that escapes the existing claim. |
| AC-04 | Race independent producers/dispatch workers for one logical intent in real Postgres; also submit distinct authorized intents. | One winning dispatch attempt for the shared intent; independent legitimate messages proceed. Verify database claim/uniqueness behavior, not only fake call sequencing. | Concurrent sends for one intent or global deduplication that suppresses unrelated valid messages. |
| AC-05 | Kill after committed claim but before provider I/O; recover after the approved stale threshold. Compare a provably unattempted pending request. | Conservative uncertain/non-redispatch handling when the system cannot prove non-attempt; documented possible missed touch. The independently proven safe pending control can still dispatch. | Reopening every stale claim, claiming no message can be missed, or marking the unknown attempt delivered. |
| AC-06 | Recording provider accepts, then kill the application before outcome commit on paused-search, AI continuation and both operator actions; cover the other migrated producer too. Restart/retry. | Acceptance ledger still records one call for the intent. Durable claim survives; recovery records uncertainty or trusted reconciled outcome without a second dispatch. | A second provider call, in-memory-only “crash” proof or guaranteed provider delivery inferred from the test. |
| AC-07 | After acceptance, fail outcome/completion persistence, a later repository operation or CRM/notification-related completion bookkeeping; retry through the real worker/action boundary. | Send identity remains protected; only missing persistence/completion obligations retry. Where acceptance is durably recorded or resolved by verified evidence, successful-send accounting completes once. If that evidence was lost and cannot be resolved, retain uncertainty under AC-06/AC-12/AC-27 and expose unfinished work. | Re-running lead-provider dispatch to repair bookkeeping, losing the obligation, using the test transport's private ledger alone to count unresolved uncertainty as sent, or claiming exactly-once CRM/staff-notification side effects. |
| AC-08 | Simulate raw Twilio timeout/connection loss, an ambiguous HTTP response, SendGrid ambiguity and an empty acceptance ID. Retry the original action. | Consistent UNCERTAIN plus reconciliation/evidence, no blind redispatch or channel switch, no confirmed-delivery claim. Adapter serialization/exception tests cover the actual boundary. | Internal uncertain kind saved as ordinary retryable failure, automatic retry from an SDK, or 17-B cadence advancement added here. |
| AC-09 | Return a documented definitely-unaccepted temporary rejection, then acceptance; separately exhaust retries and return a definite permanent rejection. | Existing bounded retry/backoff and final safety checks apply; one successful logical completion or visible accurate failure. Preserve integrated provider-fallback policy, not new error-to-email behavior. | Treating every exception as safely retryable, retrying forever, suppressing all legitimate retries or writing an arbitrary error as opt-out. |
| AC-10 | Keep a worker/provider call slow while another worker recovers its stale claim; release the old worker's success/failure later. | No second dispatch. Conditional outcome handling retains coherent evidence and cannot reopen the claim or overwrite a stronger already-reconciled result. | A stale worker returning a request to pending, duplicate provider calls or callback evidence replaced by stale data. |
| AC-11 | Deliver authenticated supported callbacks before outcome commit, concurrently, duplicated and out of order; race them with late acceptance persistence. | Original message/request/reconciliation/occurrence converge under the approved precedence rules; no double count or lost completion. Delivered evidence is not downgraded to generic accepted. | Callback-before-save loss hidden as success, duplicate signals changing progress twice or stale upserts reopening work. |
| AC-12 | Lose the provider ID after possible acceptance. Exercise real supported correlation, missing/unsupported correlation and a callback for another tenant/message. | Only verified exact correlation can resolve. Unmatched/unresolvable evidence follows R2's visible capture/recovery limit without resend or guessed association. | Matching by content/address/time, fake-only key echo claimed as real provider support, cross-tenant correction or fabricated resolution. |
| AC-13 | After queueing, commit opt-out/global DNC, a manual/handoff/review block, a newer unresolved reply, campaign/workspace stop or the integrated CRM-control change before final validation. | Applicable latest-state restriction prevents the provider call with an accurate persisted outcome. Existing authorized purpose exceptions are narrow; they cannot release ordinary nurture. | Enqueue-time eligibility treated as permanent permission, a STOP bypass or implementing/removing a separate B policy. |
| AC-14 | Validate genuine AI, recurring, approval and acknowledgment purposes; then malformed/missing purpose/run linkage, wrong step/channel and missing expected execution. | Valid journeys remain usable through purpose-correct checks; malformed work is visibly non-sendable. Original run/purpose governs completion and recovery. | Fake cadence/Temporal IDs, borrowing a successor run, deleting mismatch checks or blocking every non-cadence message. |
| AC-15 | Required CRM/history/configuration refresh fails, dependencies are omitted or provider configuration no longer matches the queued payload. | Accurate bounded retry/non-sendable outcome under existing rules; no direct fallback. Unknown consent alone is not conflated with unavailable safety data under the integrated consent contract. | Optional-wiring fail-open, stale payload dispatch or a new consent/A2P policy hidden in queue migration. |
| AC-16 | Edit/cancel/reapprove or replace a message while queued/claimed; repeat the source after its content was already accepted/uncertain. | Immutable dispatched content/version evidence; safe invalidation of proven unattempted work. Only a separately authorized valid replacement can proceed, without escaping an ambiguous original claim. | Silently changing an accepted message body, unapproved copy, both versions sent or version bump used as retry. |
| AC-17 | Execute ordinary cadence with no provider delivery callback. Delay and duplicate dispatch-completion instructions. | Queued is not advanced; recorded acceptance completes/advances once through real execution and retains the normal next schedule. Delivery status can remain pending. | Waiting for delivered/opened before every next step, advancing on queue acknowledgment or double advancement. |
| AC-18 | Run paused-search single-fire and recurring multi-occurrence/phase tracks through queue, acceptance and completion. Delay completion and replay the activity. | Correct original occurrence/cursor, preserved due time/number/caps, one successful logical touch and the next configured action. In-flight work is not another sendable PLANNED occurrence. | Repository-only migration, orphan occurrence, extra slot, skipped phase, queue-based cap consumption or catch-up burst. |
| AC-19 | Race pending paused-search sends with review resolution, timing update, skip/cancel, track migration and terminalization. | Existing control/approval semantics remain; unattempted obsolete work cannot send. Late outcomes stay with their original occurrence/run and cannot resurrect it or act on a successor. | Cancellation that creates a replacement duplicate, stale signal resume or borrowed latest-workflow linkage. |
| AC-20 | Exercise integrated consent fallback and signed G3 configured provider-fallback behavior with asynchronous primary outcomes; include an uncertain primary. | Any authorized alternate remains the same logical touch with durable per-attempt lineage and once-only completion. Uncertain primary never triggers another-channel copy. | Dropping an existing allowed fallback because the producer returned pending, general new provider fallback or counting both channel attempts as two steps. |
| AC-21 | Process an ordinary inbound reply into a valid AI continuation, then queue/complete it; duplicate processing and introduce a newer unresolved reply. | Correct original reply/thread/content, one AI-turn charge at the applicable successful completion milestone and correct workflow state. New unresolved input still protects against stale sending. | Count at enqueue, lost reply budget, duplicate reply or marking all inbound holds resolved to satisfy the dispatcher. |
| AC-22 | Fail inbound processing after its send obligation is created or after dispatch accepted it; restart the inbound worker. | Source processing and durable obligations recover coherently; replay does not send/rewrite the original response. Required STOP/reply evidence and other unresolved holds remain effective. | A processed event concealing a lost reply obligation, another AI message on each retry or migration weakening 9-A. |
| AC-23 | Authorized Send now queues successfully; lose its response, click again and allow final validation to accept, defer or reject. Repeat with an unauthorized actor. | Stable original message/action, truthful queued/existing/final responses and UI; applicable existing override only. Actual completion advances the right journey once; unauthorized call produces no send. | Static “sent immediately” on enqueue, repeat dispatch, newly bypassed timing/consent or disabling Send now. |
| AC-24 | Approve a rejected draft and delay dispatch; duplicate approval and race edit/dismiss/failure/completion. | Approval and delivery states stay distinct; no APPROVED_SENT before actual acceptance. Dispatch only the approved version and finalize review/required instruction once with truthful failure/recovery UX. | Queue success marked sent, altered copy inheriting old approval, lost review or repeated approval causing another call. |
| AC-25 | Trigger configured handoff acknowledgments with one or both intended channels; replay inbound work and return uncertain/failure. | Each originally enabled acknowledgment identity uses durable dispatch without duplicate; acknowledgment outcome does not undo handoff or suppress staff accountability. No unconfigured message is added. | Treating staff notification as lead cadence, moving HUMAN_HANDOFF to active nurture, periodic resend of unconfirmed acknowledgments or collapsing intentional two-channel messages. |
| AC-26 | Commit accepted-send completion/outbox work, then fail signal dispatch or completion processing; retry/duplicate it, including a missing old execution and a successor run. | Required work is retained and retried/contained visibly. Normal completion eventually reaches the correct live execution once when available; original provider message is never re-sent and successor is untouched. | Outbox append called engine delivery, missing next action hidden as healthy, double count or broad callback-policy removal. |
| AC-27 | Exercise uncertain dispatch, stale recovery, later success/failure callback and no-callback timeout under the documented A-release contract. | Honest uncertainty and no redispatch; exact R3 workflow/count/signal expectations verified. Any known remaining uncertainty stall is disclosed and tracked to 17-B/explicit dependencies, not reported fixed by A. | Advancing/counting solely on uncertainty, deleting the hold/timer or all callback workflow effects in the A PR, or presenting the approved B target as current behavior. |
| AC-28 | Fetch actual APIs and refresh UI for queued, retry/deferred, accepted, delivered, uncertain, rejected and failed sends, including approved-but-not-sent. | Timeline, action responses, review state and next-action view agree; reasons/permitted recovery are useful. signal_queued is not send confirmation; loading/empty/error states remain sound. | Uncertain shown as delivered, queue shown as sent, unsafe resend button or invented success from HTTP 2xx. |
| AC-29 | Use assigned/authorized operators, unrelated agents and another workspace across send, approval, read, callback and recovery boundaries. | Existing role/ownership/tenant isolation remains; original workspace/provider attribution governs every record. Diagnostics use scoped IDs/statuses without exposing message bodies/destinations or credentials. | Cross-tenant dispatch/correlation, privilege escalation or leakage through new queue/status reads. |
| AC-30 | Stop the dispatch worker, delay finalization and exhaust completion/signal retries; restart the compatible worker or use the approved recovery action. | Queued/unfinished work and age/reason are visible to the right owner under R4; safe pending work resumes and uncertain work is not replayed. No unsupported latency/delivery guarantee. | Silent queued forever, direct-send fallback on worker outage, unsafe operator retry or undocumented “will retry” success. |
| AC-31 | Dry-run cutover with old direct pending/failed/uncertain/sent records, claimed requests, recurring occurrences, inbound retries, open reviews and old signals; include mixed worker versions. | Bounded inventory/treatment and compatible rollout prevent old producers bypassing durability. Unknown prior acceptance remains contained until separately authorized evidence-based recovery. | Blind backfill to PENDING, historical re-send, ignored old workers or marking A all-journey complete while a live bypass remains. |
| AC-32 | Rehearse rollback after new requests/claims exist, using R4's actual containment and compatible executors. | Stop/contain affected dispatch first; keep claims, opt-outs, approvals, occurrences and audit evidence. No old inline route can redispatch new or ambiguous work. | Simply reverting code as a safe rollback, deleting the ledger, resetting all claims or bulk resuming leads. |
| AC-33 | Run permitted original-channel sends, authorized operator actions and acknowledgments under current rules; create two distinct legitimate intents with identical content. | All supported journeys still work; distinct intents are not collapsed by body/destination deduplication. Normal timing, limits, protected holds and integrated separate policies remain unchanged. | Passing by disabling providers/features, broad global deduplication, removed safeguards or incidental B behavior. |
| AC-34 | Run a synthetic end-to-end standard and migrated journey through enqueue → real dispatch boundary → crash/recovery or acceptance → completion → fresh API/UI observation. | Persisted state, surviving transport call ledger, execution, counters and user-visible results support the specific contract. Record exact commands/results and unverified vendor limits. | Helper-only green, skipped SQL/Temporal integration labeled pass, live customer outreach or an unconditional exactly-once claim. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — approve before implementation:**
- **Producer/action → persisted intent → provider boundary:** actual cadence, inbound AI/acknowledgment
  and operator application/API entry points, not calls to an enqueue helper alone. Observe source
  progress, authorized content, request identity, transport calls and user-readable results.
- **Claim/recovery/completion persistence:** real local/disposable Postgres, independent sessions
  and transactions; public repository/use-case observations plus persisted evidence at this approved
  persistence seam. Fakes cannot establish row locking, uniqueness, rollback or stale-write protection.
- **Execution lifecycle:** existing Temporal test boundaries for pending/completion, replay, timers,
  signals, recurring occurrences and original-run isolation. Exercise actual signal consumption,
  not only an appended outbox row. Preserve the A/17-B distinction in literal expectations.
- **Provider adapters/callback normalization:** recording SDK/HTTP transports and realistic redacted
  callback fixtures; real mapping/classification within the seam. Capability documentation is required
  for dedup/correlation claims; fake acceptance is not vendor-delivery proof.
- **API/UI and recovery:** real permission/response mapping plus focused existing UI route tests;
  controlled synthetic integrated demonstration. Separately approve sandbox writes or any deployment.

CRM, LLM, messaging and notification transports and clocks may be hand-written fakes. Keep business
decisions, rendering validation, identity, transitions and accounting real within the agreed boundary.
For kill tests, the provider-acceptance ledger must live outside the process being killed. Inject
failure at observed transaction boundaries; do not simulate a crash only by returning a failed result.

1. Pick one journey/scenario and write one behavioral test before its implementation. A useful first
   red is provider acceptance followed by a lost commit on a direct path, then original-work retry:
   assert one surviving provider call and recoverable intent/outcome. A simpler producer-boundary red
   may precede it, but does not replace this crash proof.
2. Run against unchanged behavior and capture the meaningful failing assertion; make the smallest
   change for that vertical slice, rerun green, then select the next. Minimal interface scaffolding
   may make a case runnable; record it separately. Missing imports/infra, bad fixtures, no collection
   and skips are not the defect's red evidence. Do not implement all journeys before writing tests.
3. Existing standard-durable behavior and safety controls may already be green. Retain them as
   controls; demonstrate sensitivity with an isolated mutation where needed, rather than fabricating
   a failure or changing business expectations to accommodate the implementation.
4. Critical sensitivity checks: bypass durable enqueue; omit claim commit; reopen stale/uncertain
   claims; mint a new key/version on retry; allow an SDK retry after ambiguity; skip final revalidation;
   count/advance on enqueue; lose the occurrence/completion obligation; regress callback evidence;
   or show queued as sent. Restore mutations and rerun the affected checks.
5. Positive controls must prove every migrated purpose still sends when allowed, normal acceptance
   progresses without a delivery receipt, distinct intents both work, and permitted recovery can
   finish bookkeeping without sending again. Independently review expected states and call counts.

| AC / journey / failure point | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Remaining integration limit |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each variant | Exact invocation | Failing business assertion | Revision, exit code, pass/fail/skip counts | Actual protected behavior | Named unverified claim |

## 6. Engineering starting points and design review

Navigation only; paths below are qualified by repository and relative to that repository. Retrace
current signatures and consumers before implementation; this is not a prescribed new schema.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — send intent and dispatch | app/application/use_cases/send_outbound_message.py; dispatch_outbound_send_requests.py; refresh_outbound_send_request.py; revalidate_outbound_send_request.py in that directory; app/interfaces/workers/outbound_send_dispatch_worker.py |
| API — request/message/reconciliation | app/domain/campaigns/outbound_send_request.py; outbound_send_reconciliation.py; outbound_message.py in that directory; app/infrastructure/persistence/postgres/outbound_send_request_repository.py; outbound_send_reconciliation_repository.py; models.py in that directory |
| API — standard/paused-search lifecycle | app/application/use_cases/campaign_cadence_execution.py; schedule_next_paused_search_action.py; paused_search_operations.py in that directory; app/domain/campaigns/paused_search_occurrences.py; app/infrastructure/workflows/temporal/lead_nurture.py |
| API — inbound and operator producers | app/application/use_cases/continue_ai_conversation_after_inbound.py; process_inbound_message_event.py; process_queued_inbound_message_events.py; send_deferred_outbound_message_now.py; lead_draft_review.py in that directory; app/interfaces/api/v1/leads.py; app/interfaces/api/schemas/leads.py |
| API — completion and callbacks | app/application/use_cases/complete_outbound_message_crm_sync.py; process_provider_delivery_callback.py; dispatch_temporal_signals.py; timeout_uncertain_outbound_send.py in that directory; app/infrastructure/messaging/twilio/client.py; app/infrastructure/messaging/sendgrid/client.py |
| Web — actual action/status consumers | src/lib/api/leads.ts; src/pages/LeadDetailPage.tsx; src/lib/helpers/leadPresentation.ts; src/lib/helpers/workflowReasons.ts; src/app/LeadsRoutes.test.tsx |

**Compare at least two approaches before code:**
1. Extend the existing request/revalidation/completion orchestration with bounded, explicit
   purpose-specific behavior. One durable mechanism minimizes duplicated claim/recovery logic, but
   an oversized dispatcher could absorb unrelated journey rules and make every change risky.
2. Keep existing journey use cases responsible for intent preparation and idempotent completion;
   extend the dispatcher only with persisted validated context and durable completion obligations
   delivered through existing seams. This keeps journey rules local but adds asynchronous lifecycle
   coordination and must prove no missing/double completion or callback race.

Recommend the smallest extension of existing request/outbox and journey seams that satisfies R1,
not a parallel cache, arbitrary new ledger or generic dispatch framework. Record maintainability,
queue latency, validation freshness, transaction/lock behavior and migration cost. Obtain design
approval; do not treat this recommendation as approval to write code.

**Existing test starting points, not claimed coverage:**
- API application: tests/application/use_cases/test_send_outbound_message.py;
  test_dispatch_outbound_send_requests.py; test_revalidate_outbound_send_request.py;
  test_campaign_cadence_execution.py; test_schedule_next_paused_search_action.py;
  test_process_inbound_message_event.py; test_process_queued_inbound_message_events.py;
  test_send_deferred_outbound_message_now.py; test_process_provider_delivery_callback.py;
  test_uncertain_paused_search_occurrence.py; test_dispatch_temporal_signals.py;
  test_business_flow_harness.py in that directory. Draft-approval API coverage starts in
  tests/interfaces/api/v1/test_leads.py; do not assume a standalone AI/draft test file exists.
- API integration/adapters: tests/infrastructure/persistence/postgres/test_business_flow_harness.py;
  test_temporal_paused_search_workflow_postgres_e2e.py in that directory;
  tests/infrastructure/test_temporal_lead_nurture_workflow.py;
  tests/infrastructure/messaging/test_twilio.py; test_sendgrid.py in that directory.
- Web: src/app/LeadsRoutes.test.tsx plus affected presentation tests. Add/update focused tests for
  truthful asynchronous responses, review state and permitted recovery rather than screenshot-only proof.

Use Python 3.12/uv: exact pytest node, its file, related suites, then make lint, make typecheck and
make test. For changed frontend behavior, focused Vitest targets then pnpm test, pnpm typecheck and
pnpm lint. Confirm SQL/Temporal targets are local/disposable and record actual commands/exit codes /
counts. A skipped integration is an evidence gap. No behavioral tests ran to draft this ticket.

## 7. Existing records, cutover and safe recovery

1. **Inventory first, without mutation.** By workspace/original run/purpose: direct pending, failed,
   sent and uncertain messages; request/reconciliation/claim state; recurring occurrences; retries
   of inbound events; open approvals; completion/signal outboxes; missing execution IDs; provider
   evidence and unmatched callbacks. Include old worker versions and configured fallback tracks.
2. **Separate proven unattempted from unknown prior acceptance.** An old FAILED/PENDING row or absent
   provider ID alone does not prove the provider was never called. Do not backfill every old row to
   a new PENDING request. Preserve sent/uncertain identity, consent, approved content and source history;
   ambiguous cohorts stay contained with a named owner until an evidence-based plan is approved.
3. **Record the actual recovery operation.** R4 names environment, bounded cohort, operator,
   dry-run/approval, real supported command/action and verification. Safe replay must reuse intent
   and repair missing completion only. If a tool is missing, scope/review/test it first. This draft
   authorizes no webhook replay, CRM write, migration run, bulk restart/resend, data repair or deploy.
4. **Coordinate compatible producers and consumers.** Expand any required schema/contracts before
   switching producers; keep API/UI, dispatch workers, inbound workers and Temporal histories/builds
   compatible. Ensure no old direct producer can run alongside the new path for the same intent.
   Rehearse old queued signals and workflow replay before activation, not after customer sends.
5. **Verify and observe narrowly.** Use synthetic leads and sink/recording providers for normal
   dispatch plus crash/late-callback/completion recovery, including a recurring and operator journey.
   Name queue-age, uncertain-claim and failed-finalization thresholds, owners and actions. Preserve
   scoped audit IDs/statuses; no raw contact data, message bodies or credentials in broad reports.

## 8. Release, operator explanation and rollback

**Explain the change to operators:**
> Send now and Approve and send first show that the message is queued. That does not prove it was
> sent or delivered; final safety checks still apply. An uncertain outcome may already have reached
> the lead, so do not submit a replacement to force it through. Follow the displayed recovery action.
> This release improves duplicate prevention; the separate uncertain-send cadence policy is not
> being activated by this ticket.

Record the named release owner's authorization, D6/G6/R1–R4 closure, integrated prerequisite revisions,
test-first and real persistence/execution evidence, provider limitations and compatible cutover.
Class A is not a blanket deployment/data-write authorization. Any B behavior in the release requires
its own PR boundary, owner sign-off and applicable D5/G7 briefing; do not advertise it through A.

**Rollback:** contain affected producer/dispatch activity first using verified controls. Reverting
code can restore direct-send duplicate windows and cannot undo external acceptance. Preserve durable
claims, message/source identity, approvals, occurrences, consent and outcome/completion evidence.
Keep a compatible consumer or safely contain the queue; never delete/reset it, route new work inline,
recreate uncertain sends with fresh keys or revive terminal runs. Rehearse the bounded procedure and
tell operators which actions are unavailable while containment is active.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves business outcomes and ACs; D6/G6 scope is sized and any A-only slices named.
- [ ] R1/R2 design/capability questions and R3 per-purpose/API/A-only expectations are recorded;
      relevant configured-fallback policy gates are not silently resolved by the migration.
- [ ] Test seams, first meaningful red, independent expectation review and R4 recovery design agreed.
      No promise of an unsupported provider feature, recovery tool or exactly-once delivery remains.

### Ready to merge
- [ ] Every named lead-send journey is durably integrated through final validation and completion;
      a source inventory proves no production lead-provider bypass. Partial slices are labeled partial.
- [ ] Each AC/variant maps to meaningful red/green or justified existing-control evidence; critical
      sensitivity, real SQL crash/concurrency and actual Temporal completion/replay checks pass.
- [ ] Once-only occurrence/AI/review completion works on ordinary acceptance without waiting for
      delivery callbacks. Claim/late-result/callback races and source retries cannot redispatch it.
- [ ] Truthful API/UI pending/accepted/uncertain/failure/review states, safe permissions and recovery
      are proven alongside legitimate-send controls. No fake-success or queue-as-delivery claim.
- [ ] Integrated consent/human/reply/CRM controls remain; provider limits and known remaining
      uncertainty-lifecycle defects are explicit. No 17-B policy or neighboring B work is hidden in A.
- [ ] Compatible rollout/rollback, bounded recovery runbook, old-record treatment and operational
      ownership are reviewed. Governing help/docs describe the actual release, not all target policies.

### Production acceptance complete — not merely merged
- [ ] Owner authorizes the bounded activation; compatible producers/consumers are active and the
      operator explanation reflects queued/uncertain behavior and the still-separate 17-B release.
- [ ] Approved synthetic end-to-end observations support dispatch, completion, UI and recovery
      claims; worker/queue health has an accountable owner and no direct-send escape route.
- [ ] Historical unknowns and failed completion cohorts are reconciled or safely contained with
      named follow-up; no unauthorized resend, resume, consent change or data operation occurred.
- [ ] 17-A is accepted for its tested mechanics only; 17-B and other explicit residual dependencies
      remain tracked until their own acceptance, not implicitly closed with the parent Issue 17.

**Evidence status at drafting:** source/code trace and document review only. No application changes,
new behavioral tests, runtime pass, Jira publication, commit, deployment or production data operation.

## 10. References and decision precedence

- [Issue 16-A — suppression-preservation/recovery prerequisite](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — STOP ordering and unresolved-reply protection](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 11-A — ownership-projection repair](issue-11-a-project-crm-reassignment-immediately.md)
- [Issue 14-B — separate CRM-control policy](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [Issue 13-B — separate consent/fallback contract and G3](issue-13-b-consistent-consent-and-channel-fallback.md)
- [Source Issue 17 and business/readiness appendix, including G6](../production-state-consistency-issues.md)
- [D6 sizing and D7 ship-class boundary](../production-state-consistency-review-consensus.md)
- [Pre-send target — includes separately released policies](../../business-rules/04-pre-send-safety-checks.md)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product, layering and design review.

The code describes current behavior; the dated owner rules describe the target. D7 determines which
part may ship in this PR. Reading uncertain-as-sent in the target guidance does not include it in A;
preserving the A boundary does not reopen or reject the approved B decision. Escalate a new material
conflict to the owner instead of quietly changing a product rule or claiming an untested guarantee.