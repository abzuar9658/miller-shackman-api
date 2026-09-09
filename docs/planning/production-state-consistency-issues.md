# Production State Consistency Issues

## Purpose

This document records seventeen defects found while investigating a single lead that appeared to be
"actively nurturing" in production for nine days without a single message being sent.

Issues 1–4 were the original findings from that lead. Issues 5–7 were identified immediately
afterwards by tracing the other ways a live lead can lose its running automation. Issues 8–15 came
out of broader audits of inbound processing, completion, enrollment, CRM activity, send-time
consent, and retry queues. Issues 16–17 were added after tracing suppression ownership and every
production outbound dispatch path. All issues were re-verified against current code on 2026-09-03;
claims that did not match the production wiring were corrected rather than preserved as hypotheses.

Each issue is described in business terms first: what goes wrong, why, who is affected, and the
structural fix. None of these are cosmetic, and none should be closed with a one-off data patch —
each one will recur until the underlying rule is corrected.

Investigation date: 2026-09-03. Reference lead: `c6355342-5cf2-4c3a-9b0f-c2dc0c8e4a0a`.

---

## Issue 1 — A lead can be silently parked forever with no visible reason

**The issue.** A paused-search lead was enrolled, shown as actively nurturing, and assigned to an
agent. Behind the scenes the system decided on day one that it could not work out when to contact
the lead, and stopped. It never contacted the lead, never notified anyone, and never recorded that
it had stopped. Nine days passed. The dashboard, the lead record, and the agent's queue all
continued to say the lead was being nurtured.

**Why it happened.** When the system cannot determine a valid next contact date, it produces an
internal outcome called "hold for review". That outcome clears the scheduled next action but leaves
the lead's status untouched, writes no history entry, and creates no review item for a human. The
automation then waits indefinitely for a manual instruction that nobody knows to give, because
nobody was told anything happened.

In this case the trigger was a missing re-engagement date on the lead's paused-search profile
combined with a track configured to hold rather than fall back to a default interval. Those inputs
are legitimate and will occur again; the failure is that the hold is unobservable.

**Consequences.**

- Leads go completely dark while every screen reports healthy activity.
- No operator, manager, or admin has any way to discover the condition; there is no queue, alert,
  count, or filter that surfaces it.
- Recovery requires someone to notice the absence of messages by chance and manually re-trigger the
  lead — which is what happened here, after nine days.
- Reported nurture volumes and engagement rates are overstated, because parked leads are counted as
  in-progress.

**Paths disturbed.** Paused-search nurture scheduling; agent lead detail and assigned-lead lists;
manager pipeline and activity views; the attention/review surface (which should have owned this
case); any reporting that counts leads by workflow status.

**The real fix.** A hold must be a first-class, visible state rather than the absence of a
schedule. Concretely: when scheduling produces a hold, the system must transition the lead into an
explicit review-required state, record the transition and its reason in workflow history, and
create a review item so the lead appears on the operator's attention surface with the reason shown.
"No schedule and no explanation" must not be a representable outcome — if scheduling cannot proceed,
someone is told.

---

## Issue 2 — Pause and resume instructions were reported as delivered but never applied

**The issue.** An operator paused this lead and then resumed it. Both instructions were recorded as
successfully delivered. Neither instruction actually reached the running automation.

**Why it happened.** Operator instructions are queued and then handed to the automation engine. If
the engine no longer has a live copy of that lead's automation, the system starts a fresh one — and
then marks the original instruction as delivered without dispatching it to the new execution. Most
current instructions duplicate state already committed in Postgres, so the new execution will
usually reconstruct the correct business state on its first scheduling activity. The confirmed
defect is false delivery audit and loss of signal-specific wake-up semantics; an unsafe send from
this branch has not been demonstrated because pre-send checks still re-read Postgres.

**Consequences.**

- An operator instruction can be reported as delivered when no signal handler accepted it.
- A restarted execution depends on reconstructing intent indirectly from Postgres instead of applying
  the requested signal, so wake-up behavior can diverge even when contact safety remains intact.
- The delivery log cannot be trusted as evidence of what the automation actually did, which
  undermines audit and incident review.
- Failures are invisible: nothing is retried, flagged, or reported, because the system believes it
  succeeded.

**Paths disturbed.** Manual pause and resume; human handoff and hand-back; any operator or
compliance action that depends on signalling a running automation; the audit trail for those
actions.

**The real fix.** An instruction may only be marked delivered once the automation has actually
accepted it. When a fresh automation has to be started, the pending instruction must be carried into
it and applied, not dropped. If it cannot be applied, the instruction must remain unresolved and be
raised for attention rather than silently marked successful.

---

## Issue 3 — Campaign enrollments never report that they have started

**The issue.** Every live enrollment in production reports status `queued`, including leads that
have been messaging for days. `started_at` is empty on all 78 enrollment records. Enrollments only
ever change status when they finish.

**Why it happened.** Enrollments are created as `queued` and are only updated when the lead reaches
a terminal outcome (completed, closed, suppressed). Nothing writes the intermediate statuses, even
though `active`, `paused`, and `handoff` exist in the data model and are assumed by uniqueness
rules. There is no point in the flow where "this enrollment has begun" is recorded.

**Consequences.**

- 59 leads currently show "queued" while actively being nurtured. This is the most visible symptom
  of the investigated lead and is the most likely thing an operator would report as "inconsistent".
- Queue depth, time-to-start, and throughput cannot be measured, because start time is never
  captured.
- Enrollment status cannot be used to filter, triage, or report, so operators must infer progress
  from workflow state instead — two representations of the same fact, only one of which is
  maintained.
- Uniqueness rules written against the active statuses are not doing the work they were designed to
  do, because those statuses never occur.
- The campaign daily start cap never engages. The cap counts enrollments that started today, using
  `started_at`; because `started_at` is never written, the count is always zero, so a campaign can
  start its entire dormant backlog in a single day. This turns a reporting defect into a
  volume-control failure: deliverability damage and provider rate-limiting are exactly what the cap
  exists to prevent.

**Paths disturbed.** Campaign lists and campaign detail; enrollment queue views; manager pipeline
and response-time metrics; any report or filter keyed on enrollment status or start time.

**The real fix.** Enrollment status must be derived from, and kept in step with, the lead's workflow
status through a single shared mapping — covering active, paused, and handoff, not only terminal
outcomes — and `started_at` must be stamped when the first action for the enrollment is taken.
Alternatively, if enrollment status is not intended to be an independent fact, it should be removed
as a stored field and read from workflow state, so there is one source of truth rather than two.

---

## Issue 4 — Automation history is discarded after 24 hours

**The issue.** Detailed execution history for lead automations is retained for 24 hours. Any
incident older than one day cannot be reconstructed. In this investigation the earliest records were
already gone; the root cause was recoverable only because one later execution happened to survive.

**Why it happened.** The automation engine's retention period is set to 24 hours in production and
was never raised for operational needs.

**Consequences.**

- Incidents reported by agents or clients — typically noticed days later — cannot be investigated
  with confidence.
- Questions such as "why was this lead never contacted" or "was this message actually sent" become
  unanswerable, leaving guesswork in front of the client.
- Slow-burn defects, exactly like Issue 1, are structurally hard to detect and prove.

**Paths disturbed.** All incident investigation, support escalation, and compliance enquiry that
depends on execution history.

**The real fix.** Raise retention to a period that matches the product's own timescales — nurture
cadences run over weeks, so retention must cover weeks, not hours — and ensure the decisions that
matter to the business (why a lead was or was not contacted) are also recorded durably in the
application's own history, so investigation does not depend on the engine's retention at all.

---

## Issue 5 — A hold discovered at send time quietly finishes the automation

**The issue.** Issue 1 parks the automation when a hold is decided at scheduling time. The same
hold, if it is only discovered at the moment a message is about to be sent, does not park. The
automation treats the hold as "there is no next step" and finishes. The lead continues to appear as
actively nurturing. Unlike Issue 1, there is no running automation left waiting for a human
instruction.

**Why it happened.** Immediately before send, paused-search timing is checked again. If that check
now returns a hold, a missing profile, a missing track, or a similar "not ready" result, the send
path reports "no next step" instead of "hold for review". The engine only knows how to wait on a
hold from the scheduler. From the sender, "no next step" means the work is done, so it exits.

*Correction (2026-09-03 review).* The earlier draft also claimed that a timing change which pushes
the next contact into the future makes the engine exit. It does not: that case is reported as
"skipped", and the engine treats "skipped" as "go back and schedule again", so it picks up the new
time. Only the hold / not-ready results are affected.

**Consequences.**

- The lead goes dark with a healthy status, as in Issue 1.
- There is no running automation to receive a later pause, resume, or inbound reply.
- Recovery depends on Issue 7: nothing restarts the engine unless a later instruction happens to be
  queued for the lead, and even then only if the stored status is one the restart path accepts.
- The condition is produced by the same legitimate missing re-engagement-date inputs as Issue 1, so
  it will recur.

**Paths disturbed.** Paused-search send-time revalidation; any later operator pause/resume or inbound
reply for that lead; agent and manager views that still show the lead as in nurture.

**The real fix.** A hold at send time must be the same outcome as a hold at schedule time: wait, make
the hold visible, and do not finish. "Cannot send yet" must not be representable as "nurture is
finished".

---

## Issue 6 — The automation can finish while the lead is still in nurture

**The issue.** Several internal "cannot proceed right now" answers cause the automation to complete
successfully while the lead record remains queued, actively nurturing, or waiting for a reply.
Operators still see an in-progress lead. The engine is already gone.

**Why it happened.** The automation only continues when scheduling produces a next contact time, or
when sending produces a small set of in-progress results. Every other answer is treated as finished.
Those answers are not first turned into a matching lead status. The live cases include: the
paused-search profile or track is missing; campaign configuration has no remaining step; the
workspace record cannot be read at send time; and, for paused-search leads only, the lead was paused
or handed off when the engine next scheduled, which the paused-search scheduler reports as "not
sendable" and the engine reads as "nothing left to do".

*Correction (2026-09-03 review).* On the standard cadence a paused or handed-off lead does not end
the engine: the send step reports "skipped" and the engine schedules again, so it stays alive. And
when a paused-search track reaches its own occurrence, touch, or duration limit, the stored lead
status *is* transitioned (completed, closed, or paused for review) before the engine finishes — that
case is consistent and is not part of this issue.

*Correction (2026-09-03 third review).* After the last standard-cadence send, the engine does **not**
exit. It waits on `_closed` while Postgres stays `waiting_for_response`. That is Issue 8 (missing
completion), not this issue. This issue applies when scheduling later reports "no remaining step"
for a still-live lead — including if Issue 8's waiting engine is restarted — and then exits without
changing stored status.

**Consequences.**

- A paused-search lead that was paused or handed off can be resumed in the product, while the engine
  that should continue the work no longer exists. Recovery then relies on the restart-on-instruction
  path in Issue 7 (which does work for a resumed lead, but drops the instruction — Issue 2).
- Transient missing configuration (profile, track, campaign step, workspace) permanently stops
  nurture even if the data is repaired moments later.
- Without the reconciler described in Issue 7, none of these recover on their own.

**Paths disturbed.** Paused-search and standard cadence scheduling; inbound reply handling after an
engine exit; pause then later resume; any repair of missing profile, track, or campaign
configuration. The last-step wait itself is Issue 8.

**The real fix.** The automation may only finish when the lead's stored status is also finished, or
is explicitly paused with a durable, visible reason. Any other "cannot proceed" result must wait,
reschedule, or transition the lead into a review-required state first — the same rule as Issue 1.
Completing the engine while the lead still looks live must not be a representable outcome.

---

## Issue 7 — A live lead with no running automation is only ever restarted by accident

**The issue.** There is no process that checks whether every live lead still has a running
automation. The only restart path runs as a side effect of delivering a queued instruction (pause,
resume, inbound reply, reschedule): if the engine reports "no such automation", the system starts a
fresh one — but only when the lead's stored status is queued, actively nurturing, waiting for a
reply, or processing a reply, and only when the enrollment record still matches. Otherwise the
instruction is marked as a terminal failure and nothing else happens. A lead whose engine has gone
away and for which no instruction is ever queued is never restarted at all.

