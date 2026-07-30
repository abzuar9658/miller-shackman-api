# Paused Search Feature 02 — Enrollment and Start Semantics

## Purpose

This document defines how a lead becomes eligible to start AI nurture once the
business has decided to use a single universal enrollment trigger: the
`ai_nurture` tag.

It builds on `paused-search-01-lead-profile.md`.

Doc 1 defined how paused-search is represented. This document defines what the
system should do after `ai_nurture` is present, how paused-search and dormant
paths are chosen, and which parts admins may configure safely.

It assumes the lead may already have paused-search state before `ai_nurture` is
added, because AI classification from conversation context can happen earlier
than nurture enrollment.

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
- dormant journey content and message-goal design
- cadence steps and template selection
- Temporal wait/reactivation behavior
- full AI-router implementation details
- listing-aware or rate-aware integrations

Those belong to Docs 3 and 4 plus the dormant journey companion doc.

## Plain-language model

- **Universal enrollment gate**: the lead may only enter any AI nurture path if `ai_nurture` is present.
- **Paused-search path**: the path used when the lead has an explicit active paused-search profile.
- **Dormant path**: the path used when no paused-search profile is active and dormancy rules pass.
- **Human handoff path**: the path used when current lead facts or conversation meaning show that a human should take over immediately.
- **Held for review**: the lead is intentionally stopped because the app cannot safely decide the right path.
- **Startable candidate**: a routed lead that still passes enrollment eligibility and campaign-start rules.
- **AI-first classification**: the app may classify paused-search state from conversation context before nurture enrollment is requested.
- **Reply-time re-classification**: any meaningful inbound reply from a paused-search or dormant lead must re-run classification on the updated conversation before the workflow continues.

## Core principle

`ai_nurture` is the only trigger that opens the door.

Paused-search classification and nurture enrollment are separate decisions.

The app may understand that a lead is paused-search before the lead is approved
to start any paused-search nurture path.

The app may also classify a lead as dormant, handoff-ready, or review-needed
before the tag exists, but none of those classifications may start nurture by
themselves.

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
2. load the current paused-search state, which may have been classified earlier by AI or set by a human
3. otherwise evaluate dormant eligibility
4. otherwise hold for review or no-start
5. only then attach the lead to the correct workflow path

## AI Nurture Router component

This feature should be implemented around an explicit **AI Nurture Router**
application component.

The router's job is to:

- consume the internal `ai_nurture` gate signal
- load current lead facts, paused-search state, and recent conversation context
- optionally consume recent structured AI classification artifacts or previously accepted review facts
- apply application-owned routing rules
- produce one explicit routing outcome with reason codes and audit details

The router is not a freeform AI agent. It is an application-owned decision point
that uses structured inputs and returns bounded outcomes.

## Approved routing outcomes

The router should return one of a bounded set of application-owned outcomes:

- `paused_search`
- `dormant`
- `human_handoff`
- `review_hold`
- `rejected_or_blocked`

Admins may configure which approved paths or subpaths are enabled for a
workspace, but they must still map back to these bounded outcomes. V1 should
not allow admins to invent arbitrary new top-level routing states or bypass
safety rules.

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

If `ai_nurture` is absent, even a high-confidence AI classification must not
start paused-search nurture or dormant nurture.

### Rule 3: paused-search path has precedence over dormant path

If the lead has an active paused-search profile from Doc 1, the app must route
the lead to paused-search handling before considering generic dormant nurture.

A tagged lead must not be treated as ordinary dormant if explicit paused-search
state already exists.

### Rule 4: paused-search start requires explicit paused-search state

A lead may start the paused-search path only when paused-search is represented as
explicit persisted product state.

That persisted state may have come from AI-first conversation classification,
from a human override, or from another approved explicit capture path.

Paused-search workflow start must still rely on explicit persisted fields, not
only ad hoc prompt output.

### Rule 5: dormant path is the fallback when paused-search is not active

If no active paused-search profile exists, the app may evaluate the tagged lead
against dormant-enrollment rules.

If the dormant rules pass, the lead may enter the dormant path.

When dormant routing wins and the existing enrollment/start checks pass, the
lead should start the dormant journey automatically. V1 should not require a
second manual approval step after routing for ordinary dormant starts.

### Rule 6: active-interest and handoff signals beat nurture

If the tagged lead shows active interest, requests a person, or otherwise meets
handoff conditions, the app must route to `human_handoff` immediately rather
than starting paused-search or dormant nurture.

This rule also protects against accidental tagging of a live or newly re-engaged
lead.

### Rule 7: unclear tagged leads fail safe

If the lead has `ai_nurture` but the app cannot safely determine paused-search
or dormant eligibility, the lead must be held for review rather than guessed
into a nurture path.

This includes cases where the latest AI classification is low-confidence,
conflicting with trusted human state, or missing enough timing detail to choose
the right path safely.

### Rule 8: tag-based starts count as human approval for start semantics

