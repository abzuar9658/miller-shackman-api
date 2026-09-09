# Business Rule Change Register

**Purpose.** The 17 issues in `production-state-consistency-issues.md` change the product along eight
business rules, not seventeen. This register is the human review surface: one row per rule, today vs.
after, who is affected, and what sign-off it needs. Review this table; do not re-read the issues doc.

**How to review (30 minutes, one sitting).** For each row ask: (1) *What does someone do today that
stops working?* (2) *Can I explain this to a client in one sentence without flinching?* Any row that
fails question 2 is a hold on the Class B release, not a document edit.

---

## R1 — What blocks a message (consent)
**Issues:** 9, 12, 13, 16 · **Class:** B (approved 2026-09-04) · **Reversible:** the rule, yes; a recorded opt-out, no (by design)
- **Today:** path-dependent — denied consent blocks a cadence step but not an AI reply or operator
  send-now; STOP requires the AI to be up; a carrier unsubscribe is filed as a generic failure; any
  CRM refresh can erase a recorded opt-out.
- **After:** one rule at one choke point — an explicit lead "no" blocks that channel on every path;
  the same message goes out on the other usable channel; unknown consent never blocks; opt-outs the
  platform observed are durable (CRM sync can add suppression, never remove one); a carrier
  unsubscribe is an opt-out.
- **Stops working:** agents lifting an opt-out by editing the CRM custom field (capability loss
  accepted, Issue 16 rule 3); the lenient AI-reply path.
- **Client sentence:** "When someone tells us no on one channel, we stop on that channel everywhere,
  permanently, and we don't need their CRM to remember it for us."
- **Owner check:** tone call only — is email-after-SMS-STOP too aggressive for your brokerages?

## R2 — What stops the AI
**Issues:** 11, 14 · **Class:** B (approved 2026-09-04) · **Reversible:** yes
- **Today:** almost any CRM activity pauses the AI (any note, any tag, stage/status change, logged
  calls/texts) — including the platform's own writes; reassignment does nothing; tag removal does
  nothing.
- **After:** the enrollment tag is the only switch — removing it ends the nurture (terminal, not
  pause); re-adding it starts a fresh enrollment from step one; nothing else pauses; handoff still
  requires explicit resume.
- **Stops working:** the agent habit "add a note / log a call to stop the AI." After this, that does
  nothing, silently. Dormancy-enrolled leads get a tag written into the client's CRM.
- **Client sentence:** "One tag on the lead is the on switch. Take it off and the AI stops for good;
  everything else an agent does in the CRM no longer interrupts it."
- **Requires:** the D5 agent briefing before release — this is the change agents must be told about
  before it ships, not after.

## R3 — When nurture ends
**Issues:** 8, 14 · **Class:** A (completion) + B (tag re-add re-entry) · **Reversible:** yes
- **Today:** a finished cadence never completes; the lead is stuck in "waiting" and is refused by
  every future enrollment, forever.
- **After:** finishing the cadence is a recorded completion — but completed leads do **not** auto-
  re-enter nurture; re-entry is manual-admin or the tag-re-add rule once built.
- **Stops working:** nothing. This is pure addition.
- **Client sentence:** "Finishing a campaign finally closes the file instead of locking it."

## R4 — What an operator can see
**Issues:** 1, 5, 6, 10, 15 · **Class:** A · **Reversible:** yes
- **Today:** leads stall invisibly; three retry queues give up with no reader.
- **After:** every unbounded stall becomes a review item with a reason; exhausted/dead work lands on
  the attention surface with age.
- **Expect:** dashboards look worse in week one — invisible stalls become enumerated. That is the fix
  working, not a regression.
- **Client sentence:** "If the system stops working on a lead, it now has to say so."

## R5 — Send reliability
**Issues:** 17 · **Class:** A (durable dispatch mechanics) + B (uncertain=sent) · **Reversible:** yes
- **Today:** a crash after provider acceptance can double-send on direct paths; an uncertain outcome
  freezes the lead for 24 hours; even a later "it did send" leaves them paused and dark.
- **After:** intent is committed before the provider is called, on every journey; an uncertain send
  is treated as sent, never resent; reconciliation corrects the record only.
- **Trade-off accepted:** on a rare ambiguous send, the lead may miss that one touch. Never two
  copies.
- **Client sentence:** "No duplicate texts, and one ambiguous send no longer takes a lead offline."

## R6 — Volume
**Issues:** 3, 8 · **Class:** A · **Reversible:** yes
- **Today:** the daily start cap counts a field that is never written — it has never engaged.
- **After:** the cap works (backlog starts throttle and spread out). Completed leads add **no**
  automatic volume (verified: manual re-entry only).
- **Client sentence:** "Daily limits finally mean something."

## R7 — Operator trust
**Issues:** 2, 7 · **Class:** A · **Reversible:** yes
- **Today:** pause/resume can report "delivered" and never arrive; dead engines restart only by
  accident.
- **After:** delivery is real; a reconciler finds live leads without engines and restarts them.
- **Client sentence:** "The pause button does what it says, and nothing gets lost quietly."

## R8 — Evidence
**Issues:** 4 · **Class:** A · **Reversible:** yes
- **Today:** execution history is deleted after 24 hours; last week's incident is unanswerable.
- **After:** weeks of retention, and the business reasons for contact decisions are recorded in the
  product's own audit.
- **Client sentence:** "When a client asks why we did or didn't contact someone, we have the answer."

---

## Per-PR review habit
Do not re-review this register per PR. Each PR names the rows it touches in its description
("touches R1, R4"); you review only whether the delivered behavior matches those rows. The failing
test each fix starts with is the human-readable statement of the change — read the test names.

## Holds
Only three things can pause a row's implementation: a failed client-sentence test (owner), a D5
briefing not yet delivered (R2), or the D6 sizing (R5 paused-search scope). Everything else proceeds.
