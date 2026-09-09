# Issue 9-B — Retry reply classification for 30 minutes, then escalate for review

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the nineteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not authorize production access, historical replay, notifications or release.

## 1. Business impact — read this first

**The promise:** A short AI-classifier outage does not lose a lead's reply or unnecessarily call
people away from their work. The reply remains protected from automated outreach while the platform
retries with backoff for up to **30 minutes from its original received_at**. If classification is
still unresolved at the deadline, the reply becomes a durable, actionable review item and the
assigned agent and their manager are notified. Neither elapsed time nor a notification makes the
lead safe to contact again.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | The current queue gives up after three total processing attempts, normally separated by 30 and 60 seconds. It has no receipt-based 30-minute policy or durable agent-and-manager escalation. 9-A separately supplies the missing safety and exhaustion visibility. |
| What changes during a short classifier outage? | Eligible failures continue retrying within the original window, with no new per-reply outage Attention item or outage notification. The temporary no-send guard remains effective on both channels. |
| What if the classifier recovers in time? | The reply follows its normal, permitted business outcome. No outage alert is created. A normal handoff or substantive review may still legitimately notify someone; that is not an outage alert. |
| What happens after 30 minutes? | The still-unclassified reply needs human review. Local review visibility and durable notification obligations are established independently of the failed classifier. Both agent and manager belong to this escalation, not a second 24-hour escalation. |
| Does every rejected AI answer wait 30 minutes? | No. An unusable, low-confidence or unclear returned answer keeps the existing immediate review behavior. It is not automatically an infrastructure outage. |
| Can a STOP wait for the retry window? | No. 9-A applies exact hard-word restrictions before AI. Other wording still needs classification; the no-send guard protects the lead while that work is unresolved. This ticket changes no keyword or consent rule. |
| Is “paused for review” a paused-search campaign? | No. Here it means unresolved reply processing needs a person. It does not select a paused-search track, invent a pause reason from the lead, or start a new enrollment. |
| What if an agent or manager cannot be reached? | The review remains visible to authorized operators, and the missing/failed recipient is an explicit unresolved obligation with an owned remedy. A workspace fallback is not silently assumed to be “their manager.” |
| Does the deadline guarantee email delivery at that exact second? | No. It ends the silent retry window. Detection, local recording and notice dispatch have separately approved, monitored latency bounds; provider acceptance is not delivery or proof that a person read it. |
| Does service recovery automatically resume an escalated lead? | No. After expiry, ordinary classifier retries stop. An approved, authorized disposition or bounded recovery is required; seen, notified, reconnected and resolved are different facts. |

The approved cost is up to 30 minutes of waiting for a non-hard-word reply during an outage,
without contacting that lead. Silence means no new per-reply outage alarm, not hidden diagnostics,
misleading sendability or suppression of existing unrelated reviews and service-health monitoring.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — recorded reply-handling policy; confirm at publication |
| Source / delivery class | Production-state consistency Issue 9 / **Class B: 30-minute retry window and agent/manager escalation** |
| Components | Normalized inbound receipt/processing; classification failure boundaries; durable deadline/review/notice lifecycle; scoped Attention/detail; authorized resolution and monitoring |
| Repositories | miller-schackman-api and miller-schackman-web; receipt → protected retry → recovery or expiry → review and notices → truthful operator disposition |
| Sequence | Nineteenth draft, following initial coverage of all seventeen source issues; the policy follow-up to 9-A, not a replacement for that draft |
| Required safety foundation | Separately integrated 9-A durable receipt/STOP/no-send/guard-resolution/exhaustion behavior and 16-A opt-out preservation, with relevant tests passing. Drafts are not integrated code. |
| Sending and instructions | Any automatic or authorized continuation that can contact a lead needs verified integrated 17-A intent/claim/outcome safety on that route. Use integrated 2-A original-instruction and applied/accepted contracts where workflow coordination is required; no new restart authority. |
| Ownership and evidence | Use the authoritative current lead assignment, including 11-A when integrated; reuse 4-A operational history and 9-A review identity. Coordinate with 15-A source-owned terminal discovery without duplicate reviews or a second classifier retry owner. |
| Adjacent policy | Preserve the actual separately released 12-B/13-B/14-B/17-B and 8-A/G1 reply-lifecycle baseline. This ticket neither enables nor rolls those policies back. |
| Decision ownership | Name product/release owner, implementer, independent reviewer, queue/runtime owner, API/web owner and incident-response owner. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-09; no live production state inspected. Retrace the implementation branch. |
| Release authorization | Individual D7 Class B owner sign-off and agent/operator briefing. Approval to draft, approval of the 30-minute principle and permission to release are distinct. |

**Included:** valid, matched SMS/email replies already entering the normalized inbound pipeline;
time-bounded classifier-infrastructure retries; original receipt/deadline identity; crash/concurrency
safety; independently discoverable expiry; durable review plus per-recipient notification progress;
scoped reads and a usable review/recovery/support journey; historical containment and bounded rollout.

**Excluded:**
- Reimplementing 9-A safety inside this PR, changing hard words, lifting opt-outs, channel fallback,
  new contact rights, handoff auto-resume, terminal re-entry or resetting a journey/touch/AI budget.
- Delaying existing substantive rejection/unclear reviews or changing their notification program.
- Treating every exception in inbound processing, every native CRM envelope or every background job
  as a classifier outage; changing those other retry budgets belongs to their own approved work.
- New recurring reminders, broadcast-to-all-staff alerts, a second manager waiting period, digest
  policy, universal notification platform, general manager/team administration or raw-message export.
- A new inbound source, raw MIME interpretation, automatic historical replay/notification campaign,
  production fault injection or real-customer test traffic. Earlier eighteen drafts remain unchanged.

**D4 fixes the policy boundary; D7 fixes the release boundary. Class A and Class B must not share a
PR.** A missing A foundation is a separately integrated prerequisite, not permission to mix classes.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

