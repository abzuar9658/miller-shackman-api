# Paused Search Feature 02 — Enrollment and Start Semantics

## Purpose

This document defines how a lead becomes eligible to start AI nurture once the
business has decided to use a single universal enrollment trigger: the
`ai_nurture` tag.

It builds on `paused-search-01-lead-profile.md`.

Doc 1 defined how paused-search is represented. This document defines what the
system should do after `ai_nurture` is present, how paused-search and dormant
paths are chosen, and which parts admins may configure safely.

## Problem

Today CRM tag enrollment behaves like a direct campaign start trigger. That is
not enough for the product we want.

Our business goal is more specific:

- one lead may need paused-search nurture because the reason and timing are known
- another may be dormant with no clear reason
- another may actually need human handoff or review

We need `ai_nurture` to mean **"evaluate this lead for AI nurture"**, not
**"immediately start one generic campaign."**

## Desired outcome

After this slice is implemented, the system should:

1. require `ai_nurture` before any AI nurture path can begin
2. treat the tag as an evaluation gate, not as immediate send approval
3. route the tagged lead into the correct start path: paused-search, dormant, or hold
4. allow admins to configure bounded enrollment behavior without bypassing safety
5. preserve the existing safety model for eligibility, queueing, and pre-send checks

## In scope

- universal enrollment-gate semantics for `ai_nurture`
- routing precedence between paused-search and dormant paths
- start/hold behavior for tagged leads
- admin-configurable enrollment and fallback settings
- relationship to existing eligibility and start-queue rules

## Out of scope

- reason-specific nurture track design
- cadence steps and template selection
- Temporal wait/reactivation behavior
- full AI-router implementation details
- listing-aware or rate-aware integrations

Those belong to Docs 3 and 4.

## Plain-language model

- **Universal enrollment gate**: the lead may only enter any AI nurture path if `ai_nurture` is present.
- **Paused-search path**: the path used when the lead has an explicit active paused-search profile.
- **Dormant path**: the path used when no paused-search profile is active and dormancy rules pass.
- **Held for review**: the lead is intentionally stopped because the app cannot safely decide the right path.
- **Startable candidate**: a routed lead that still passes enrollment eligibility and campaign-start rules.

## Core principle

`ai_nurture` is the only trigger that opens the door.

It does **not** decide:

- which path the lead belongs in
- whether nurture starts immediately
- whether a message may send now
- whether safety rules may be skipped

The application decides those things explicitly.

## Intelligence note

For semantic enrollment interpretation, the app should rely on structured
LLM-based extraction from conversation history, not regex or simple keyword
matching.

Regex is not generic enough to reliably decide whether a tagged lead is truly
paused-search, merely dormant, ambiguous, or showing renewed intent. The final
routing decision still belongs to application rules, but the interpretation
inputs should come from structured LLM output.

Regex or deterministic matching remains acceptable only for narrow safety and
compliance cases, such as explicit opt-out phrases, provider-normalized
unsubscribe signals, or other intentionally bounded checks.

## Current-to-future behavior shift

### Today

`crm_enrollment_tag` directly matches a campaign config and starts normal tag-based enrollment.

### After this feature

`ai_nurture` should first trigger routing:

1. verify the lead is allowed to be evaluated
2. determine whether paused-search is active
3. otherwise evaluate dormant eligibility
4. otherwise hold for review or no-start
5. only then attach the lead to the correct workflow path

## AI Nurture Router component

This feature should be implemented around an explicit **AI Nurture Router**
application component.

The router's job is to:

- consume the internal `ai_nurture` gate signal
- load current lead facts, paused-search state, and recent conversation context
- optionally consume structured LLM analysis or previously accepted review facts
- apply application-owned routing rules
- produce one explicit routing outcome with reason codes and audit details

The router is not a freeform AI agent. It is an application-owned decision point
that uses structured inputs and returns bounded outcomes.

Relevant implementation anchor points include:

- `app/application/use_cases/process_crm_tag_campaign_enrollment.py`
- `app/application/use_cases/run_dormant_selector_batch.py`
- existing campaign-enrollment eligibility and start-queue rules

## Enrollment and start rules

### Rule 1: `ai_nurture` is mandatory

If `ai_nurture` is absent, the lead must not start paused-search nurture or
dormant nurture through this feature.

### Rule 2: tag means evaluation, not immediate messaging

When `ai_nurture` is added, the system may create or refresh an enrollment
candidate, but message sending still depends on later start-queue and pre-send
rules.

### Rule 3: paused-search path has precedence over dormant path

If the lead has an active paused-search profile from Doc 1, the app must route
the lead to paused-search handling before considering generic dormant nurture.

A tagged lead must not be treated as ordinary dormant if explicit paused-search
state already exists.

### Rule 4: paused-search start requires explicit paused-search state

A lead may start the paused-search path only when paused-search is represented as
explicit persisted product state.

This document does not require that the profile be manual forever. Future
AI-assisted extraction may propose or populate the profile, but paused-search
workflow start must still rely on explicit persisted fields, not only ad hoc
prompt output.

### Rule 5: dormant path is the fallback when paused-search is not active

