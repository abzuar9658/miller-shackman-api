# Paused Search Feature 01 — Lead Profile

## Purpose

This document defines the first product slice required to make paused-search
lead nurture a first-class workflow in the app.

This slice does **not** yet change enrollment rules, cadence behavior, or
automatic reactivation. It only defines how the system should explicitly
represent a lead whose search is paused for now but likely to resume later.

## Why this slice comes first

The current app can nurture dormant leads and store freeform conversation
summaries, but it does not have a structured way to answer:

- is this lead actively searching or temporarily paused?
- why did they pause?
- when should we think about re-engaging?

Until those facts are modeled explicitly, later features will keep relying on
notes, summaries, and operator memory.

## Problem

Our primary business goal is not generic outreach to any old lead. It is to
nurture leads who are still relevant but have paused their search because of
timing, life circumstances, rates, inventory, or temporary rental decisions.

Today the app can remember parts of that story in conversation text, but it
cannot treat paused-search status as durable product state.

## Current app behavior

Today the app can:

- enroll leads through dormant selection, CRM tag enrollment, or manual start
- store conversation summaries and extracted preferences
- pause on human activity, opt-out, unclear replies, or handoff conditions
- resume manually with permission checks

Today the app cannot:

- mark a lead as a structured paused-search lead
- store a normalized paused-search reason code
- store a normalized target re-engagement timeframe/date
- distinguish paused-search leads from generic dormant leads in the product

## Desired outcome

The app should have a first-class paused-search profile that answers four
questions for each lead:

1. Is the lead currently in a paused-search state?
2. What is the main reason the search is paused?
3. When is re-engagement likely to make sense again?
4. Where did that understanding come from?

This profile must be explicit, reviewable, auditable, and safe to use in later
business rules.

## In scope

- define paused-search as an explicit product concept
- define the V1 paused-search reason taxonomy
- define the minimum structured fields required on a lead/profile
- define source and audit expectations for those fields
- define how this state should be shown in lead details and future filters

## Out of scope

- automatic inference from AI replies
- automatic campaign enrollment into a paused-search nurture flow
- changing cadence timing based on paused-search reasons
- automatic wake-up or scheduled reactivation
- listing-aware outreach behavior
- reporting rollups beyond basic visibility

Those will be handled in later docs.

## User stories

### Brokerage admin / manager

- As an operator, I want to see that a lead is paused rather than lost.
- As an operator, I want to record why the lead paused in a structured way.
- As an operator, I want to record roughly when the lead may be worth
  re-engaging.

### Assigned agent

- As the assigned agent, I want to quickly understand whether a lead paused
  because of rates, timing, renting, or inventory.
- As the assigned agent, I want the app to preserve that context instead of
  forcing me to rediscover it from notes.

### System / future workflow logic

- As the system, I need paused-search status to be explicit so later workflow
  rules can safely decide whether to wait, nudge lightly, or reactivate.

## V1 paused-search definition

A **paused-search lead** is a lead that is still considered potentially viable
for future re-engagement, but is not presently in an active search or immediate
handoff state.

This is different from:

- `not_interested`
- `opted_out`
- `do_not_contact`
- active human handoff
- active live search with immediate buying intent

Paused-search status means the lead is still relevant, but their timeline is not
current.

## V1 paused-search reason codes

Use explicit enums, not freeform status strings.

Initial V1 reason codes:

- `rented_temporarily`
- `timing_not_right`
- `waiting_for_rates`
- `waiting_for_inventory`
- `financial_prep`
- `personal_life_timing`
- `other_known_pause`

### Notes on intent

- `rented_temporarily`: lead decided to rent for a period before resuming a buy
  search.
- `timing_not_right`: lead still intends to move, but not yet, with no more
  specific reason.
- `waiting_for_rates`: lead is explicitly waiting for interest-rate conditions.
- `waiting_for_inventory`: lead is waiting for better-fit listings or more
  market options.
- `financial_prep`: lead is waiting to improve cash position, down payment,
  credit, or related readiness.
- `personal_life_timing`: lead is delayed by school, work, family, relocation,
  lease timing, or similar life events.
- `other_known_pause`: a real pause exists, but it does not fit the initial V1
  taxonomy.

## Proposed profile fields

This feature should introduce a structured paused-search profile with at least:

| Field | Meaning |
| --- | --- |
| `paused_search_active` | Whether the lead is currently considered paused-search |
| `pause_reason_code` | Normalized V1 reason enum |
| `pause_reason_note` | Short operator-visible explanation when needed |
| `reengagement_not_before` | Earliest safe date to actively re-engage, when known |
| `reengagement_window_label` | Human-readable summary such as `next quarter`, `after lease ends`, or `unknown` |
| `paused_search_source` | Where this understanding came from |
| `paused_search_recorded_at` | When the profile was last set or confirmed |
| `paused_search_recorded_by_user_id` | Which internal user recorded it, when applicable |
| `paused_search_last_confirmed_at` | Latest confirmation timestamp if reaffirmed later |

