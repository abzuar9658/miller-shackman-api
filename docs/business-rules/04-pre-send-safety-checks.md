# Pre-Send Safety Check Rules

## Purpose

This document defines the fourth business decision for Phase One:

**Can this exact scheduled SMS or email be sent right now?**

This is the final application-owned gate immediately before calling an SMS or email provider. A lead may have passed contactability, enrollment eligibility, and campaign start selection earlier, but the system must still re-check current state at send time.

## What this decision includes

This rule decides whether one scheduled outbound message may send based on:

- campaign state
- workflow state
- scheduled message state and idempotency
- selected channel and campaign channel policy
- current channel contactability
- pre-flight veto status where applicable
- human handoff or human-owned state
- inbound lead replies since scheduling
- enrollment tag still present on the lead
- brokerage allowed sending hours
- frequency limits across global, campaign, and channel scopes
- stale message or campaign version checks
- channel fallback when the primary channel is explicitly blocked

## What this decision does not include

This rule does **not** decide:

- whether the lead originally qualified for contactability
- whether the lead should enter a campaign enrollment queue
- whether the lead should start the campaign today
- message copy generation or AI personalization
- LLM intent classification
- provider-specific sending behavior
- CRM note writing
- handoff creation
- retry scheduling after temporary provider failures

Those belong to separate rules, use cases, or infrastructure adapters.

## Plain-language definitions

- **Pre-send safety check**: the last rule evaluated immediately before a provider send call.
- **Scheduled message**: a campaign cadence message that the workflow intends to send at a specific time.
- **Sendable workflow state**: a workflow state where automated outreach is allowed, such as `active_nurture` or `waiting_for_response` when no reply has arrived.
- **Enrollment tag**: the configured CRM tag every enrolled lead carries. Its presence is the only CRM-side signal this rule reads. Agent activity in the CRM (messages, calls, notes, tags, stage/status, reassignment) is not an input to this rule.
- **Held for review**: the workflow is transitioned to `paused` with a specific reason code and the triggering evidence recorded, the lead is visible on the dashboard, and the assigned agent is notified. A human resumes or ends it. This replaces silent step skips.
- **Lead reply**: inbound SMS or normalized email reply received after the message was scheduled or generated.
- **Frequency limit**: a configured minimum gap between automated outreach attempts. The strictest applicable limit wins.
- **Idempotency key**: a deterministic key for the outbound send attempt, such as workflow ID + cadence step ID + channel + message version.
- **Provider status uncertain**: a previous send attempt reached an ambiguous state. The step is treated as sent for cadence purposes and is never re-sent; it does not block the next step.
- **Channel fallback**: when the step's channel is blocked by an explicit lead "no" and the other channel is usable, the same message is re-rendered and sent on the other channel; the step is completed, not skipped.

## Safety principles

1. Never trust a stale scheduled message.
2. Re-run safety checks immediately before every provider call.
3. Suppression, opt-out, `DENIED` consent, do-not-contact, and handoff states always block automated sending on the affected channel.
4. Human ownership always wins over automation.
5. Any inbound reply blocks pending automated messages until explicitly handled.
6. Unknown or incomplete safety data must fail safe. Unknown *consent* is not incomplete data; it never blocks.
7. Frequency limits are hard limits.
8. There is no workspace-level SMS compliance (A2P/10DLC) gate in V1.
9. Duplicate send attempts must be blocked by idempotency.
10. This decision must run inside an application transaction with a pessimistic lock on the send-relevant lead/workflow state.
11. A block is never silent. Every blocking outcome other than a timing/frequency deferral either completes the step on the other channel, ends the workflow with a recorded reason, or holds the lead for review with a specific reason.
12. An ambiguous provider outcome never pauses the lead.

## Decision rules

### Rule 1: Campaign and workflow must be sendable

| Condition                                                                                 | Result     |
| ----------------------------------------------------------------------------------------- | ---------- |
| Campaign is active and workflow is in a sendable state                                    | Continue   |
| Campaign is paused, draft, inactive, completed, suppressed, human handoff, or human owned | Block send |

### Rule 2: Message must be current and not already sent

| Condition                                                                  | Result                      |
| -------------------------------------------------------------------------- | --------------------------- |
| Message version matches the active cadence step and has not been sent      | Continue                    |
| Message is stale, cancelled, already accepted by provider, or already sent | Block send                  |
| Idempotency key was already used                                           | Block send                  |
| This step's previous attempt is uncertain                                  | Block re-send of this step; cadence proceeds to the next step |

An uncertain outcome on step N blocks only a re-send of step N (its idempotency key stays claimed). It does not block step N+1, does not pause the workflow, and reconciliation of the message record (to `sent` or `failed`) has no workflow side effect.

### Rule 3: Channel must be allowed now

