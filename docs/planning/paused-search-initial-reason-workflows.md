> **Superseded for paused-search track routing.** Use
> `paused-search-dynamic-track-classification-correction-plan.md` as the current contract.
> This historical design is retained for context only and must not drive new implementation.

# Paused-Search Initial Reason Workflows & Setup Plan

## Goal

Define the default paused-search workflows for each curated reason and the one-time engineering work needed to make them demo/pilot-ready.

After this setup, admins can change timing, channels, templates, and step order for any existing reason through the UI without engineering.

This document is intended to answer five practical questions:

1. which paused-search reasons we support at launch
2. which default workflow each reason gets
3. what message style each workflow should use
4. what admins will be allowed to change later without engineering
5. what one-time engineering work is still required before the demo or pilot

## What this document defines

This document is the launch-default operating plan for paused-search.

It defines:

- the initial curated reason list
- the default track for each reason
- the default cadence, timing, and tone for each track
- the admin change model for future edits
- the engineering plan needed to make these defaults real

It does not define:

- final production email copy for every message body
- a WhatsApp integration
- a new dynamic workflow engine
- automatic migration of all already-enrolled leads to newly published versions

## Business flow and operator model

The intended paused-search operating flow is:

1. a lead is marked as paused-search
2. the operator or AI-assisted classification assigns one of the approved reason codes
3. the application pins the lead to the currently published track version for that reason
4. the workflow schedules the next maintenance or reactivation step
5. before every send, normal safety and compliance checks still run
6. if an admin later changes the workflow, they publish a new version
7. new leads use the new version; existing leads remain pinned unless explicitly migrated

This keeps paused-search flexible for admins without making workflow behavior unsafe or unpredictable.

## Channel reality at launch

For the initial implementation, the default workflows should be treated as:

- **email-first by default**
- **SMS optional later**, only where consent and workspace compliance already allow it
- **Twilio transport may carry either normal SMS or WhatsApp-style destinations**, but the current product-level channel model still treats that path as `sms`, not as a separate third channel in paused-search configuration

That means a business request like "send email, SMS, or WhatsApp after two months" should be interpreted at launch as:

- email is supported immediately
- SMS can be added to a track if compliance and product rules already allow it
- if the brokerage is using Twilio WhatsApp delivery, that should be described in the product as part of the SMS/Twilio transport path unless and until the app introduces a distinct WhatsApp channel model, separate reporting, or separate compliance treatment

## Reason selection guidance

Use these reasons as the initial operating vocabulary:

- `rented_temporarily`: the lead is committed to a temporary living arrangement and expects to revisit the search later
- `timing_not_right`: the lead is not ready, but no narrower operational reason is known
- `waiting_for_rates`: financing conditions are the main blocker
- `waiting_for_inventory`: the lead is open but does not see enough suitable inventory yet
- `financial_prep`: the lead needs savings, debt reduction, lender prep, or general financial readiness work before resuming
- `personal_life_timing`: family, work, health, relocation, school-year, or life-event timing is the blocker
- `other_known_pause`: the team knows the lead is paused, but the explanation does not fit the curated list cleanly

## Curated reason taxonomy

| Reason code | Business meaning | Default track key |
|---|---|---|
| `rented_temporarily` | Renting for a fixed period; lease ending later | `paused-search-rented-temporarily` |
| `timing_not_right` | General timing is off; no specific trigger | `paused-search-timing-not-right` |
| `waiting_for_rates` | Waiting for interest-rate environment to improve | `paused-search-waiting-for-rates` |
| `waiting_for_inventory` | Waiting for the right listing to hit the market | `paused-search-waiting-for-inventory` |
| `financial_prep` | Saving, paying down debt, or getting financing ready | `paused-search-financial-prep` |
| `personal_life_timing` | Personal/family timing (school, divorce, job change, etc.) | `paused-search-personal-life-timing` |
| `other_known_pause` | Pause reason is known but not covered above | `paused-search-other-known-pause` |

## Initial default workflows

All workflows use **email only** in the initial default. Admins can later add SMS to any track through the UI if the workspace has consent and A2P 10DLC approval. Delays are relative to the phase start or the previous completed step, based on the current timing engine.

The message-goal column below should be treated as the content brief for the template, not just a label. It tells the team what each message is supposed to accomplish.

### rented_temporarily (1-year lease / contract hold)

- `maintenance_interval_days`: 120
- `reactivation_window_days`: 45
- `max_total_touches`: 5
- best for: lease-ending, temporary rental, short-term contract housing, or a deliberate wait until a known date

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 30 days | Welcome-to-pause + set expectations | `paused-search-rented-temporarily-maintenance-email-1` |
| 2 | maintenance | email | 120 days | Quarterly check-in while renting | `paused-search-rented-temporarily-maintenance-email-2` |
| 3 | maintenance | email | 120 days | Planning ahead as lease end approaches | `paused-search-rented-temporarily-maintenance-email-3` |
| 4 | reactivation | email | 0 days | Getting ready to resume search | `paused-search-rented-temporarily-reactivation-email-1` |
| 5 | reactivation | email | 14 days | Two weeks before expected return | `paused-search-rented-temporarily-reactivation-email-2` |