- Webhooks commit a PENDING external event before returning accepted. Enqueue copies the incoming
  event's received_at and uses enqueue-time now for created_at. Twilio and SendGrid/Mailgun inbound
  handlers currently construct received_at from server time; the normalized FUB inbound-message
  endpoint accepts request.received_at. These are not universally provider-send timestamps.
  Native FUB envelopes are a separate path, with their own occurrence timestamp and retry policy;
  native notes/text/call activity must not be presumed to enqueue a normalized lead reply.
- The normalized queue claims PENDING/RETRYABLE_FAILURE rows, increments attempt_count, and uses
  three total attempts with exponential delay starting at 30 seconds, capped at ten minutes.
  The two normally scheduled delays are **30 and 60 seconds**, not ten minutes of retries or three
  additional attempts. Processing/queue latency means this is not a wall-clock duration guarantee.
- Primary reply classification and required reply-route classification can call the model. Their
  structured-output retry is distinct from the queue's retry. Returned REJECTED results reach a
  review path; raised failures propagate. The queue catches exceptions from the entire processor
  and its commit, assigning the generic queued_inbound_processing_failed reason. That is not
  reliable evidence that the classifier itself failed rather than later work or persistence.
- The worker passes one now value through a batch. Claims use FOR UPDATE SKIP LOCKED, but per-event
  commit/rollback releases transaction locks while the loop retains earlier returned objects.
  External-event upsert can replace received_at and other mutable fields. Neither that lock nor
  the preliminary duplicate lookup proves durable attempt ownership or immutable first receipt.
- The existing review helper chooses one CRM agent email or a workspace handoff fallback. It
  catches notification exceptions and records an audit result; it is not a durable two-recipient
  notice queue. EmailNotificationProvider returns provider acceptance, not confirmed delivery.
  PausedSearchNotification has useful persisted status/idempotency shapes, but its policy's
  24-hour manager parameter and outbound-uncertainty use case are **not** this inbound deadline.
- Users, memberships and CRM mappings provide roles and effective/fallback ownership, not a verified
  per-agent manager relationship. The fallback resolver can choose a configured or first active
  manager for an unmapped lead; that does not establish who manages an otherwise assigned agent.
- Attention already shows paused/blocked leads and handoffs, not only handoffs. It does not expose
  this reply deadline or recipient lifecycle. The existing “Resolve as dormant/paused-search”
  lead-review action requires a lead-state classification artifact and no existing workflow, and
  can enroll a campaign. It is not an exhausted-reply disposition simply because both say “review.”

9-A and 15-A describe required foundations, not current code in this traced baseline. In particular,
9-B cannot be implemented safely by replacing the number three with a larger number in a broad catch.

### 3.2 Separate classifier outage from other unresolved work

Approve the exact phase/failure matrix at R1. The following meanings must remain distinct:

| Observed situation | Required treatment |
| --- | --- |
| Exact hard word | Apply 9-A's deterministic restriction without AI or deadline delay; preserve the released consent/lifecycle outcome. No classifier-outage episode for optional enrichment failure. |
| An ordinary reply has a usable classification and required routing result | Apply the existing permitted business outcome once, subject to the durable completion boundary in §3.3 and all current safeguards. |
| Required classification call fails for an eligible infrastructure reason, such as transport timeout, network/provider unavailability or approved quota/rate-limit failure | Retry with backoff within the original window, retain protection and remain free of new per-reply outage alerts until expiry. Normalize vendor evidence behind existing ports. |
| The model returns rejected, invalid-after-its-structured-output-retry, low-confidence or unclear evidence | Preserve existing immediate review and its reason/notification behavior. Do not keep asking the model for 30 minutes merely to obtain a more convenient answer. |
| Classification succeeded but CRM completion, optional summary, drafting, lead dispatch, workflow instruction or local commit fails | Preserve actual completed phases, failure category and independent protection/recovery. Do not label it a classifier outage, repeat an external effect, or borrow a new 30-minute classifier budget. |
| Invalid stored payload, unsupported source, unmapped/unmatched event or a known permanent/configuration/programming failure | Keep the appropriate existing rejection/ignored/terminal handling and 9-A/15-A visibility where applicable. Unknown cause stays unknown; an exception alone is not an approved retry classification. |
| Accepted, matched reply still awaiting classification at its deadline, including never-claimed/stalled work | Proposed unattended-work boundary for R1/R2: discover and surface it at the same deadline with its truthful “classification not completed” reason and escalation. Do not wait for a fresh exception or invent a provider outage. |
| Service, storage or discovery coverage is unavailable | Retain known protections; expose the operational coverage failure through the approved monitoring route. Do not report healthy empty queues or claim a review was saved while storage was down. |

Required primary and reply-route calls share one reply deadline; no fresh clock for a second model
call or structured-output retry. R1 names the covered phases and canonical failure categories,
including unknown/permanent/configuration cases. Enrollment classification is outside this slice.
Existing application rules, not the model, decide consent, handoff and send permission.

A substantive rejected/unclear outcome durably recorded before cutoff is not eligible for later
classifier-outage expiry. Complete or retain its immediate review and protection under that actual
cause; a later sweep must not add an outage episode or outage notices. Failure to finish the review
remains its actual incomplete phase, not a new classifier outage. §3.3 governs late results.

### 3.3 One original clock, bounded retries and an explicit success boundary

1. The deadline is the original accepted reply's received_at plus **30 elapsed minutes**, normalized
   to an unambiguous instant. It is not first failure, last retry, row update, worker start, CRM sync
   or page-open time. Preserve timestamp provenance and the effective policy with the same durable
   reply identity. Duplicate ingress, concurrent upsert, restart, reassignment and configuration
   reload cannot silently move the deadline or erase its history.
2. Source-specific timestamp trust, timezone/offset handling and malformed/future/missing legacy
   values need R1 agreement. Never silently substitute now to grant another window or fabricate an
   old receipt. Evidence-limited accepted work stays protected and explicitly contained for review.
   A valid delayed receipt may have little or none of its window left when first claimed.
