# Consensus Review — Production State Consistency Issues

**Purpose.** This single reply consolidates the four independent reviews (Kimi K3, Grok 4.6, GPT 5.6, Opus 4.5) of `docs/planning/production-state-consistency-issues.md`. Every disputed claim has been re-verified against the codebase, not settled by vote. The goal of this round is agreement: the next pass of any reviewer responds to this document, not to a re-review of the original.

---

## 1. Settled facts — no reviewer may relitigate these

Verified against current code:

- The 17 defects are real and code-backed. The document's own correction trail (dated correction blocks) is accurate.
- **Paused-search cadence steps are NOT on the durable dispatch path.** `campaign_cadence_execution.py:896-898` (and the fallback branch at 967-969) sets `outbound_send_request_repository=None` when `is_paused_search_step`. Paused-search sends therefore currently have neither strict consent revalidation (Issue 13) nor duplicate protection (Issue 17). Kimi K3's correction to the Issue 13/17 bodies is accepted as the last word; any text claiming paused-search steps use the durable queue is superseded.
- Issue 11's dashboard gap is exact: `crm_sync_incremental_interval_seconds = 300` (`app/core/config.py:44`).
- Issue 1: `_save_hold` (`schedule_next_paused_search_action.py:435-447`) clears `next_action_at`, leaves the workflow state untouched, writes no transition, creates no review item.
- Issue 3: enrollments are created `QUEUED` with `started_at=None` (`campaign_enrollment_starter.py:151-155`); `count_started_today` filters on `started_at`, so the daily-cap count is always zero.
- Issue 9: `classify_inbound_reply` (`process_inbound_message_event.py:467`) runs before `_apply_explicit_opt_out_override` (`:474`). A classifier *raise* propagates before any suppression logic; the worker retries 3× then marks the event `EXHAUSTED`, which no code reads.
- Issue 13: `evaluate_contactability` has two modes; strict mode is requested at exactly one call site (`revalidate_outbound_send_request.py:277`, SMS only, durable-queue path).
- Issue 16: `preserve_app_owned_lead_state` (`canonical.py:217-241`) carries only paused-search fields; all four refresh paths rebuild consent from the CRM payload.
- Issue 12: `classify_http_status` sees only the HTTP status; Twilio's `exc.code` is discarded.

## 2. Corrections each reviewer must accept