Content intent:

- keep tone calm and low-pressure during maintenance
- acknowledge the lead's existing commitment instead of pushing listings too early
- shift to practical restart language in reactivation

### timing_not_right

- `maintenance_interval_days`: 60
- `reactivation_window_days`: 30
- `max_total_touches`: 4
- best for: vague delay, "circle back later," or a known pause without a stronger specific category

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 30 days | Soft check-in on timing | `paused-search-timing-not-right-maintenance-email-1` |
| 2 | maintenance | email | 60 days | Follow-up on timing | `paused-search-timing-not-right-maintenance-email-2` |
| 3 | reactivation | email | 0 days | Reactivation check-in | `paused-search-timing-not-right-reactivation-email-1` |
| 4 | reactivation | email | 14 days | Final reactivation nudge | `paused-search-timing-not-right-reactivation-email-2` |

Content intent:

- keep the copy generic, polite, and easy to ignore without frustration
- avoid acting as if the team knows the exact blocker

### waiting_for_rates

- `maintenance_interval_days`: 45
- `reactivation_window_days`: 21
- `max_total_touches`: 4
- best for: rate sensitivity, affordability pressure, or leads delaying until financing conditions feel better

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 30 days | Readiness check while watching rates | `paused-search-waiting-for-rates-maintenance-email-1` |
| 2 | maintenance | email | 45 days | Market-rate pulse check | `paused-search-waiting-for-rates-maintenance-email-2` |
| 3 | reactivation | email | 0 days | Reactivate as rate window nears | `paused-search-waiting-for-rates-reactivation-email-1` |
| 4 | reactivation | email | 7 days | Final rate-driven reactivation | `paused-search-waiting-for-rates-reactivation-email-2` |

Content intent:

- stay non-advisory and avoid forecasting rates
- focus on readiness, priorities, and whether the lead wants to re-open the conversation

### waiting_for_inventory

- `maintenance_interval_days`: 30
- `reactivation_window_days`: 14
- `max_total_touches`: 5
- best for: buyers who are active in principle but not seeing the right homes yet

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 14 days | Stay-aware check-in | `paused-search-waiting-for-inventory-maintenance-email-1` |
| 2 | maintenance | email | 30 days | Inventory update offer | `paused-search-waiting-for-inventory-maintenance-email-2` |
| 3 | maintenance | email | 30 days | Another inventory pulse | `paused-search-waiting-for-inventory-maintenance-email-3` |
| 4 | reactivation | email | 0 days | Reactivate as search window opens | `paused-search-waiting-for-inventory-reactivation-email-1` |
| 5 | reactivation | email | 7 days | Final inventory-driven reactivation | `paused-search-waiting-for-inventory-reactivation-email-2` |

Content intent:

- focus on staying aware, not pushing specific unverified listings
- if listing context is ever added, it must use approved, fresh, bounded listing data only

### financial_prep

- `maintenance_interval_days`: 60
- `reactivation_window_days`: 30
- `max_total_touches`: 4
- best for: saving for down payment, improving credit readiness, waiting for lender readiness, or reducing monthly uncertainty

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 60 days | Supportive financial-prep check-in | `paused-search-financial-prep-maintenance-email-1` |
| 2 | maintenance | email | 30 days | Follow-up on financial readiness | `paused-search-financial-prep-maintenance-email-2` |
| 3 | reactivation | email | 0 days | Reactivate as financial prep matures | `paused-search-financial-prep-reactivation-email-1` |
| 4 | reactivation | email | 14 days | Final readiness check | `paused-search-financial-prep-reactivation-email-2` |

Content intent:

- this is the closest match to the example: first touch after two months, then a follow-up one month later
- messages must be supportive and non-judgmental
- do not give mortgage, legal, tax, or investment advice

### personal_life_timing

- `maintenance_interval_days`: 60
- `reactivation_window_days`: 30
- `max_total_touches`: 4
- best for: family timing, job transitions, medical or personal priorities, or similar life-stage pauses

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 30 days | Respectful check-in | `paused-search-personal-life-timing-maintenance-email-1` |
| 2 | maintenance | email | 60 days | Follow-up on personal timeline | `paused-search-personal-life-timing-maintenance-email-2` |
| 3 | reactivation | email | 0 days | Reactivate as personal window nears | `paused-search-personal-life-timing-reactivation-email-1` |
| 4 | reactivation | email | 14 days | Final reactivation nudge | `paused-search-personal-life-timing-reactivation-email-2` |

Content intent:

- preserve empathy and avoid sounding transactional
- keep messages simple and respectful of uncertainty

### other_known_pause

- `maintenance_interval_days`: 90
- `reactivation_window_days`: 30
- `max_total_touches`: 4
- best for: known but uncommon pauses that do not justify a new curated code yet