3. Eligible failures continue to get bounded retry opportunities before the deadline; retaining
   three attempts and then sitting idle until minute 30 does not implement the approved policy.
   R1 approves the actual backoff, provider retry-after handling, call/SDK retry limits and timeout
   budget. No hot loop, unlimited calls, fresh per-phase budget or rate-limit bypass is permitted.
4. Check a fresh authoritative time and current ownership before each eligible call and when
   recording its result, not only once per poll. The proposed exact boundary is: before the
   deadline, an eligible attempt may start; **at or after the deadline, no new ordinary classifier
   attempt starts**. A retry due after the cutoff must still produce timely expiry discovery.
5. Proposed success boundary for R1/R2: required validated classification/routing evidence must be
   durably recorded before the deadline. Then the normal disposition may continue without an
   outage alert, even if a delayed expiry sweep runs later. An in-memory answer or rolled-back
   success is insufficient. The 9-A guard remains until the business disposition is safely applied;
   classification success alone does not make outreach sendable or prove downstream completion.
6. An attempt may begin before expiry and return after it. Bound its execution and fence its result
   against expiry, newer replies and human decisions. A late ordinary result cannot release the
   guard, auto-resume, send a reply or retract an established escalation. Preserve valid late
   restrictive evidence through the existing suppression rules; expiry is not a reason to discard
   an opt-out. R1/R2 must approve this cutoff/race contract before tests encode it as policy.
7. Expiry discovery must not require another classifier exception, successful CRM/LLM call, an
   active lead engine or a user opening the lead. It covers due/future retry rows and accepted work
   still awaiting a classifier outcome under §3.2, with complete bounded traversal and restart repair.
   A slow classification batch must not prevent other replies reaching review. At deadline the silent
   window is over; R4 sets measurable detection/recording/dispatch lag bounds and independent monitoring.
   Storage outages may prevent immediate recording; recover retained obligations after restoration
   and report actual observation/recording times rather than claiming on-time delivery.
8. Expiry closes ordinary automatic classification retries for that reply. A subsequent worker
   restart or healthy provider cannot reopen them. Authorized recovery, if offered, has a separately
   bounded request and retained original deadline/history, not a new receipt or endless 30-minute
   windows. A policy constant may be revisited under D4, but its change cannot implicitly resurrect
   expired work; compatibility and active/historical cohort handling belong to R4.

### 3.4 Durable review and agent/manager notification obligations

- Anchor the episode to workspace and original inbound event/message identity, retaining proven
  lead, conversation and workflow/run links. Do not collapse all replies into one moving lead-level
  timer. A newer reply cannot extend an older deadline or clear its protection. Shared presentation
  may group replies only while preserving every original obligation and age.
- Reuse 9-A's protected review/evidence rather than creating a duplicate handoff or fake rejected
  classification artifact. Expiry, review protection and local discoverability must be atomic or
  independently reconstructable from the authoritative committed source. Create a durable notice
  obligation for both required roles with that outcome, including an explicit pending-resolution
  obligation when a recipient cannot yet be resolved. CRM, AI summaries and email cannot be
  prerequisites for saving or discovering review.
- “Paused for review” is the business disposition, not a mandated new WorkflowState enum. Use the
  sanctioned workflow transition where legal. Preserve handoff/human-owned, manually paused,
  suppressed, terminal and successor-run state; keep the unresolved reply discoverable even without
  a workflow. Do not force a protected state into generic PAUSED just to make Attention render it.
- Source writers, ordinary retry eligibility and 9-A/15-A reads must use the same authoritative
  policy/outcome. A third eligible failure within the B window is not a stopped reply. An expired
  reply is not successfully PROCESSED merely to stop claims. Approve the reason/status mapping and
  classification-success checkpoint at R1/R2; do not choose an enum by copying a neighboring path.
- Keep durable per-recipient identity, current routing evidence, attempt/claim state and outcome.
  Record pending destination resolution, queued, accepted, definite failure and uncertain result
  distinctly, with safe reason and actual observation times. Both agent and manager obligations
  must be inspectable; acceptance for one cannot mark the other complete. Deduplicate repeated
  expiry handling and recover only outstanding obligations, not the entire inbound pipeline.
- Resolve “assigned agent and their manager” under an owner-approved R3 rule. Verify active user,
  workspace membership, permitted lead scope, destination and current assignment before dispatch.
  Missing agent/manager, multiple possible managers, inactive users, fallback ownership, absent
  destination and the same person filling both roles need explicit approved treatment. Do not
  silently select every manager, the first manager or a handoff mailbox as the required manager.
- R3 fixes staff channel(s), minimum safe content, authenticated destination links, preferences,
  quiet-hours/digest interaction and fallback ownership. No new channel is assumed just because
  an enum lists it. No extra 24-hour wait or digest may silently replace deadline escalation.
  Staff notices are not lead outreach; they must not consume cadence/AI/contact budgets or borrow
  a lead-consent fallback rule. Existing notification programs remain otherwise unchanged.
- Commit notice intent/claim before external I/O and reconcile results under durable ownership.
  Bounded notice-delivery retries are separate from the expired classifier budget. Provider
  acceptance followed by lost acknowledgment is uncertain, not proof of failure: no blind resend
  unless the actual provider contract makes it safe. An idempotency key passed to a port alone
  proves neither provider deduplication nor exactly-once delivery. Keep uncertainty visible with
  a supported reconciliation/escalation route; do not promise “delivered” or “read” from acceptance.
- Revalidate routing after reassignment or membership changes. Do not send a queued notice to a
  now-unauthorized former owner. Retain already-sent history honestly; it cannot be unsent. R3
  bounds recipient replacement, dual-role deduplication and any allowed follow-up so assignment
  churn or repeated polling cannot generate unlimited new notices. This is not a general “notify
  the new agent on reassignment” policy; that remains excluded from 11-A.
- Claim/version fencing must survive concurrent workers, expiry, human resolution, crashes and
  batch commit/rollback. Stale objects cannot overwrite newer success or send a stale actionable
  notice after a resolved episode. Approve cancellation/reconciliation of outstanding notices at
  R2/R3; retain the obligation's truthful disposition instead of calling a cancelled notice sent.

