# Paused Search Feature 03 — Nurture Tracks

## Purpose

This document defines the actual paused-search nurture strategies that run after
Doc 2 routes a tagged lead into the paused-search path.

Doc 1 defined paused-search state. Doc 2 defined when `ai_nurture` may route a
lead into paused-search. This document defines what the app should do next:
which track to use, what steps it contains, and what admins may control.

## Problem

Knowing that a lead is paused is not enough. The business needs different
behavior for different situations.

Examples:

- a lead who rented for a year should not get the same cadence as a lead waiting for rates
- a lead waiting for inventory may need light market touches, not hard reactivation
- a lead with unknown timing may need low-pressure maintenance, not frequent outreach

Without track definitions, paused-search is only a label, not an operating
system for nurture.

## Desired outcome

After this slice is implemented, the app should:

1. map paused-search leads into reason-appropriate nurture tracks
2. let admins manage tracks, cadence steps, templates, and channels safely
3. version and publish track changes without mutating active workflows blindly
4. keep paused-search outreach low-pressure, auditable, and compliant

## In scope

- paused-search track selection rules
- track structure and required fields
- cadence-step structure
- content and channel rules
- admin track controls and publishing behavior
- relationship to the current campaign/version model

## Out of scope

- Temporal timer behavior and long waits
- automatic wake-up calculations
- AI extraction prompt design and confidence scoring
- MLS/IDX-driven listing matching
- automated rate-feed triggers

Those belong to Doc 4 or later integrations.

## Core principle

Admins may control **tracks**. The application still controls **safety and
routing outcomes**.

Admins are not building arbitrary workflows from scratch. They are configuring
bounded nurture tracks that fit inside fixed system rules.

## Relationship to existing campaign models

Paused-search tracks must not become a disconnected parallel system with its own
totally separate execution semantics.

Implementation should anchor track design to the existing campaign domain and
admin-version model, especially:

- `app/domain/campaigns/execution.py`
- `app/domain/campaigns/admin.py`

During Slice 4, the team should make one explicit implementation decision and
record it:

- either paused-search tracks are a bounded new entity that compiles down into
  existing campaign execution concepts
- or paused-search tracks are a specialized campaign family built directly on
  top of `CampaignExecutionConfig`, versioned admin models, and cadence-step
  structures

Either choice is valid for V1, but the relationship must be explicit so track
publishing, auditability, and workflow pinning do not drift from the existing
campaign architecture.

## Intelligence note

The choice of paused-search reason inputs, fallback timing interpretation, and
track-selection context should come from structured LLM-based understanding of
conversation history rather than regex or keyword matching.

Regex is too brittle to be the primary decision mechanism for serious paused-
search intelligence because the same business intent may be expressed in many
different ways. Deterministic matching should remain limited to narrow
safety/compliance detections, not semantic track routing.

## Track families

Doc 3 should support three paused-search track families:

- **maintenance**: low-pressure periodic touches while the lead is still paused
- **reactivation**: stronger but still compliant outreach as the re-engagement window approaches
- **agent-owned reminder**: minimal AI outreach, with the main action being a reminder or handoff to the assigned agent

A single track may combine maintenance and reactivation phases.

## Reason-to-track selection

The app should support a default mapping from paused-search reason to track.

| Paused-search reason | Default track behavior |
| --- | --- |
| `rented_temporarily` | long quiet period + occasional maintenance + reactivation before expected return |
| `timing_not_right` | light-touch maintenance + later soft reactivation |
| `waiting_for_rates` | low-pressure value touches + periodic readiness check |
| `waiting_for_inventory` | market-aware maintenance touches, but no property-specific claims without listing data |
| `financial_prep` | supportive non-advisory check-ins + reactivation near expected timing |
| `personal_life_timing` | respectful low-frequency maintenance + reactivation near stated window |
| `other_known_pause` | configurable fallback paused-search track |

If no specific mapping exists, the app should use a workspace default paused-search fallback track or hold for review.