*Correction (2026-09-03 review).* The earlier draft stated that the engine refuses to reuse an
automation identity once a run has completed successfully, and that instructions are retried and
then abandoned. Neither is the case: no identity-reuse restriction is configured, so a fresh start
against a completed run is accepted, and on "no such automation" the instruction is either marked
delivered immediately (restart accepted; the instruction itself is discarded — Issue 2) or marked a
terminal failure immediately (stored status not restartable). The gap is the absence of any
independent reconciliation, not a refusal to restart.

**Why it happened.** Restart was built as a fallback inside instruction delivery, not as a
first-class responsibility. Leads that go quiet after Issues 5, 6, or 10 have no trigger that would
even attempt a restart. Issue 8 is different: the engine is usually still waiting, not missing; it
only becomes an Issue 6 exit if that waiting run is later restarted. Enrollment has the same shape
of gap: the enrollment and workflow rows are committed first and the engine is started afterwards;
if that start fails, the failure is reported to the caller but the rows stay committed as "queued",
later enrollment batches skip the lead because it is already enrolled, and nothing independently
starts the missing automation.

**Consequences.**

- Issues 5, 6 and 10 are not just parks; they are sticky. The lead stays live in the product and
  dead in the engine until an unrelated instruction happens to be queued. Issue 8 stays live in both
  until someone restarts it or a close never arrives.
- A lead whose enrollment saved but whose engine never started sits in "queued" indefinitely and is
  invisible to the next enrollment run.
- An inbound reply or a resume for a lead in a non-restartable stored status (paused, handed off,
  human-owned) is marked as a terminal failure with no operator-visible follow-up.
- Investigation looks like "the instruction was delivered" or "terminal failure", not "the engine
  was missing while the lead was still live".

**Paths disturbed.** Restart-on-missing-engine; enrollment start; inbound reply, resume, or pause
for a lead whose engine has finished; any future sweeper or support re-trigger.

**The real fix.** Two rules. First, the engine must not finish or fail while the lead is still live
(Issues 5, 6, 10), and a finished cadence must be recorded as completed rather than left waiting
(Issue 8). Second, a reconciler must periodically find live leads without a running automation —
including enrollments whose start failed — and start one, applying any pending instruction rather
than discarding it (Issue 2). Restart must not depend on a chance inbound or operator action.

---

## Issue 8 — A standard-cadence lead never reaches "completed"

**The issue.** When the last step of a standard campaign cadence has been sent and the lead does not
reply, nothing ever marks the lead's nurture as finished. The lead stays in "waiting for a reply"
forever, the enrollment stays "queued" (Issue 3), and the engine sits idle waiting for a "close"
instruction that no part of the system ever sends. The stored status has a "completed" outcome and a
"completed" history reason, but no code path produces either for a standard cadence.

**Why it happened.** After the final send, the cursor is advanced to "no next step" but the status is
left as waiting-for-reply. Enrollment admission treats every non-finished status — including waiting
for a reply — as already active, so automatic and most manual re-enrollment is refused for the life
of that workflow. The engine, seeing there are no more steps, waits indefinitely for an external
close that was never wired up.

*Correction (2026-09-03 third review).* This is not another "engine finished while the lead stayed
live" exit. After the last send, Temporal waits on `_closed` rather than returning immediately. The
business defect is the missing completion / timeout transition, not a completed engine. If that
waiting engine is later restarted (Issue 7), scheduling reports "no remaining step" and *then* the
engine exits (Issue 6) — still without changing the stored status.

**Consequences.**

- Every lead that finishes a campaign without replying is shown as "Waiting for response"
  indefinitely, to agents and managers alike, with no way to tell it apart from a lead the system is
  genuinely still waiting on.
- Because only one non-finished workflow is permitted per lead, such a lead can **never be enrolled in
  any future campaign**: dormant selection and manual enrollment both refuse it as already active.
  This is the most durable business harm in this document — it silently removes leads from the
  addressable pool.
- Campaign completion, completion rate, and time-to-complete cannot be reported.
- A later inbound reply is routed to an engine that is either idle-waiting or already gone (Issues 6
  and 7).

**Paths disturbed.** Final cadence step; campaign completion reporting; re-enrollment (dormant
selector and manual); lead detail and assigned-lead lists; inbound reply after the last step.

**The real fix.** Finishing the cadence must be an explicit, recorded transition to "completed" in
the same unit of work that records the final send, with the enrollment marked completed alongside it
(Issue 3), and the engine must end because the stored status is finished — not wait for a close that
never comes. Once this exists, the "no remaining step" answers in Issue 6 become impossible for a
live lead.

**Release-volume note.** Completion does not automatically return the lead to dormant selection.
`enrollment_admission` continues to require explicit manual re-entry after `COMPLETED`; only a workflow
ended by enrollment-tag removal may start fresh when that tag is re-added. Fixing Issues 3 and 8 can
therefore restore manual re-enrollment and correct the daily-cap accounting, but it does not itself
create an automatic surge of previously completed leads.

---

## Issue 9 — A lead's "STOP" is only honored if the AI service is available

**The issue.** When a lead replies with an opt-out keyword, the system is supposed to suppress the
lead deterministically, without relying on the AI. In practice the opt-out check runs *after* the AI
classification call. If that call fails for infrastructure reasons — timeout, provider outage, quota,
network — the whole reply fails, is retried three times over roughly ninety seconds, and is then
marked as exhausted. The "STOP" is never applied, no suppression is recorded, the lead's automation is
not paused, nobody is notified, and scheduled messages continue to go out.

**Why it happened.** The keyword override was implemented as a post-processing step on the AI result
rather than as a gate in front of it. The override *does* recover STOP if the AI call returns,
including when classification is rejected for invalid JSON or low confidence: it upgrades that
result to opt-out. The drop happens only when the AI call *raises* (timeout, transport, provider
outage). The inbound worker then retries three times and marks the event exhausted. Suppression
never runs, and no inbound-processed signal is queued. The reply pipeline also does not pause the
lead's automation before attempting classification, so any reply that cannot be classified leaves
the lead in the same state as if they had never replied. After a non-last send the cadence does not
wait for a reply between steps, so later touches remain free to send. After the last step the engine
is only waiting for close (Issue 8), so it will not send another cadence message — but the lead is
still not opted out, so resume or another journey can still text them.

**Consequences.**

- A roughly two-minute AI-provider outage is enough to permanently drop an opt-out. Continuing to
  message a lead who has said "STOP" is a compliance exposure, not a UX defect.
- The same window drops *every* inbound reply: a lead who replied with interest is re-messaged by the
  cadence as if silent.
- The failure is recorded only as a generic "processing failed / exhausted" event with no
  lead-facing or operator-facing surface.
- This contradicts the platform rule that consent, opt-out, and send eligibility are decided by
  explicit application logic, never by the AI.

**Paths disturbed.** Inbound reply processing (SMS and email); suppression; opt-out audit; workflow
pause on reply; the attention/review surface, which should own unclassifiable replies.

**The real fix.** Order of operations must be: (1) record the reply and place a temporary inbound-
processing hold on the lead, (2) apply the deterministic opt-out check and immediately record any
channel suppression, (3) resolve that channel outcome under Issue 13, and (4) ask the AI to classify
only replies that still need classification. An AI failure must leave an unclassified reply held and
visible after the bounded retry window, never silently re-eligible for sends. Exhausted inbound
events must be surfaced to operators.

**Business decision (2026-09-03, approved): opt-out recognition works both ways — hard words are
honoured deterministically without the AI; every other reply is judged by the AI; an AI failure
holds the lead silently and retries for 30 minutes before a human is told.**

What was traced before deciding:

- Order today in `process_inbound_message_event`: store the reply (`inbound_messages` status
  `PENDING`) → call the classifier (`classify_inbound_reply`) → *then* run the hard-word check
  (`_apply_explicit_opt_out_override`) → suppress / transition / CRM note / `inbound_processed`
  signal. Nothing pauses the lead's automation before the classifier is called.
- Hard words are an exact match on the whole message after stripping non-alphanumerics: SMS
  `stop`, `stopall`, `unsubscribe`, `cancel`, `end`, `quit`; email `unsubscribe`. Natural-language
  opt-outs ("please stop texting me") are not hard words and depend on the classifier.
- Three classifier outcomes end differently. Normal answer: correct. Unusable answer (bad JSON twice
  or low confidence → `REJECTED`): handled — conversation `PAUSED`, message `FAILED`, workflow
  paused-for-review, review tag and `paused_for_review` snapshot written to the CRM, and the hard
  word still upgrades the result to opt-out. Call raises (timeout, outage, quota, network): nothing
  is applied; `process_queued_inbound_message_events` retries with `_MAX_ATTEMPTS = 3` and
  `_RETRY_BASE_DELAY = 30s` (≈90 seconds total), then marks the event `EXHAUSTED`. No code in
  `app/interfaces` or `app/application/use_cases` reads `EXHAUSTED`; the reply is invisible.
- Partial backstop: pre-send `LEAD_REPLIED_SINCE_SCHEDULED` (`pre_send_facts.py`) blocks a message
  whose `scheduled_for` is earlier than the newest inbound `received_at`, even if that inbound is
  still `PENDING`. It does not cover any step scheduled after the reply arrived, so the next cadence
  touch sends. The Temporal workflow only blocks sends on the `inbound_processed` signal, which is
  enqueued only after successful processing.

The rule:

1. On any inbound reply, before anything else, the lead's automation is held: no cadence message
   may send while a reply for that lead is unprocessed. The hold is silent — no human is notified —
   because it normally clears within seconds.
2. The hard-word check runs before the classifier. An exact hard-word reply applies the channel's
   suppression immediately (lead flags and CRM note/consent field per Issue 16) with no AI
   involvement. The workflow then follows Issue 13's one rule: the opted-out channel is blocked, the
   other usable channel may continue, and a global do-not-contact blocks both. The classifier may
   still run afterwards for the summary, but its failure cannot undo or delay the suppression.
3. Every other reply is judged by the classifier, which decides whether it is an opt-out, interest,
   not-interested, or unclear. The classifier classifies; the platform applies the outcome.
4. If the classifier call fails, the reply is retried with backoff for up to 30 minutes from
   `received_at`. The lead stays held throughout. If the classifier recovers inside that window the
   reply is processed normally and nobody ever learns there was an outage.
5. Only when the 30-minute window is exhausted does the reply become a visible item: the workflow
   moves to paused-for-review (the existing `REJECTED` path), the reply appears in the attention
   surface, and the assigned agent and their manager are notified. The lead is never silently
   returned to sendable, and an exhausted reply is never dropped.
6. Why 30 minutes: one simple rule — humans are elevated only for real issues. A short AI outage
   resolves on its own and must not generate dashboard noise (Q11); the platform should keep
   retrying rather than sit idle (Q12). The cost is that a non-hard-word reply can wait up to 30
   minutes unseen during a real outage, during which nothing is sent to that lead. The window is one
   constant, changeable later.

---

## Issue 10 — The engine can fail outright while the lead stays live

**The issue.** Issues 5 and 6 cover the engine *finishing* cleanly while the lead stays live. Issue 8
is a missing completion transition, not an engine-exit. The engine can also *fail*: if one of its
scheduling or sending steps errors repeatedly — a persistent database problem, a defect in the send
logic, or an AI drafting call that keeps exceeding the two-minute limit — the engine gives up after
three attempts (`maximum_attempts=3` on both schedule and execute retry policies) and the run ends
in failure. The stored lead status is untouched, no history entry is written, and nobody is
notified. The lead looks healthy and receives nothing.

**Why it happened.** `LeadNurtureWorkflow.run` has no handling around its own step failures: nothing
catches the final failure, records why, or moves the lead into a visible review state. The failure
is only visible inside the engine's own history, which is discarded after 24 hours (Issue 4).

**Consequences.**

- Identical outward symptom to Issue 1 — a dark lead with a healthy status — but with an even
  shorter evidence window.
- A single bad deploy or a slow AI provider can silently strand every lead whose step happened to run
  during the incident, with no list of affected leads afterwards.
- Recovery depends entirely on Issue 7's accidental restart.

