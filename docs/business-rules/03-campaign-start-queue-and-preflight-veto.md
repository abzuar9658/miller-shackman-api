# Campaign Start Queue and Pre-Flight Veto Rules

## Purpose

This document defines the third business decision for Phase One:

**Which enrollment-eligible candidates actually start AI outreach now, and which ones are held back?**

This decision takes the output of the enrollment-eligibility rule and narrows it further based on campaign state, daily caps, enrollment source, agent assignment, dormant age, and the pre-flight digest veto window.

## What this decision includes

This rule decides whether a candidate lead may start outreach today based on:

- whether the campaign is active
- the campaign's daily start cap and how many leads have already started today
- FIFO ordering among eligible candidates
- whether the lead entered through `crm_tag` or `dormant_selector`
- whether an assigned or otherwise accountable agent exists
- whether an unassigned dormant-selector lead is old enough to start without agent approval
- whether a pre-flight digest is required for this candidate
- whether the pre-flight digest has been sent when required
- whether the agent veto window has expired when required
- whether the agent has explicitly vetoed this lead when required

## What this decision does not include

This rule does **not** decide:

- whether a lead is enrollment-eligible (that is `02-campaign-enrollment-eligibility.md`)
- whether a channel is contactable right now (that is `01-lead-contactability.md`)
- whether a specific message should send at the exact moment (those are pre-send safety checks)
- quiet hours
- frequency limits
- inbound reply handling
- workflow pause, resume, or handoff behavior
- message content or sequencing

Those belong to later rules.

## Plain-language definitions

- **Campaign start queue**: the ordered list of enrollment-eligible candidates ready for campaign-start selection.
- **Daily start cap**: the maximum number of leads that may start a campaign on a given day.
- **Pre-flight digest**: a notification sent to the assigned agent before dormant-selector outreach when agent confirmation is required, listing the candidates scheduled for outreach and allowing the agent to veto individual leads.
- **Veto window**: the configured time after the digest is sent during which the agent may exclude leads. The default is 24 hours.
- **Vetoed lead**: a lead the agent explicitly excluded from the first batch during the veto window.
- **Agentless dormant threshold**: the configurable number of days since last meaningful communication after which an unassigned dormant-selector lead may start without agent approval. The Phase One default is 60 days.
- **CRM tag approval**: when an authorized agent applies the configured CRM enrollment tag, that tag is treated as the human approval signal, so no additional pre-flight confirmation notification is required.
- **Held back**: a candidate that is not selected to start today but may start later.
- **Selected**: a candidate that is approved to start outreach today.

## Safety principles

1. AI does not decide which leads start today.
2. An inactive campaign must never start new leads.
3. Daily caps are hard limits, not suggestions.
4. FIFO ordering is the only allowed prioritization in V1.
5. An agent veto permanently removes a lead from the current batch, not just delays it.
6. The veto window must expire before any assigned-agent dormant-selector candidate from the first batch starts.
7. `crm_tag` enrollment is treated as human approval and does not require a pre-flight digest.
8. Unassigned dormant-selector leads may start without agent approval only when they meet the configurable dormant-age threshold.
9. Missing or uncertain data about agent assignment, dormant age, or digest state must fail safe.

## Decision rules

### Rule 1: Campaign must be active

| Condition                              | Result                                            |
| -------------------------------------- | ------------------------------------------------- |
| Campaign is active                     | Continue to next rule                             |
| Campaign is paused, draft, or inactive | Hold back all candidates with `campaign_inactive` |

### Rule 2: Enrollment-eligible candidates only

| Condition                                    | Result                                   |
| -------------------------------------------- | ---------------------------------------- |
| Candidate is an enrollment-eligible decision | Continue to next rule                    |
| Candidate is not enrollment-eligible         | Hold back with `not_enrollment_eligible` |

### Rule 3: Enrollment source determines confirmation path

| Condition                                                                                                        | Result                                  |
| ---------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| Candidate came from `crm_tag` and has an assigned/accountable agent                                              | Continue to daily cap and FIFO          |
| Candidate came from `crm_tag` but has no assigned/accountable agent                                              | Hold back with `missing_assigned_agent` |
| Candidate came from `dormant_selector` and has an assigned agent                                                 | Continue to pre-flight digest rule      |
| Candidate came from `dormant_selector`, has no assigned agent, and meets the agentless dormant threshold         | Continue to daily cap and FIFO          |
| Candidate came from `dormant_selector`, has no assigned agent, and does not meet the threshold or age is unknown | Hold back with `missing_assigned_agent` |

The default agentless dormant threshold is 60 days since last meaningful communication. This must be configurable from the admin panel later and passed into this domain policy by application code.

### Rule 4: Pre-flight digest and veto window

This rule applies only to assigned-agent `dormant_selector` candidates in the first outreach batch of a campaign.

It does not apply to `crm_tag` candidates because the tag itself is the human approval signal. It also does not apply to old unassigned dormant-selector candidates that meet the agentless dormant threshold.

| Condition                                                               | Result                                    |
| ----------------------------------------------------------------------- | ----------------------------------------- |
| Digest has been sent and veto window has expired and lead is not vetoed | Continue to next rule                     |
| Digest has been sent and veto window has expired and lead is vetoed     | Hold back with `agent_vetoed`             |
| Digest has been sent and veto window has not yet expired                | Hold back with `veto_window_not_expired`  |
| Digest has not been sent                                                | Hold back with `preflight_digest_pending` |