## Track structure

Each paused-search track should include at least:

- `track_key`
- `display_name`
- `track_family`
- `enabled`
- `allowed_channels`
- `default_for_reason_codes`
- `fallback_timing_policy`
- `maintenance_interval_days`
- `reactivation_window_days`
- `max_total_touches`
- `requires_review_before_publish`
- `version_status`
- `published_at`

`max_total_touches` must also respect the broader product-level AI interaction
cap. Paused-search tracks may set stricter limits, but they must not silently
override the code-owned maximum AI back-and-forth policy for a lead and
campaign.

## Cadence-step structure

A paused-search track uses ordered cadence steps compatible with the existing
campaign-step model.

Each step should define:

- `step_order`
- `phase`: `maintenance` or `reactivation`
- `channel`
- `delay_hours` or equivalent delay-from-previous-step behavior
- `message_goal`
- `template_key`
- `max_attempts`
- `review_required`

## Content rules

Track messages should stay administrative, supportive, and low-pressure.

Allowed examples:

- checking whether timing has changed
- offering to reconnect with the assigned agent
- light market-awareness language
- reminding the lead that help is available when ready

Not allowed without later approved features:

- specific listing claims without authorized listing data
- financial, legal, tax, or investment advice
- pretending rates or inventory changed unless an approved data source confirms it
- open-ended long AI conversations beyond the platform's turn limits

## Channel rules

- tracks may be SMS-only, email-only, or mixed
- no simultaneous SMS and email unless explicitly enabled later
- if the preferred channel is blocked, the app may use only an already-approved fallback channel
- channel-level opt-out immediately removes that channel from the track
- all normal pre-send checks still run before every step

## Admin controls

Admins may:

- create draft tracks
- edit cadence steps in draft
- map approved paused-search reasons to tracks
- create workspace-specific reason labels or aliases that still normalize to approved reason families
- change timing parameters within bounded fields
- publish, retire, pause, or replace track versions
- override a lead onto a different approved paused-search track with audit history

Admins may not:

- create new safety outcomes
- bypass handoff or suppression rules
- define arbitrary if/then logic engines
- remove send-time safety rechecks
- make AI the final authority on who gets contacted

## Versioning and publishing

Paused-search tracks should follow the same durable versioning pattern as the
existing campaign admin model:

- admins edit drafts
- publish creates an immutable version
- new leads use the latest published version
- active workflows stay pinned to the version they enrolled into unless explicitly migrated
- migrations must be manual, auditable, and permission-controlled

Lead-level track overrides are allowed only as explicit operator/admin actions
with audit history. They must not create a hidden second source of truth that
conflicts with the pinned published version and selected paused-search reason.

## Recommended product shape

For V1, expose tracks as part of a workspace-level nurture settings experience,
while preserving `campaign`, `campaign_version`, and cadence-step internals for
execution, audit, and reporting.

## Open questions to confirm during review

1. Should `waiting_for_inventory` default to email-first because it may need richer context?
2. Should admins be allowed to create multiple tracks for the same reason and choose a workspace default?
3. Should low-confidence reason extraction route into a fallback track or always require review?
4. Should lead-level track overrides expire automatically when the paused-search reason changes?

## Definition of done

This feature is complete when:

- paused-search tracks are a defined product concept
- the minimum track schema is approved
- step structure and channel/content boundaries are approved
- admin controls and non-configurable safety boundaries are approved
- versioning behavior for active workflows is approved
- the team can explain how different paused-search reasons produce different nurture behavior

## After this feature, the app can...

After this feature is implemented, the app can:

- assign paused-search leads to reason-appropriate nurture tracks
- let admins tune cadence, channels, and templates safely
- preserve auditability through versioned track publishing
- support business-specific paused-search strategies without changing core safety logic

It still will **not yet**:

- define Temporal long-wait execution details
- define exact wake-up behavior around `reengagement_not_before`
- automatically react to rates or listings from external data feeds