### 3.5 Complete the operator journey without inventing a recovery permission

1. **Discover:** Attention and lead detail show the same unresolved expired reply with original
   receipt, deadline, actual expiry/discovery time, safe failed phase/reason, known attempt history,
   no-send state, current responsible role and notice progress. Use “Reply classification still
   unresolved after 30 minutes” only where evidence supports it; do not claim outage/intent when
   none is known. Pre-deadline transient work creates no new outage card, while existing independent
   reviews and honest send-block explanations remain intact.
2. **Inspect safely:** scope list, count, detail and notification links before pagination/joins.
   ASSIGNED_AGENT sees owned leads; existing MANAGER/BROKERAGE_ADMIN/authorized PLATFORM_SUPER_ADMIN
   scope is preserved. Manager recipient selection is not a new authorization role. Unassigned
   matched leads remain available to authorized workspace operators. Removed/inaccessible anchors
   and unavailable data are explicit, not fabricated leads or broadened access.
3. **Keep evidence and counts honest:** show pending recipient resolution or a failed/uncertain
   notice without hiding the reply review. Count replies, affected leads and notice attempts as
   distinct units. Correlate 9-A/15-A's same obligation, preserve separate child failures and provide
   complete stable traversal/history; do not infer totals from the first lead page. Allowlist safe
   metadata: payload_redacted may contain message text, and truncated errors are not sanitized.
   No raw prompts, provider payloads, credentials, arbitrary URLs or unsolicited reply-body export
   in the new queue/notice. Authorized reply inspection uses the approved existing detail scope.
4. **Keep seen separate:** reuse per-user acknowledgment/versioning. Mark seen does not resolve a
   reply, deliver a notice, stop required delivery work or remove the no-send guard. Seen unresolved
   items remain reachable and counted. New distinct failures do not inherit an old seen marker;
   routine polling or a ticking age does not create a new incident version.
5. **Act through a real route:** R2/R3 must approve the exact supported reply disposition or bounded
   recovery, responsible role and destination. Existing enrollment-review buttons are not that
   implementation. Where self-service replay is unsafe, show it as unavailable and provide a named,
   reachable support route and non-replaying investigation/containment procedure. “Ask support”
   without an owner, destination and next step is not acceptance of the human escalation journey.
6. **Resolve only with authority:** any offered action requires current authorization, actor/reason,
   original episode and expected version; recheck current reply, lead/consent, independent holds,
   handoff/terminal/successor state and side effects before applying it. Recovery request, successful
   classification and business disposition remain distinct. Preserve original event/command/touch
   identity, partial progress and 17-A possible-acceptance claims; never replay a lead send merely
   to retry a staff notice or workflow signal. No blind Resume, fresh enrollment or consent lift.
7. **Refresh truthfully:** loading, empty, partial, unavailable and stale states remain distinct.
   A failed deadline/notice read is not “all handled”; acknowledgment failure cannot hide reviews.
   A stale/duplicate action returns its current result or a clear conflict, not a false success toast.
   Resolution clears only its own applicable protection after the disposition is durably applied;
   another unresolved reply or protected state still wins.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Policy, clock and failure contract | Confirm the approved 30-minute rule and exact covered primary/route phases; canonical infrastructure/returned-rejection/other/unknown matrix; source timestamp trust and invalid-time containment; backoff/call bounds; deadline equality, never-claimed work and durable success/late-result semantics; reason/status/policy evidence and protected outcomes. | Domain/application policy and behavioral test implementation |
| R2 — Durable ownership, expiry and safe continuation | Choose the smallest source-backed design; approve 9-A/16-A foundations, classification checkpoints, immutable identity, expiry/guard/review/notice commits, independent deadline discovery, batch/claim/version fencing, partial-progress and late-result handling; verify 17-A/2-A routes where needed; approve notice retry/uncertainty bounds and every offered reply recovery or disabled-replay disposition. | Persistence/worker/notification/recovery implementation and integrated safety acceptance |
| R3 — Recipients and operator contract | Decide what “their manager” means and the authoritative lookup/configuration; agent/fallback/missing/inactive/multiple/dual-role cases, channel/preferences/digest/quiet-hours behavior, recipient replacement/cancellation and fan-out bounds. Approve safe notice content, scoped API/UI/links, counts/history/seen/error states and a usable permission-checked review/support route with owner. | Notification/API/web implementation; unresolved manager routing cannot ship as completed two-role escalation |
| R4 — Compatibility, history and release | Approve policy/version/cohort cutover, legacy timestamps and already exhausted/processed work, separately authorized historical inventory/actions, mixed-version containment, exact canary/rates/stop criteria, detection/recording/dispatch and coverage-failure bounds, independent monitoring, incident owner, evidence-preserving rollback, individual D7 release sign-off and briefing. | Production rollout and accepted-live claim |

Applicable R1–R3 decisions and §4–5 seams must be approved before implementation; R4 does not block
unrelated baseline reproduction. This draft does not choose unresolved manager relationships,
notification channels, extra contact powers or fixture-default timeouts as if already approved.

## 4. Business acceptance scenarios — for approval

These are requirements, **not passing tests**. Use synthetic replies, fixed clocks, recording
providers and controlled interleavings. Parameterize applicable SMS/email and current standard/
paused-search routes. Gate-dependent cases use the approved R1–R3 matrix, never invented defaults.

