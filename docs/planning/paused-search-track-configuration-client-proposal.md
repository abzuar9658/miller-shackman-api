# Paused-Search Track Configuration

## Client Review Proposal

**Status:** For client review and product approval  
**Scope:** Paused-search track configuration and verification  
**Audience:** Brokerage administrators, operations owners, product stakeholders, and implementation team

> This document describes the proposed product direction. It is not an implementation plan. After client review and approval, the team will create a phase-by-phase implementation plan.

## Executive recommendation

Allow brokerage admins to create as many paused-search track categories as they need, while configuring each track through guided business policies, safe defaults, validation, and a clear behavior preview.

Do not force every brokerage to use one fixed workflow. Also do not require admins to design workflows from low-level technical settings without guidance.

The recommended model is:

> **Unlimited track categories + guided behavior policies + bounded customization + publish validation + time-machine verification.**

This gives admins meaningful control while preventing configurations that are technically valid but operationally unsafe or inconsistent with the lead's stated preference.

## Why this approach is needed

A paused-search track is more than a name and a sequence of messages. It defines:

- when a lead may be contacted
- whether the lead's requested timing is respected
- whether interim check-ins are allowed
- what happens when timing is missing or vague
- when automation ends
- when a human agent should be involved

The current low-level controls are powerful, but an admin could combine them in a way that saves successfully while producing the wrong business behavior. The dashboard should therefore ask business questions directly and translate the answers into a validated workflow.

## What admins should be able to configure

For each track, admins should be able to configure:

- Track name, description, and classification guidance
- Whether the track is enabled for assignment
- Waiting-period policy
- Whether interim check-ins are allowed
- Required lead permission for interim check-ins
- Interim check-in interval and maximum number
- Behavior when timing is missing or vague
- Reactivation date behavior
- Number and timing of reactivation follow-ups
- Channel and channel order
- Approved message goals, templates, and AI profile
- Per-step action: send automatically, require review, create a reminder instead, or skip
- Optional agent reminder or task behavior for each cadence step
- Completion behavior

Admins should not be able to disable code-enforced protections such as consent, suppression, opt-out handling, quiet hours, frequency limits, human handoff, ownership checks, pre-send checks, idempotency, audit logging, or stale-workflow protection.

### Per-step action choices

Agent reminders are optional. They are not automatically created for every track or every cadence step.

For each step, the admin may choose one of these actions:

- Send automatically after all safety checks pass
- Require an agent to review the drafted message before sending
- Create an agent reminder instead of sending automatically
- Skip the step

These choices may differ between interim maintenance, reactivation, and final follow-up steps. A reminder can be configured for one step without making reminders mandatory for the entire track.

## Guided starting policies

Each new track should start from one of these policies. Presets provide safe starting values; admins may customize supported settings.

### 1. Wait until requested date

- Automation pauses immediately.
- No automated contact occurs before the lead's requested date.
- The configured action for the reactivation step is applied on or after the date: automatic send, agent review, optional reminder, or skip.
- If automatic sending is selected, one controlled check-in occurs only if all safety checks pass.
- Any reply stops automation and returns ownership to the assigned agent.

### 2. Permission-based interim check-ins

- Automation pauses immediately.
- Interim messages are allowed only when the lead explicitly agreed to periodic contact.
- Messages are limited by a configured interval and touch cap.
- The lead's requested date remains the reactivation boundary.
- Any reply, opt-out, human activity, or handoff stops the sequence.

### 3. Agent-managed follow-up

- No automated messages are sent.
- The lead remains paused.
- An assigned-agent task or reminder may be created if that step is configured to create one.
- The agent must explicitly resume or take ownership.

### 4. Scheduled reactivation

- The track uses a known future date or approved date rule.
- Automation remains paused until the date.
- A bounded follow-up sequence may begin after the date.
- Current eligibility and safety checks run before every action.

### 5. Custom bounded track

Admins may create a custom track, but it must still define a waiting policy, missing-timing behavior, reactivation behavior, bounded touches and duration, channels, and terminal behavior. Arbitrary if/then rules and safety bypasses are not supported.

## Timing principles

The lead's stated timing takes priority over an administrator's preferred cadence.

The system should distinguish:

- when the lead was classified
- when timing was captured
- the requested re-engagement date
- the earliest automated contact date
- the next maintenance action
- the next reactivation action
- any configured agent reminder date

If a lead says, “Contact me in three months,” the system must not silently send a monthly message unless the selected policy permits interim contact and the required lead permission exists.

If timing is vague, such as “when rates improve,” the system must not invent a date. The track should hold for review, keep the lead paused, or apply an explicitly approved fallback policy.

## Reply handling and repeatable paused-search cycles

A paused-search track may support ongoing, low-pressure follow-up, but it must define what happens when the lead replies. A reply must never be treated as permission to continue sending without reclassification.

For every inbound reply:

1. Cancel or invalidate pending automated actions for the lead.
2. Re-run the structured classification using the latest reply and approved recent context.
3. Apply hard outcomes first: opt-out, do-not-contact, request for a person, meaningful interest, human activity, or other handoff conditions stop or redirect automation.
4. If the result is still an approved paused-search outcome, apply the track's configured reply policy.
5. Re-check consent, suppression, ownership, quiet hours, frequency limits, timing, and caps before scheduling anything new.

The admin must choose the reply policy for each repeatable track. Supported bounded choices are:

- Continue with the next step in the current cycle
- Restart the current cycle after a configured delay
- Re-anchor the next cycle to a newly stated date or timing boundary
- Hold for agent review or create an optional agent reminder
- End the track

“Restart” must not mean resetting safety limits. Touch counts, total duration, AI interaction limits, and audit history remain cumulative across every cycle. The system must also prevent a reply loop from creating an unbounded conversation.