If no active paused-search profile exists, the app may evaluate the tagged lead
against dormant-enrollment rules.

If the dormant rules pass, the lead may enter the dormant path.

### Rule 6: unclear tagged leads fail safe

If the lead has `ai_nurture` but the app cannot safely determine paused-search
or dormant eligibility, the lead must be held for review rather than guessed
into a nurture path.

### Rule 7: tag-based starts count as human approval for start semantics

A lead that enters through `ai_nurture` is treated as a deliberate operator or
agent enrollment action. It should follow the `crm_tag` confirmation behavior:
no additional pre-flight digest is required solely because the lead was tagged.

### Rule 8: existing safety rules still apply

After routing, the selected path must still pass:

- contactability rules
- campaign-enrollment eligibility rules
- campaign start-cap and FIFO rules
- pre-send safety checks
- human-ownership, suppression, and handoff rules

## Routing outcomes

| Condition after `ai_nurture` | Result |
| --- | --- |
| Active paused-search profile exists | Route to paused-search path |
| No paused-search profile, dormant rules pass | Route to dormant path |
| Active paused-search profile exists but timing is unclear | Route to paused-search path with fallback timing or review hold per track/workspace policy |
| Ready-for-handoff signal exists | Hold AI start; handoff wins |
| Human-owned or already-paused human-control state exists | Hold AI start; human-control state wins |
| Suppressed, opted out, or do-not-contact state exists | Reject or suppress per existing safety rules |
| Missing channel consent or missing contactability facts exist | Hold or reject per existing safety rules |
| Facts are unclear or conflicting | Hold for review |

These rows intentionally collapse reason-specific paused-search variants such as
`waiting_for_rates`, `waiting_for_inventory`, or `financial_prep` into the
paused-search family. The router should still preserve the underlying structured
reason and timing facts so Doc 3 can choose the correct track later.

## Admin-configurable settings

Admins may configure bounded policy inputs such as:

- which external CRM tag maps to the internal `ai_nurture` gate
- whether tagged leads without paused-search state should attempt dormant fallback or always go to review
- dormant threshold in days
- accountable-owner requirements before start
- whether review is required for selected low-confidence or conflicting cases

These settings must feed explicit application rules. They must not become a freeform rules engine.

## Non-configurable safety rules

These must remain application-owned:

- `ai_nurture` is required for any AI nurture start through this feature
- paused-search state takes precedence over generic dormant treatment
- tag presence alone never authorizes immediate sending
- opt-out, suppression, do-not-contact, and human-ownership always win
- AI cannot bypass review thresholds or safety rules
- start-time and send-time rechecks remain mandatory

## Data-model implications

This slice likely requires durable fields or records for:

- internal `ai_nurture` gate status and observed timestamp
- routed nurture path type: `paused_search`, `dormant`, `review_hold`, or `rejected`
- route decision reason codes and audit details
- review-required flags and reviewer actions where applicable
- source evidence tying the start path to the tag and lead state

For Slice 2 and Slice 3 to work cleanly, this feature should also define a
reviewable proposal artifact for AI-assisted paused-search interpretation. A V1
artifact should record at least:

- proposal status such as `pending_review`, `accepted`, `edited_and_accepted`, or `rejected`
- proposed reason code, timing fields, and review-hold flags
- model/provider metadata, prompt version, and confidence
- evidence excerpt references or summary references
- reviewer identity, decision timestamp, and final accepted values

This can land as a dedicated proposal table or another explicit review record,
but it should not live only inside transient workflow memory.

## Rule for tag removal after start

`ai_nurture` is mandatory to create or refresh an AI nurture enrollment path, but
removing the tag later should not act as an implicit destructive stop command by
itself.

Once a workflow has already started, the app should re-evaluate current state at
the next safe control point. Explicit pause, suppression, human ownership,
handoff, or operator action should determine whether the workflow stops,
continues, or moves to review.

## Open questions to confirm during review

1. Should tagged leads without an active paused-search profile default to dormant fallback or review-first?
2. Should a tagged lead with a very recent reply be held immediately even before dormant evaluation?
3. Do we want one universal external tag name (`ai_nurture`) for all workspaces, or configurable external aliases mapped to one internal concept?
4. Should managers be able to override a review hold into a chosen path manually?

## Definition of done

This feature is complete when:

- `ai_nurture` is approved as the universal enrollment gate
- paused-search vs dormant routing precedence is approved
- hold/review behavior for unclear tagged leads is approved
- admin-configurable enrollment boundaries are approved
- the team agrees which safety rules remain non-configurable
- we can explain what happens after the tag without jumping straight to one generic campaign

## After this feature, the app can...

After this feature is implemented, the app can:

- treat `ai_nurture` as the single entry point for AI nurture evaluation
- choose paused-search before dormant when both concepts could apply
- send tagged leads into the correct start path instead of one generic path
- hold unclear leads safely for review
- let admins tune enrollment behavior without owning core safety logic

It still will **not yet**:

- define the actual paused-search tracks
- define cadence steps or message goals
- define Temporal waiting and reactivation behavior
- fully specify AI classification and confidence handling
