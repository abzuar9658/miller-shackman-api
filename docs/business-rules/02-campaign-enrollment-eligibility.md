# Campaign Enrollment Eligibility Rules

## Purpose

This document defines the second business decision for Phase One:

**Can the system treat this lead as eligible to enter a campaign enrollment queue?**

This decision is intentionally narrower than starting outreach.

## What this decision includes

This rule decides whether a lead may become an enrollment candidate based on:

- the enrollment source
- the dormant-lead threshold
- whether activity data is reliable enough to evaluate dormancy
- whether at least one campaign-enabled channel is currently contactable
- FIFO priority for capped campaign starts

## What this decision does not include

This rule does **not** decide:

- whether a message should send right now
- quiet hours
- frequency limits
- pre-send safety checks
- pre-flight digest veto handling
- workflow pause, resume, or handoff behavior
- inbound reply handling
- message sequencing between SMS and email
- API authorization for who is allowed to apply tags or launch campaigns

Those belong to later rules.

## Plain-language definitions

- **Enrollment source**: the mechanism that made the lead a candidate for AI nurture.
- **Configured CRM tag enrollment**: a lead becomes a candidate because an authorized CRM tag mapped to internal `nurture_enroll` is present.
- **Dormant selector enrollment**: a lead becomes a candidate because the system determines there has been no meaningful communication for at least the configured threshold.
- **Meaningful communication**: a CRM-visible interaction that should reset dormancy, such as agent outreach, lead replies, or other configured communication activity.
- **Eligible candidate**: a lead that may enter the campaign queue for later start processing.
- **Contactable channel**: a channel currently allowed by the contactability rule in `01-lead-contactability.md`.

## Safety principles

1. V1 enrollment must stay simple: configured CRM tag or simple dormant selector only.
2. Do not build a dynamic enrollment rules engine in Phase One.
3. If CRM activity is incomplete or uncertain, do not treat the lead as dormant.
4. Hard exclusions remove a lead from eligibility; they do not lower a score.
5. Use FIFO ordering for capped campaign starts, not weighted scoring.
6. AI does not decide enrollment eligibility.

## Valid enrollment sources

### Allowed in Phase One

| Source                 | Allowed | Notes                                                        |
| ---------------------- | ------- | ------------------------------------------------------------ |
| Configured CRM tag     | Yes     | Explicit or bulk enrollment trigger mapped from CRM data     |
| Daily dormant selector | Yes     | Simple rule such as no meaningful communication for 60+ days |

Configured CRM tag enrollment is normally used for targeted batches. Large dormant populations should use the daily dormant selector instead of manual tagging.

### Not allowed in Phase One

| Source                                                                                | Allowed | Result  |
| ------------------------------------------------------------------------------------- | ------- | ------- |
| Dynamic rule combinations across stages, teams, offices, sources, or score thresholds | No      | Exclude |
| Weighted lead scoring                                                                 | No      | Exclude |
| Imported list outside the CRM                                                         | No      | Exclude |

Imported lists must first exist in the CRM and then be tagged or categorized there.

## Enrollment decision rules

### Rule 1: Determine the candidate source

| Condition                                               | Result                                         |
| ------------------------------------------------------- | ---------------------------------------------- |
| Configured CRM enrollment tag is present                | Candidate source is `crm_tag`                  |
| No configured tag, but dormant selector conditions pass | Candidate source is `dormant_selector`         |
| Neither source applies                                  | Not eligible                                   |
| Both sources apply                                      | Treat the source as `crm_tag` for auditability |

### Rule 2: Dormant selector rules

| Condition                                                         | Result                                |
| ----------------------------------------------------------------- | ------------------------------------- |
| No meaningful communication for at least the configured threshold | Dormant condition passes              |
| Meaningful communication exists within the threshold window       | Not eligible through dormant selector |
| CRM activity is incomplete, missing, or unreliable                | Not eligible through dormant selector |