| ID | Scenario and required result |
| --- | --- |
| AC-01 | Exact hard-word SMS/email with the classifier unavailable: 9-A commits the correct restriction without waiting or generating a classifier-outage episode. Other consent and the released lifecycle outcome remain intact. |
| AC-02 | Eligible first classifier outage: the reply stays protected between attempts; no automated SMS/email provider calls or new outage review/notice. An otherwise equivalent healthy lead remains sendable. |
| AC-03 | Third eligible failure well before expiry: another bounded retry opportunity remains; no premature EXHAUSTED/review/notice and no silent idle-until-deadline substitution for retrying. Non-covered work retains its own attempt policy. |
| AC-04 | Required classification recovers and commits inside the window: normal application disposition completes once, with no outage episode or agent/manager outage notices. A legitimate response/handoff still works; unrelated holds are not cleared. |
| AC-05 | A non-hard-word reply is classified as an opt-out during recovery: the existing explicit suppression/application rules apply with original reply evidence. No keyword expansion, new consent lift or fallback rule. |
| AC-06 | Returned REJECTED/unclear/low-confidence output before expiry: existing immediate review behavior remains, including the existing structured-output retry where applicable. No 30-minute waiting loop. With the substantive outcome durably recorded before cutoff, a later deadline sweep adds no outage episode/notices; its review and protection remain. |
| AC-07 | Required classification is durably successful but later CRM, summary, drafting, dispatch, signal or commit work fails: record the actual incomplete phase, preserve partial effects and protection, and do not falsely report a classifier outage or rerun a possibly sent message. |
| AC-08 | Primary and required route classification, structured-output retry and configured adapter retries share the original deadline/call bounds. A second phase cannot buy another 30 minutes; an optional or enrollment-classification failure cannot enter this policy accidentally. |
| AC-09 | A valid reply received at 12:00 first reaches the worker at 12:25: deadline remains 12:30, not 12:55. Original receipt and local enqueue times retain their different meanings. |
| AC-10 | Offset-equivalent receipts, duplicate/concurrent ingress, restart and configuration reload: one original instant/identity/deadline survives. Future, missing or invalid legacy timestamps follow R1's explicit protected containment, not a guessed new window. |
| AC-11 | Fresh decisions immediately before, exactly at and after a 12:30 deadline: permitted pre-deadline work can run; at/after 12:30 no new ordinary classifier call starts and unresolved expiry is eligible for review/escalation. |
| AC-12 | The last failure schedules a backoff beyond 12:30: deadline discovery still creates the review and notice obligations within the approved lag, without waiting for another exception, polling the lead or calling the LLM after cutoff. |
| AC-13 | Accepted matched reply is never claimed, or a classifier worker stops: R1's approved unattended-work rule surfaces it at expiry through independent discovery. Show classification not completed, not a fabricated provider failure or attempt count. |
| AC-14 | Slow batch/worker restart crosses the deadline while retaining an old now/object: fresh time and ownership checks prevent a late ordinary attempt or stale successful overwrite; other due replies still reach review within the approved coverage bound. |
| AC-15 | An in-flight result races expiry, timeout or a human decision: a late ordinary result cannot send, release protection or retract escalation. Valid restrictive evidence is handled by existing suppression rules without overriding newer authority. |
| AC-16 | Required usable evidence commits before cutoff but the expiry sweep runs later: no false classifier-outage escalation. A separate still-pending business disposition retains its protection and truthful phase/recovery state. |
| AC-17 | Crash/rollback around receipt, classification checkpoint, expiry/review/notice intent and result commits: fresh-session reads preserve original identity/guard; repair completes only outstanding obligations without phantom success or lost review. |
| AC-18 | Two workers plus per-event batch commit/rollback on real persistence: one current attempt/expiry owner wins, stale objects cannot overwrite newer disposition and replay cannot duplicate a review, notice obligation or lead effect. |
| AC-19 | Several replies arrive out of order or a newer reply succeeds first: each retains its original deadline and disposition; older unresolved protection is not cleared or postponed. Independent manual, consent and handoff holds still win. |
| AC-20 | Reply on a known lead with no workflow, or a human-owned/manually paused/suppressed/terminal/successor journey: unresolved expiry remains discoverable without a fake workflow, forced PAUSED transition, new enrollment, re-entry or auto-resume. |
| AC-21 | Deadline with approved, valid agent and manager destinations: both durable role obligations lead to the approved staff notices and usable scoped review links. No second 24-hour wait and no lead contact or cadence/AI-budget consumption. |
| AC-22 | Duplicate expiry handling, lost responses and one recipient accepted while the other fails: one episode with independent recipient outcomes; only eligible outstanding work is retried, not the accepted recipient or entire inbound processing. |
| AC-23 | CRM lookup, summary/model or notification delivery is unavailable during expiry: review/guard and unresolved recipient obligations persist and remain visible. Failed delivery cannot roll back the review or release the lead. |
| AC-24 | Notice provider accepts but acknowledgment/result persistence is lost: outcome remains uncertain, not delivered or definitely rejected; approved reconciliation/bounded retry respects actual deduplication capability and never blindly resends. |
| AC-25 | Missing/unassigned/inactive agent, unknown or multiple managers, missing destination, fallback ownership and one person in both roles: each follows R3's approved routing/deduplication matrix with honest outstanding state and owned remedy; no silent broadcast or assumed manager. |
| AC-26 | Reassignment or disabled membership before notice dispatch/detail/action: revalidate current recipient and access, prevent stale disclosures, retain already-sent history, and bound any approved replacement. No independent reassignment-alert program. |
| AC-27 | Cross-workspace, unowned-agent and inactive-membership list/count/detail/notice-link/recovery attempts: deny or scope correctly before joins/pagination/effects; valid assigned-agent and existing wider-role controls still work. |
| AC-28 | Operator follows Attention to the expired reply: original receipt/deadline, actual observation time, safe reason, no-send state and each recipient outcome agree with durable records. No invented AI artifact, paused-search intent or “delivered/read” claim. |
| AC-29 | Multiple pages, older replies, grouped lead views and correlated 9-A/15-A items: complete stable traversal and truthful reply/lead/notice counts without duplicate review obligations or latest-workflow-only omission. |
| AC-30 | Mark seen, acknowledgment failure, unavailable/partial reads and a stale action: unresolved work remains reachable and protected; new material failures have correct versions. No healthy-empty substitution, false success toast or implicit resume/notice cancellation. |
| AC-31 | After expiry/service recovery, an approved reviewer follows the supported action or explicit non-replaying support route: current authority, cause, reason and version are checked. No automatic restart or reset of received_at; requested, classified and safely disposed outcomes remain distinct. |
| AC-32 | Any authorized continuation meets partial earlier CRM/signal/lead-send effects: preserve original identities, 17-A claims and touch/AI/enrollment counters; recover only incomplete work. Notice retry cannot resend the lead message; another reply/hold still blocks contact. |
| AC-33 | Integrated 9-A/15-A readers and workers observe the B cohort: eligible in-window retry is not prematurely stopped by a count-three UI rule; expired work is not successfully processed, forgotten or separately duplicated. Other rejection/recovery/notification policies remain intact. |
| AC-34 | Invalid persisted payload, unmatched/unsupported ingress and native FUB envelope retry: source-specific behavior stays truthful and protected where applicable; no fabricated matched lead, new inbound source or change to native/generic retry policy. |
| AC-35 | Historical inventory/cutover, including already processed, already reviewed, old exhausted and evidence-limited rows: dry-run changes nothing; repeated approved reconciliation preserves original evidence and never automatically restarts classification, resends or broadcasts backlog notices. |
| AC-36 | Mixed-version canary, classifier/expiry/notification-worker outage, storage recovery and rollback rehearsal: approved coverage/lag/stop controls detect failures independently; compatible containment retains opt-outs, guards, review/notice history and owned unresolved work without an unguarded send window. |