### V1 allowed source values

- `manual_operator_entry`
- `crm_tag_mapping`
- `crm_note_review`
- `inbound_conversation_review`

This slice defines the values but does not require all capture methods to be
implemented yet.

## Business rules

### Rule 1: paused-search is explicit state, not inferred ad hoc

The app must not treat a lead as paused-search just because a freeform summary
sounds like a pause. A paused-search profile must be explicitly recorded.

### Rule 2: paused-search does not override compliance or human-control rules

Paused-search is product context only. It does not bypass:

- consent rules
- suppression rules
- opt-out handling
- handoff rules
- ownership rules

### Rule 3: only one active primary paused-search reason exists at a time

V1 should keep one primary pause reason per lead. Supporting multiple concurrent
pause reasons is unnecessary for the first version.

### Rule 4: unknown timing is allowed

The system may know that a lead is paused without knowing the exact re-engagement
date. `reengagement_not_before` may be null.

### Rule 5: paused-search is not equal to lost

The UI and downstream rules should treat paused-search leads as still viable for
future nurture, unless a separate rule later marks them not interested,
suppressed, closed, or human-owned indefinitely.

### Rule 6: freeform detail is allowed, but the enum is authoritative

Operators may record short notes such as "renewed lease through March" or
"waiting until rates improve," but workflow logic must rely on the structured
reason code and explicit date fields, not arbitrary text.

### Rule 7: semantic paused-search interpretation must not rely on regex

When the system later infers or proposes paused-search state from conversation
history, it must use structured LLM-based interpretation rather than regex or
simple keyword matching as the primary decision mechanism.

Regex or keyword rules are too brittle to serve as the main source of truth for
paused-search reasons, timing, or routing intent. They may still be used for
narrow deterministic safety/compliance cases such as explicit opt-out detection
or provider-normalized suppression events.

## API and UI implications

## Relationship to existing code and models

This product concept should be anchored to the existing canonical lead and lead-
detail surfaces rather than introduced as an isolated side model with no app
integration.

Implementation should cross-check:

- `docs/foundational-data/canonical-lead-record.md`
- the existing lead detail API response shape
- the existing lead persistence model and workspace isolation rules

The final schema may still use dedicated columns or a dedicated table, but the
meaning of paused-search must remain visible as first-class lead state in the
same product surfaces that already expose lead ownership, contactability, and
workflow context.

This slice should eventually surface paused-search profile data in:

- lead detail response
- lead detail page
- future lead list filtering and saved views

Minimum V1 UI expectation after implementation:

- lead detail clearly shows whether paused-search is active
- lead detail shows primary pause reason and timing note/date
- paused-search facts are visible without opening raw notes or handoff history

## Data-model recommendation

For V1, prefer an explicit persisted profile shape over hiding these facts inside
conversation summaries or generic mapped custom fields.

Whether this lands as dedicated nullable lead columns or a dedicated
`paused_search_profiles` table can be decided during implementation, but the
product contract must stay explicit either way.

Recommended bias for V1:

- if we only need the latest active profile, explicit lead-owned columns are the
  simpler path
- if we need historical revisions immediately, a dedicated profile/history table
  may be justified

Because this slice is about product definition, not schema finalization, both are
acceptable so long as the final fields remain explicit and queryable.

## Open questions to confirm during review

1. Do we want `financial_prep` and `personal_life_timing` as separate V1 codes,
   or should they collapse into broader categories?
2. Should `reengagement_window_label` be operator-entered free text, or derived
   from structured date/timeframe inputs only?
3. Do we want paused-search to be visible on the lead list immediately in this
   slice, or only on lead detail first?

## Definition of done

This feature is complete when:

- paused-search is a documented first-class lead concept
- the V1 reason taxonomy is approved
- the minimum structured field set is approved
- source/audit expectations are approved
- the team agrees what this feature does **not** yet automate
- we can truthfully describe the product using paused-search language instead of
  only dormant-lead language

## After this feature, the app can...

After this feature is implemented, the app can:

- explicitly identify a lead as a paused-search lead
- show a normalized reason that the search is paused
- show the best-known re-engagement timing target
- preserve paused-search context as durable product state
- support later enrollment, timing, and messaging features without depending on
  freeform notes alone

It still will **not yet**:

- auto-enroll those leads into a special workflow
- change cadence behavior based on the paused reason
- automatically wake the lead up later
- monitor listings specifically for paused-search re-engagement