# Paused-Search Track Control and Recurring Maintenance Plan

## Purpose

Define how admins can change paused-search behavior while the application keeps
ownership of safety, workflow state, and send eligibility.

This plan extends the existing paused-search track model. It does not create a
generic workflow or rules engine.

## Product decision

Paused-search tracks are **bounded, versioned configurations**.

Admins configure approved phases, steps, timing, channels, templates, and repeat
limits. The application owns safety rules, valid state transitions, maximum
limits, and final send decisions.

## What admins can control

Admins may configure, within platform limits:

- Which track is active for each approved pause reason
- Phase sequence, such as maintenance and reactivation
- Step timing:
  - after phase start
  - after the previous step
  - before pause end
  - before a customer-provided date
  - repeating interval
- Maintenance interval, such as every 30 days
- Maximum repetitions and total attempts
- Default pause duration and reactivation timing
- Channel and approved fallback channel
- Template key and message goal
- Manual review required or not
- Whether a customer-provided date affects scheduling
- Track-specific notification preferences

Example: financial preparation may use an email check-in every 30 days, up to
six times, followed by one reactivation message.

## What the application controls

These rules remain code-owned and cannot be bypassed by track settings:

- Consent, opt-out, suppression, and do-not-contact precedence
- A2P 10DLC requirements for SMS
- Quiet hours and frequency limits
- Ownership and recent human-activity checks
- Stop-on-reply and stop-on-agent-activity behavior
- Human handoff and review-hold rules
- Valid workflow state transitions
- Maximum track duration and maximum automated attempts
- Allowed channels, template keys, and pause-reason capabilities
- AI interaction limits and listing-context safety rules
- Idempotency, locking, retries, and pre-send checks

## Bounded recurring maintenance

Recurring steps are supported, but always require limits:

- Minimum and maximum interval
- Maximum repetitions
- Maximum total touches
- Maximum track duration
- No overlapping active pause tracks
- Immediate cancellation on reply, suppression, or human ownership

The UI and backend must both show and enforce the maximum possible outreach before
publishing a track.

## Pause-reason capability profiles

Each approved pause reason should define which settings are available. Examples:

- **Financial preparation:** low-pressure monthly or quarterly check-ins; no financial advice.
- **Waiting for rates:** periodic readiness checks; no rate predictions or financing advice.
- **Lease timing:** reminders relative to the lease-end date and controlled reactivation.
- **Waiting for inventory:** approved listing context only when fresh and authorized.
- **Personal life timing:** lower-frequency, respectful maintenance with fewer attempts.
- **Unclear timing:** conservative cadence or manual review.

Admins configure inside the profile; they do not create new safety categories or
arbitrary conditions.

## Versioning and active workflows

Use the existing draft/publish model:

1. Admin edits a draft.
2. Validation checks the complete track.
3. Publishing creates an immutable version.
4. New enrollments use the latest published version.
5. Existing workflows remain pinned to their version.
6. Migration requires an explicit, permission-controlled, audited action.

Published versions must retain their phases, steps, timing, limits, template keys,
and message goals for audit and replay.

## Admin preview and validation

Before publishing, show a timeline such as:

- January 31 — maintenance check-in
- February 28 — maintenance check-in
- March 31 — maintenance check-in
- July 1 — reactivation

Show warnings for recurring outreach, SMS restrictions, manual review, maximum
attempts, and prohibited content categories.

Reject tracks with invalid phases, unsupported channels, missing templates,
intervals outside limits, excessive repetitions, or no terminal behavior.

## Execution behavior

Temporal executes the pinned published version. It does not invent schedule or
routing behavior.

Before every send, the application re-checks current eligibility, consent,
suppression, ownership, human activity, quiet hours, frequency, channel policy,
and idempotency. A reply or agent action cancels or reclassifies the remaining
track before another step is selected.

## Suggested delivery sequence

1. Finalize pause-reason capability profiles and platform limits.
2. Extend the track schema with timing basis, repeat interval, repetition limit,
   and terminal behavior.
3. Add backend validation, immutable publishing, and audit events.
4. Add recurring and pause-end scheduling to Temporal.
5. Add admin timeline preview, warnings, and publish controls.
6. Add explicit lead migration and live-workflow override tools.
7. Test monthly maintenance, customer-date timing, replies, agent activity,
   version pinning, suppression, and duplicate-send protection.

## Definition of done

This plan is ready for implementation when the team approves:

- The admin-versus-application ownership boundary
- Supported timing modes and recurring-step limits
- Pause-reason capability profiles
- Version behavior for active workflows
- Preview, validation, migration, and audit requirements