## 5. Test-first implementation contract

**No application test or code change is authorized by this draft.** Approve the behavior, R1–R3
decisions and public seams first. Then work one vertical slice at a time: **meaningful red → minimal
implementation → green**. Do not bulk-write speculative tests or make expected results match code.

**Proposed seams for approval:**
- Normalized accepted ingress and public inbound-processing/expiry use cases: fixed receipt/clock,
  canonical model responses/failures and observable protected/review outcomes, not private helpers.
- Actual persistence/claim/checkpoint boundary: separate sessions, rollback/restart, concurrent
  duplicate receipt, current-version expiry/result fencing and durable notice dispatch ownership.
- Notification port/adapter boundary: valid recipient requests, actual acceptance/rejection/
  uncertainty evidence and bounded retry, with recording providers and independent positive controls.
- Scoped list/detail/count and any approved recovery endpoints, followed through actual Attention/
  lead/notification-link UI. Test permissions and a usable role-specific support route, not only DTOs.
- Applicable real local workflow coordination and 17-A dispatch integration: hold during processing,
  legitimate continuation, retained possible-acceptance claims and no premature cadence advance.

**Evidence rules:**
1. Reproduce the time-policy gap on the intended integrated A baseline, not merely the old
   STOP-ordering defect. For example, show a third eligible infrastructure failure ending retries
   before its original deadline, then fix only the approved B behavior. Record the exact failing
   assertion and command; missing imports, broken fixtures and infrastructure skips are not red.
2. Derive expectations independently: a synthetic 12:00 receipt has a literal 12:30 deadline, not
   an expectation computed by the production deadline helper. Use virtual/fixed time, not real
   30-minute sleeps. R1/R3 choices must not be quietly made by a test fixture or recipient default.
3. Hand-written fakes may replace external LLM/CRM/SMS/email/notification ports and clocks. They
   must model failure/uncertainty and relevant recording behavior. Do not mock the expiry decision,
   authorization, guard read or notification outcome under test. Fake commit cannot prove durability.
4. “No send” means zero lead-provider calls while the guard applies; “no outage notification” means
   zero such notice intents/dispatches, not simply no toast. Keep a healthy permitted send, a normal
   substantive review/handoff notice and a correctly expired two-role escalation as positive controls.
5. Sensitivity-check original-clock preservation, count-three replacement, cutoff/in-flight fencing,
   phase distinction, guard retention and recipient deduplication. Mutating each protection should
   fail its intended assertion without breaking the test harness. Restore the change and rerun.
6. Prove commit/rollback/restart and concurrent claims on disposable real Postgres; prove applicable
   workflow timer/signal behavior on local Temporal. At provider boundaries use supported sandbox/
   contract evidence for the exact claim. No fake idempotency behavior as proof a provider deduplicates.
7. For each acceptance ID attach actual node/file, red/green and relevant integration evidence,
   expected/forbidden effects, positive controls and known limitations. Review business expectations
   independently. Do not widen consent, time, recipient or recovery policy to make a failing test pass.

## 6. Source-backed implementation notes and alternatives

Paths below are verified starting points at the stated baseline, not a prescribed edit list or
claims of new coverage. app/ and tests/ paths are API; src/ paths are web.

| Responsibility | Existing reference |
| --- | --- |
| Accepted receipt and source-specific timestamp | app/interfaces/api/v1/webhooks.py; app/application/use_cases/enqueue_inbound_message_event.py |
| Processing phases and broad retry boundary | app/application/use_cases/process_inbound_message_event.py; app/application/use_cases/process_queued_inbound_message_events.py; app/interfaces/workers/inbound_message_worker.py |
| Required model work and port | app/application/services/llm/reply_classification.py; app/application/services/llm/reply_route_classification.py; app/application/ports/llm.py |
| Vendor call/timeout behavior to recheck | app/infrastructure/llm/openrouter/client.py; app/infrastructure/llm/bedrock/client.py |
| Persisted event and queue ownership | app/domain/crm_sync.py; app/infrastructure/persistence/postgres/crm_sync_repository.py |
| Separate native envelope/activity mapping | app/infrastructure/crm/follow_up_boss/webhook_event_parsers.py; app/infrastructure/crm/follow_up_boss/webhook_event_mappers.py |
| Current staff review notification | app/application/ports/notifications.py; app/infrastructure/notifications/email.py; process_inbound_message_event.py's review helper above |
| Related but distinct persisted notice pattern | app/domain/campaigns/paused_search_notifications.py; app/application/use_cases/timeout_uncertain_paused_search_occurrence.py |
| Current ownership versus manager selection | app/application/services/lead_assignment_resolution.py; app/domain/crm_agent_mapping.py; app/domain/identity/models.py; app/domain/identity/permissions.py |
| Existing review/read/acknowledgment boundaries | app/application/use_cases/lead_read.py; app/application/use_cases/review_queue_read.py; app/application/use_cases/lead_review_hold_resolution.py; app/application/use_cases/attention_acknowledgements.py; app/interfaces/api/v1/leads.py |
| Attention and its source versions | src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/attentionVersions.ts; src/lib/presentation/operations.ts |
| Existing operator destinations | src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx; src/pages/ReviewQueuePage.tsx; src/lib/api/leads.ts |

