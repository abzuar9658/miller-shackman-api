# Lead Contactability Rules

## Purpose

This document defines the first business decision for Phase One:

**Can the system consider this lead contactable for automated outreach on a specific channel?**

Channels in scope:

- SMS
- Email

This decision is intentionally narrower than full message sending.

## What this decision includes

This rule decides whether a lead is contactable on a channel based on:

- whether a usable email address or SMS-capable phone is present
- suppression state
- do-not-contact state
- whether required data is known or unknown

In **Phase One**, the presence of a usable destination is the V1 permission signal. A lead with a mobile number is considered SMS-contactable; a lead with an email address is considered email-contactable. Workspace SMS compliance (A2P/10DLC) and the raw consent/permission status fields are stored for future stricter policy but do not block the contactability decision in V1. Explicit suppression (opt-out, unsubscribe) and do-not-contact always override the destination signal.

## What this decision does not include

This rule does **not** decide:

- whether a campaign is active
- whether a lead should be enrolled
- whether a message should send right now
- quiet hours
- frequency limits
- pre-flight digest vetoes
- recent agent activity
- inbound reply handling
- workflow state

Those belong to later rules.

## Plain-language definitions

- **Contactable**: the platform is allowed to use a channel for automated outreach in principle.
- **Not contactable**: the platform must not use that channel.
- **Unknown**: the system does not have reliable enough data to safely allow the channel.
- **Suppression**: an explicit rule that blocks outreach, even if other data suggests the channel might be allowed.

## Safety principles

1. Suppression always overrides permission.
2. Unknown or uncertain data must fail safe unless a usable channel is present and
   V1 policy treats that presence as sufficient permission.
3. Do-not-contact blocks all automated outreach. When CRM data does not provide an
   explicit do-not-contact value, V1 derives `do_not_contact = false` if any email or
   phone destination is present, otherwise `true`.
4. SMS compliance data may be stored for future use, but it does not block SMS in V1.
5. These rules are application rules, not AI decisions.

## Channel decision rules

### Global blocking rule

| Condition                     | SMS   | Email | Result                                 |
| ----------------------------- | ----- | ----- | -------------------------------------- |
| Lead is marked do-not-contact | Block | Block | Lead is not contactable on any channel |

### SMS rules

| Condition                                  | Result    |
| ------------------------------------------ | --------- |
| Lead has SMS opt-out suppression           | Block SMS |
| No usable SMS-capable phone is present     | Block SMS |
| No SMS suppression and a phone is present | Allow SMS |

### Email rules

| Condition                                      | Result      |
| ---------------------------------------------- | ----------- |
| Lead has email unsubscribe suppression         | Block email |
| No usable email address is present             | Block email |
| No email suppression and an email is present   | Allow email |

## Decision precedence

When multiple facts exist, evaluate in this order:

1. Do-not-contact
2. Channel suppression
3. Channel destination present
4. Otherwise block as unknown or unavailable

## Outputs the rule must produce

For each requested channel, the rule should return:

- `allowed`: yes or no
- `channel`: sms or email
- `reasons`: one or more machine-readable reason codes

## Initial reason codes

### Global

- `do_not_contact`
- `insufficient_data`

### SMS

- `sms_opted_out`
- `missing_sms_consent`

### Email

- `email_unsubscribed`
- `missing_email_permission`

## Configurable inputs

These may vary by workspace and should be configurable later:

- how consent evidence is mapped from CRM or provider data
- how email permission is mapped from CRM or provider data
- suppression keyword mappings from providers
- the source of future workspace SMS compliance state

## Hard-coded safety rules

These must stay explicit in code and tests:

- do-not-contact blocks all channels
- suppression overrides any destination-based permission signal
- a usable SMS destination present allows SMS unless a suppression or do-not-contact blocks it
- a usable email destination present allows email unless a suppression or do-not-contact blocks it
- no usable SMS destination blocks SMS
- no usable email destination blocks email
- workspace SMS compliance does not block SMS in V1
- raw SMS consent or email permission status fields do not block the V1 decision
- AI cannot override these decisions

## Required unit tests

At minimum, test:

- do-not-contact blocks both SMS and email
- SMS opt-out blocks SMS even when a destination is present
- email unsubscribe blocks email even when a destination is present
- a usable SMS destination present allows SMS in V1 regardless of consent status
- a usable email destination present allows email in V1 regardless of permission status
- no usable SMS destination blocks SMS
- no usable email destination blocks email
- workspace SMS compliance does not block SMS in V1
- explicit denied consent or permission does not block when a usable destination is present in V1
- multiple blocking reasons return deterministic precedence
- uncertain or missing data fails safe

## Database implications to design later

This rule implies we will likely need durable records for:

- lead-level do-not-contact state
- channel-specific consent or permission state
- channel-specific suppression state and history
- workspace-level SMS compliance state
- evidence source and timestamp where available
- auditable decision reasons

## Client confirmation questions

Before locking the implementation, confirm:

1. What exact CRM fields or tags represent do-not-contact?
2. What exact CRM fields or provider signals represent SMS opt-out?
3. What exact CRM fields or provider signals represent email unsubscribe?
4. What exact CRM fields identify a usable mobile number and a usable email address?
5. Are there any brokerage-level overrides that should block outreach beyond do-not-contact?

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing the database schema or APIs.
