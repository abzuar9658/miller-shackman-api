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
- manual agent activity since scheduling
- lead ownership changes since scheduling
- brokerage allowed sending hours
- frequency limits across global, campaign, and channel scopes
- stale message or campaign version checks
- uncertain provider status from a previous send attempt

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
- **Human activity**: CRM-visible activity by an agent or manual dashboard action that indicates a person is handling the lead.
- **Lead reply**: inbound SMS or normalized email reply received after the message was scheduled or generated.
- **Ownership change**: the assigned agent/accountable owner differs from the owner captured when the message was scheduled.
- **Frequency limit**: a configured minimum gap between automated outreach attempts. The strictest applicable limit wins.
- **Idempotency key**: a deterministic key for the outbound send attempt, such as workflow ID + cadence step ID + channel + message version.
- **Provider status uncertain**: a previous send attempt reached an ambiguous state where retrying may create a duplicate message.

## Safety principles

1. Never trust a stale scheduled message.
2. Re-run safety checks immediately before every provider call.
3. Suppression, opt-out, do-not-contact, and handoff states always block automated sending.
4. Human ownership always wins over automation.
5. Any inbound reply blocks pending automated messages until explicitly handled.
6. Unknown or incomplete safety data must fail safe.
7. Frequency limits are hard limits.
8. SMS compliance state may be stored for future use, but it does not block sends in V1.
9. Duplicate send attempts must be blocked by idempotency.
10. This decision must run inside an application transaction with a pessimistic lock on the send-relevant lead/workflow state.

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
| Previous provider status is uncertain                                      | Block send until reconciled |

### Rule 3: Channel must be allowed now

| Condition                                                    | Result     |
| ------------------------------------------------------------ | ---------- |
| Channel is enabled for campaign and currently contactable    | Continue   |
| Channel is disabled, opted out, suppressed, or lacks consent | Block send |

This rule consumes the current contactability decision from `01-lead-contactability.md`; it does not duplicate that logic.

### Rule 4: Human-control conditions must not exist

| Condition                                                                                 | Result     |
| ----------------------------------------------------------------------------------------- | ---------- |
| No lead reply, no recent manual agent activity, no active handoff, and owner is unchanged | Continue   |
| Lead replied after scheduling                                                             | Block send |
| Agent contacted or handled the lead after scheduling                                      | Block send |
| Lead entered handoff or human-owned state                                                 | Block send |
| Assigned/accountable owner changed after scheduling                                       | Block send |

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
4. Channel policy and contactability
5. Handoff, human-owned state, lead reply, manual activity, and ownership change
6. Pre-flight veto
7. Allowed sending hours
8. Frequency limits
9. Mixed-channel sequencing

The system may collect multiple reasons for audit, but any one blocking reason prevents the provider call.

## Outputs the rule must produce

For each scheduled message, the rule should return:

- `allowed`: yes or no
- `channel`: `sms` or `email`
- `evaluated_at`: timestamp of the safety check
- `reasons`: one or more machine-readable reason codes when blocked
- `next_allowed_at`: timestamp when a timing or frequency block may be retried, when computable

## Initial reason codes

- `missing_required_data`
- `campaign_not_active`
- `workflow_not_sendable`
- `message_already_sent`
- `message_cancelled`
- `message_version_stale`
- `duplicate_send_request`
- `provider_status_uncertain`
- `channel_not_enabled`
- `channel_not_contactable`
- `preflight_vetoed`
- `handoff_active`
- `human_owned`
- `lead_replied_since_scheduled`
- `recent_human_activity`
- `ownership_changed`
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
- how recent human activity is detected from CRM data

## Hard-coded safety rules

These must stay explicit in code and tests:

- pre-send checks run immediately before every provider call
- any blocking reason prevents sending
- suppression and do-not-contact cannot be bypassed
- any inbound reply after scheduling blocks pending automated messages
- any manual agent activity after scheduling blocks pending automated messages
- ownership change blocks sending until re-evaluated by an authorized user
- handoff and human-owned states block automated sending
- unknown required data fails safe
- idempotency prevents duplicate provider calls
- uncertain provider status is not blindly retried
- strictest frequency limit wins
- AI output cannot override this decision

## Required unit tests

At minimum, test:

- active campaign and sendable workflow allow evaluation to continue
- inactive campaign blocks sending
- non-sendable workflow state blocks sending
- already sent message blocks duplicate send
- reused idempotency key blocks duplicate send
- stale message version blocks sending
- provider status uncertain blocks retry
- channel not enabled blocks sending
- channel not contactable blocks sending
- pre-flight veto blocks sending
- active handoff blocks sending
- human-owned state blocks sending
- lead reply after scheduling blocks sending
- manual agent activity after scheduling blocks sending
- ownership change after scheduling blocks sending
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
- manual agent activity timestamps
- owner at scheduling time and current owner
- handoff and human-owned state
- pre-flight veto records
- recent automated outreach attempts by lead, campaign, and channel
- provider send attempt status and reconciliation state
- auditable pre-send decisions and reason codes

The application use case must evaluate this rule while holding a pessimistic lock over the send-relevant lead, workflow, and message state so a reply, opt-out, or manual activity cannot race with the provider call.

## Client confirmation questions

Before locking the implementation, confirm:

1. Are default send hours 10 AM to 5 PM in brokerage timezone acceptable?
2. Should the global default frequency limit remain one automated outreach per lead per 24 hours across all channels?
3. How long should manual agent activity block AI sends: any activity after scheduling, or only within a configured recent-activity window?
4. Which workflow states should be considered sendable in V1?
5. Should uncertain provider status always require manual reconciliation, or can some statuses be retried automatically after provider lookup?

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing database schema, APIs, Temporal activities, or provider send orchestration.