| Technical approach | Benefits | Costs / risks |
| --- | --- | --- |
| A — Extend the existing durable inbound owner with deadline-aware phase/checkpoint state, independently runnable expiry discovery and focused durable recipient work | One reply authority, reuse of 9-A protection and 15-A source discovery, no dependency on a lead engine existing; bounded polling latency is explicit. | Requires careful receipt/claim/phase commits, deadline traversal and separate notice-result ownership. A larger catch/attempt limit alone is insufficient. |
| B — Add a dedicated per-reply Temporal coordinator while keeping the same database guard/review/notice truth | Durable timers and model-attempt orchestration can be explicit, with native workflow test support. | Adds engine-start/recovery and rollout/replay concerns, ownership transfer from the existing inbound worker and an independent missing-coordinator backstop. Cannot replace local protection or authoritative review evidence with a timer. |

**Recommendation for R2:** prefer A unless a focused sizing/reuse trace shows B is materially
simpler. Compare the already integrated 9-A representation before adding a table, event or service.
Do not prescribe a new manager-assignment schema from an unapproved recipient rule. Keep application
failure meanings canonical, vendor logic in adapters, and external event publication transactional.
No database locks across LLM/CRM/email I/O; short claim/commit and fenced result boundaries must
protect the full journey. The owner approves the design before implementation begins.

**Existing test starting points, not claimed deadline/escalation coverage:**
- tests/application/use_cases/test_process_queued_inbound_message_events.py
- tests/application/use_cases/test_process_inbound_message_event.py
- tests/application/services/llm/test_reply_classification.py
- tests/application/services/llm/test_reply_route_classification.py
- tests/application/use_cases/test_attention_acknowledgements.py
- tests/application/use_cases/test_review_queue_read.py
- tests/application/use_cases/test_lead_review_hold_resolution.py
- tests/application/use_cases/test_crm_agent_mapping_admin.py
- tests/application/use_cases/test_send_outbound_message.py
- tests/application/use_cases/test_dispatch_outbound_send_requests.py
- tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/notifications/test_email.py
- tests/domain/campaigns/test_paused_search_reviews_notifications.py
- tests/infrastructure/persistence/postgres/test_crm_sync_repository.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/interfaces/api/v1/test_webhooks.py
- tests/interfaces/api/v1/test_leads.py
- tests/interfaces/api/v1/test_reporting.py
- tests/interfaces/api/v1/test_lead_review_hold_resolutions.py
- src/app/LeadsRoutes.test.tsx
- src/pages/ReviewQueuePage.test.tsx
- src/components/operations/operations.test.tsx
- src/lib/api/reporting.test.ts

For implementation, start with one exact pytest node, then its file and related suites using
Python 3.12/uv; run make lint, make typecheck and make test as applicable. For web changes run the
affected Vitest tests, then pnpm test, pnpm typecheck, pnpm lint and pnpm format:check. Record actual
commands, selected counts and exits. Confirm integration targets are local/disposable before use;
skipped Postgres/Temporal coverage is missing evidence, not a passing product journey.

## 7. Historical work and recovery boundary

- A separately authorized metadata-only inventory must distinguish new B-cohort pending work,
  old A-budget exhaustion, existing reviews, correctly processed/rejected/ignored replies and
  ambiguous legacy timestamps or phase evidence. Do not classify every external-event failure
  as a 30-minute classifier outage or treat native envelope occurrence time as normalized receipt.
- R4 approves which retained replies adopt this policy and how existing episodes are represented.
  Preserve original receipt/event/body access controls, attempt evidence, applied restrictions,
  business disposition, current ownership and notice history. Do not reset clocks/counts to make
  old work look newly received, or claim it was escalated/notified at a time that was never recorded.
- Deployment is not authorization to rerun classifiers on old text, reopen reviewed/terminal work,
  clear dedupe keys or send a burst of backlog notices. Any historical review reconstruction or
  notification action needs explicit workspace/event scope, operator, exclusions, rate/batch limits,
  dry-run counts, expected effects and repeat-safe reconciliation. Keep unproven cases contained.
- A recovery that can reach AI response, CRM completion, handoff acknowledgment or lead dispatch
  must first prove original-identity partial-progress safety at its approved boundary. Never recover
  a failed staff notice by replaying the inbound message. A newly inferred restriction is not
  evidence that it was originally recorded; 16-A owns evidence-backed suppression restoration.
- Retained unknown/unsafe cases require a reachable owned support route with no unverified replay
  controls. A visibility-only limitation must be accepted explicitly, not hidden behind “Resume.”
  This ticket does not grant production read, write, resend or consent-change authority.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4 decisions, verify separately integrated safety/read/
   dispatch foundations and record the actual released policy baseline. Obtain individual D7
   owner release approval; define exact receipt cohort and compatibility behavior for active rows.
2. **Rehearse locally/staging:** synthetic exact STOP during outage; more than three ordinary
   classification failures; recovery inside the window; rejected answer; expiry with no classifier
   worker; valid and unresolved agent/manager routing; uncertain staff notice; protected resolution.
   Use recording/sink/sandbox providers and fresh persisted reads, including operator UI paths.
3. **Deploy compatibly:** schema/read support and source-policy understanding must precede writers
   that require them. Explicitly contain older workers that could expire at count three, overwrite
   phase/deadline state, suppress reviews or retry after B expiry. Do not run two independent reply
   processors against the same work without a verified ownership handover. Preserve final no-send
   checks throughout; activation must not bulk replay, notify, resume or enroll.
4. **Bound the canary:** approve workspace/cohort size, model-call and staff-notice load bounds,
   rollout pace and stop criteria. The longer retry window increases work per unresolved reply;
   verify load/rate limits and delayed-work traversal rather than assuming the old capacity is enough.
   Historical actions remain separately authorized under §7.