**Paths disturbed.** All cadence scheduling and sending; incident response after a deploy or
provider degradation.

**The real fix.** A step that exhausts its retries must be treated as a business outcome, not an
engine crash: record a "nurture blocked — system error" transition and review item so the lead is on
the attention surface with the reason, then either wait for an operator instruction or hand off. The
engine must not end while the stored status is live (same rule as Issue 6). The reconciler in Issue 7
covers whatever slips through.

---

## Issue 11 — A reassigned lead temporarily disappears from agent dashboards

**The issue.** Reassignment is not an automation control: it does not pause nurture and does not
notify the new agent. The required behavior is simpler — the lead must appear under the correct agent
immediately. Today the people webhook temporarily removes the app-level owner mapping, so the lead
disappears from agent-scoped dashboards until the next incremental sync or pre-send refresh.

**Why it happened.** Full CRM sync and pre-send refresh both resolve the CRM assignee to an app user
before saving the lead. The people-webhook path maps and saves the CRM person without running that
same resolution, overwriting the resolved owner ids with `None`.

**Consequences.**

- The lead disappears from the old agent's dashboard but does not yet appear on the new agent's.
- The gap can last until the next incremental sync, configured for five minutes.
- Future drafts already use the new CRM agent's name; that is current behavior, not part of this fix.

**Paths disturbed.** CRM people webhooks; agent-scoped lead lists; assignment visibility.

**Business decision (2026-09-04, approved): no reassignment notification. The requirement is that
the lead appears under the correct agent on the dashboard as soon as the CRM reassigns it.** No
workflow change, no notification.

Against that requirement there is a defect, traced 2026-09-04:

- The agent dashboard scopes leads by `_owner_scope_clause` (`lead_repository.py:851-865`):
  `effective_owner_user_id`, else `assigned_agent_user_id`, else the legacy
  `mapped_custom_fields["assigned_agent_user_id"]`.
- Those two user-id columns are set only by `apply_lead_assignment_resolution` /
  `_resolve_lead_assignment`, which the full CRM sync (`crm_sync.py:289`) and the pre-send refresh
  (`pre_send_crm_refresh.py:154`) both run before upserting.
- The webhook people path does not. `webhook_event_people.py:51-59` maps the fetched FUB person
  (`lead_mapper.py` sets `assigned_agent_crm_id` and `assigned_agent_name` only — the user-id
  fields are left `None`), wraps it in `preserve_app_owned_lead_state` (which carries paused-search
  fields only, `canonical.py:217-241`), and upserts. So the first thing a reassignment webhook does
  is overwrite `assigned_agent_user_id` and `effective_owner_user_id` with `None`.
- Result: from the webhook until the next incremental sync (`crm_sync_incremental_interval_seconds`
  = 300) or the next pre-send refresh on that lead, the lead is scoped to *no* agent — it disappears
  from the old agent's dashboard and does not yet appear on the new agent's. It reappears under the
  new agent when the sync runs. The same wipe happens on every `peopleUpdated` webhook, not only
  reassignments; a sync then restores the value, so the columns flap.

**The real fix.** The webhook people path runs the same assignment resolution as the other two
write paths before it upserts (one resolution, three callers — today it is two). Load the assignment
context once per webhook batch, not per person. With that in place the dashboard is correct on the
webhook itself and the reconciler's `previous_lead` / `current_lead` comparison is finally
meaningful on the webhook path. Test: a `peopleUpdated` reassignment webhook moves the lead from
agent A's scoped list to agent B's in the same request, and a subsequent sync changes nothing.

---

## Issue 12 — A carrier-level opt-out is treated as a generic send failure

**The issue.** When a lead has opted out at the carrier level, the SMS provider rejects the send
with a specific "recipient unsubscribed" error. The system classifies that rejection only by its
HTTP status — a generic client error — and records it as a permanent provider failure. The lead is
never marked as opted out locally.

**Why it happened.** Provider failures are mapped from HTTP status codes alone; the provider's
specific error code is not inspected.

**Consequences.**

- The cadence path pauses after the failure, so it does not automatically continue through every
  later step. The underlying lead contactability is still not corrected.
- The lead's opt-out state in the product does not reflect reality, so an explicit resume, manual
  contact, or later re-enrollment can attempt the unsubscribed number again.
- The failure is available on the lead send-exceptions surface but is not converted into the
  lead-level suppression state used by future eligibility checks.

**Paths disturbed.** SMS dispatch; provider-failure review queue; suppression; re-enrollment
eligibility.

**The real fix.** Map the provider's unsubscribe / blocked-recipient error codes to an explicit
opt-out outcome that records suppression for that channel and stops further sends on that channel,
rather than to a generic permanent failure.

**Business decision (2026-09-04, approved): a carrier-level unsubscribe is an opt-out, with the same
durability as the lead texting STOP, and the step falls back to email when usable.**

Traced: `TwilioSMSProvider.send` (`client.py:56-61`) raises `ProviderSendFailure(classify_http_status(exc.status))`;
`classify_http_status` (`provider_errors.py`) sees only the HTTP status, so Twilio 21610 ("recipient
has unsubscribed", HTTP 400) and 21614 (not a mobile number) both become `PERMANENT`. `TwilioRestException.code`
carries the Twilio error code and is discarded.

The rule:

1. The Twilio adapter inspects `exc.code` before the HTTP status. Codes meaning "this recipient has
   opted out of messages from this sender" (21610; verify the current list against Twilio's error
   reference before implementation) raise a distinct failure the port already has room for — a new
   `ProviderFailureKind.RECIPIENT_OPTED_OUT` — rather than `PERMANENT`. Everything else keeps the
   existing status-based classification. The code list is one constant in the adapter.
2. `send_outbound_message` handles `RECIPIENT_OPTED_OUT` by recording an `sms_opt_out` suppression
   through the same path Issue 9 / Issue 16 use for a platform-observed STOP (durable; not cleared
   by CRM sync), then treating the step as an explicit SMS "no" under Issue 13 rule 3: send on email
   if usable, otherwise `no_usable_channel` hold. The step is completed or held, never
   `provider_failure_exhausted`.
3. No new reason code for contactability. Once the suppression is written, every later check blocks
   SMS via the existing `sms_opted_out` reason, and the send-exceptions surface does not receive an
   entry — this is a consent outcome, not a provider failure.
4. SendGrid: the equivalent is the unsubscribe/bounce group reported on the event webhook, not a
   send-time rejection; it is out of scope for this issue and already handled by email
   unsubscribe suppression where the callback path records it.

---

## Issue 13 — Explicit channel denials are enforced differently across outbound journeys

**The issue.** Current production consent behavior depends on the outbound path. Standard cadence can
block a CRM `DENIED` SMS status while paused-search, AI-reply, and operator paths can send with the
same facts. The approved V1 rule is now recorded: an explicit no blocks that channel everywhere;
unknown consent does not block; and there is no workspace-level A2P approval gate.

**Why it happened.** Standard-cadence sends use the durable queue, whose dispatch-time revalidation
requests strict SMS permission. Paused-search cadence steps, AI conversation replies,
operator-triggered immediate sends, and draft-review approve-and-send dispatch directly against the
weaker check — the cadence executor withholds the durable request repositories for paused-search
steps (`campaign_cadence_execution.py:896-898`), so those sends never see the strict revalidation.
Even strict SMS mode blocks only `DENIED`, not `UNKNOWN`. Email would block unknown permission only
if strict mode were requested, but production send paths request strict mode only for SMS. The
brokerage-level A2P 10DLC `approved` state is not modelled anywhere, so no path can check it.

**Consequences.**

- Whether denied SMS consent blocks a send depends on which path the lead happens to be on: the same
  lead data blocks on the durable standard-cadence path and sends through the direct paths
  (paused-search steps, AI replies, operator send-now, draft approval). The direct sends violate the
  approved channel-denial rule; the inconsistency is itself a defect.
- Unknown-consent leads are texted on every journey. That matches the approved V1 decision; the
  remaining work is to make explicit-denial behavior equally consistent.
- Workspace SMS enablement is effectively "automation is on"; there is no approval gate to review,
  audit, or revoke. The API rule documents state this is intentional for V1.
- The strict email branch's tests give false assurance: they pass against code production never
  runs.

**Paths disturbed.** Standard and paused-search cadence; AI conversation replies; operator send-now;
draft-review approve-and-send; workspace SMS enablement; compliance audit; business-rule documents.

**The real fix.** Implement the approved rule once at the final pre-send point used by every journey,
remove the strict/default split, and reconcile the remaining business-rule documents. Issue 17 also
routes the direct journeys through durable dispatch, but consent enforcement must be correct at the
final send boundary regardless of which journey invoked it.

**Business decision (2026-09-04, approved): the only consent-based blocker is an explicit "no" from
the lead for a specific channel. That channel is blocked on every path; the same message goes out on
the other channel if one is usable. Unknown consent never blocks. No workspace-level SMS approval
gate in V1.**

What was traced before deciding:

- `evaluate_contactability` (`app/domain/compliance/contactability.py`) has two modes. Default:
  blocks only on `sms_opted_out` / `email_unsubscribed` suppression, `do_not_contact`, or a missing
  destination; the consent status field is ignored. Strict (`require_explicit_automated_permission`):
  additionally blocks SMS on `DENIED` (not `UNKNOWN`) and email on `DENIED`/`UNKNOWN`/`None`.
- Ten callers. Strict is requested by exactly one: `revalidate_outbound_send_request.py:277`, for SMS
  only, on the durable-queue cadence path. The final pre-send check every path passes through
  (`send_outbound_message.py:283`), AI conversation replies
  (`process_inbound_message_event.py:1755`), planning, enrollment, resume, and the leads API all use
  default mode. Result: `DENIED` blocks a cadence step but not an AI reply or operator send-now.
- Consent status comes only from FUB custom fields (`sms_permission_status`,
  `smsPermissionStatus`, `sms_consent_status`; `email_permission_status`,
  `emailPermissionStatus`) via `lead_mapper.py:45-53, 262-297`. No native FUB opt-out field is read.
  A workspace without the custom field yields `UNKNOWN` for every lead.
- No workspace-level SMS approval / A2P 10DLC state exists in domain, persistence, or settings.
  `enabled_channels` is derived from the cadence step's channel
  (`campaign_cadence_execution.py:723`), not from any workspace setting.
- Earlier rule documents disagreed about explicit denial, unknown consent, and workspace approval.
  The approved decision below supersedes both versions; implementation must update the remaining
  stale documentation at the same time as the code.

The rule:

1. An explicit lead "no" for a channel blocks that channel. "Explicit" means any of: a platform-
   observed opt-out (hard word or classifier-detected, per Issues 9 and 16); a CRM
   `sms_opted_out` / `email_unsubscribed` flag; a CRM consent status of `DENIED` for that channel.
   `do_not_contact` blocks both channels, as today.
2. The block is enforced identically on every path — cadence, AI reply, operator send-now,
   draft-review approve-and-send — at the single pre-send point (`send_outbound_message`). The
   `require_explicit_automated_permission` split is removed; there is one mode.