**Kimi K3.**
(a) Point 8 ("every can't-proceed outcome becomes a visible hold") overstates the end state. The approved decisions *remove* most hold causes (Issue 14) and *retain* one deliberate bounded-silent hold (Issue 9's reply-hold — silent because it normally clears in seconds, bounded at 30 minutes). The accurate claim: fewer things hold at all, the remaining holds are bounded, and every unbounded hold becomes visible.
(b) Everything else stands (see §3).

**Grok 4.6.**
(a) The unbundle axis (structural fixes vs. policy decisions) is accepted and adopted — see §3.
(b) The "treat the later decisions as proposed; the status quo is safer" framing is rejected for Issues 13 and 17 specifically: **the status quo is the defect.** For 13, production currently blocks a denied-consent lead on one path and texts them on another — the document itself records "neither outcome satisfies both rule documents; the inconsistency is itself a defect." For 17, a lead whose uncertain send is later confirmed as delivered goes permanently dark (the callback never unpauses the Postgres workflow, and `execute_cadence_step` refuses to send from `PAUSED`). For these two, declining to decide picks the harmful side by default; there is no neutral "old behavior" to fall back to.
(c) On Issue 14: the origin-filtering alternative implied by the review was the document's *original* fix proposal and was superseded deliberately, because the platform cannot reliably recognize its own CRM writes. Re-litigating the decision is legitimate; implying it was unconsidered is not.

**GPT 5.6.**
(a) The claimed "material contradiction" between Issues 9/16 and Issue 13 is reclassified: it is an **escalation**, not a contradiction. Issue 16's closing note explicitly reserves the channel-fallback question as undecided ("to be decided as its own question"), and the proposed resolution (email continues after a hard-word STOP) directly contradicts the recorded Issue 9 decision ("SUPPRESSED workflow"). A reviewer cannot resolve a deliberately reserved question unilaterally.
(b) The underlying catch is nevertheless the single most important output of this round — it is formalized as Decision D1 in §4.
(c) The stale-wording list is accepted with one exception: Issue 11's "use the new agent's identity on future messages" is *current* behavior (`_assigned_agent_name_from_lead` reads the agent name from the current lead record at draft time), not a change.

**Opus 4.5.**
(a) All eleven verification-table entries are confirmed — the cleanest audit of the round.
(b) Accepted in full: the Issue 3+8 volume counterweight (D2), the Issue 16 capability loss (D3), week-one dashboard optics, and Issue 14 as a change-management requirement (D5).
(c) Two corrections: the through-line count is eight (1, 5, 6, 7, 8, 10, 15, 17), not ten; and the review's own Issue 12 sentence ("same permanence as STOP… falls back to email") sits directly against its Issue 9 sentence (STOP ends everything) without a cross-check. That cross-check is D1.

## 3. Contributions adopted into the consensus

- **From Kimi K3:** the durable-dispatch blast-radius correction (§1); the paired reading that Issue 8's completion fix restores Issue 3's statuses and the daily cap as one causal chain.
- **From Grok 4.6:** the governing axis for sequencing — **structural fixes vs. policy decisions**. Structural: 1, 2, 3, 4, 5, 6, 7, 8, 10, 15, and the dispatch mechanics of 17. Policy: 11 (no pause on reassignment), 13 (consent rule + channel fallback), 14 (tag-only switch + veto removal), 17 (uncertain-sent rule), 9 (30-minute window). Policy items are decisions with owners and parameters, not defects with fixes; they are handled through the decision register (§4), not blanket "implement it."
- **From GPT 5.6:** the three-path opt-out asymmetry (D1); the documentation-hygiene list (§5).
- **From Opus 4.5:** the volume-model gate (D2); recording accepted capability losses per decision (D3); release-communication requirements (D5); the through-line, corrected: *"the system may not stop working on a lead without saying so"* is one structural rule with eight symptoms.

## 4. Decision register — must be recorded before implementation starts

These are product decisions, not code questions. The structural work does not block on them, except where noted.

**D1 — One question, one rule: when a lead blocks one channel, does the nurture continue on the other?** *(blocks Issue 12's fallback rule; originated from GPT 5.6's escalation; re-scoped by Opus 4.5 round 2 — supersedes the original three-way framing and Kimi's two-tier amendment).*

**Re-scoping (Opus 4.5, verified):** all three paths record the *same* consent fact — a channel-scoped suppression (`_contact_suppression_kind`, `process_inbound_message_event.py:1157-1160`: SMS→`SMS_OPT_OUT`, email→`EMAIL_UNSUBSCRIBED`). There is no "opt-out asymmetry" in what is recorded; the only divergence is a second, separate question — does a channel-scoped block end the nurture or move it to the other channel? Decide that once; apply to all three paths:

- **Path A — lead texts STOP:** workflow → terminal `SUPPRESSED` (current shipping code, `process_inbound_message_event.py:751-761` + `:2502`; preserved by Issue 9 rule 2).
- **Path B — provider/CRM unsubscribe event:** workflow → `PAUSED` if any channel sendable, else `SUPPRESSED` (`process_contact_suppression_event.py:306-319`).
- **Path C — carrier rejects at send (Issue 12, unbuilt):** suppression + email fallback + cadence continues.

**The intent-attribution rationale for keeping the asymmetry is refuted.** Kimi's round-2 defense (human word = terminal, technical event = channel block) does not survive the unsubscribe-click counterexample: `process_contact_suppression_event` is reachable from the FUB `emEvents type=unsubscribe` mapper (`webhook_event_mappers.py:146`) and the suppression webhook endpoint (`webhooks.py:573`), so a lead *clicking* an email unsubscribe link lands in Path B. Same human intent, same recorded fact, opposite outcomes depending on mechanism. Intent is not what separates the paths; mechanism is. No intent-attribution rationale can be written.

**Recommended resolution (consistent with Issue 13's recorded decision):** the answer is *continue* — a channel-scoped block blocks that channel and the message goes out on the other usable channel; the step counts as delivered. Then:
- **Path B's shape is the template** — it already has the "no channel left → `SUPPRESSED`" branch that any unified rule needs; Paths A and C conform to it (A upgraded from terminal to channel-scoped, C already conforms).
- **Terminalization is reserved for global signals** (`do_not_contact`), never a channel-scoped one. State machine supports this: `SUPPRESSED` is terminal (`models.py:215`) and reachable from `PAUSED` (`:163-170`).
- **Cost note:** unifying toward *continue* changes live production behavior for Path A (not merely a recorded decision — the code ships today), and reverses Issue 9 rule 2's "SUPPRESSED workflow" wording. Issue 9's invariants (STOP honored without AI; hold on unprocessed replies; exhausted replies surfaced) are untouched — only the workflow outcome of a hard word changes.
- **The residual product call, named for the owner (not decidable by tracing):** continuing by email after an SMS "STOP" is legally defensible (carrier STOP is per-number) but some brokerages will read it as aggressive. This is the only genuinely open part of D1.

Until D1 is recorded, Issue 12 rule 2 implementation is blocked. Kimi's round-2 D1 vote is superseded by this re-scope and should be re-cast against it.

**D2 — Net send-volume model before shipping Issues 3 and 8 together.**
The cap fix throttles backlog starts; the completion fix returns completed leads to the addressable pool. These pull in opposite directions and the combined net change in outbound volume is unmodeled. Model it; the daily cap is the counterweight. Gate on shipping both in the same release.

**D3 — Issue 16 removes an agent capability.**
After the durability rule, editing the CRM consent custom field no longer lifts an opt-out — a workflow some agents may rely on today. Record the accepted loss alongside the sanctioned lift paths (lead-initiated START/resubscribe; audited platform action with recorded actor and reason).

**D4 — Issue 9's parameters are policy constants, not part of the invariant.**
The invariants: STOP is honored without the AI; no cadence message sends while a reply is unprocessed; an exhausted reply becomes visible. The 30-minute window and the silent-then-notify choice are tunable parameters, revisitable without reopening the issue.

**D5 — Issue 14 ships with change management, not just code.**
Release requirements: an agent briefing that notes/calls/tags no longer stop the AI and that tag removal is the only switch; disclosure that dormancy-enrolled leads get a tag written into the client's CRM; expectation-setting that dashboards will look worse in week one as invisible stalls become enumerated (applies to Issues 1/5/6/7/8/10/15 collectively).

**D6 — Issue 17's "every journey through durable dispatch" explicitly includes paused-search steps, and the scope is larger than a repository passthrough.**
Per §1, the current withholding means paused-search sends have neither consent revalidation nor duplicate protection. Kimi's correction is the reference for scope. **Opus round-2 addition (verified):** the same branch also nulls `workflow_id` and `temporal_workflow_id` (`campaign_cadence_execution.py:899-900`), so paused-search sends currently cannot be reconciled or signaled back to a workflow. Onboarding them makes those steps signal-bearing, which touches the paused-search occurrence lifecycle. **Size this before treating it as a one-line change alongside Issue 17.**

## 5. Document edits to apply before implementation

1. Issue 13: retitle — the recorded decision removes "confirmed consent" and the A2P gate from the question.
2. Issue 16: rule 2's monotonic merge clause **stays**. *(Corrected on Opus round-2: the earlier instruction to mark `last_agent_activity_at` a deletion candidate was wrong — the field has five live readers after the veto removal (`lead_resume.py:363`, `pre_send_crm_refresh.py:197`, `lead_state_classification.py:439`, `leads.py:1656`, `schemas/leads.py:214`), and Issue 14 removes its only writer (`process_crm_human_activity_event.py:186-187`). Deleting the writer leaves a permanently stale field behind live readers. Owner must instead decide: retain the writer's narrow stamping path, or schedule reader migration + field removal as its own work item. Either way the monotonicity clause remains.)*
3. Issue 16 closing note: once D1 is decided, replace "to be decided as its own question" with the recorded decision.
4. Issues 11, 13, 14: delete or clearly date superseded original text — the inline supersession markers help reviewers but mislead implementers.
5. Suggested order of work: add D2 as a gate for shipping 3 and 8 together; add D1 as a gate for Issue 12.
6. Fix the through-line count wherever quoted (eight issues, not ten).

## 6. Instructions for the next pass

Each reviewer, on the next round:
(a) adopt §1 as settled;
(b) accept the §2 corrections;
(c) respond only to §4 — D1 is the only open item that changes code paths;
(d) do not relitigate settled items. A review that re-raises a §1 item or ignores a §2 correction is out of scope.

Agreement is reached when all four reviewers accept §1–§3 and the owner records decisions D1–D6.

**ROUND-2 OUTCOME (all four reviewers responded): CONSENSUS REACHED.**
- §1 settled facts: accepted by all four, with three independent re-verifications and zero contested entries.
- D1: closed by authority — the owner's recorded rule already answers it (channel fallback, no hard-word carve-out).
- D2: narrowed then closed — no automatic re-entry exists (`_TERMINAL_REENTRY_SOURCES = {MANUAL_ADMIN}`; dormant selector excludes any prior workflow, `dormant_candidate_selector.py:102`).
- D3–D6: accepted as written by all four.
- D7 (added): the ship-class gate separating defect fixes from product decisions.

**FINAL ACKNOWLEDGMENT (2026-09-04): all four reviewers replied "Accepted" with no objections.** D1's closure by authority, D2's closure by code, and the D7 ship-class gate are unanimously acknowledged. The review phase is formally CLOSED. Per §6d, no further review rounds: future disagreements are escalated to the owner as decisions, not reopened as reviews. Implementation authorization: Class A starts at Issue 16 (failing test first), then Issue 9's ordering fix; Class B items require individual owner release sign-off per D7.

---

## 7. Round-2 status — consensus log

**GPT 5.6 — ACCEPTED §1 (its round-1 paused-search disagreement self-corrected and confirmed); made two verified rulings; edited the issues document directly.**
1. **Confirmed paused-search durable-dispatch bypass** after tracing end-to-end (its round-1 objection stopped at dependency wiring; the later branch deliberately replaces the repositories with None). Issue 17 scope and D6 confirmed.
2. **D1 is already resolved by the owner's authoritative rule.** `CLAUDE.md` (updated 2026-09-04): "When one channel is explicitly blocked and the other is usable, the same message goes out on the other channel" — no hard-word carve-out. Issue 13's decision postdates and supersedes Issue 9's older outcome wording. **D1 CLOSED: channel-scoped fallback on every path; terminal reserved for global signals.** No re-circulation needed. The issues document has been edited to match (Issue 9 rule 2 now resolves the channel outcome under Issue 13; Issue 16's open question is answered; the "SUPPRESSED workflow" wording is gone).
3. **D2's surge premise is refuted** — verified: `_TERMINAL_REENTRY_SOURCES = {MANUAL_ADMIN}` and the dormant selector enrolls with `DORMANT_SELECTOR`, which hits `TERMINAL_REQUIRES_MANUAL_ENROLLMENT`. Completed leads return to the pool only by explicit manual re-entry (or Issue 14's tag re-add). A "Release-volume note" was added to Issue 8. **D2 NARROWED:** no automatic volume surge to model; the daily-cap throttle (Issue 3) remains the only throughput change and needs no joint-release gate.
4. **One regression re-introduced and re-fixed:** its Issue 16 edit restored "last_agent_activity_at is a deletion candidate" — refuted by the Opus round-2 trace (four live readers; Issue 14 removes the only writer). The monotonicity clause and reader list are restored in the issues document; Issue 14's paths note now says the stamping is retained or relocated rather than deleted.

