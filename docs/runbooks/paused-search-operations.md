# Paused-search operations runbook

Use the workspace operations board and the paused-search occurrence list as the first
triage surfaces. Never resend an uncertain provider outcome without checking the
provider status and the occurrence idempotency key.

## Health buckets

- **Due**: planned or approved occurrences whose `due_at` has passed.
- **Held**: deferred occurrences waiting on timing or an operator control.
- **Review pending**: occurrences waiting for an explicit review decision.
- **Expired**: occurrences past the permitted execution window.
- **Failed**: provider or policy execution failures that reached a terminal failed state.
- **Uncertain**: provider acceptance is unknown; reconcile before retrying.
- **Terminal**: sent, skipped, cancelled, or migrated-legacy occurrences.
- **Fallback**: occurrences sent through an alternate configured channel.

## Stale timers or due work not moving

1. Confirm the workflow is still `queued`, `active_nurture`, `waiting_for_response`, or
   `response_processing` and that the occurrence is still open.
2. Check Temporal worker health and the signal/outbox queue for pending or failed entries.
3. Check the lead's current consent, suppression, ownership, quiet-hours, and recent
   human-activity facts. Do not manually send around a failed pre-send check.
4. If timing or the track is wrong, use the existing timing override, migration, or
   skip-next-touch action. These actions cancel stale open occurrences and preserve history.
5. If the workflow is no longer intended to continue, terminalize it instead of deleting
   the occurrence.

## Uncertain sends

1. Locate the occurrence and provider message id, if present.
2. Query the provider using the provider id or the stored idempotency key.
3. Resolve the occurrence to `sent`, `failed`, or `skipped` with the provider evidence and
   an operator reason.
4. Do not blindly retry an uncertain SMS or email; duplicate outreach is a compliance risk.
5. Record the reconciliation in the normal audit trail and notify the assigned owner when
   the result changes lead state.

## Stuck reviews

1. Review the latest inbound message, lead facts, track version, authored message, and
   review reason.
2. Choose an explicit review action: approve, edit the immutable message version, migrate,
   skip, terminalize, or resolve to a human-owned state.
3. Use a reason on every action. Do not edit a sent message or mutate historical occurrence
   state.
4. If ownership or human activity changed, pause or hand off rather than resuming AI.

## Provider failures

- **Failed** means the provider rejected or failed the operation; inspect provider errors,
  retry only temporary failures, and respect the maximum retry policy.
- **Uncertain** means delivery or acceptance is not known; reconcile first.
- Check workspace A2P 10DLC approval before investigating an SMS send; unknown or unapproved
  state must remain blocked.
- Verify the configured fallback channel has consent and a valid destination before relying
  on fallback.

## Manual migration and resumption

1. Confirm the target track version is published, enabled, and compatible with the lead's
   channel permissions and reason mapping.
2. Migrate through the lead control route. Do not update workflow or occurrence rows directly.
3. For resume, re-run the current eligibility response immediately before the action. A
   recent human activity signal or another active paused-search workflow blocks the action.
4. Resolve the human owner and obtain explicit permission. Assigned agents may act only on
   their own leads; managers and brokerage admins may act within their workspace scope.
5. Confirm the audit entry, workflow transition, occurrence cancellation, and Temporal
   signal/outbox result after the action.

## Pilot rollout and rollback

Recurring maintenance is fail-closed behind two controls:

1. The workspace's audited `recurring_paused_search_enabled` setting must be `true`.
2. The workspace id must be present in `RECURRING_PAUSED_SEARCH_PILOT_WORKSPACE_IDS` in
   the worker/API deployment configuration.

An empty allowlist enables no recurring paused-search work. Draft validation and preview
remain available, but enrollment, occurrence planning, and cadence execution hold without
creating a new occurrence. A disabled workspace is logged with workspace, lead, workflow,
track-step, occurrence, and reason identifiers; message bodies and credentials are never
logged. Re-enabling requires the normal audited setting change and an explicit workflow
resume/revalidation rather than automatic continuation.

For rollback, first disable the persisted workspace flag, then remove the workspace from
the deployment allowlist. Do not delete occurrences, reviews, audit records, or published
track versions. Investigate any `uncertain` result with the provider before changing the
flag or retrying work.

Initial operating thresholds:

- Page the on-call owner for any uncertain send or repeated provider failure.
- Review due or review-pending work older than one brokerage business day.
- Escalate workflow failures or repeated hold/deferral events after three attempts.

Engineering owns worker and provider failures; brokerage operations owns review queues and
pilot decisions; brokerage admins approve workspace-level policy changes. Product, QA,
security, and operations provide release sign-off before expanding the allowlist.

## Escalation

Escalate to engineering when an outbox entry repeatedly fails, an occurrence remains locked,
a provider result cannot be reconciled, the partial unique active-workflow index rejects a
write unexpectedly, or database migration detects pre-existing overlapping active workflows.
Include workspace id, lead id, workflow id, occurrence id, provider id, and correlation id;
exclude message bodies and credentials from tickets and logs.