A lead that enters through `ai_nurture` is treated as a deliberate operator or
agent enrollment action. It should follow the `crm_tag` confirmation behavior:
no additional pre-flight digest is required solely because the lead was tagged.

### Rule 9: existing safety rules still apply

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
| AI classified paused-search earlier and a human later overrode it | Route from the current persisted human state |
| Active paused-search profile exists but timing is unclear | Route to paused-search path with fallback timing or review hold per track/workspace policy |
| Active-interest or ready-for-handoff signal exists, including accidental tag on a hot lead | Route to handoff immediately; no paused-search or dormant nurture starts |
| Human-owned or already-paused human-control state exists | Hold AI start; human-control state wins |
| Suppressed, opted out, or do-not-contact state exists | Reject or suppress per existing safety rules |
| Missing channel consent or missing contactability facts exist | Hold or reject per existing safety rules |
| Facts are unclear or conflicting | Hold for review |

These rows intentionally collapse reason-specific paused-search variants such as
`waiting_for_rates`, `waiting_for_inventory`, or `financial_prep` into the
paused-search family. The router should still preserve the underlying structured
reason and timing facts so Doc 3 can choose the correct track later.

## Reply-driven re-classification after start

Once a paused-search or dormant path has started, any meaningful inbound reply
must trigger re-classification using the updated conversation context before the
workflow continues.

Possible outcomes after reply-time re-classification include:

- remain in `paused_search` with the same or updated reason/timing
- move to `dormant` if the lead is still quiet or non-committal with no known pause reason
- move to `human_handoff` if the lead shows active interest or asks for a person
- move to `review_hold` if the new evidence is ambiguous or conflicting
- move to `rejected_or_blocked` if opt-out, suppression, or another safety block appears

The workflow must then re-route, pause, reschedule, or stop based on the new
application-owned outcome rather than blindly continuing the previous path.

Dormant-path message drafting and dormant-specific reply behavior should use the
companion technical design in
`dormant-reengagement-01-journey-and-reply-handling.md`.

## Admin-configurable settings

Admins may configure bounded policy inputs such as:

- which external CRM tag maps to the internal `ai_nurture` gate
- whether tagged leads without paused-search state should attempt dormant fallback or always go to review
- which approved path or subpath options are enabled for the workspace, as long as they map back to bounded application-owned outcomes
- dormant threshold in days
- accountable-owner requirements before start
- whether review is required for selected low-confidence or conflicting cases

These settings must feed explicit application rules. They must not become a freeform rules engine.

## Non-configurable safety rules

These must remain application-owned:

- `ai_nurture` is required for any AI nurture start through this feature
- paused-search state takes precedence over generic dormant treatment
- tag presence alone never authorizes immediate sending
- active-interest and handoff signals beat paused-search and dormant nurture
- opt-out, suppression, do-not-contact, and human-ownership always win
- meaningful replies to paused-search or dormant leads trigger re-classification before the workflow continues
- AI cannot bypass review thresholds or safety rules
- admins may tune approved path options but may not create arbitrary top-level routing outcomes
- start-time and send-time rechecks remain mandatory

## Data-model implications

This slice likely requires durable fields or records for:

- internal `ai_nurture` gate status and observed timestamp
- routed nurture path type: `paused_search`, `dormant`, `human_handoff`,
  `review_hold`, or `rejected_or_blocked`
- route decision reason codes and audit details
- review-required flags and reviewer actions where applicable
- source evidence tying the start path to the tag and lead state

For Slice 2 and Slice 3 to work cleanly, this feature should also define a
durable AI classification artifact for lead-state interpretation. A V1
artifact should record at least:

- classification status such as `applied`, `pending_review`, `edited_and_applied`, `rejected`, or `superseded`
- proposed or applied reason code, timing fields, and review-hold flags
- model/provider metadata, prompt version, and confidence
- evidence excerpt references or summary references
- whether the current lead profile was updated directly or held for review
- reviewer identity, decision timestamp, and final accepted values when a human intervenes

This can land as a dedicated classification table plus review record, or as one
explicit artifact that supports both direct AI application and review fallback,
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
- handoff precedence over paused-search and dormant is approved
- hold/review behavior for unclear tagged leads is approved
- reply-driven re-classification behavior is approved
- admin-configurable enrollment boundaries are approved
- the team agrees which safety rules remain non-configurable
- we can explain what happens after the tag without jumping straight to one generic campaign

## After this feature, the app can...

After this feature is implemented, the app can:

- treat `ai_nurture` as the single entry point for AI nurture evaluation
- choose paused-search before dormant when both concepts could apply
- protect accidentally tagged hot leads by routing them to handoff instead of nurture
- send tagged leads into the correct start path instead of one generic path
- re-classify paused-search and dormant leads after meaningful replies before continuing automation
- hold unclear leads safely for review
- let admins tune enrollment behavior without owning core safety logic

It still will **not yet**:

- define the actual paused-search tracks
- define cadence steps or message goals
- define Temporal waiting and reactivation behavior
- fully specify AI classification and confidence handling
