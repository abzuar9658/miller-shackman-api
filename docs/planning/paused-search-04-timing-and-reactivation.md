# Paused Search Feature 04 — Timing and Reactivation

## Purpose

This document defines how paused-search nurture runs over time after Doc 3 has
selected a paused-search track.

Doc 1 defined paused-search state. Doc 2 defined enrollment and routing. Doc 3
defined the nurture tracks. This document defines how the workflow waits,
maintains context, wakes up later, and reacts safely when the re-engagement
window arrives.

## Problem

A paused-search lead may need to wait for weeks, months, or a year before active
re-engagement makes sense.

That creates a product requirement the app must handle reliably:

- remember long timelines without manual follow-up
- wake up at the correct future time
- send optional maintenance touches before full reactivation
- pause immediately if a human or the lead changes the situation
- survive deploys, worker restarts, and delayed external events

Without durable timing behavior, paused-search becomes only a label and track,
not a dependable nurture system.

## Desired outcome

After this slice is implemented, the app should:

1. honor `reengagement_not_before` and related timing fields durably
2. run maintenance touches before the reactivation window when configured
3. enter a stronger reactivation phase near the expected return window
4. re-check safety at every wake-up and send attempt
5. pause or hand off immediately when new facts make the prior timing stale

## In scope

- long-running workflow timing semantics
- maintenance vs reactivation timing phases
- how Temporal should wake, sleep, defer, and resume
- how lead-level overrides or new facts reschedule future actions
- state expectations for paused-search workflows over time

## Out of scope

- detailed track schema and cadence content
- AI extraction prompt behavior
- external listing or rate-feed integrations
- full UI design for lead overrides

## Core timing principle

**Search paused is business state. Workflow paused is engine state.**

A lead may be paused-search for months while the workflow remains valid and
active. The workflow should not enter engine state `paused` merely because the
lead's home-search timeline is delayed.

Use workflow `paused` only when automation must stop because of:

- manual operator pause
- human ownership or handoff
- suppression or policy block requiring explicit resume
- another safety interruption that should stop future sends

## Intelligence note

Any semantic re-interpretation of the lead's timing, readiness, or paused-
search status over time should rely on structured LLM-based understanding of
conversation history, not regex or keyword matching.

Regex is not a serious primary mechanism for deciding whether timing changed,
whether a lead is still paused, or whether the workflow should shift phases.
Use deterministic matching only for intentionally narrow safety/compliance
signals; use LLM extraction plus application rules for the broader timing and
reactivation logic.

## Timing phases

A paused-search track may contain two timing phases:

- **maintenance phase**: low-frequency touches while the lead is still not ready
- **reactivation phase**: closer-in outreach once the lead is approaching the expected return window

The track chosen in Doc 3 defines whether both phases exist and how aggressive
each phase may be.

## Timing rules

### Rule 1: `reengagement_not_before` is the earliest active reactivation date

The app must not begin stronger reactivation behavior before
`reengagement_not_before` unless an authorized lead-level override changes the
schedule.

### Rule 2: maintenance touches may happen before reactivation

If the selected track allows maintenance touches, the workflow may send them
before `reengagement_not_before`, subject to all normal safety rules.

### Rule 3: unknown timing uses the track fallback policy

If `reengagement_not_before` is unknown, the workflow should use the selected
track's fallback timing policy, such as every 60 or 90 days, or hold for review
if the track requires explicit timing.

### Rule 4: reactivation window is relative to the target date

If a track has `reactivation_window_days`, the workflow should enter its
reactivation phase that many days before `reengagement_not_before`.

### Rule 5: new facts may reschedule the workflow

If the lead replies, an operator updates the paused-search profile, ownership
changes, or a manual override adjusts timing, the workflow must recompute the
next scheduled action instead of trusting the stale timer.

## Temporal execution model

Use Temporal as the durable owner of long waits and wake-ups.

Implementation should align this behavior with the existing workflow-state model
and transition guardrails, especially:

