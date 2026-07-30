# Dormant Re-Engagement Feature 01 — Journey and Reply Handling

## Purpose

This document defines how the dormant AI nurture path should behave once a lead
has been classified as dormant and is allowed to start AI nurture.

It complements `paused-search-02-enrollment-and-start-semantics.md` by defining
what should happen after a lead is routed into the dormant path.

## Problem

A dormant lead is not the same as a paused-search lead.

With dormant leads, the business does not know why the lead went quiet. The
goal is not to assume a known pause reason. The goal is to re-open the
conversation safely and determine whether the lead is still interested, needs to
be re-classified, or should no longer be nurtured.

Without an explicit dormant-journey design, the system may route a lead to the
dormant path but still lack clear rules for when the path starts, what the first
message should do, and how replies change the lead's state.

## Desired outcome

After this feature is implemented, the app should:

1. start the dormant journey automatically when the configured start rule,
   dormant routing, and safety rules all pass
2. generate dormant outreach from recent conversation context rather than using
   generic copy alone
3. keep dormant outreach low-pressure and administrative
4. re-classify the lead on any meaningful reply before continuing automation
5. hand off immediately when the lead shows active interest or asks for a person

## In scope

- dormant journey start semantics after routing
- dormant message goals and content boundaries
- use of recent conversation context and known preferences
- reply-driven re-classification rules for dormant leads
- relationship to handoff, suppression, and blocked states

## Out of scope

- paused-search timing and reactivation behavior
- MLS or IDX listing recommendations
- live market data integrations
- provider-specific delivery behavior
- detailed admin UI layout

## Plain-language model

- **Dormant**: the lead is quiet and there is no known pause reason.
- **Dormant journey**: the low-pressure outreach path used to ask whether the
  lead is still interested and whether circumstances changed.
- **Meaningful reply**: a reply that gives new signal about interest, timing,
  human handoff, blocking state, or lack of clarity.
- **Re-classification**: re-reading the updated conversation to decide whether
  the lead is still dormant or now belongs in another state.

## Core principle

Dormant means **unknown reason**, not **known delayed timing**.

The dormant path should therefore try to learn what changed, not pretend the app
already knows why the lead stepped back.

## Relationship to other docs

- Doc 1 defines paused-search as explicit structured state.
- Doc 2 defines that `ai_nurture` is the hard gate and that paused-search beats
  dormant when both could apply.
- This document defines what the dormant path does after dormant routing wins.
- Paused-search track and long-wait behavior remain defined in Docs 3 and 4.

## Dormant journey entry rules

### Rule 1: `ai_nurture` is still mandatory

The dormant path must not start unless the configured `ai_nurture` tag is
present.

### Rule 2: dormant starts only when dormant routing wins

The dormant path may start only when:

- no higher-priority handoff or blocked state exists
- no active paused-search state exists that should take precedence
- dormant routing is the current application-owned outcome

### Rule 3: dormant start is automatic after routing and safety checks

Once a lead is classified as dormant, the configured tag is present, dormant
routing wins, and the normal enrollment/start rules pass, the dormant path
should start automatically.

V1 should not require a second manual per-lead approval step after those rules
have already passed.

## Dormant message drafting rules

### Rule 4: use recent conversation context

Dormant messages should be drafted from the lead's recent conversation context,
recent summary, and already-known preferences where available.

The message should sound connected to what the lead previously discussed rather
than like a generic blast sent with no memory.

### Rule 5: dormant message goals are narrow

Dormant outreach should focus on goals such as:

- asking whether the lead is still interested
- asking whether timing changed
- asking whether preferences changed
- offering reconnection with the assigned agent
- inviting the lead to reply if they want help

### Rule 6: dormant outreach stays low-pressure

Dormant messages should be administrative, respectful, and light-touch.

The dormant journey should not assume the lead is ready now, and it should not
sound like aggressive sales outreach.

### Rule 7: dormant outreach does not invent listings or market facts

In V1, the dormant journey may reference approved brokerage links or approved
static resources.

It must not:

- invent listing recommendations
- claim specific inventory changes without an approved source
- claim market changes without an approved source
- act like a live property-matching assistant

## Implementation note

The current implementation reuses the shared outbound planning and send pipeline
rather than creating a dormant-only send path.

That means:

- dormant cadence execution builds the normal approved outbound lead context
- drafting receives an explicit dormant journey hint so the prompt stays
  low-pressure and administrative
- the final pre-send safety gate still runs through the shared pre-send decision
  and the locked `send_outbound_message` use case immediately before provider
  send

This keeps dormant outreach aligned with the same idempotency, locking,
frequency-limit, quiet-hours, handoff, and suppression rules used elsewhere in
the platform.

## Reply-driven re-classification for dormant leads

### Rule 8: any meaningful reply pauses the old assumption

If a dormant lead replies, the system must not continue the dormant journey
blindly.

Instead, it must re-read the updated conversation and make a fresh
classification decision.

### Rule 9: reply-time outcomes are bounded

After reply-time re-classification, the lead may:

- remain `dormant`
- move to `paused_search`
- move to `human_handoff`
- move to `review_hold`
- move to `rejected_or_blocked`

### Rule 10: active-interest replies go to handoff

If the reply shows active interest, asks for listings, requests a person, or
otherwise needs human handling, the dormant journey must stop and the lead must
go to handoff.

### Rule 11: known pause reasons move the lead out of dormant

If the reply reveals a clear pause reason such as rates, lease timing,
inventory, finances, or life timing, the lead should be re-classified into the
paused-search path rather than staying in dormant.

### Implementation note: reply-time reroute happens before AI continuation

When a dormant workflow receives a meaningful inbound reply and the inbound
decision would otherwise continue AI, the system now re-runs the AI-nurture
route before drafting the next automated follow-up.

That reroute uses:

- the newly saved inbound reply
- the latest saved conversation summary
- the recent CRM conversation context already approved for classification

If the refreshed route is no longer `dormant`, the system blocks automated
continuation and pauses the workflow safely instead of sending a stale dormant
follow-up.

## Operational outcomes

Once started, the dormant journey should be able to result in:

- continued dormant follow-up
- re-classification into paused-search
- human handoff
- blocked/suppressed stop
- review hold for human review

## Open questions to confirm during review

1. Should dormant outreach include approved brokerage links by default or only
   when enabled per workspace?
2. What is the preferred first-touch channel for dormant outreach when both SMS
   and email are available?
3. After a reply that still reads as dormant, should the journey restart its
   cadence from the beginning or resume from the next step?

## Definition of done

This feature is complete when:

- the dormant path has explicit start rules after routing
- dormant message goals and content boundaries are approved
- use of conversation context in dormant drafting is approved
- reply-driven re-classification for dormant leads is approved
- the team can explain how dormant differs from paused-search in business terms

Current implementation status:

- dormant drafting uses recent summary, recent approved conversation context,
  and known preferences
- dormant prompts are explicitly constrained to low-pressure re-engagement goals
- final send safety still runs through the shared locked pre-send gate
- reply-time rerouting now happens before AI continuation after inbound replies
- reply-time paused-search reroutes now pin the paused-search track and queue
  workflow rescheduling before stale dormant continuation is paused
- ambiguous silent leads with no workflow now have a dedicated operator
  review-hold resolution action that can explicitly start dormant or
  paused-search follow-up

Deferred later-phase follow-up:

- review-hold resolution for already-active workflows is still a broader
  cross-phase workflow-management problem and is not closed by this document
- route-decision auditing still depends on artifacts plus workflow state rather
  than a dedicated single decision record