**Kimi K3 — ACCEPTED (full agreement on §1–§3, §4 D2–D6).** D1 two-tier vote superseded by the re-scope and then closed by GPT's authoritative-rule finding — moot; no re-vote required.
Adopted §1 as settled with no re-verification to add. Accepted the §2 Point 8 correction verbatim. Raised no new code claims. Cast the first formal D1 vote:

> **D1 — Kimi's position: option (i), amended.** Keep the asymmetry, but as a **two-tier intent ladder**, not three paths:
> - **Tier 1 — human-authored word (Path A, Issue 9):** terminal `SUPPRESSED`. A lead who types STOP is making a statement about the relationship, not the channel; email fallback after an explicit STOP is a spam-complaint generator. The recorded Issue 9 decision stands.
> - **Tier 2 — carrier/provider event (Paths B + C):** channel-scoped `sms_opt_out` suppression + email fallback + cadence continues. A transport event is a fact about the channel, not a sentence the lead said.
> - **Amendment:** Path B (`process_contact_suppression_event.py:306-319`) currently pauses the whole workflow when any channel is sendable — inconsistent with the approved Issue 13 fallback rule. Path B converges with Path C.
>
> **Decisive argument — the same-physical-event problem:** a STOP texted to a Twilio number can surface as *both* a carrier opt-out and an inbound STOP webhook. The two-tier ladder is order-independent in the safe direction: carrier event first → channel block + email; the human word, whenever it arrives, escalates to terminal. The stronger signal always wins.
>
> Verified against the state machine (`app/domain/workflows/models.py`): `SUPPRESSED` is terminal (`:215`) and reachable from `PAUSED` (`:163-170`), so the escalation ordering is mechanically legal and terminal states are absorbing. **Issue 12 rule 2 is unblocked once the two-tier rationale is recorded in Issues 9 and 12.**