| Condition                                                                              | Result                                   |
| -------------------------------------------------------------------------------------- | ---------------------------------------- |
| Channel is enabled for campaign and currently contactable                              | Continue                                 |
| Channel is blocked by an explicit "no" (opt-out, unsubscribe, `DENIED`) and the other channel is usable | Send the same message on the other channel |
| Channel is blocked and no other channel is usable                                      | Hold for review (`no_usable_channel`)    |
| Lead is do-not-contact                                                                 | Block send; end workflow                 |

This rule consumes the current contactability decision from `01-lead-contactability.md`; it does not duplicate that logic. `UNKNOWN` consent is not a block. The same rule runs on every send path — cadence, AI reply, operator send-now, draft approval.

Fallback applies to consent blocks only. A permanent provider rejection (invalid number, undeliverable address) is not a consent block: on the standard cadence it holds the lead for review (`provider_failure_exhausted`) and does not re-route the message to the other channel. The paused-search journey keeps its existing per-step configured fallback channel; that is a track configuration, not this rule. The one exception is a carrier-level unsubscribe (Rule 3a).

### Rule 3a: Carrier-level opt-out is an opt-out

| Condition                                                                 | Result                                                             |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| SMS provider rejects the send as "recipient unsubscribed / blocked sender" | Record a durable SMS opt-out for the lead; treat as an explicit SMS "no" |
| ...and email is usable                                                    | Send the same message on email                                     |
| ...and email is not usable                                                | Hold for review (`no_usable_channel`)                              |

The provider's specific error code, not the HTTP status alone, decides this. The recorded suppression is the existing `sms_opt_out` kind with a carrier source; it has the same durability as a lead texting STOP, and a later CRM sync does not clear it. Subsequent sends are then blocked by the ordinary contactability rule (`sms_opted_out`), not by a provider-failure path.

### Rule 4: Human-control conditions must not exist

| Condition                                                                | Result                                          |
| ------------------------------------------------------------------------ | ----------------------------------------------- |
| Enrollment tag present, no lead reply, no active handoff                 | Continue                                        |
| Enrollment tag has been removed from the lead                            | Block send; end workflow (`enrollment_tag_removed`) |
| Lead replied after scheduling                                            | Block send; route the reply                     |
| Lead entered handoff or human-owned state                                | Block send                                      |

Agent activity in the CRM is not a condition in this rule. While the enrollment tag is on the lead, the track continues on schedule regardless of what an agent does in the CRM — a manual text or call, a note, another tag, a stage/status change, or a reassignment. Removing the enrollment tag is the single CRM-side control that stops automation; re-adding it starts a fresh enrollment. An agent who wants the AI to stop while they work a lead removes the tag.

### Rule 5: Pre-flight veto must still be respected

| Condition                                       | Result     |
| ----------------------------------------------- | ---------- |
| Candidate was not vetoed or veto does not apply | Continue   |
| Candidate was vetoed for this campaign/batch    | Block send |

### Rule 6: Timing and frequency must allow the send

| Condition                                                                                       | Result     |
| ----------------------------------------------------------------------------------------------- | ---------- |
| Current brokerage-local time is within allowed sending hours and no frequency limit is exceeded | Continue   |
| Outside allowed sending hours                                                                   | Block send |
| Any applicable global, campaign, or channel frequency limit is exceeded                         | Block send |

Phase One defaults are brokerage timezone, 10 AM to 5 PM allowed sending hours, and no more than one automated outreach attempt to the same lead within 24 hours across all channels.

### Rule 7: Mixed-channel sequencing must be respected

| Condition                                                                                                       | Result     |
| --------------------------------------------------------------------------------------------------------------- | ---------- |
| Campaign allows this channel at this cadence step                                                               | Continue   |
| Campaign does not allow simultaneous SMS and email and another channel was already sent in the protected window | Block send |

## Decision precedence

When multiple blocking conditions apply, evaluate and report in this order:

1. Missing or incomplete required safety data
2. Campaign and workflow state
3. Message state, version, and idempotency
4. Enrollment tag presence
5. Channel policy and contactability (with fallback)
6. Handoff, human-owned state, lead reply
7. Pre-flight veto
8. Allowed sending hours
9. Frequency limits
10. Mixed-channel sequencing

The system may collect multiple reasons for audit, but any one blocking reason prevents the provider call on the evaluated channel. Each blocking outcome must resolve to one of: fallback to the other channel, deferral (timing/frequency), end of workflow, or held for review.

## Outputs the rule must produce

For each scheduled message, the rule should return:

- `allowed`: yes or no
- `channel`: `sms` or `email` — the channel actually used, which may differ from the step's configured channel after fallback
- `evaluated_at`: timestamp of the safety check
- `reasons`: one or more machine-readable reason codes when blocked
- `next_allowed_at`: timestamp when a timing or frequency block may be retried, when computable
- `outcome` when blocked: `fallback_channel`, `deferred`, `workflow_ended`, or `held_for_review`

