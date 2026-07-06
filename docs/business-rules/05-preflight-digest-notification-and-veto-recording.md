# Pre-Flight Digest Notification and Veto Recording Rules

## Purpose

This document defines the fifth business process for Phase One:

**How does the system notify agents before dormant-selector outreach, and how are agent vetoes recorded?**

This process operationalizes the pre-flight digest and veto window referenced by the campaign-start queue rule. It does not decide final campaign start selection by itself. Instead, it prepares durable digest/veto state that `03-campaign-start-queue-and-preflight-veto.md` consumes.

## What this process includes

This process covers:

- identifying dormant-selector candidates that require a pre-flight digest
- grouping digest entries by the assigned or accountable agent
- sending a pre-flight digest notification through an internal notification port
- recording the digest issue timestamp
- computing the veto-window expiration timestamp
- accepting or rejecting agent veto requests
- recording vetoed lead IDs durably
- preventing duplicate digest issuance for the same batch
- making digest and veto state available to campaign-start evaluation

## What this process does not include

This process does **not** decide:

- whether a lead is contactable
- whether a lead is enrollment-eligible
- whether a candidate starts outreach today
- whether a specific SMS or email can send right now
- message content generation
- provider-specific email/SMS implementation details
- CRM tag mapping
- Temporal workflow implementation
- database schema details

Those belong to separate domain rules, application use cases, infrastructure adapters, migrations, or workflow code.

## Plain-language definitions

- **Pre-flight digest**: a notification sent before dormant-selector outreach when agent review is required.
- **Digest batch**: the durable group of candidate leads included in one pre-flight digest run for one workspace and campaign.
- **Digest entry**: one lead shown in a digest for agent review.
- **Digest recipient**: the assigned or accountable agent who should review candidate leads. Additional recipients, such as managers, are configurable later and must not be guessed by code.
- **Veto**: an explicit agent action excluding a lead from the applicable outreach batch.
- **Veto window**: the configured period after digest issuance during which vetoes may be recorded. The Phase One default is 24 hours.
- **Digest issued**: the digest notification was accepted by the notification port and the system durably recorded `digest_sent_at`.
- **Idempotency key**: a deterministic key for preventing duplicate digest notifications or duplicate veto records.

## Safety principles

1. AI does not decide which leads appear in the digest.
2. A digest must be based only on candidates that already passed enrollment eligibility and require pre-flight review.
3. The system must not send duplicate digests for the same batch.
4. The veto window starts only after digest issuance is durably recorded.
5. A veto must be explicit, attributable, and auditable.
6. Unknown recipient, candidate, campaign, workspace, or digest state must fail safe.
7. A candidate must not start outreach while a required veto window is still open.
8. A candidate vetoed during the applicable window must not start in that batch.
9. Provider-specific notification details must stay outside the domain and application decision rules.
10. The application layer must persist state before later campaign-start evaluation relies on it.

## Process rules

### Rule 1: Digest candidates must be explicitly eligible for pre-flight review

| Condition                                                                                                                                    | Result                                                      |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Candidate came from `dormant_selector`, is enrollment-eligible, has an assigned/accountable agent, and the first-batch digest policy applies | Include candidate in digest preparation                     |
| Candidate came from `crm_tag`                                                                                                                | Do not include; CRM tag is the human approval signal        |
| Candidate is unassigned and qualifies for agentless dormant handling                                                                         | Do not include; no recipient exists                         |
| Candidate is not enrollment-eligible or required facts are missing                                                                           | Do not include; hold back through campaign-start evaluation |

The digest process should reuse the same candidate facts used by campaign-start evaluation. It must not create a second, inconsistent eligibility rule.

### Rule 2: Digest entries must be grouped by accountable recipient

| Condition                                                                                  | Result                                                                               |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Candidate has a known assigned/accountable agent with a reachable notification destination | Group under that recipient                                                           |
| Candidate has no known recipient or recipient destination is missing                       | Do not issue a digest for that candidate; fail safe and keep the candidate held back |

The default recipient is the assigned/accountable agent. If managers or other recipients are later added, they must come from validated workspace or campaign configuration.

### Rule 3: Digest notification must be idempotent

| Condition                                                                              | Result                                              |
| -------------------------------------------------------------------------------------- | --------------------------------------------------- |
| No digest has been issued for this workspace, campaign, batch, and recipient group     | Send notification and record `digest_sent_at`       |
| Digest was already issued for the same workspace, campaign, batch, and recipient group | Do not send again; return the existing digest state |
| Previous digest issue status is uncertain                                              | Do not blindly resend; require reconciliation       |

The idempotency key should be deterministic from workspace ID, campaign ID, batch ID, recipient ID, and digest version.

### Rule 4: Digest issuance must be durable before the veto window starts

| Condition                                                                | Result                                                                               |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Notification is accepted by the notification port and state is persisted | Mark digest issued and set `digest_sent_at`                                          |
| Notification fails before acceptance                                     | Do not mark digest issued; candidates remain blocked with `preflight_digest_pending` |
| Persistence fails after notification acceptance                          | Treat state as uncertain; do not start outreach until reconciled                     |

The veto window starts at the persisted `digest_sent_at`. The application must not infer the start time from local memory or provider timestamps alone.

### Rule 5: Veto requests must be validated before recording

| Condition                                                                                                                                       | Result                                                       |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Request references an existing digest entry, comes from an authorized recipient or authorized manager/admin, and arrives within the veto window | Record veto                                                  |
| Request references a lead not in the digest                                                                                                     | Reject veto request                                          |
| Request arrives after the veto window expires                                                                                                   | Reject or ignore as too late; do not modify batch veto state |
| Request comes from an unauthorized user                                                                                                         | Reject veto request                                          |
| Digest state is missing or uncertain                                                                                                            | Reject request until state is reconciled                     |