3. When a channel is blocked by an explicit "no" and the other channel is usable (destination
   present, not itself blocked), the same message is delivered on the other channel. The message
   content is re-rendered for that channel; the cadence step is considered completed, not skipped.
   Channel fallback is new behaviour (the cadence does not switch a step's channel today) and is
   scoped with this issue. If neither channel is usable, the step cannot be delivered and the lead
   becomes a needs-a-human hold under Q11.
   Fallback is for consent blocks only (decided 2026-09-04, Q17). A `PERMANENT` provider rejection
   on the standard cadence keeps today's behaviour — `_pause_after_block` with
   `provider_failure_exhausted` (`campaign_cadence_execution.py:1101-1127`), i.e. the lead is held
   for review — and is not re-routed to the other channel. The paused-search journey's per-step
   `fallback_channel` (`provider_fallback_allowed`, `provider_fallback.py`) is unchanged; it is a
   track configuration the operator opted into, not a general rule. The single carve-out is a
   carrier-level unsubscribe, which is a consent block and follows Issue 12.
4. `UNKNOWN` consent never blocks either channel. A brokerage-authorised destination in the
   brokerage's own CRM is the V1 consent basis, exactly as when the brokerage's own agents text or
   email. Beyond an explicit "no", there are no consent-based blockers to outreach.
5. No workspace-level SMS approval gate in V1. Any remaining documentation that requires one, or
   says explicit denied consent does not block, is corrected to this rule so there is one answer.

---

## Issue 14 — Routine CRM changes pause the AI, and nobody can tell why

**The issue.** Current code treats notes, logged activity, tag additions, and stage/status changes as
automatic pause commands. That conflicts with the approved operating model: the enrollment tag is
the only CRM-side on/off switch. These routine events can therefore stop nurture even though the tag
still says it should run, often under a generic reason that nobody understands.

**Why it happened.** The inbound CRM mapping classifies tag creation and stage changes as "human
activity" unconditionally; nothing checks whether a person did the work or an automation did. The
same webhook that enrolls a lead on a tag also runs the pause path for that tag, so the two rules
fight: for a lead that already has a running automation, re-adding an enrollment tag — or any
unrelated tag — pauses the very nurture the operator was trying to start or keep running.

**Consequences.**

- Leads silently stop nurturing because an unrelated tag or an automation-driven stage change paused
  them; agents see "paused" with a reason that does not explain what actually happened.
- Automation coverage quietly shrinks over time. Externally this looks like "the AI is flaky", and
  each case needs a manual resume from someone who may never know it is needed.
- The pause log cannot be trusted as evidence that an operator deliberately turned nurture off.
- *The platform can pause itself (code-side verified 2026-09-03; vendor documentation reviewed
  2026-09-03).* When an inbound message arrives outside the CRM, the platform can write a summary note
  back to the CRM; on review or handoff it can write a review or handoff tag. The CRM webhook
  handlers for note creation and tag creation have no origin check: a note maps to "note added" and
  a tag to "activity created", and both pause the workflow and stamp the lead's
  last-human-activity time.
  Transitioning *into* paused is legal from every non-terminal, non-human-owned state, including
  human-handoff — so the platform's own handoff tag can demote a handed-off lead to plain "paused",
  overwriting the handoff pause reason and changing who is allowed to resume it.
  The Follow Up Boss webhooks guide describes `notesCreated` and `peopleTagsCreated` as firing on the
  resource event itself, with no exemption for API-originated writes; the tag event is documented as
  firing "regardless of whether a tag was previously removed and re-added". The documentation gives
  no basis for assuming the platform's own writes are excluded, so implementation must treat the
  echo as real. The two feedback paths and what the code currently has to work with:
  - **Tags.** The `peopleTagsCreated` payload carries the added tag names in `data.tags`; the
    handler currently discards `data` and reads only `eventId`, `event`, `eventCreated`, and `uri`.
    The people-path activity event is built with `actor_agent_id=None`, so an author filter is not
    possible on this path — the platform must recognise its own tags by name (the workspace's
    configured `crm_review_tag` / `crm_handoff_tag`) from `data.tags`.
  - **Notes.** The fetched note resource carries `createdBy` / `updatedBy` (display names) and the
    mapper reads `userId`. `add_note` discards the CRM response, so the platform does not record the
    ids of the notes it writes. Recognising its own notes therefore needs either a stable marker
    the platform controls (subject/body) or author matching against the integration's own CRM
    user. The pre-send CRM refresh treats any agent-attributed activity newer than the message as
    recent human activity, so the same attribution that lets a platform note pass the webhook
    filter can also trip the pre-send veto.
  The remaining live-CRM check is narrow: confirm which author fields (`userId`, `createdBy`) Follow
  Up Boss populates on an API-written note, so the note filter is built on the field that is
  actually present. It is a design input for the fix, not a gate on whether the fix is needed.

**Paths disturbed.** CRM tag and stage webhooks; tag-based enrollment; the pause/resume queue; agent
lead views; the send-time recent-human-activity veto.

**The real fix (superseded 2026-09-04 — see business decision below).** The original proposal was
to keep every CRM-event pause and add origin filtering (human vs automation vs the platform's own
writes). The approved decision replaces that with a single, explicit control and makes the origin
filtering unnecessary: if CRM notes, tags, and stage changes do not pause, the echo of the platform's
own notes and tags is harmless.

**Business decision (2026-09-04, approved): the enrollment tag is the on/off switch. Removing it
ends the automation; re-adding it starts a fresh enrollment. No other CRM change pauses or holds the
AI. While the tag is on the lead the track step runs as configured, regardless of agent activity in
the CRM. (Revised later the same day: the send-time recent-human-activity hold originally kept as
rule 5 is withdrawn — see rule 5 below.)**

What was traced before deciding:

- `process_crm_human_activity_event.py` transitions the workflow to `PAUSED` and stamps
  `lead.last_agent_activity_at` for: note created (`webhook_event_mappers.py:54`), any tag added
  (`webhook_event_people.py:148`), stage changed (`:138`), status changed, and any FUB text message
  or call logged (`webhook_event_mappers.py:84-121` → `activity_created`), with no direction or
  author check. Lead reassignment is mapped (`lead_reassigned`) but `_meaningful_human_activity_kind`
  (`:265-290`) never matches it, so it is a no-op today.
- Tag removal does nothing today. `_PEOPLE_EVENTS` (`webhook_event_handler.py:38-46`) does not
  include `peopleTagsDeleted`, and neither the pre-send CRM refresh nor `revalidate_outbound_send_request`
  checks that the enrollment tag is still present.
- The send-time veto `RECENT_HUMAN_ACTIVITY` (`pre_send_crm_refresh.py:189-205`) fires when either
  (a) `last_agent_activity_at` moved past the message's `created_at` during the refresh, or (b) any
  fetched CRM activity with a non-null `agent_id` (FUB `userId`) is newer than `created_at`. Source
  (a) is written only by the pause path above (`process_crm_human_activity_event.py:187`); source
  (b) is independent of it. When the veto fires the cadence calls `_pause_after_block`
  (`campaign_cadence_execution.py:1101-1127`) → `PAUSED` with `pause_reason="cadence_step_blocked"`,
  the same generic reason used for every other non-timing block, and nobody is notified.
- The platform publishes its own outbound SMS into FUB via Inbox Apps with `isAutomation: true` and
  `owner.userId` = the assigned agent (`client.py:288-323`). Any veto built on FUB activity
  attribution must exclude these, or the platform's own sends trip the veto.
- Automatic re-enrollment after a terminal workflow state is blocked
  (`enrollment_admission.py:41-49`, `TERMINAL_REQUIRES_MANUAL_ENROLLMENT`); track reassignment is
  the only sanctioned exception today.

The rule:

1. **Tag removal ends the automation.** When the enrollment tag is removed from a lead with a
   non-terminal workflow, the workflow is transitioned to a terminal state with a specific reason
   (`enrollment_tag_removed`). It is not `PAUSED`; there is nothing to resume. Detection is
   two-layered so a missed webhook cannot leave a de-tagged lead sending: subscribe to
   `peopleTagsDeleted` (new), and check tag presence in the pre-send CRM refresh on every path —
   a missing enrollment tag at send time ends the workflow the same way.
2. **Re-adding the tag starts a fresh enrollment.** Nurture does not resume from where it stopped;
   the lead enters as a new enrollment at step one. `enrollment_admission` carves out "previous
   workflow ended by `enrollment_tag_removed`" from the terminal-requires-manual-enrollment block.
   Workflows ended for any other terminal reason (completed, suppressed, closed by handoff) keep the
   existing rule.
3. **Every lead has the tag, however it was enrolled.** Dormancy enrollment (60+ days) applies the
   workspace's enrollment tag to the lead in the CRM as part of enrollment, so the same switch works
   for every lead. Enrollment is not confirmed until the tag write succeeds; a failed tag write is
   a needs-a-human hold, not a silently untagged running workflow.
4. **No other CRM change pauses the AI.** Note created, any other tag added, stage or status
   changed, reassignment, and calls/texts logged in the CRM do not transition the workflow. The
   `crm_note_added` / `crm_activity_created` / `crm_stage_changed` / `crm_status_changed` pause
   paths are removed. The enrollment tag being re-added to an already-running lead is a no-op.
   The platform's own notes and tags echoing back are therefore harmless; no author/tag-name
   filtering is built.
5. **No send-time human-activity check.** (Revised 2026-09-04, Q18.) The `RECENT_HUMAN_ACTIVITY`
   veto in `pre_send_crm_refresh.py:189-205` is removed, along with both of its inputs: the
   `last_agent_activity_at` comparison (source (a), which loses its only writer under rule 4
   anyway) and the fetched-activity `agent_id` scan (source (b)). An agent who texts or calls a lead
   while the tag is present does not stop the next automated step; an agent who wants the AI off
   removes the tag. This also retires the open attribution question — how to exclude the platform's
   own Inbox App messages from the activity scan — because nothing scans activities for this
   purpose any more. The pre-send CRM refresh keeps its other jobs: refreshing the lead record,
   re-running assignment resolution, and (new under rule 1) checking tag presence.
   What still stops a send at that point is unchanged and unrelated to agent activity: a lead reply
   since scheduling, an opt-out, handoff/human-owned state, tag removal, timing, frequency.
6. **Human-handoff is untouched.** Nothing in this rule transitions a lead in `HUMAN_HANDOFF` or
   `HUMAN_OWNED`; the handoff pause reason is never overwritten (as already required above).

Paths changed: `_PEOPLE_EVENTS` and the people-event mapper (add `peopleTagsDeleted`, drop the
tag/stage pause mapping); `process_crm_human_activity_event` (pause kinds removed — with rules 4
and 5 together every kind it handled is gone, so the use case is a deletion candidate; the
`last_agent_activity_at` stamping it performed is retained or relocated — four readers survive, see
Issue 16); pre-send CRM refresh (tag-presence check added,
`RECENT_HUMAN_ACTIVITY` veto and its `crm_activity_source.get_recent_activity` fetch removed);
`enrollment_admission` (tag-removed carve-out); dormancy enrollment (tag write).
`docs/business-rules/04-pre-send-safety-checks.md` and the "human activity always pauses AI"
statements in `CLAUDE.md` are corrected to this rule.

**Rollout requirement.** This change needs agent-facing communication, not only code. Agents must be
told that notes, calls, texts, stage changes, reassignment, and unrelated tags no longer stop AI; they
must remove the enrollment tag to end it. Brokerages must also be told that dormancy enrollment writes
that tag into their CRM. The attention dashboard may initially show more problems because previously
invisible stalls become visible; that is improved detection, not a new failure spike.

---

## Issue 15 — Work that fails permanently disappears from every queue

**The issue.** When background work fails enough times to be given up on, it surfaces nowhere.
Inbound CRM events that fail processing three times are marked exhausted and never shown to anyone.
Instructions to the automation engine that cannot be delivered are marked as terminal failures and
never shown to anyone. Events waiting to be published to the internal event bus are simply never
tried again after ten attempts — they remain "failed" forever, with no dead-letter state, no queue,
and no alert.

**Why it happened.** Each of the three retry mechanisms stops retrying, but none of them has a
"this is now dead — tell someone" step, and no operator surface queries for these terminal states.

*Correction (2026-09-03 second review).* An earlier draft stated that the attention surface only
shows items created by successful notification sends. That is not what the code does: review items
are created from the classification outcome regardless of whether the notification succeeded, so a
failed notification produces a review item that is queryable but unannounced. The gap in this issue
is narrower and specific — the three terminal queue states (exhausted inbound events, terminal
signal failures, failed outbox events) have no reader at all — and the fix should not touch review
creation.

**Consequences.**

- A poison CRM event — for example a reply the classifier repeatedly cannot process — is retried,
  exhausted, and forgotten; the lead's automation waits for a signal that will never arrive. This is
  Issue 1's invisible stall produced by infrastructure rather than scheduling.
- A publish failure that keeps recurring (broker down, malformed payload) leaves events stranded in
  "failed" with nothing watching them; downstream consumers simply go quiet.
- Terminal instruction failures left over from Issue 2 are visible only in logs.
- Every other issue in this document is harder to detect because the failure queues themselves are
  blind.

**Paths disturbed.** Inbound event processing; the automation-instruction outbox; the event outbox;
the attention/review surface; incident response.

**The real fix.** Every retry mechanism needs a terminal state that is a first-class, queryable
outcome — exhausted, dead-lettered — and the attention surface must list those items with their
reasons and ages. "Failed and nobody can see it" must not be a representable end state for any
queue.

---

## Issue 16 — A CRM refresh can erase an opt-out or do-not-contact decision

**The issue.** Provider webhooks correctly record SMS opt-outs, email unsubscribes, and do-not-contact
evidence on the canonical lead. A later Follow Up Boss person snapshot, full sync, or immediate
pre-send refresh can replace those stronger facts with absent or stale CRM values.

**Why it happened.** CRM snapshots replace the canonical lead after calling
`preserve_app_owned_lead_state()`. That merge preserves only paused-search fields. It does not
preserve provider-originated suppression, permission evidence, or do-not-contact state. The same
merge rule is used by people webhooks, full CRM sync, and pre-send refresh.

**Consequences.**

- The current workflow will usually remain paused or suppressed, but the lead itself can become
  falsely contactable.
- An explicit resume, a later enrollment, or a different outbound journey can then bypass the
  original provider opt-out.
- The next CRM refresh can undo a correct suppression decision without any audit event explaining
  the reversal.

**Paths disturbed.** Provider suppression webhooks; Follow Up Boss people webhooks and full sync;
immediate pre-send CRM refresh; resume; enrollment eligibility; every future outbound journey.

**The real fix.** Give provider suppression and consent evidence a durable, monotonic source of truth
that a CRM snapshot cannot erase. Merge CRM data without clearing stronger app-observed suppression
evidence. Reconstruct affected production lead state from suppression events and provider callbacks
before sends are re-enabled. Add regression tests for every refresh path. The monotonic merge keeps
`last_agent_activity_at` (newer wins): Issue 14 removes the field's only writer, but four live
readers remain (`lead_resume.py:363`, `pre_send_crm_refresh.py:197`, `lead_state_classification.py:439`,
`leads.py:1656` / `schemas/leads.py:214`), so the field must be preserved and its writer disposition
(retain a narrow stamping path vs. reader migration + removal) is a separate, tracked decision.

*Recovery inputs verified (2026-09-03).* Every suppression event the platform has processed is
durably stored: `process_contact_suppression_event` writes an `external_events` row carrying the
source provider, a suppression-specific `event_type`, `crm_lead_id`, the resolved `lead_id`, and the
redacted payload, before applying the suppression to the lead. Provider delivery callbacks are stored
in `provider_message_events`. Reconstruction is therefore a replay over those two tables, not a
best-effort guess. Two details for whoever writes the script: events that arrived before the lead
existed are stored with status `IGNORED` and reason `lead_not_found` and should be re-applied if the
lead now exists; and the reconstruction must be monotonic (a stored opt-out re-asserts suppression,
it never clears one).

**Business decision (2026-09-03, approved): an opt-out the lead gives the platform is durable on
its own — the CRM copy never clears it.**

What was traced before deciding:

- Opt-outs reach the platform two ways. (A) The lead replies with a hard word (`STOP`, `STOPALL`,
  `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`; email: `UNSUBSCRIBE`) or the classifier marks the reply as
  an opt-out: the lead record is marked opted out and the workflow goes to the terminal
  `SUPPRESSED` state, so automatic re-enrollment is blocked and only manual enrollment can restart
  it. (B) The provider reports it (Twilio unsubscribe, SendGrid unsubscribe): the lead record is
  marked the same way, but the workflow goes to `PAUSED` when the other channel is still usable and
  to `SUPPRESSED` only when neither is (`process_contact_suppression_event._target_workflow_state`).
- The platform never writes the opt-out into the CRM. The only CRM write is the optional snapshot
  status custom field (`"suppressed"`), which the mapper does not read as consent.
- The CRM fields the mapper reads for consent (`sms_opted_out`, `email_unsubscribed`,
  `do_not_contact`, `sms_permission_status`, `email_permission_status`) are workspace custom fields,
  not native Follow Up Boss fields. They can be written with the existing `update_custom_fields`
  client method; no new CRM capability is needed.
- All four refresh paths (full sync, person webhook, pre-send refresh, on-demand refresh) rebuild
  consent from the CRM payload and `preserve_app_owned_lead_state` carries only paused-search fields
  forward, so every refresh resets the lead to "contactable" and drops the evidence from the record.
  The STOP survives only in `inbound_messages` / `external_events`, which nothing reads at send time.
- Concrete exposure today: path (B) with an email present → `PAUSED` → human resumes → pre-send
  refresh wipes the opt-out → SMS is sent. Twilio rejects it (error 21610) only if the STOP was sent
  to the same Twilio number. Email unsubscribes have no carrier backstop at all. Path (A) is safe
  only because the workflow is terminal; the lead record still forgets the opt-out, so a manual
  re-enrollment would send.

The rule:

1. An opt-out observed by the platform (hard word, classified reply, or provider callback) is
   recorded on the lead as a platform-owned fact, per channel (`sms_opted_out`,
   `email_unsubscribed`) or global (`do_not_contact`), with its evidence.
2. No CRM refresh path may clear a platform-observed opt-out or its evidence. The merge is monotonic:
   the CRM may add a suppression (an agent set do-not-contact in the CRM) but never remove one the
   platform observed.
3. A platform-observed opt-out is lifted only by (a) the lead themselves (START / re-subscribe,
   delivered through the same inbound or provider path) or (b) a permitted human clearing it in the
   platform with a recorded actor and reason. A change to the CRM custom field is neither of these
   and must not clear it.
   This deliberately removes any current agent habit of lifting an opt-out by editing only the CRM
   custom field; that capability loss is accepted in favor of an auditable consent history.
4. The CRM is informed as a courtesy so agents see it in their own tool: on opt-out the platform
   writes a CRM note (what the lead asked, channel, timestamp) and sets the matching CRM consent
   custom field when the workspace has one configured. Failure to write either is logged and
   retried; it does not block the suppression itself, which is already applied.
5. Rejected alternative (B): make the CRM the single source of truth by writing the opt-out there
   and letting refreshes carry it back. Rejected because a bulk import, mis-click, or missing custom
   field would silently re-enable outreach to someone who said stop, with no record of who did it.

Issue 13 resolves the earlier channel-outcome question: a channel-specific opt-out blocks that
channel and uses the other channel when usable. A do-not-contact decision blocks both. The source of
the opt-out — hard word, classifier, provider callback, or carrier rejection — does not change that
business outcome.

---

## Issue 17 — Some outbound journeys can send twice after a process crash

**The issue.** Standard-cadence steps persist a durable outbound request before provider I/O.
Paused-search cadence steps, AI continuation after an inbound reply, deferred operator sends, and
rejected-draft approval sends call Twilio or SendGrid directly instead.

**Why it happened.** The direct paths rely on a database commit immediately before or after provider
dispatch rather than the durable claim, commit, revalidate, and dispatch lifecycle. The inbound
worker commits its event only after AI continuation returns. Twilio does not consume the
application's idempotency key as a provider-side deduplication key.

*Mechanics verified (2026-09-03).* AI continuation — including the provider call — runs inside
`process_inbound_message_event`, which the inbound worker executes as one unit of work per claimed
event and commits only when the processor returns. Any exception raised after the provider has
accepted the message (a later CRM write, a repository save, a notification) rolls that unit of work
back, records the event as a retryable failure, and retries it up to three times; each retry can
send again. The window is therefore not limited to a process crash. On the provider side, Twilio
HTTP errors are classified by status (5xx → uncertain, and those do enter reconciliation); it is the
non-HTTP transport exceptions (timeouts, connection errors) that are tagged `UNCERTAIN` but raised
with `reconcile_as_uncertain=False`, so they are persisted as ordinary failed sends.

**Consequences.**

- If the provider accepts a message and the process dies — or any later step in the same unit of
  work raises — before final database state is committed, retry or operator resubmission can send
  the same message again.
- Non-HTTP Twilio transport exceptions are tagged `UNCERTAIN` internally but persisted as ordinary
  failed sends instead of entering uncertain-delivery reconciliation.
- Duplicate prevention depends on the application process surviving the precise interval in which
  the external side effect has happened but its outcome has not been committed.

**Paths disturbed.** Paused-search cadence steps; inbound AI continuation; deferred "send now";
rejected-draft approval; provider failure reconciliation; outbound-message audit.

**The real fix.** Route every production outbound journey through the durable outbound dispatcher.
Persist and commit intent before provider I/O, and reconcile uncertain provider outcomes rather than
converting them to ordinary failure. Add kill-after-provider-acceptance tests for paused-search,
inbound AI continuation, and operator actions. Provider-specific deduplication must be verified
rather than inferred from the internal idempotency key.

**Business decision (2026-09-04, approved): an uncertain send never pauses the lead. The cadence
continues to the next step on the configured track and schedule as if the step had been sent.
Reconciliation of the uncertain message runs in the background and only corrects the record.**

What was traced before deciding:

- `UNCERTAIN` is produced when the provider call fails ambiguously (`send_outbound_message.py:640-693`):
  the message is saved with `status=UNCERTAIN`, `provider_message_id=None`, and — when the send has a
  workflow and a Temporal id — an `OutboundSendReconciliation` row is created in `PENDING`.
- The cadence then treats it like a block: `_pause_after_block` (`campaign_cadence_execution.py:1101-1127`)
  transitions the Postgres workflow to `PAUSED` with `pause_reason="cadence_step_blocked"`, and the
  Temporal workflow enters `_wait_for_uncertain_resolution` (`lead_nurture.py:527-571`): a 24-hour
  `wait_condition` on `_send_blocked`. AI continuation does the same with
  `pause_reason="ai_continuation_send_uncertain"` (`continue_ai_conversation_after_inbound.py:474`).
- A later provider callback resolves the reconciliation (`process_provider_delivery_callback.py:186-230`):
  `CONFIRMED` rewrites the message to `SENT`, `FAILED` to `FAILED`, and a `BLOCKED_REVIEW_COMPLETED`
  Temporal signal is queued (`:237-245`, `:322-332`). **The callback never transitions the Postgres
  workflow out of `PAUSED`.** Temporal unblocks and schedules the next step, but
  `execute_cadence_step` refuses to send from `PAUSED` (`campaign_cadence_execution.py:506-519`,
  `SKIPPED`), so a lead whose uncertain send was later confirmed still goes dark. This is one of the
  concrete paths behind Issues 1 and 5.
- If no callback arrives within 24 hours, `timeout_uncertain_outbound_send` marks the reconciliation
  `TIMED_OUT` (`timeout_uncertain_outbound_send.py`) and the Temporal workflow waits again with no
  timeout. Nothing notifies anyone and the Postgres workflow stays `PAUSED`.
- Duplicate protection for a retry of the *same* step is the idempotency key
  (workflow id + cadence step id + channel + message version); the provider's acceptance of an
  uncertain call cannot be confirmed from the application side without a callback.

The rule:

1. **Uncertain is treated as sent for cadence purposes.** On `UNCERTAIN`, the cadence advances the
   workflow exactly as it does after a confirmed send: same state transition
   (`ACTIVE_NURTURE` → `WAITING_FOR_RESPONSE` or the next scheduled step, per the track's
   configuration), same scheduling of the next step, same logical-touch accounting. The
   `_pause_after_block` call for `UNCERTAIN` is removed on every path — standard cadence,
   paused-search recurring, and AI continuation — and `_wait_for_uncertain_resolution` is removed
   from the Temporal workflow. The 24-hour hold and the `TIMED_OUT` wait no longer exist.
2. **The uncertain step is not re-sent.** The idempotency key for that step stays claimed by the
   uncertain message; nothing retries the same content. The lead receives either the uncertain
   message (if the provider did deliver it) or nothing for that step — never two copies, and never
   a later duplicate of it.
3. **Reconciliation only corrects the record.** The `OutboundSendReconciliation` row is still
   created and a provider callback still resolves it to `CONFIRMED` (message → `SENT`) or `FAILED`
   (message → `FAILED`), so the conversation history and outbound audit are eventually correct.
   Resolution has no workflow side effect: no Temporal signal is queued and no state transition is
   made. The `provider_confirmation_timeout` activity is replaced by a background sweep that marks
   long-pending reconciliations `TIMED_OUT` for reporting only.
4. **Failure of the uncertain message is not a hold either.** If the callback later says the
   message failed, the lead has already moved on; the next step goes out on its own schedule. The
   failed message is recorded and visible on the conversation timeline. Only an explicit rejection
   (consent, suppression, no usable channel) or an exhausted hard failure at send time — never an
   ambiguous provider outcome — produces a hold.
5. **Non-HTTP transport errors are classified as uncertain**, consistent with the "reconcile
   rather than convert to failure" fix above: they enter reconciliation and, under rule 1, the
   cadence continues.

Paths changed: `campaign_cadence_execution` (`UNCERTAIN` routed to `advance_workflow_after_outbound_send`
/ `advance_paused_search_workflow_after_outbound_send` instead of `_pause_after_block`);
`continue_ai_conversation_after_inbound` (no pause for `UNCERTAIN`); `lead_nurture.py`
(`_wait_for_uncertain_resolution`, `timeout-uncertain-*` activities removed);
`process_provider_delivery_callback` (drop the `BLOCKED_REVIEW_COMPLETED` signal on reconciliation;
keep message/occurrence correction); `timeout_uncertain_outbound_send` (repurposed as a reporting
sweep). The trade-off is explicit and accepted: cadence momentum is preferred over the possibility
that a lead receives the uncertain message and the next step closer together than the track
intended.

---

## Suggested order of work

1. **Issue 16** — a correct opt-out can be erased by the next CRM refresh. Fix and reconstruct
   production suppression state before automated sends are re-enabled.
2. **Issue 9** — "STOP" can be dropped by an AI outage and sends continue. Compliance exposure;
   smallest fix.
3. **Issue 14 and Issue 11** — decided 2026-09-04: the enrollment tag is the only on/off switch
   (removal ends, re-add starts fresh); no other CRM change pauses or holds; the send-time
   recent-activity veto is removed outright. No author/note filter is built, so the live-CRM
   author-field and Inbox-App attribution checks are no longer needed. Issue 11 no longer shares a
   resume path with this — its remaining fix is the webhook people path running assignment
   resolution so the dashboard shows the lead under the right agent immediately.
4. **Issue 13** — decided 2026-09-04: an explicit "no" for a channel blocks that channel on every
   path and the same message goes out on the other channel; unknown consent never blocks; no
   workspace-level SMS approval gate. Implement at the single pre-send point.
5. **Issue 17** — the direct journeys (paused-search steps, AI continuation, deferred operator
   sends, draft approvals) have a provider-accepted/database-uncommitted duplicate-send window, and
   any exception later in the same unit of work triggers a retry that sends again. Unify all journeys behind durable dispatch; this also gives Issue 13 its single
   enforcement point. Decided 2026-09-04: an uncertain send never pauses the lead — the cadence
   continues and reconciliation only corrects the record.
6. **Issue 1** — leads go dark and nobody finds out. Highest visible business impact.
7. **Issue 8** — cadence completion never recorded; permanently blocks re-enrollment. Fix together
   with Issue 3, which shares the root cause (and whose fix also restores the daily start cap).
8. **Issue 5** — the same hold as Issue 1, but the engine exits, so the lead cannot be woken later.
9. **Issue 7** — reconciler for live leads without a running engine (including failed enrollment
   starts). Makes Issues 5, 6 and 10 recoverable and closes the gap under Issue 2. Issue 8 is
   recovered by recording completion, not by restarting a still-waiting engine.
10. **Issue 6** and **Issue 10** — remaining ways the engine ends while the lead stays live.
11. **Issue 2** — operator controls are falsely reported as delivered; fix with the reconciler work.
12. **Issue 12** — decided 2026-09-04: carrier unsubscribe (Twilio error code, not HTTP status) is
    recorded as a durable `sms_opt_out` suppression and the step falls back to email under Issue 13;
    all other permanent provider failures keep holding for review (Q17). Depends on Issue 13's
    fallback and Issue 16's durable-suppression write.
13. **Issue 15** — failed work disappears from every queue. The early-warning system for everything
    above; cheap relative to its diagnostic value, and it is what turns the next defect from
    "discovered by a client" into "seen on a dashboard".
14. **Issue 4** — enables everything above to be diagnosed in future.

---

## Implementation readiness (2026-09-04)

This list is complete enough to start implementing. All seventeen issues are grounded in current
code. Remaining unknowns are scoped and do not block the first fixes.

### Must fix before automated sends stay on

These change who gets contacted, or whether a contacted lead can ever be contacted again:

- **Issue 16** — a later CRM snapshot can erase opt-out / DNC evidence.
- **Issue 9** — keyword STOP is applied only after the AI call returns; an AI *raise* drops it.
- **Issue 13** — product decision recorded 2026-09-04 (see Issue 13); implement against it.
- **Issue 8** — finished cadences stay non-terminal and permanently block re-enrollment.
- **Issue 1 / 5 / 6 / 10** — live lead, no progressing automation, no operator-visible reason.
- **Issue 17** — direct sends (paused-search steps, AI continuation, operator send-now, draft
  approval) can double-send after a crash or after any later exception in the same unit of work.
- **Issue 12** — carrier unsubscribe is a generic failure, so later journeys can retry the number.
- **Issue 14** — the platform's own notes and tags pause its own conversations and can demote a
  handoff. Decision recorded 2026-09-04: only enrollment-tag removal stops the AI; nothing else
  pauses; the self-pause disappears with the pause paths rather than through a filter.

### Must fix for operator trust, but not a send-safety block

- **Issue 3** — enrollment status/`started_at` never leave `queued`; daily start cap is inert. Fix
  with Issue 8.
- **Issue 11** — people webhooks temporarily remove the app owner mapping, so reassigned leads can
  disappear from both agents' scoped dashboards until the next sync.
- **Issue 2 + 7** — false delivery audit, and no independent restart of live leads with a missing
  engine.
- **Issue 15** — exhausted inbound events, terminal signals, and failed outbox rows have no reader.
- **Issue 4** — 24-hour Temporal history. Raise after the send-safety fixes, not instead of them.

### Can wait / do not "fix" by guessing

- Cosmetic dashboard copy, extra abstractions, or a generic rules engine.
- (Resolved 2026-09-04) Issue 13 implementation was gated on a product decision, and the Issue 14
  note filter on a live-CRM author-field check. Both gates are closed: Issue 13's rule is recorded,
  and Issue 14's decision removes the note filter entirely.

### Verified 2026-09-03 (previously listed as unknowns)

- **Issue 17 duplicate-send window** — AI continuation runs inside the inbound worker's per-event
  unit of work; commit happens only after the processor returns; failures are retried up to three
  times. Twilio 5xx does enter uncertain reconciliation; non-HTTP transport exceptions do not.
- **Issue 16 recovery inputs** — suppression events are durably stored in `external_events` with
  lead linkage and payload; delivery callbacks in `provider_message_events`. Reconstruction is a
  replay, including `IGNORED`/`lead_not_found` rows for leads that now exist.
- **Issue 14 webhook echo** — the Follow Up Boss webhooks guide documents `notesCreated` and
  `peopleTagsCreated` as firing on the resource event with no exemption for API-originated writes.
  The `peopleTagsCreated` payload includes the added tag names in `data.tags`, which the handler
  currently discards.

### Remaining unknowns (do not block Issue 16 / 9)

1. ~~Which author fields Follow Up Boss populates on an API-written note.~~ No longer needed: the
   Issue 14 decision removes the note pause and therefore the note filter. ~~How the
   recent-human-activity check excludes the platform's own Inbox App messages.~~ Also no longer
   needed: the Q18 revision removes the recent-activity veto entirely, so nothing scans CRM
   activities for agent attribution.
2. ~~Whether `reconcile_lead_assignment_change` is a total no-op on every assignment path.~~
   Verified 2026-09-04: it publishes `LEAD_ASSIGNMENT_RECONCILED` and nothing else on every path.
   No pause and no notification are wanted (Q15). The defect that remains under Issue 11 is the
   webhook people path wiping `assigned_agent_user_id` / `effective_owner_user_id` because it skips
   assignment resolution; that is traced in the issue body and is not an unknown.
3. Twilio's current list of "recipient opted out / blocked sender" error codes (Issue 12). 21610 is
   the known one; confirm against the vendor error reference before fixing the constant.
4. Twilio/SendGrid provider-side idempotency for the application's key (Issue 17). Assume it is not
   consumed until proven.
5. Exact production volume of Issues 5, 6, 8, and 10. The code paths exist; a count is operational
   follow-up, not a reason to delay the structural fix.

### What this list is not

It is not a proof that no further defects exist. It is a proof that the seventeen named defects are
real, that the earlier "engine refuses completed workflow ids" claim was wrong (Python SDK default
is `ALLOW_DUPLICATE`; Issue 7 is missing reconciliation, not identity refusal), and that Issue 8/9
were overstated as immediate engine-exits / all-LLM-failures. Those corrections are now in the issue
bodies.

Start with Issue 16, then Issue 9, then Issue 14 + 11, then Issue 13 (its product decision is now
recorded). Each fix starts with a failing test that reproduces the defect through the existing fakes
or the business-flow harness.

---

## Business impact and acceptance guide (2026-09-05)

### Does this document settle every business behavior?

**No. It identifies real defects and records several deliberate business decisions, but it is not
yet a complete acceptance specification for all seventeen issues.** Some repairs can start now;
some changes need separate policy releases; a few outcomes still need clarification before their
implementation can be accepted. In particular, completing a campaign must not silently break replies
to its final message.

This appendix explains the difference in plain language. It qualifies the earlier broad readiness
statements; it does not approve missing decisions or claim that the proposed changes already work.
The application review used API commit `a761c1b` and frontend commit `04d4361`. **“Today” means that
reviewed code, not a fresh production measurement. “After” means the intended result once built and
tested.** The incident counts earlier in the document are historical observations.

Read this guide before accepting an issue, then use that issue's technical section to implement it.
Recorded owner rules in `CLAUDE.md` and the final D1–D7 decisions remain the authority for intended
behavior. Conflicts identified below must be resolved explicitly, not by choosing whichever older
paragraph is easiest to implement. This is not another LLM consensus round.

### Three kinds of change — not three release classes

- **Repair:** make the product do what it was already supposed to do. Example: a pause instruction
  must actually reach the automation. A repair can still have a noticeable business impact.
- **Operations:** make problems discoverable, recoverable, or explainable. Example: show failed
  background work to an operator. This can add work to a dashboard without changing contact policy.
- **Policy:** deliberately change who gets contacted, when automation continues, or how agents
  control it. Example: logging a CRM call will no longer stop the AI. This is not merely fixing code.

An issue can contain more than one kind. The agreed **D7 release classes** remain separate:

- **Class A:** structural repairs and operational improvements. Start with a reproducing test;
  “may start” does not mean “safe to release without validation.”
- **Class B:** recorded product-rule changes. Require the owner's explicit release sign-off and
  applicable agent/brokerage communication. Previous decision approval is not release sign-off.
- **Never mix A and B in one PR.** For a mixed issue, ship separately identified parts. In
  particular, fixing STOP detection must not quietly introduce email-after-STOP in the same PR.

The grouped business-rule register is a useful overview, not an issue-level release classification.
Issue 11's remaining owner-mapping repair is A: reassignment already does not pause or notify.
Issue 16's suppression-preservation repair is also A, even though the register groups it with
Class-B consent changes.

### At a glance

| Issue | Kind | What the business will notice | Release class |
| --- | --- | --- | --- |
| 1 | Repair + operations | A scheduling hold becomes a visible problem instead of a falsely healthy lead. | A |
| 2 | Repair | Pause/resume delivery records become truthful; restarted engines receive the instruction. | A |
| 3 | Repair | Enrollment statuses become accurate and the existing daily start cap begins limiting starts. | A |
| 4 | Operations | Support has weeks of execution evidence and durable business reasons, not only one day. | A |
| 5 | Repair + operations | A send-time hold waits for resolution instead of quietly ending the automation. | A |
| 6 | Repair + operations | Missing configuration or other “cannot proceed” cases stop looking like healthy nurture. | A |
| 7 | Repair + operations | Eligible live leads recover a missing engine without a chance operator action. | A |
| 8 | Repair; lifecycle gap remains | Campaigns record completion and allow controlled future enrollment; late-reply handling still needs G1 resolved. | A completion work; resolve G1 first |
| 9 | Repair + policy | STOP survives an AI outage; other replies hold outreach; the approved 30-minute escalation is separate policy. | A ordering/hold; B timing policy |
| 10 | Repair + operations | Exhausted engine failures become visible, recoverable problems. | A |
| 11 | Repair | A reassigned lead appears under the correct agent after webhook processing, not the next sync. | A |
| 12 | Repair + policy | A carrier unsubscribe becomes a durable SMS block and can redirect the step to email. | B under D7 |
| 13 | Repair + policy | Every send path follows the same consent rule and can use the other usable channel. | B |
| 14 | Repair + policy | The enrollment tag replaces routine CRM activity as the CRM-side automation control. | B |
| 15 | Repair + operations | Background work that has stopped retrying appears in an attention queue. | A |
| 16 | Repair with an accepted capability loss | CRM refreshes stop erasing opt-outs; editing a CRM field no longer lifts a platform-observed block. | A preservation/recovery |
| 17 | Repair + policy | Durable sending closes known duplicate windows; uncertain sends no longer freeze nurture. | A dispatch; B uncertain-send behavior |

### What to expect and test, issue by issue

**These are acceptance requirements, not test results.** Failure examples should be reproduced
with the existing fakes/business-flow harness and controlled clocks, not by sending real customers
messages or deliberately breaking production. “Fits” means the change fits the reviewed application;
it does not mean the implementation already exists.

#### 1 — Show a lead that cannot be scheduled

- **Today → after:** a missing re-engagement date can leave a lead labelled active with no next
  action. After the repair, the lead is visibly held for review, with a reason and history entry.
- **Business impact:** operators gain an actionable item; healthy-nurture counts may fall and review
  counts rise. That exposes existing stalled work rather than creating a new contact restriction.
- **Unchanged:** the track's rule for a missing date. The repair must not invent a date or send anyway.
- **Acceptance:** enroll a paused-search lead with a missing required date and a hold-configured track.
  No message sends; lead detail and attention explain the hold. Correct the date and use the
  permitted recovery action; the next action is scheduled without duplicating a touch.
- **Fit / gate:** A; use the application's existing pause/review/history mechanisms.

#### 2 — Make pause and resume delivery truthful

- **Today → after:** a missing engine can be restarted while the original instruction is discarded
  and logged as delivered. After the repair, the restarted engine receives the instruction; failed
  delivery remains unresolved and visible.
- **Business impact:** operators and support can trust the delivery record instead of relying on
  the engine indirectly reconstructing the requested state from the database.
- **Unchanged:** pause/resume permissions and database-backed send checks. The traced defect is not
  proof that the old pause button necessarily allowed an unsafe message.
- **Acceptance:** send pause/resume instructions when the engine is missing. Confirm the intended
  instruction is accepted after restart. If delivery fails, it must not be marked delivered.
- **Fit / gate:** A; coordinate with Issue 7's recovery and retain retry/idempotency protection.

#### 3 — Report actual enrollment progress and enforce the existing cap

- **Today → after:** an enrollment stays “queued” while messaging, and an empty start time makes
  the daily start count zero. After the repair, started/paused/handoff/finished states stay aligned
  with the workflow and the actual start is recorded once.
- **Business impact:** backlog starts spread across days when the configured cap is reached.
  Lower same-day starts can be the intended repair, not a performance regression. Metrics improve.
- **Unchanged:** the configured cap value and enrollment eligibility; no automatic re-entry is added.
- **Acceptance:** with a daily cap of two, no earlier starts, and three eligible queued leads, only
  two start that day. Pausing/resuming or retrying a start does not reset its start timestamp.
- **Fit / gate:** A; existing status/cap concepts support this. Coordinate completion with Issue 8;
  use evidence for historical data repair rather than inventing old start times.

#### 4 — Keep enough history to answer a client

- **Today → after:** closed execution history expires after 24 hours. After the improvement,
  retention covers weeks and important contact decisions also have durable application history.
- **Business impact:** support can explain last week's incident; storage and retention costs increase.
- **Unchanged:** who is contacted, cadence timing, consent, and agent controls. Increasing retention
  cannot recover history already deleted.
- **Acceptance:** verify the deployed retention setting and that an execution remains inspectable
  beyond 24 hours. Confirm the application's audit shows the reason for a send or hold even when
  engine history is unavailable. A local config edit alone is not deployment evidence.
- **Fit / gate:** A operations; choose and verify the exact retention period and its storage impact.

#### 5 — Do not mistake a send-time hold for finished work

- **Today → after:** a paused-search hold found just before sending can end the engine while the
  product still says active. After the repair, it produces the same visible, recoverable hold as
  Issue 1 instead of pretending the campaign finished.
- **Business impact:** repairing missing timing information no longer leaves a lead silently stranded.
- **Unchanged:** a legitimate move to a future contact date still reschedules; it is not a review
  failure and was not the engine-exit defect.
- **Acceptance:** schedule a valid step, then remove required timing data before execution. No send
  occurs; a review reason appears. Restore the data and recover; exactly one due touch proceeds.
- **Fit / gate:** A; share the hold outcome with Issue 1 and the missing-engine backstop in Issue 7.

#### 6 — Keep the stored business status consistent with the engine

- **Today → after:** “profile missing,” “track missing,” and other not-ready results can end an
  engine while the lead still looks live. After the repair, each result explicitly waits,
  reschedules, or records a visible hold/valid finished outcome.
- **Business impact:** operators can distinguish a recoverable setup problem from a completed campaign.
- **Unchanged:** deliberate pause and human handoff remain protected. This is not permission to
  restart their messaging or to change valid paused-search track-end limits.
- **Acceptance:** remove a required track/profile, then run scheduling. The lead must not remain
  falsely active with no engine or reason. Also pause and hand off a paused-search lead; neither
  case may send or lose its recorded human-control reason.
- **Fit / gate:** A; an engine exit and the persisted status must agree. Issue 8 owns genuine completion.

#### 7 — Recover a missing engine without restarting the business campaign

- **Today → after:** a saved enrollment whose engine never starts, or a live lead whose engine
  disappears, waits for a chance instruction. After the improvement, a periodic check finds and
  restarts eligible missing executions from their existing stored progress.
- **Business impact:** fewer leads need support to manually wake them. Recovery resumes intended
  work; it is not a new campaign enrollment or an extra marketing touch.
- **Unchanged:** completed/suppressed leads do not auto-enroll; intentionally paused, handed-off,
  or human-owned leads do not automatically resume sending.
- **Acceptance:** commit an eligible enrollment but fail its engine start. The check restores one
  execution with the existing enrollment, pending instruction, and progress. Run the check again:
  no duplicate execution/touch. Protected and terminal cases stay protected.
- **Fit / gate:** A; build on stored state and current restart rules. Issue 8's still-waiting engine
  is not fixed merely by adding this check.

#### 8 — Finish a campaign without losing the conversation

- **Today → after:** after a standard cadence's final send, the lead waits indefinitely and cannot
  normally re-enroll. The target is a recorded completion, consistent enrollment/history, and
  controlled future enrollment **without silently discarding replies to the final message**.
- **Business impact:** truthful completion reporting and restored manual re-entry. It is not safe
  to call this a “pure addition”: marking the workflow completed too early changes reply behavior.
- **Unchanged:** completion alone does not return leads to automatic dormant selection. Tag re-add
  is a separate Issue 14 exception for workflows ended by tag removal, not all completed workflows.
- **Acceptance:** a silent lead eventually completes under the agreed lifecycle and does not
  auto-enroll. Test an ordinary reply, an interested reply, and STOP after the final send and after
  declared completion; each must follow its agreed route, not disappear or bypass suppression.
- **Fit / gate:** **G1 must be resolved first.** AI continuation currently requires
  `WAITING_FOR_RESPONSE`. The earlier instruction to complete in the final-send transaction is
  incomplete unless post-completion routing is supplied. Choose a response window or explicit
  post-completion handling; do not invent a duration. A covers completion repair, not an undisclosed
  change to which replies receive AI/human attention.

#### 9 — Protect replies during an AI outage; separate the response-time policy

- **Today → after (A):** an AI call that raises can prevent STOP from being applied. Record the
  reply/processing hold first, apply hard-word opt-outs without AI, and surface exhausted processing
  rather than silently allowing subsequent cadence messages.
- **Separate policy (B):** the approved target retries classifier outages for up to 30 minutes from
  receipt, silently during that window; on exhaustion, show a review item and notify the assigned
  agent and their manager.
- **Business impact:** cadence outreach waits while a reply is processed. A short outage does not
  immediately burden agents; an interested non-hard-word reply can wait up to the approved window.
- **Unchanged / boundary:** do not change the STOP workflow outcome inside the A repair PR.
  Replacing today's terminal outcome with cross-channel continuation is already decided, but belongs
  to Issue 13's B release. Natural-language opt-outs still need classification; exact hard words do not.
- **Acceptance:** make the classifier raise on SMS STOP: SMS suppression still persists immediately.
  For an ordinary reply, prove even a newly scheduled cadence step cannot send while it is pending.
  For the B release, test recovery before the deadline and visible escalation at exhaustion.
- **Fit / gate:** A then B; suppression, hold persistence, and exhaustion visibility must survive retries.

#### 10 — Turn exhausted engine failures into operator-visible problems

- **Today → after:** repeated scheduling/sending errors can kill the engine with no change to the
  apparently healthy lead. After the repair, exhaustion records a system-error hold/review outcome
  with a reason, and recovery has an explicit path.
- **Business impact:** an outage produces a list of affected leads instead of individual client
  complaints days later. Operators may see more failures because they are finally being counted.
- **Unchanged:** normal bounded retries and all contact safeguards. Recovery is not unlimited retry
  or permission to repeat a message that might already have reached the provider.
- **Acceptance:** exhaust an activity's retries. The lead shows a review reason and no further
  automatic send. If the database was unavailable too, verify the problem is found after recovery
  by the independent check rather than assuming the failed engine could write an audit immediately.
- **Fit / gate:** A; pair with Issue 7's backstop and Issue 17's duplicate protection.

#### 11 — Put a reassigned lead on the correct dashboard

- **Today → after:** a people webhook can temporarily erase the app's agent mapping; the lead
  appears under neither agent until sync repairs it. Run the existing assignment resolution on the
  webhook path so the new agent's scoped list is correct as soon as that event is processed.
- **Business impact:** ownership visibility updates without waiting for the next five-minute sync.
- **Unchanged:** reassignment does not pause nurture or notify the new agent today, and still will
  not. Future drafts already read the current agent's name. Those are not new features in this fix.
- **Acceptance:** reassign a lead from mapped agent A to mapped agent B via a people webhook. It
  leaves A's scoped list and enters B's in that processing cycle; the next sync changes nothing.
  An unrelated people update must not wipe ownership either.
- **Fit / gate:** A; reuse the existing resolver and preserve tenant/permission scoping. Do not bundle
  Issue 14's new CRM control policy merely because both touch webhooks.

#### 12 — Recognize a carrier unsubscribe, then apply the agreed channel rule

- **Today → after:** a carrier unsubscribe looks like a generic permanent failure and does not
  update local SMS consent. The target records a durable SMS opt-out and sends the same step via
  usable email; with no usable alternative, it creates a `no_usable_channel` review hold.
- **Business impact:** future journeys stop attempting the unsubscribed number. Email may still
  reach the lead; agents see a consent outcome instead of a generic SMS send exception.
- **Unchanged:** a global do-not-contact prevents both channels. A generic permanent rejection is
  not itself evidence of opt-out and must not be recorded as one.
- **Acceptance:** simulate Twilio code 21610, first with usable email and then without. Expect one
  email plus durable SMS suppression, or no send plus visible hold, respectively. On the standard
  cadence, an unrelated permanent rejection remains a provider-failure review, not email fallback.
- **Fit / gate:** B under D7, even though error-code recognition repairs a defect. Confirm vendor
  codes, use Issue 16 durability and Issue 13 fallback, and close documentation mismatch G2.

#### 13 — Use one consent rule on every send journey

- **Today → after:** strict consent enforcement depends on the path, and general consent-based
  channel switching is absent. The target blocks an explicit “no” on its channel everywhere;
  a usable other channel carries the same logical message, re-rendered for that channel.
  With no usable channel, the issue/pre-send target is a visible review hold (see G2).
- **Business impact:** AI replies and operator sends cannot bypass explicit denial. Unknown consent
  alone will not block outreach; SMS STOP can lead to email instead of ending all nurture. This
  changes actual contact behavior, not just implementation structure.
- **Unchanged:** do-not-contact still blocks both. Unknown consent is not permission to ignore a
  missing destination, stale safety data, manual pause, handoff, pending reply, timing, frequency,
  or other applicable checks.
- **Acceptance:** on standard cadence, paused-search, AI continuation, send-now, and draft approval,
  test explicit SMS denial with usable email, both channels unusable, global do-not-contact, and
  unknown consent. Assert the actual provider channel, touch count, reason, and stored outcome.
- **Fit / gate:** B; the existing contactability/pre-send boundary fits, but every journey must
  reach it. No V1 workspace SMS approval gate is introduced. Resolve G2/G3 and include the
  email-after-STOP expectation in owner sign-off; this document is not legal compliance assurance.

#### 14 — Change how agents stop automation from the CRM

- **Today → after:** routine CRM notes, tags, stage/status changes, calls, and texts can pause AI,
  including the platform's own writes; enrollment-tag removal does nothing. The target makes tag
  removal end nurture, and re-add after that tag-ended workflow start fresh at step one. Dormancy
  enrollment writes the tag; other routine CRM activity no longer pauses the track.
- **Business impact:** “log a call/add a note to stop AI” stops working. An agent can contact a lead
  manually and still have the next automated touch occur. This removes self-pauses but deliberately
  changes agent habits and writes a control tag into the brokerage's CRM.
- **Unchanged:** **the tag is the only CRM-side switch, not the only safeguard in the application.**
  Dashboard manual pause, permission-checked resume, human handoff/ownership, reply holds, consent,
  timing, and frequency checks remain. Tag cycling must not bypass handoff or opt-out restrictions.
- **Acceptance:** with the tag present, a routine note/call does not pause. Remove the tag from
  ordinary active nurture: it ends and a queued send is blocked, even if the deletion webhook was
  missed. Re-add: one fresh enrollment, not a resumed old step. Separately prove manual pause and
  human handoff remain effective; failed dormancy-tag writes cannot leave untagged active nurture.
- **Fit / gate:** B; new behavior, not merely an echo filter. Brief agents before release. Retain or
  relocate activity timestamp recording for surviving consumers before deleting its old writer (G5).

#### 15 — Show background work that has stopped retrying

- **Today → after:** exhausted inbound events, terminal instruction-delivery failures, and failed
  event publications have no operator reader. After the improvement, each appears with its reason,
  age, and affected context on an appropriate attention surface.
- **Business impact:** operations can find failed work before a customer reports a quiet lead.
  Counts may initially rise; visibility does not itself mean the failure rate increased.
- **Unchanged:** existing review items do not depend on notification delivery and must not be
  rebuilt on that assumption. Visibility does not authorize unlimited or unsafe automatic replay.
- **Acceptance:** exhaust one item in each of the three queues. Each remains queryable and visible
  with a reason and age, even if notification delivery fails. Verify tenant-scoped access.
- **Fit / gate:** A; extend the existing operational surfaces without duplicating review creation.

#### 16 — Make an opt-out survive a CRM refresh

- **Today → after:** stale or absent CRM fields can erase a platform-observed opt-out and its
  evidence. After the repair, CRM sync can add suppression but cannot clear that stronger fact;
  historical evidence is used to re-assert lost suppression before sends are re-enabled.
- **Business impact:** an agent cannot lift a platform-observed opt-out merely by changing the CRM
  custom field. That capability loss is accepted. Resume or re-enrollment does not clear consent.
- **Unchanged:** normal CRM updates still apply; do not freeze unrelated fields. Keep channel blocks
  distinct from global do-not-contact and preserve newer agent-activity timestamps.
- **Additional target:** CRM opt-out notes/consent-field writes inform agents in their own tool;
  they are a courtesy update, not a prerequisite for local blocking.
- **Acceptance:** record SMS, email, and global suppression cases; run full sync, people webhook,
  pre-send refresh, and on-demand refresh with absent/stale consent values. The relevant blocks
  and evidence survive. Replay recovery twice, including previously ignored events for leads that
  now exist: it may re-assert suppression, never clear it. Failed CRM writes must not unblock contact.
- **Fit / gate:** A preservation/recovery is the first assignment. **Do not promise that START,
  resubscribe, or an audited human clear already works:** the reviewed application does not provide
  verified end-to-end lift paths. Build/test the sanctioned routes or explicitly defer them and
  disclose the limitation (G4); do not weaken the preservation fix as a workaround.

#### 17 — Prevent known retry duplicates; separately change uncertain-send behavior

- **Today → after (A):** several direct send journeys can call the provider again after acceptance
  followed by a crash or later transaction failure. Route them through committed send intent and
  durable dispatch, with consistent handling of ambiguous provider results.
- **Separate policy (B):** an uncertain step counts as attempted/sent **for cadence progress only**,
  is not resent, and does not pause nurture. Later delivery callbacks correct the message record,
  not the workflow. The timeline must not present uncertainty as confirmed delivery.
- **Business impact:** fewer duplicate touches and fewer stranded leads. The accepted trade-off is
  a possibly missed touch, or a delayed uncertain message arriving close to the next scheduled one.
- **Unchanged:** later steps still follow their normal schedule and safety checks. Durable dispatch
  is not proof of provider-wide exactly-once delivery; provider idempotency remains to be verified.
- **Acceptance:** for each migrated journey, simulate provider acceptance followed by a crash or
  later failure, then retry: no second provider dispatch for that logical touch. For B, simulate
  uncertainty and later success/failure callbacks: no resend, no callback-driven resume/pause, and
  the next step follows its configured schedule. Verify UI distinguishes queued, uncertain, and sent.
- **Fit / gate:** separate A/B PRs. D6 sizing is required: paused-search includes occurrence and
  workflow linkage, not just passing a repository argument. Keep that lifecycle intact (G6).

### Readiness conditions that remain — do not discover these during manual testing

These conditions are scoped to the affected behavior. They do **not** reopen D1 or block the first
Issue 16 preservation and Issue 9 ordering fixes. An issue is not fully accepted merely because its
structural part ships.

1. **G1 — Completion and late replies (Issue 8): product/lifecycle gap.** Decide when completion
   happens and how ordinary, interested, and opt-out replies are handled afterwards. A response
   window needs an explicit duration; immediate completion needs explicit post-completion routing.
   Test against `continue_ai_conversation_after_inbound`, which currently rejects states other than
   `WAITING_FOR_RESPONSE`. Do not ship a completion transition that silently disables that journey.
2. **G2 — No usable channel (Issues 12/13): documentation mismatch, not a new fallback vote.** The
   current issue rules and `04-pre-send-safety-checks.md` say visible `no_usable_channel` hold when
   no alternative is usable; global do-not-contact ends outreach. The consensus's earlier D1
   template still mentions “no channel left → SUPPRESSED.” Align that stale passage and record the
   expected states in tests before release. Do not use it to silently terminalize a missing-email case.
3. **G3 — Configured provider-failure fallback (Issue 13): unresolved scope conflict.** `CLAUDE.md`
   says non-opt-out permanent rejections hold rather than reroute. Issue 13 and the pre-send document
   retain the paused-search track's configured provider fallback. The governing rule is no general
   provider-failure fallback; an intended paused-search exception needs explicit owner confirmation
   and aligned documents. Identify affected configured tracks and test the chosen outcome; do not
   quietly preserve or remove an operator setting. Consent fallback itself is already decided.
4. **G4 — Lifting an opt-out (Issue 16): approved capability, unverified implementation.** The target
   names lead-initiated resubscribe and permission-checked human clearing with evidence. Neither is
   a verified complete replacement for editing the CRM field today. Name who can do what, the real
   user/provider entry point, audit requirements, and tests before advertising it; otherwise explicitly
   defer it and tell operators there is not yet a supported replacement. This must not delay making
   existing opt-outs durable. “CRM cannot clear it” does not mean “no legitimate lift is ever allowed.”
5. **G5 — Agent-activity recording (Issues 14/16): implementation boundary.** Removing the activity
   pause/send veto must not leave `last_agent_activity_at` stale for surviving resume, classification,
   and API consumers. Retain/relocate its narrow writer, or separately migrate those consumers before
   removing it. That decision is not permission to retain the removed CRM activity veto.
6. **G6 — Durable-dispatch scope (Issue 17): engineering readiness.** Size standard and paused-search
   occurrence handling, AI replies, operator sends, draft approvals, callbacks, and transaction
   failures. Prove the lifecycle and claim/retry behavior, not only a happy-path send. Do not use the
   shorthand “never two copies” as an unconditional guarantee about external provider delivery.
7. **G7 — Release ownership and communication (all B parts): operational readiness.** Before each
   B release, record the owner's yes, its acceptance evidence, and applicable operator briefing.
   Explain tag-only CRM control and dormancy tag writes, email-after-SMS-STOP, unknown-consent behavior,
   the reply escalation window, and uncertain-send trade-offs for the parts being released. Disclose
   Issue 16's accepted CRM-field capability loss as well, despite its A repair classification.

The exact retention period (Issue 4), recovery/check intervals and operational ownership (Issues
7/15), and handling of existing inconsistent rows also need concrete implementation/release plans.
They are not reasons to guess a new consent or re-entry rule.

### How to accept each change without testing blindly

1. **Scope the PR:** name the issue number, A or B, the specific part delivered, and anything
   deliberately excluded. “Implements Issue 17” is insufficient if it only migrates one send journey.
2. **Agree on the expected result before coding:** copy its “Today → after,” “Unchanged,” and
   acceptance examples into the implementation checklist. Close the applicable G-condition first.
   If a tester cannot say which message, state, dashboard item, or permission result to expect, the
   specification for that part is not ready.
3. **Automate the failure first, then prove the repair:** use the existing application fakes and
   `tests/application/use_cases/test_business_flow_harness.py`; add persistence/transaction coverage
   in `tests/infrastructure/persistence/postgres/test_business_flow_harness.py` where relevant.
   Run the focused tests. Assert saved state/history and actual fake-provider call counts, not only
   a successful function return. Cover retries, duplicates, late callbacks, and protected states
   when those affect the change. Fakes do not by themselves prove a real provider integration.
4. **Keep manual acceptance small and specific:** use test leads and sandbox/sink providers. Check
   only the affected human journey: the attention reason, pause/resume outcome, new owner's list,
   enrollment status, or conversation timeline. Test both the changed behavior and the safeguard
   that must remain. Do not manually repeat all seventeen issues for every PR, and do not rely on
   a manual tester to reproduce an AI outage or provider-acceptance crash.
5. **Attach evidence before sign-off:** record fixture/setup, action, expected result, actual result,
   automated test command/result, and targeted UI/API checks. A blocked scenario is a remaining
   condition, not a pass. A Class B release also needs the owner's release approval and communication.
6. **Separate rollout from the fix:** inventory affected existing leads/queued work, dry-run any
   repair or replay, and approve its production scope separately. Issue 16 recovery must precede
   re-enabling affected sends. Recovery must respect consent, human control, daily caps, and send
   identity; it must not restart every historical lead or guess missing history.

**Practical starting point:** implement Issue 16's preservation tests/fix, then Issue 9's
STOP-before-AI and reply-hold repair. Resolve G1 before building Issue 8's terminal transition.
Use the per-issue acceptance examples for each subsequent PR, and schedule Class B changes as
explicit behavior releases—not as surprises discovered while testing a “bugfix.”