The system must not send the same digest twice for the same batch.

### Rule 5: Daily start cap

| Condition                                               | Result                                                  |
| ------------------------------------------------------- | ------------------------------------------------------- |
| Candidates already started today is below the daily cap | Continue to next rule                                   |
| Daily cap has already been reached                      | Hold back remaining candidates with `daily_cap_reached` |

The cap is checked after all other start conditions pass, so the oldest qualifying candidates consume the cap first.

### Rule 6: FIFO selection

Among candidates that pass all rules, select the oldest by `eligible_at` first until the daily cap is reached.

## Decision precedence

When multiple blocking conditions apply, evaluate and report in this order:

1. Campaign active
2. Enrollment eligibility
3. Enrollment source and assigned/accountable agent
4. Agentless dormant threshold for unassigned dormant-selector leads
5. Pre-flight digest and veto window, when required
6. Agent veto, when required
7. Daily start cap
8. FIFO selection among remaining candidates

The first blocking rule wins for reporting, but the system may collect additional reasons for audit purposes.

## Outputs the rule must produce

For each candidate, the rule should return:

- `selected`: yes or no
- `lead_id`: internal lead identifier
- `selected_at`: timestamp when the candidate was selected, when applicable
- `reasons`: one or more machine-readable reason codes when held back

For the batch, the rule should return:

- `selected`: ordered list of candidates starting today
- `held_back`: candidates not starting today with reasons
- `digest_required`: whether any candidate in the batch still needs a pre-flight digest
- `veto_window_expires_at`: timestamp when the veto window ends, when applicable

## Initial reason codes

- `campaign_inactive`
- `not_enrollment_eligible`
- `missing_assigned_agent`
- `preflight_digest_pending`
- `veto_window_not_expired`
- `agent_vetoed`
- `daily_cap_reached`
- `duplicate_candidate`
- `missing_eligible_at`

## Configurable inputs

These may vary by workspace or campaign and should be configurable later:

- campaign daily start cap
- whether pre-flight digest is enabled for the campaign
- veto window duration in hours (default 24)
- agentless dormant threshold in days (default 60)
- recipients of the pre-flight digest (assigned agent, manager, etc.)
- whether the digest is required for the first batch only or for every batch

## Hard-coded safety rules

These must stay explicit in code and tests:

- an inactive campaign never starts new leads
- daily caps are hard limits
- FIFO is the only allowed prioritization method in V1
- a vetoed lead must not start in the same batch when veto applies
- the veto window must expire before assigned-agent dormant-selector candidates from the first batch start
- `crm_tag` candidates do not require a pre-flight digest because the tag is human approval
- unassigned dormant-selector leads may start without agent approval only when they meet the configured dormant-age threshold
- unassigned `crm_tag` candidates must still have an accountable owner before starting
- duplicate candidates are not counted against the cap twice
- candidates missing `eligible_at` must be held back because FIFO ordering cannot be applied safely
- AI cannot override these decisions

## Required unit tests

At minimum, test:

- active campaign selects the oldest eligible candidates up to the daily cap
- inactive campaign holds back all candidates
- unassigned `crm_tag` leads are held back unless there is an accountable owner
- `crm_tag` candidates skip pre-flight digest and can start without waiting for veto confirmation
- assigned-agent dormant-selector candidates require pre-flight digest before first-batch selection
- unassigned dormant-selector candidates at or above the configured threshold can start without digest
- unassigned dormant-selector candidates below the configured threshold are held back
- the agentless dormant threshold is configurable
- daily cap limits the number of selected candidates per day
- FIFO ordering selects oldest `eligible_at` first
- pre-flight digest pending holds back assigned-agent dormant-selector first-batch candidates
- veto window not expired holds back assigned-agent dormant-selector first-batch candidates
- agent vetoed leads are held back even after the window expires
- non-vetoed leads start after the veto window expires
- duplicate candidates are deduplicated and only count once against the cap
- candidates missing `eligible_at` are held back
- candidates that are not enrollment-eligible are held back
- multiple blocking reasons can be reported for audit purposes

## Database implications to design later

This rule implies we will likely need durable records for:

- campaign state and daily start cap
- number of leads started per campaign per day
- pre-flight digest sent status and timestamp
- vetoed lead IDs per digest
- veto window expiration timestamp
- selected and held-back candidate records
- auditable reason codes for held-back candidates
- assigned agent reference per lead
- source of enrollment approval, including agent-added CRM tags
- last meaningful communication timestamp or computed dormant age for agentless dormant evaluation

## Client confirmation questions

Before locking the implementation, confirm:

1. What should the default daily start cap be per campaign?
2. Who should receive the pre-flight digest? Assigned agent only, or also managers?
3. Is the default 24-hour veto window acceptable?
4. Should a vetoed lead be permanently removed from the campaign, or only held back for a later batch?
5. Should the daily cap reset at midnight brokerage time?

## Next step after approval

Once this document is approved, implement pure domain logic and unit tests for this decision before designing database schema or APIs.