- `app/domain/workflows/models.py`
- the existing `WorkflowState` enum and `transition_workflow()` rules
- the Temporal lead-nurture workflow implementation used for current nurture
  execution

At a high level:

1. workflow starts with the pinned published nurture version
2. workflow computes the next action from the current track phase and lead facts
3. Temporal sleeps until the next action time
4. at wake-up, the app re-loads current persisted facts
5. the workflow either sends, defers, pauses, hands off, or reschedules
6. the cycle repeats until the lead is completed, suppressed, closed, or human-owned

## Workflow state expectations

Recommended behavior for paused-search workflows:

- use `active_nurture` while the workflow is durably alive and scheduling future actions
- use `waiting_for_response` after an outbound message when the system is awaiting a reply window
- use `paused` only for explicit stop conditions, not for ordinary long-term waiting
- use `human_handoff` or `human_owned` when a person should take over
- use terminal states only when the nurture path truly ends

This keeps long-term paused-search timing distinct from emergency or manual
stoppage.

Phase transition between maintenance and reactivation should be computed from the
pinned track version plus current persisted lead facts at each wake-up. The
workflow should not trust an old assumed phase if `reengagement_not_before`,
overrides, or paused-search context changed since the prior timer was scheduled.

## Rescheduling triggers

The workflow should recompute `next_action_at` when any of these happen:

- paused-search reason changes
- `reengagement_not_before` changes
- lead-level track override changes
- manual pause or resume occurs
- inbound reply changes the lead's status
- human activity or ownership change is detected
- suppression, consent, or contactability facts change

## Failure and defer behavior

When the workflow wakes up, it should not blindly send.

Possible outcomes at wake-up:

- **send now**: all rules pass and the step is due
- **defer**: temporary operational block, quiet-hours conflict, or temporary automation stop
- **pause**: manual pause, human-owned state, or policy condition requiring explicit resume
- **handoff**: meaningful interest or human-request signal exists
- **suppress/close**: lead is no longer eligible for automated nurture
- **reschedule**: timing changed and a later action is now correct

## Admin and operator controls

Operators should be able to:

- move `reengagement_not_before`
- switch the lead to another approved paused-search track
- pause the workflow manually
- resume after permission checks
- skip the next maintenance touch
- force review when timing or context becomes uncertain

These actions must be auditable and must update the future schedule explicitly.

Normal quiet-hours, frequency-limit, consent, suppression, and contactability
checks still apply at every wake-up and send attempt. Temporal owns durable
waiting, but application rules still decide whether a due action may actually
execute now, should defer, or should stop.

## Versioning behavior over long waits

A lead that entered a paused-search track should keep following the pinned
published version it enrolled into, even if months pass.

Newly published versions affect new enrollments by default. Existing workflows
should migrate only through an explicit admin action that records:

- old version
- new version
- who changed it
- when it changed
- why migration was needed

## Open questions to confirm during review

1. Should a maintenance touch reset when the lead confirms "still not ready"?
2. Should the reactivation window support both absolute dates and season-style labels such as `next spring`?
3. Should a lead-level timing override automatically re-evaluate the whole remaining track or only the next action?
4. Should a paused-search workflow auto-close after a maximum age with no engagement, or stay open until manually ended?

## Definition of done

This feature is complete when:

- long-wait paused-search execution semantics are approved
- maintenance and reactivation phase timing is approved
- workflow-state expectations for ordinary waiting vs true pause are approved
- rescheduling triggers are approved
- version-pinning behavior for long-running workflows is approved
- the team can explain how a year-long paused lead wakes up safely later

## After this feature, the app can...

After this feature is implemented, the app can:

- honor long paused-search timelines durably
- send low-frequency maintenance touches before active reactivation
- wake up at the right future window without manual babysitting
- recompute timing safely when the lead or business context changes
- keep long-running workflows auditable and version-pinned

At that point, the end-to-end paused-search design is complete.