5. **Observe independently:** monitor oldest unclassified reply and deadline overrun, eligible retry
   cadence, stopped/stale workers, missing review/notice obligations, per-recipient resolution and
   accepted/failed/uncertain age, duplicate attempts, protected-send violations and discovery coverage.
   R4 names measurable detection/recording/dispatch bounds, alert destinations and incident owner.
   The health monitor cannot require the same failed classifier or notification transport to work.
6. **Accept the actual journey:** demonstrate quiet recovery without outage noise, honest expiry
   review, both approved recipients or explicitly owned outstanding obligations, correct role access,
   zero guarded lead sends and a working review/support next step. Brief agents on the 30-minute
   wait, immediate hard-word protection, normal-rejection difference and why seen/notified is not
   resolved. Record deployed evidence separately from merged code and sandbox/provider limits.

**Rollback:** contain incompatible classification/notification workers through the approved scoped
controls before reverting. Preserve receipt/deadline/policy identity, opt-outs, no-send guards,
reviews, per-recipient outcomes and possible-acceptance claims. Do not clear protection, delete
episodes, reset clocks or replay inbound work to obtain a green dashboard. Keep compatible readers
and independent monitoring with a named operator for outstanding obligations. Already-started
provider effects cannot be unsent; reconcile them honestly. A forward-compatible repair or explicit
containment may be safer than reverting to the old three-attempt worker. Rehearse the procedure;
production rollback and data actions need separate authorization.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder accepts the business impact, separate B scope and applicable R1–R4 decisions;
  exact test seams/expectations and design are approved before implementation.
- [ ] Required 9-A/16-A and applicable 17-A/2-A/read/ownership integrations are verified; no A fix
  is hidden in the B PR and no adjacent policy is accidentally enabled or reverted.
- [ ] Original receipt and phase identity survive retries/restart; the approved 30-minute window
  has bounded retry, fresh-clock/cutoff checks, independent expiry discovery and safe late results.
- [ ] Review protection/discovery and both recipient obligations are durable, duplicate-safe,
  truthfully scoped and independent of successful classifier/CRM/notification I/O.
- [ ] Approved agent/manager routing, missing-recipient remedies, channel/preferences and uncertain
  notice handling are implemented; no fake manager link, broadcast or provider delivery guarantee.
- [ ] Attention/detail/count/history and review/support actions work for the intended roles, with
  honest unavailable/seen states and no unauthorized release of a pending reply or other protection.
- [ ] AC-01 through AC-36 map to meaningful red/green, sensitivity, positive-control and real
  integration evidence at each claimed boundary. Skips and unsupported self-service are explicit.
- [ ] Bounded historical treatment, compatible canary, load/coverage/lag monitoring and evidence-
  preserving rollback are rehearsed; individual D7 release sign-off and briefing are recorded.
- [ ] Independent product/technical reviewers accept the implemented journey. Production acceptance
  is separate from merge. Drafting checks none of these implementation or release boxes.

## 10. Related records and draft review record

- [Source Issue 9 and business-impact/readiness guide](../production-state-consistency-issues.md)
- [D1–D7 consensus — D4 policy parameters and D7 release separation](../production-state-consistency-review-consensus.md)
- [9-A — deterministic STOP, durable reply protection and exhaustion visibility](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [16-A — preserve recorded opt-outs through refresh](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [11-A — current ownership projection, not reassignment notifications](issue-11-a-project-crm-reassignment-immediately.md)
- [17-A — durable lead sends and retained possible-acceptance claims](issue-17-a-durable-outbound-dispatch.md)
- [2-A — original instructions and accepted/applied evidence](issue-2-a-reliable-instruction-delivery.md)
- [4-A — durable operational evidence and scoped history](issue-4-a-retained-operational-evidence.md)
- [15-A — source-owned stopped-work discovery and recovery](issue-15-a-exhausted-background-work-visibility.md)
- [8-A — separate completion and G1 late-reply contract](issue-8-a-completion-lifecycle.md)
- [12-B — separate carrier opt-out handling](issue-12-b-carrier-opt-out-handling-and-fallback.md)
- [13-B — separate consent and channel-fallback policy](issue-13-b-consistent-consent-and-channel-fallback.md)
- [14-B — separate tag-only CRM control](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [17-B — separate uncertain-send accounting](issue-17-b-continue-cadence-after-uncertain-send.md)

Source trace completed against API a761c1b and web 04d4361 on 2026-09-09. It distinguishes source
receipt semantics, three total attempts, classifier versus full-pipeline failures, required result
versus safely applied disposition, transaction-scoped locks versus durable ownership, manager role
versus reporting relationship, and provider acceptance versus delivery. The outbound paused-search
24-hour notice pattern is not evidence of an implemented inbound manager escalation.

Independent technical/source and fresh-reader reviews completed. Findings were checked against
source and the current-versus-proposed boundary: the three-attempt/broad-catch and single-recipient
baselines are current; the deadline and two-role escalation are new B requirements, not existing
capabilities. Reader review clarified that a substantive rejected/unclear outcome durably recorded
before cutoff is excluded from later outage escalation while its review/protection remain. A focused
reader recheck found no material contradiction with the late-result or commit-failure rules.

Documentation validation passed (exit code 0): ten numbered sections, AC-01 through AC-36, R1–R4,
review-only/test-first guards, table/whitespace checks, 61 existing source/test references, 14 local
draft links and 40 index links with applicable heading anchors. The index covers nineteen drafts
and seventeen source issues. The earlier eighteen drafts retain their recorded aggregate SHA-256:
c50057a87931167776fa43e8fd79af399901ce6f7447a8f1d667edda1c9d3d45.

Stakeholder review and R1–R4 remain open. The reviews and documentation checks approve no design,
test boundary, recipient policy or release and do not establish working application behavior.

**Evidence status:** source trace, documentation reviews/checks and proposed test contract only.
No application code, behavioral tests, production access, Jira publication, implementation or
release was performed for this draft. The two application source worktrees remain unchanged.