Authorization rules must be enforced by the application/interface layer. The domain rule should receive already-validated actor facts.

### Rule 6: Veto recording must be idempotent and auditable

| Condition                                        | Result                                                         |
| ------------------------------------------------ | -------------------------------------------------------------- |
| Lead has not already been vetoed for this digest | Add lead ID to the digest's veto set and record audit metadata |
| Lead was already vetoed for this digest          | Return success without duplicating side effects                |

At minimum, the recorded veto metadata should include workspace ID, campaign ID, digest ID, lead ID, actor ID, recorded timestamp, and reason text when supplied.

### Rule 7: Campaign-start evaluation consumes persisted digest state

| Condition                                                            | Result                                                                    |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Digest has not been issued                                           | Campaign-start rule holds candidates back with `preflight_digest_pending` |
| Digest has been issued and the veto window is still open             | Campaign-start rule holds candidates back with `veto_window_not_expired`  |
| Digest has been issued, veto window expired, and lead was vetoed     | Campaign-start rule holds lead back with `agent_vetoed`                   |
| Digest has been issued, veto window expired, and lead was not vetoed | Candidate may continue to daily cap and FIFO selection                    |

This process must not bypass `evaluate_campaign_start_batch(...)`. It only prepares the context that evaluator consumes.

## Decision precedence

When multiple blocking conditions apply, evaluate and report in this order:

1. Missing required workspace, campaign, batch, digest, candidate, or actor data
2. Campaign is not active
3. Candidate does not require pre-flight digest
4. Missing assigned/accountable recipient
5. Digest already issued or digest state uncertain
6. Notification failure
7. Veto request references a non-digest lead
8. Veto request actor is unauthorized
9. Veto request is outside the veto window
10. Duplicate veto request

The first blocking rule wins for user-facing status, but the system should keep enough context for audit records.

## Outputs the use cases must produce

### Digest preparation output

For digest preparation, return:

- `digest_id`
- `workspace_id`
- `campaign_id`
- `batch_id`
- `digest_sent_at`, when issued
- `veto_window_expires_at`, when computable
- recipients notified
- lead IDs included
- lead IDs held back from digest with reasons
- idempotency key
- status such as `issued`, `already_issued`, `not_required`, `failed`, or `uncertain`

### Veto recording output

For veto recording, return:

- `digest_id`
- `lead_id`
- `recorded`: yes or no
- `recorded_at`, when applicable
- `actor_id`
- `reasons`, when rejected or ignored
- whether the request was a duplicate no-op

## Initial reason codes

- `missing_required_data`
- `campaign_not_active`
- `digest_not_required`
- `missing_digest_recipient`
- `digest_already_issued`
- `digest_state_uncertain`
- `notification_failed`
- `candidate_not_in_digest`
- `unauthorized_veto_actor`
- `veto_window_expired`
- `duplicate_veto`

## Configurable inputs

These may vary by workspace or campaign and should be configurable later:

- whether pre-flight digest is enabled for dormant-selector first batches
- veto window duration, default 24 hours
- recipient policy, starting with assigned/accountable agent
- optional manager/admin recipients
- digest notification channel, such as email or in-app notification
- digest template content
- allowed veto actor roles

## Hard-coded safety rules

These must stay explicit in code and tests:

- a required digest must be issued before the veto window can expire
- a candidate must not start while its required veto window is open
- a vetoed lead must not start in the applicable batch
- `crm_tag` enrollment does not require a digest because the tag is human approval
- missing recipient or uncertain digest state fails safe
- duplicate digest sends are blocked by idempotency
- duplicate veto requests do not create duplicate side effects
- notification provider details do not leak into domain rules
- AI cannot override digest or veto decisions

## Required unit tests

At minimum, test:

- digest preparation includes only assigned-agent dormant-selector candidates requiring review
- `crm_tag` candidates are not included in digest preparation
- unassigned dormant-selector candidates are not included in digest preparation
- missing recipient holds candidate back from digest issuance
- candidates are grouped by assigned/accountable agent
- first digest issuance records `digest_sent_at`
- duplicate digest preparation returns existing digest state without sending again
- notification failure does not mark digest as issued
- uncertain digest issue status blocks campaign start until reconciled
- veto within the window records the lead ID
- veto for a lead not in the digest is rejected
- veto after the window expires is rejected or ignored without modifying state
- unauthorized veto actor is rejected
- duplicate veto request is an idempotent no-op
- persisted digest state can be converted into `CampaignStartContext`

## Database and transaction implications to design later

This process implies durable records for:

- digest batch identity
- workspace ID and campaign ID
- candidate lead IDs included in the digest
- recipient IDs and notification destinations
- digest issue status and `digest_sent_at`
- notification idempotency key
- notification provider status, without provider-specific objects leaking into application code
- vetoed lead IDs
- veto actor metadata
- audit reason codes

Digest issuance and veto recording should be transactionally safe. If an outbox is available for notification fan-out later, digest state and outbox records should be written in the same database transaction.

## Client confirmation questions

Before locking implementation details, confirm:

1. Should Phase One notify only assigned/accountable agents, or also managers/admins by default?
2. Should the digest be sent by email first, in-app notification first, or should the first implementation only define a notification port and fake tests?
3. Should a vetoed lead be excluded only from the current digest batch, or removed from the campaign until manually re-enrolled?
4. Should late veto attempts be rejected with an error, or accepted as feedback without affecting the current batch?
5. What minimal lead fields should appear in the digest, without exposing unnecessary sensitive data?

## Next step after approval

Once this document is approved, implement the minimal application-layer use cases, ports, and fake-based tests for digest issuance and veto recording. Do not add infrastructure adapters, database schema, APIs, or Temporal workflow code until the application seam is clear and tested.