## Initial reason codes

- `missing_required_data`
- `campaign_not_active`
- `workflow_not_sendable`
- `message_already_sent`
- `message_cancelled`
- `message_version_stale`
- `duplicate_send_request`
- `provider_status_uncertain` (blocks re-send of the same step only)
- `enrollment_tag_removed`
- `channel_not_enabled`
- `channel_not_contactable`
- `no_usable_channel`
- `preflight_vetoed`
- `handoff_active`
- `human_owned`
- `lead_replied_since_scheduled`
- `provider_failure_exhausted`
- `outside_allowed_hours`
- `frequency_limit_reached`
- `simultaneous_channel_not_allowed`

## Configurable inputs

These may vary by workspace, campaign, or channel and should be configurable later:

- brokerage timezone
- allowed sending hours, default 10 AM to 5 PM brokerage time
- global, campaign, and channel frequency limits
- whether a campaign allows simultaneous SMS and email
- campaign channel sequence and cadence steps
- which workflow states are considered sendable

## Hard-coded safety rules

These must stay explicit in code and tests:

- pre-send checks run immediately before every provider call
- any blocking reason prevents sending
- suppression, `DENIED` consent, and do-not-contact cannot be bypassed
- unknown consent never blocks
- an explicit block on one channel with a usable other channel sends on the other channel
- enrollment tag removal ends the workflow; nothing else in the CRM pauses or holds it
- any inbound reply after scheduling blocks pending automated messages
- a carrier-level unsubscribe is recorded as a durable SMS opt-out
- a permanent provider failure holds the lead for review; it does not re-route to the other channel
- handoff and human-owned states block automated sending
- unknown required data fails safe
- idempotency prevents duplicate provider calls
- an uncertain step is never re-sent and never pauses the workflow
- strictest frequency limit wins
- no blocking outcome is silent
- AI output cannot override this decision

## Required unit tests

At minimum, test:

- active campaign and sendable workflow allow evaluation to continue
- inactive campaign blocks sending
- non-sendable workflow state blocks sending
- already sent message blocks duplicate send
- reused idempotency key blocks duplicate send
- stale message version blocks sending
- provider status uncertain blocks re-send of that step and does not block the next step
- uncertain send advances the workflow exactly as a confirmed send
- reconciliation of an uncertain message to sent or failed makes no workflow transition
- channel not enabled blocks sending
- channel explicitly blocked with other channel usable sends on the other channel and completes the step
- channel explicitly blocked with no other channel holds for review
- `UNKNOWN` consent does not block
- enrollment tag removed ends the workflow and blocks sending
- pre-flight veto blocks sending
- active handoff blocks sending
- human-owned state blocks sending
- lead reply after scheduling blocks sending
- manual agent text/call, note, stage change, other tag, and reassignment do not block, pause, or hold while the tag is present
- carrier unsubscribe rejection records a durable SMS opt-out, sends on email when usable, holds for review otherwise
- permanent provider failure on the standard cadence holds for review and does not fall back
- outside allowed hours blocks sending and returns next possible send time when computable
- global frequency limit blocks sending
- campaign frequency limit blocks sending
- channel frequency limit blocks sending
- simultaneous SMS/email protection blocks sending
- multiple blocking reasons return deterministic precedence
- missing required data fails safe

## Database and transaction implications to design later

This rule implies we will likely need durable records for:

- scheduled message state, cadence step, message version, and idempotency key
- workflow state and campaign state
- current contactability inputs or decisions
- inbound reply timestamps
- enrollment tag presence as of the last CRM refresh
- handoff and human-owned state
- pre-flight veto records
- recent automated outreach attempts by lead, campaign, and channel
- provider send attempt status and reconciliation state
- auditable pre-send decisions and reason codes

The application use case must evaluate this rule while holding a pessimistic lock over the send-relevant lead, workflow, and message state so a reply, opt-out, or tag removal cannot race with the provider call.

## Client confirmation questions

Before locking the implementation, confirm:

1. Are default send hours 10 AM to 5 PM in brokerage timezone acceptable?
2. Should the global default frequency limit remain one automated outreach per lead per 24 hours across all channels?
3. Which workflow states should be considered sendable in V1?

Decided 2026-09-04 (see `docs/planning/production-state-consistency-issues.md`, Issues 11–14, 17):
uncertain provider status never pauses the lead and is not retried; only enrollment tag removal
stops the AI from the CRM side and no agent CRM activity holds or pauses it; explicit consent blocks
fall back to the other channel while permanent provider failures hold for review; a carrier
unsubscribe is a durable SMS opt-out; unknown consent never blocks.

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing database schema, APIs, Temporal activities, or provider send orchestration.