D2–D6 accepted as written. ~~D6 confirmed closed~~ *superseded — see Opus round-2 D6 scope addition below.*

**Opus 4.5 — ACCEPTED §1–§3 (all 11 §1 entries re-verified, including line numbers); round-2 contributions all CONFIRMED against code and adopted:**
1. **§5 item 2 was wrong — consensus document corrected.** `last_agent_activity_at` is not a deletion candidate: five live readers remain after the send-time veto is removed, and Issue 14 removes the field's only writer (`process_crm_human_activity_event.py:186-187`). §5 item 2 revised accordingly (monotonicity clause stays; writer disposition becomes an owner decision). This also corrects the underlying issue-document error the item came from.
2. **D1 re-scoped (see §4).** The "opt-out asymmetry" framing was wrong: all three paths record the identical channel-scoped consent fact (`_contact_suppression_kind`, `process_inbound_message_event.py:1157-1160`); the only divergence is whether a channel-scoped block ends or reroutes the nurture. Kimi's two-tier intent ladder is refuted by the unsubscribe-click counterexample: Path B is reachable from the FUB `emEvents type=unsubscribe` mapper (`webhook_event_mappers.py:146`) and the suppression webhook (`webhooks.py:573`), so *clicking* an unsubscribe link — same human intent as texting STOP — lands in the lenient path. **Kimi's D1 vote is superseded; re-cast against the re-scoped question.** Recommended resolution recorded in §4 (continue, conform A and C to B, terminal reserved for `do_not_contact`).
3. **D6 scope expanded (see §4).** The paused-search withholding branch also nulls `workflow_id`/`temporal_workflow_id` (`campaign_cadence_execution.py:899-900`), so onboarding paused-search to durable dispatch makes steps signal-bearing — sizing required, not a one-line change.