### Example: waiting for rates

For a lead who says, “I am waiting for rates to come down, maybe after six months,” an admin could configure:

- a six-month earliest reactivation boundary
- monthly low-pressure maintenance messages only when the lead has explicitly agreed to interim contact
- SMS and email as sequential channels, never simultaneous by default
- a per-step action such as automatic send, review, optional reminder, or skip
- a reply policy of continue, restart after a delay, re-anchor to updated timing, review, or end
- cumulative touch, duration, and AI-interaction caps

If the lead replies during the sequence and classification still indicates waiting for rates, the system can continue or begin another bounded cycle according to that policy. It must preserve the original or newly stated timing boundary and must not blindly repeat step one. If the lead says rates have improved, requests a person, shows buying interest, opts out, or becomes subject to human activity, the waiting-for-rates track stops and the appropriate handoff or suppression path takes precedence.

The lead's statement about waiting for rates does not by itself grant permission for monthly SMS or email. Existing consent for each channel and the approved interim-contact policy are required. If the required permission is absent, the system must not send; it may remain paused, require review, or create an optional reminder.

## Dashboard experience

The setup flow should guide admins through:

1. Choose a starting policy.
2. Define the lead situation and exclusions.
3. Configure timing and interim-contact behavior.
4. Configure the action for each step, including whether an optional agent reminder is created.
5. Define what happens after each possible reply classification, including whether the track continues, restarts, re-anchors, pauses, or ends.
6. Choose channels and approved content.
7. Review the visual timeline and plain-language summary.
8. Fix validation findings.
9. Save a draft and run an exact preview.
10. Confirm and publish the version.

The dashboard should show a timeline such as:

> Lead says “contact me in three months” → automation pauses → no contact before the requested date → apply the configured step action (automatic send, review, optional reminder, or skip) → classify any reply → continue, re-anchor, review, hand off, suppress, or end according to the published reply policy.

## Validation and publishing

A track must not be publishable merely because required fields are present. Server validation must check behavior combinations, including:

- interim interval configured while interim contact is disabled
- contact scheduled before a strict requested date
- no behavior for missing or vague timing
- no allowed channel or invalid fallback channel
- unbounded touches or duration
- no terminal behavior
- incompatible review and automatic-send settings
- a reminder configured for a step that has no valid due time or assigned-agent scope
- a repeatable track with no reply policy
- restart or continuation configured without cumulative touch, duration, and AI-interaction caps
- a reply policy that could schedule contact before the original or newly stated timing boundary
- simultaneous SMS and email where the track has not explicitly enabled that behavior
- cadence steps exceeding the track's duration

Errors block publishing. Warnings require explicit administrator confirmation. Each finding should include the affected field, problem, business impact, and correction guidance.

Before publishing, the admin should approve a plain-language summary generated from the actual saved configuration. The summary and configuration version should be retained in the audit history.

## Verification requirement

The feature will not be considered complete after the UI and backend compile. It must be verified with a deterministic time-machine test harness using fake CRM, messaging, LLM, notification, and workflow dependencies.

Required scenarios include:

- exact three-month wait
- permitted monthly interim check-ins
- monthly cadence without lead permission
- configured reminder at one step and no reminder at other steps
- configured automatic send with no reminder created
- configured review-before-send behavior
- reply that remains waiting for rates and follows the configured continuation policy
- reply that remains waiting for rates but reaches cumulative caps
- reply that updates the requested timing and re-anchors the next cycle
- reply that changes intent and triggers handoff instead of restarting the track
- repeated replies with pending messages cancelled and no duplicate cycle created
- vague timing with no guessed date
- reply before a scheduled action
- agent activity before a scheduled action
- opt-out and suppression
- reassignment
- track version changes after assignment
- provider failure and uncertain send status
- workflow restart and long-wait recovery

For each scenario, verification must inspect workflow state, scheduled actions, outbound messages, optional agent tasks, CRM updates, handoffs, classification artifacts, timing boundaries, cumulative counters, and audit events. Tests must confirm that no reminder is created when the step is configured without one, and that no pending message survives a reply or reclassification.

## Definition of done for client approval

The proposal is ready for implementation when the client agrees on:

- which starting policies are needed
- whether interim contact is allowed and under what permission model
- what happens when timing is missing or vague
- which individual steps, if any, should create agent reminders
- what happens at reactivation
- what should happen when a lead replies and remains in the same paused-search category
- whether a reply may continue, restart, or re-anchor a cycle, and the required delay for each
- the cumulative touch, duration, and AI-interaction caps for repeatable tracks
- how much customization admins need
- which warnings require confirmation

The implementation is done only when the actual runtime behavior matches the dashboard summary and all time-machine scenarios pass. No feature should be declared complete before that testing is performed.

## Client review questions

1. Which paused-search track types should be available as starting policies?
2. Should “contact me in three months” always prohibit interim automation by default?
3. If interim contact is allowed, what exact lead permission is required?
4. What should happen when the lead gives vague timing?
5. Should reactivation send one message, create an agent task, or support both options?
6. Which channels and channel order should be the default?
7. When a lead replies but remains in the same paused-search situation, should the track continue, restart after a delay, re-anchor to updated timing, require review, or end?
8. What explicit permission is required for recurring monthly SMS and email check-ins?
9. What cumulative limits should apply across repeated cycles?
10. Which settings may admins customize freely, and which require manager or admin confirmation?
11. Are there brokerage-specific policies that must be represented before implementation begins?

## Related internal references

- `docs/planning/paused-search-03-nurture-tracks.md`
- `docs/planning/paused-search-04-timing-and-reactivation.md`
- `docs/planning/paused-search-test-matrix-and-verification-plan.md`
- `docs/planning/paused-search-track-control-and-recurring-maintenance-plan.md`
