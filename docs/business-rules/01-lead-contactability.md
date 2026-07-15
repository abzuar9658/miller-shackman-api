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
- channel-specific consent or permission
- suppression state
- do-not-contact state
- workspace SMS compliance state
- whether required data is known or unknown

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

| Condition                                                  | Result    |
| ---------------------------------------------------------- | --------- |
| Lead has SMS opt-out suppression                           | Block SMS |
| SMS consent is unknown and no SMS-capable phone is present | Block SMS |
| SMS consent is denied or unavailable                       | Block SMS |
| SMS consent is unknown and an SMS-capable phone is present | Allow SMS |
| SMS consent is confirmed and no SMS suppression applies    | Allow SMS |

### Email rules

| Condition                                                      | Result      |
| -------------------------------------------------------------- | ----------- |
| Lead has email unsubscribe suppression                         | Block email |
| Email permission is unknown and no usable email is present     | Block email |
| Email permission is denied or unavailable                      | Block email |
| Email permission is unknown and a usable email is present      | Allow email |
| Email permission is confirmed and no email suppression applies | Allow email |

## Decision precedence

When multiple facts exist, evaluate in this order:

1. Do-not-contact
2. Channel suppression
3. Channel consent or permission
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
- `sms_permission_denied`

### Email

- `email_unsubscribed`
- `missing_email_permission`
- `email_permission_denied`

## Configurable inputs

These may vary by workspace and should be configurable later:

- how consent evidence is mapped from CRM or provider data
- how email permission is mapped from CRM or provider data
- suppression keyword mappings from providers
- the source of future workspace SMS compliance state

## Hard-coded safety rules

These must stay explicit in code and tests:

- do-not-contact blocks all channels
- suppression overrides permission
- unknown SMS consent without a usable SMS destination blocks SMS
- unknown email permission without a usable email destination blocks email
- usable channel presence implies channel permission in V1 unless an explicit denial or suppression blocks it
- workspace SMS compliance does not block SMS in V1
- AI cannot override these decisions

## Required unit tests

At minimum, test:

- do-not-contact blocks both SMS and email
- SMS opt-out blocks SMS even when consent exists
- email unsubscribe blocks email even when permission exists
- unknown SMS consent with a usable SMS destination allows SMS
- unknown SMS consent without a usable SMS destination blocks SMS
- unknown email permission with a usable email destination allows email
- unknown email permission without a usable email destination blocks email
- workspace SMS compliance does not block SMS in V1
- confirmed SMS consent allows SMS
- confirmed email permission allows email
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
2. What exact CRM fields or provider signals represent SMS consent?
3. What exact CRM fields or provider signals represent email permission?
4. Should email ever be allowed when permission is unknown, or always blocked in V1?
5. Are there any brokerage-level overrides that should block outreach beyond do-not-contact?

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing the database schema or APIs.