**Grok 4.6 — ACCEPTED §1 (all code facts confirmed); round-2 raises the process objection that closes the review:**
1. **All "today" claims verified, including a claim none of the other reviewers traced:** the dormant selector excludes any lead with *any* workflow row, terminal or not, forever (`dormant_candidate_selector.py:76-83,102` — `~exists(has_any_workflow)`). This independently confirms GPT's D2 narrowing and refutes the residual "addressable pool grows automatically" reading of Issue 8: completion + cap fix produce **no automatic volume change**; re-entry is strictly operator-controlled (manual admin enrollment, or Issue 14's tag re-add once built).
2. **The process objection — sustained and it defines the finish line.** Grok's position: the consensus conflates two ship classes. *Defect fixes* (visible holds, real pause/resume delivery, cap accounting, cadence completion without auto re-entry, STOP-before-AI, monotonic suppression merge, durable dispatch mechanics, dead-letter surfaces) can start as fixes. *Product-rule changes* (channel fallback outcomes, tag-as-only-switch, unknown-consent-never-blocks, uncertain=sent, 30-minute window) are recorded decisions that change who gets contacted and how agents work — they ship on the owner's explicit yes, batched with change management (D5), not hidden inside bugfix PRs.
3. **Its "where the other LLM guessed" table is confirmed in every row** — most importantly: the tag-re-add carve-out and dormancy-tag-write do not exist in code yet (they are the Issue 14 build), and carrier-rejection email fallback does not exist (it is Issue 12's build). These are targets, not current behavior — the consensus document and the issues document both already frame them that way after the round-2 edits, and Grok's objection is to implementation framing, not to the records.

**Convergence verdict:** all four reviewers now accept the code facts. The remaining disagreement is not factual — it is Grok's ship-class gate, which is a process control, not a dispute. Adopted as **D7** below.

**D7 — Ship-class gate (from Grok round-2).** Implementation proceeds in two explicitly labeled classes:
- **Class A — defect fixes (may start immediately):** Issues 1, 2, 3, 4, 5, 6, 7, 10, 15, 16, Issue 9's ordering fix (STOP-before-AI, hold-on-failure, exhausted-reply surfacing — without binding the 30-minute constant), Issue 17's durable-dispatch mechanics (subject to D6 sizing), Issue 8's completion transition (without auto re-entry).
- **Class B — recorded product decisions (each ships only with owner sign-off in the release, batched with D5 change management):** Issue 13's fallback rule + unknown-consent-never-blocks, Issue 12's carrier-opt-out + email fallback, Issue 14's tag-only switch, Issue 17's uncertain=sent cadence rule, Issue 9's 30-minute window.
A PR must not mix the classes. A Class-B behavior shipping inside a Class-A PR is a review-blocker.

**Owner actions outstanding before implementation:**
1. ~~Re-circulate the re-scoped D1~~ **CLOSED.** ~~D2 volume gate~~ **NARROWED then closed by Grok's dormant-selector trace:** no automatic re-entry exists anywhere; no volume gate.
2. `last_agent_activity_at` disposition: writer's stamping retained or relocated (four readers survive); reader migration + field removal tracked as its own work item if desired.
3. Remaining §5 edits largely applied by GPT round-2; remaining: D6 sizing before scheduling Issue 17.
4. **Class A may start now at Issue 16, then Issue 9's ordering fix.** Class B items go to the owner's release checklist one by one. This satisfies Grok's go-ahead condition and preserves the other three reviewers' accepted decisions.