| Step | Phase | Channel | Delay | Message goal | Template key |
|---|---|---|---|---|---|
| 1 | maintenance | email | 30 days | Gentle generic check-in | `paused-search-other-known-pause-maintenance-email-1` |
| 2 | maintenance | email | 90 days | Follow-up on custom context | `paused-search-other-known-pause-maintenance-email-2` |
| 3 | reactivation | email | 0 days | Reactivate | `paused-search-other-known-pause-reactivation-email-1` |
| 4 | reactivation | email | 14 days | Final reactivation | `paused-search-other-known-pause-reactivation-email-2` |

Content intent:

- use this as a bounded fallback, not a dumping ground for poor classification
- if one subtype appears often, it probably deserves its own curated reason later

## What admins can change later without engineering

Once the initial implementation is complete, admins should be able to change all of the following through the paused-search track UI:

- maintenance delays
- reactivation delays
- email versus supported SMS usage
- step order
- message goal and template assignment
- reactivation window length
- max touches
- which reason maps to which track

The expected operating model is:

1. admin edits a draft track version
2. admin publishes the new version
3. new leads get the new version automatically
4. existing leads stay pinned to the old version unless someone explicitly migrates them

This is the key product promise behind paused-search track configuration. Changing business strategy for an existing reason should not require engineering.

## What still requires engineering

Even after the initial paused-search setup is done, these situations still require engineering:

- adding a brand-new curated reason code
- introducing a distinct product-level WhatsApp channel model with separate UI semantics, reporting, or policy handling
- adding bulk migration for already-enrolled leads
- changing core workflow safety rules, pinning rules, or compliance checks
- introducing new automation behavior outside the bounded track model

## Implementation plan

### Phase 1 — Enrich default track seeding (2–3 days)

- Update `app/application/use_cases/seed_default_paused_search_tracks.py` so each reason gets a multi-step sequence instead of the current two-step default.
- Keep the existing `_DefaultPausedSearchTrackTemplate` but add a per-reason step list.
- Ensure `max_total_touches` matches the number of AI touches in the workflow.
- Add unit tests for the seed output and idempotency.

### Phase 2 — Create template content (2–4 days)

- Add real email body/subject templates for every template key listed above.
- Keep templates bounded and non-advisory: no rate predictions, no guarantee language, no financing advice.
- Include placeholders for lead first name, agent name, and brokerage name.
- Make sure each template reflects the reason-specific content intent documented above.
- Add tests that render each template and verify no prohibited terms leak through.

### Phase 3 — Verify AI classification (1–2 days)

- Confirm the lead-state classifier can map natural-language pause explanations to the 7 reason codes.
- Add representative examples to the prompt or classification tests for each reason.
- Tune confidence threshold if the classifier is uncertain on common phrasing.

### Phase 4 — UI verification (1–2 days)

- Confirm `PausedSearchTracksCard` can display and edit tracks with 4–5 steps.
- Confirm the reason dropdown (`PAUSED_SEARCH_REASON_CODES`) shows all 7 codes with readable labels.
- Confirm the lead-detail page can resolve review holds as paused-search and assign the correct reason.

### Phase 5 — End-to-end testing (2–3 days)

- Run a full paused-search workflow through Temporal for at least two reasons (long hold + short hold).
- Verify phase transitions, step advancement, and reactivation timing.
- Verify publishing a new track version leaves existing leads on the old version and routes new leads to the new version.
- Verify manual lead migration from the lead-detail page.

### Phase 6 — Pilot readiness (1–2 days)

- Document the admin SOP for editing a track and publishing a new version.
- Document the operator SOP for migrating a lead to a new track version.
- Add runbook for paused-search failures and monitoring alerts.

## Definition of done for this document's plan

The paused-search reason-workflow setup is complete only when:

- each curated reason has a seeded published default track
- each step has a real template behind its `template_key`
- the reason classifier can reliably land on the curated codes
- admins can edit a reason track, save draft changes, and publish a new version
- new leads get the latest published version for that reason
- existing leads remain pinned safely unless explicitly migrated
- at least one long-horizon reason and one short-horizon reason have passed end-to-end workflow validation

## Engineering estimates

| Work | Estimate |
|---|---:|
| Phases 1–6 (one-time setup) | 9–16 days |
| Adding a new curated reason later | 0.5–1.5 days |
| Admin edits an existing track (timing, channel, content) | 0 days |
| Migrating one lead to a new track version | 0 days (operator action) |
| Bulk migration tool for many leads | 2–4 days one-time |
| Introducing a distinct product-level WhatsApp channel (instead of using the existing Twilio/SMS transport path) | 1–2+ weeks |

## Operational notes

- Admins edit tracks in **Settings > Paused-search tracks**.
- Changes are saved as a **draft** and only take effect after **publish**.
- Existing leads stay pinned to the version they started on. New leads get the latest published version.
- Operators can migrate an individual lead through the lead-detail page.
- If an admin wants to change `financial_prep` from "email after 60 days, then follow up 30 days later" to a different cadence, they edit the track, publish a new version, and optionally migrate existing leads. No engineering is required.

## Bottom line

The system should ship with a strong default workflow for each of the seven curated reasons, but the long-term product value comes from versioned admin control rather than hard-coded cadence decisions.

Engineering's job is to build the initial rails correctly once. After that, normal reason-level workflow changes should belong to admins and operators, not to the engineering backlog.