The default dormant threshold starts at 60 days and remains configurable.

### Rule 3: Contactability dependency

| Condition                                                      | Result                        |
| -------------------------------------------------------------- | ----------------------------- |
| At least one campaign-enabled channel is currently contactable | Candidate may remain eligible |
| No campaign-enabled channels are currently contactable         | Not eligible                  |

This rule depends on the contactability decision from `01-lead-contactability.md`.

This is an eligibility requirement, but it does **not** replace later send-time rechecks. A lead that is eligible today may still be blocked later if consent, suppression, ownership, or recent activity changes.

### Rule 4: FIFO priority for capped starts

When a campaign cannot start all eligible leads at once, prioritize the oldest eligible candidates first.

Use these timestamps:

- for `crm_tag` candidates: the time the enrollment tag was applied or first observed
- for `dormant_selector` candidates: the time the lead first crossed the dormancy threshold, such as `last_meaningful_communication_at + threshold`

Do not use weighted scores or subjective rankings in V1.

## Decision precedence

When multiple facts exist, evaluate in this order:

1. Enrollment source validity
2. Dormant-selector data reliability and dormancy threshold
3. Campaign-enabled channel contactability
4. FIFO ordering among the remaining eligible candidates

## Outputs the rule must produce

For each evaluated lead and campaign, the rule should return:

- `eligible`: yes or no
- `source`: `crm_tag`, `dormant_selector`, or `none`
- `eligible_at`: timestamp used for FIFO ordering when eligible
- `reasons`: one or more machine-readable reason codes when not eligible

## Initial reason codes

### Source and scope

- `missing_enrollment_trigger`
- `unsupported_enrollment_source`

### Dormant selector

- `lead_not_dormant`
- `activity_data_incomplete`

### Contactability

- `no_campaign_channels_contactable`

## Configurable inputs

These may vary by workspace or campaign and should be configurable later:

- which CRM tags map to internal enrollment triggers
- the dormant threshold in days
- which CRM activities count as meaningful communication
- which channels are enabled for a campaign
- how activity reliability or completeness is determined from CRM data

## Hard-coded safety rules

These must stay explicit in code and tests:

- only configured CRM tag enrollment and simple dormant selection are allowed in V1
- uncertain CRM activity data blocks dormant enrollment
- no weighted scoring is allowed in V1
- FIFO ordering must use the oldest eligible candidates first
- a lead with no currently contactable campaign channel is not eligible
- AI cannot override these decisions

## Required unit tests

At minimum, test:

- configured CRM tag makes a lead eligible when at least one enabled channel is contactable
- dormant selector makes a lead eligible when the threshold is met and activity data is reliable
- a lead is not eligible through dormant selector when meaningful communication is too recent
- incomplete or uncertain activity data blocks dormant enrollment
- a lead with no contactable enabled channels is not eligible
- unsupported enrollment sources are excluded
- when both tag and dormant source apply, the decision uses deterministic source precedence
- FIFO ordering uses the oldest eligible timestamp first

## Database implications to design later

This rule implies we will likely need durable records for:

- enrollment source and source evidence
- CRM tag timestamps relevant to enrollment
- last meaningful communication timestamp
- activity reliability or completeness status
- campaign-enabled channels
- eligibility timestamps used for FIFO ordering
- auditable ineligibility reasons

## Client confirmation questions

Before locking the implementation, confirm:

1. What exact CRM tag or tags should map to internal campaign enrollment?
2. What CRM activities count as meaningful communication for dormancy?
3. Should manual CRM tag enrollment be allowed even when a lead is not dormant? This document currently assumes yes.
4. Should a lead with zero currently contactable campaign channels be excluded immediately, or kept for later review? This document currently assumes exclude.
5. Should unassigned leads ever be eligible for campaign enrollment, or must an assigned agent always exist before enrollment?

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing database schema or APIs.
