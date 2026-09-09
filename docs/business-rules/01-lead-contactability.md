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

In **Phase One**, the presence of a usable destination is the V1 permission signal. A lead with a mobile number is considered SMS-contactable; a lead with an email address is considered email-contactable. There is no workspace-level SMS compliance (A2P/10DLC) gate in V1. The only consent-based blocker is an explicit lead "no" for a channel: a platform-observed opt-out, a CRM `sms_opted_out` / `email_unsubscribed` flag, or a CRM consent status of `DENIED` for that channel. An `UNKNOWN` consent status never blocks. Do-not-contact always overrides the destination signal on both channels. (Decision recorded 2026-09-04; see `docs/planning/production-state-consistency-issues.md`, Issue 13.)

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
2. Unknown consent never blocks a channel; a usable destination in the brokerage's own CRM is the
   V1 consent basis. Only an explicit "no" (suppression or `DENIED` consent status) blocks.
3. Do-not-contact blocks all automated outreach. When CRM data does not provide an
   explicit do-not-contact value, V1 derives `do_not_contact = false` if any email or
   phone destination is present, otherwise `true`.
4. There is no workspace-level SMS compliance (A2P/10DLC) gate in V1.
5. There is one evaluation mode. The former strict / `require_explicit_automated_permission` split
   is removed; every send path gets the same answer.
6. These rules are application rules, not AI decisions.

## Channel decision rules

### Global blocking rule

| Condition                     | SMS   | Email | Result                                 |
| ----------------------------- | ----- | ----- | -------------------------------------- |
| Lead is marked do-not-contact | Block | Block | Lead is not contactable on any channel |

### SMS rules

| Condition                                            | Result    |
| ---------------------------------------------------- | --------- |
| Lead has SMS opt-out suppression                     | Block SMS |
| CRM SMS consent status is `DENIED`                   | Block SMS |
| No usable SMS-capable phone is present               | Block SMS |
| No explicit SMS "no" and a phone is present          | Allow SMS |

An SMS opt-out suppression is recorded from any of: the lead texting a stop word to the platform, a
classifier-detected opt-out, the CRM `sms_opted_out` flag, or the SMS provider rejecting a send as
"recipient unsubscribed / blocked sender" (carrier-level opt-out, decided 2026-09-04, Issue 12). All
four are the same suppression kind and are durable: a later CRM sync does not clear a
platform-recorded one.

### Email rules

| Condition                                            | Result      |
| ---------------------------------------------------- | ----------- |
| Lead has email unsubscribe suppression               | Block email |
| CRM email permission status is `DENIED`              | Block email |
| No usable email address is present                   | Block email |
| No explicit email "no" and an email is present       | Allow email |

## Decision precedence

When multiple facts exist, evaluate in this order:

1. Do-not-contact
2. Channel suppression or explicit `DENIED` consent status
3. Channel destination present
4. Otherwise block as unavailable

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
- `sms_permission_denied`

(`missing_sms_consent` / `missing_email_permission` remain defined for the removed strict mode and
are no longer emitted by the V1 rule.)

### Email

- `email_unsubscribed`
- `email_permission_denied`

## Configurable inputs

These may vary by workspace and should be configurable later:

- how consent evidence is mapped from CRM or provider data
- how email permission is mapped from CRM or provider data
- suppression keyword mappings from providers
- which provider error codes are treated as a carrier-level opt-out

## Hard-coded safety rules

These must stay explicit in code and tests:

- do-not-contact blocks all channels
- suppression overrides any destination-based permission signal
- a usable SMS destination present allows SMS unless a suppression, `DENIED` consent, or do-not-contact blocks it
- a usable email destination present allows email unless a suppression, `DENIED` permission, or do-not-contact blocks it
- no usable SMS destination blocks SMS
- no usable email destination blocks email
- no workspace-level SMS compliance gate exists in V1
- an `UNKNOWN` consent or permission status never blocks
- the same rule applies on every send path; there is no strict/lenient mode
- AI cannot override these decisions

## Required unit tests

At minimum, test:

- do-not-contact blocks both SMS and email
- SMS opt-out blocks SMS even when a destination is present
- email unsubscribe blocks email even when a destination is present
- a usable SMS destination with `UNKNOWN` consent status allows SMS
- a usable email destination with `UNKNOWN` permission status allows email
- no usable SMS destination blocks SMS
- no usable email destination blocks email
- `DENIED` SMS consent blocks SMS even when a destination is present
- `DENIED` email permission blocks email even when a destination is present
- multiple blocking reasons return deterministic precedence
- missing destination data blocks the channel

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
