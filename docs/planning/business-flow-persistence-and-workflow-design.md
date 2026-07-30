# Business Flow Persistence and Workflow Design

This document defines the V1 backend backbone needed to pull Follow Up Boss leads,
decide whether outreach is allowed, run durable nurture workflows, handle inbound
replies, hand off to humans, and make system state queryable.

Implementation order and slice boundaries now live in
`docs/planning/business-flow-implementation-plan.md`.

## Current implementation baseline

Already implemented and kept:

- `leads`: canonical lead facts from CRM payloads.
- `outbound_messages`: planned/sent message records and provider send metadata.
- user-management tables: users, workspaces, memberships, sessions, invitations,
  and auth audit logs.
- domain rules for contactability, enrollment eligibility, FIFO start queue,
  pre-flight veto, and pre-send safety.
- Follow Up Boss adapter and lead mapper foundation.
- Twilio, SendGrid, OpenRouter, Redis, S3, and Temporal provider foundations.

The previously missing reporting/audit views, deployed RLS hardening, and final
operational readiness checks are now implemented in the current backend slice plan.

## Design principles

1. PostgreSQL is the queryable source of truth for business state and audit records.
2. Temporal owns durable multi-day timing and workflow history, but important state is
   also persisted in Postgres for reporting and operational visibility.
3. Every tenant-owned table has `workspace_id`.
4. External events are idempotent by `(workspace_id, provider, external_event_id)`.
5. Outbound actions are idempotent by internal idempotency keys.
6. Decision records are append-only. Do not overwrite why something happened.
7. AI output is stored as structured metadata, never as the only source of a business
   decision.
8. Human handoff always pauses AI and requires explicit authorized resume.

## Existing tables to keep and extend

### `leads`

Keep as the canonical lead facts table. Add only if needed:

- `last_synced_at`
- `sync_status`
- `sync_error_code`

The table already has the most important identity constraint:

- unique `(workspace_id, crm_provider, crm_lead_id)`

### `outbound_messages`

Keep as the send-attempt record. Extend later with:

- `workflow_id`
- `campaign_enrollment_id`
- `conversation_id`
- `reply_to_message_id`, nullable

Keep the existing unique idempotency constraint:

- unique `(workspace_id, idempotency_key)`

## New core tables

### CRM sync

#### `crm_sync_jobs`

Tracks each bulk or incremental CRM pull.

Important columns:

- `sync_job_id`, `workspace_id`, `crm_provider`
- `sync_type`: `bulk`, `incremental`, `single_lead`, `webhook_replay`
- `status`: `pending`, `running`, `completed`, `failed`, `cancelled`
- `started_at`, `finished_at`
- `cursor_started_at`, `cursor_finished_at`
- `total_seen`, `total_upserted`, `total_failed`
- `failure_reason`, `created_by_user_id`

Indexes:

- `(workspace_id, crm_provider, created_at)`
- `(workspace_id, status, created_at)`

#### `external_events`

Stores CRM/provider/webhook events idempotently.

Important columns:

- `external_event_id`, `workspace_id`, `provider`, `event_type`
- `provider_event_id`
- `crm_lead_id`, `lead_id`, nullable
- `received_at`, `processed_at`
- `status`: `received`, `processed`, `ignored`, `failed`
- `payload_redacted`, `failure_reason`

Constraints:

- unique `(workspace_id, provider, provider_event_id)`

### Campaign configuration

#### `campaigns`

Stable campaign identity.

Columns:

- `campaign_id`, `workspace_id`, `name`
- `status`: `draft`, `active`, `paused`, `archived`
- `active_version_id`, nullable
- `created_by_user_id`, `created_at`, `updated_at`

Constraints:

- unique `(workspace_id, name)`

#### `campaign_versions`

Immutable published campaign config snapshot.

Columns:

- `campaign_version_id`, `workspace_id`, `campaign_id`
- `version_number`, `status`: `draft`, `published`, `retired`
- `enabled_channels`, `daily_start_cap`, `dormant_threshold_days`
- `quiet_hours_start`, `quiet_hours_end`, `timezone`
- `sms_compliance_required`, `preflight_digest_enabled`
- `prompt_version`, `approved_model`, `created_by_user_id`
- `published_at`, `created_at`

Constraints:

- unique `(workspace_id, campaign_id, version_number)`

#### `campaign_cadence_steps`

Ordered steps inside a campaign version.

Columns:

- `cadence_step_id`, `workspace_id`, `campaign_version_id`
- `step_order`, `channel`, `delay_hours`
- `message_goal`, `template_key`, `max_attempts`

Constraints:

- unique `(workspace_id, campaign_version_id, step_order)`

### Enrollment and workflow state

#### `campaign_enrollments`

One lead enrolled into one campaign version.

Columns:

- `campaign_enrollment_id`, `workspace_id`, `campaign_id`, `campaign_version_id`
- `lead_id`, `source`: `crm_tag`, `dormant_selector`, `manual_admin`, `manual_agent`
- `status`: `candidate`, `queued`, `active`, `paused`, `handoff`, `completed`, `suppressed`, `closed`
- `eligible_at`, `enrolled_at`, `started_at`, `ended_at`
- `created_by_user_id`, nullable
- `reason_codes`, JSONB

Constraints:

- unique active enrollment per `(workspace_id, campaign_id, lead_id)`

#### `lead_workflows`

Queryable mirror of Temporal workflow state.

Columns:

- `workflow_id`, `temporal_workflow_id`, `workspace_id`
- `campaign_enrollment_id`, `campaign_id`, `lead_id`
- `state`: `eligible`, `queued`, `active_nurture`, `waiting_for_response`,
  `response_processing`, `paused`, `human_handoff`, `human_owned`, `completed`,
  `suppressed`, `closed`
- `current_step_id`, `next_action_at`, `last_transition_at`
- `pause_reason`, `resume_reason`, `state_version`

Indexes:

- `(workspace_id, state, next_action_at)`
- `(workspace_id, lead_id, last_transition_at)`

#### `workflow_transitions`

Append-only state transition history.

Columns:

- `transition_id`, `workspace_id`, `workflow_id`, `lead_id`, `campaign_id`
- `from_state`, `to_state`, `reason_code`
- `actor_user_id`, nullable
- `external_event_id`, nullable
- `created_at`, `metadata`

### Decision audit

#### `decision_audit_events`

Unified append-only decision log.

Decision types:

- `contactability`
- `campaign_enrollment`
- `start_queue`
- `pre_send`
- `reply_classification`
- `handoff_decision`
- `resume_decision`

Columns:

- `decision_id`, `workspace_id`, `lead_id`, `campaign_id`, `workflow_id`, nullable
- `decision_type`, `channel`, nullable
- `allowed`, `reason_codes`, `policy_version`, `facts_snapshot`
- `ai_provider`, `ai_model`, `prompt_version`, `confidence`, nullable
- `actor_user_id`, nullable
- `created_at`, `correlation_id`

Indexes:

- `(workspace_id, lead_id, created_at)`
- `(workspace_id, decision_type, created_at)`
- `(workspace_id, campaign_id, allowed, created_at)`

### Pre-flight digest

#### `preflight_digests`

Columns:

- `digest_id`, `workspace_id`, `campaign_id`, `batch_id`
- `recipient_user_id`, `status`, `sent_at`, `veto_window_expires_at`
- `provider_reference`, `idempotency_key`, `created_at`

Constraints:

- unique `(workspace_id, campaign_id, batch_id, recipient_user_id)`

#### `preflight_vetoes`

Columns:

- `veto_id`, `workspace_id`, `campaign_id`, `batch_id`, `lead_id`
- `actor_user_id`, `reason`, `idempotency_key`, `created_at`

Constraints:

- unique `(workspace_id, campaign_id, batch_id, lead_id, actor_user_id)`

### Conversations and inbound messages

#### `conversations`

Columns:

- `conversation_id`, `workspace_id`, `lead_id`, `campaign_id`, nullable
- `workflow_id`, nullable
- `status`: `active_ai`, `paused`, `human_handoff`, `human_owned`, `closed`
- `ai_interaction_count`, `last_message_at`, `created_at`, `updated_at`

#### `inbound_messages`

Columns:

- `inbound_message_id`, `workspace_id`, `conversation_id`, `lead_id`
- `channel`: `sms`, `email`
- `provider`, `provider_message_id`, `external_event_id`
- `from_address_redacted`, `to_address_redacted`
- `body`, `received_at`, `processed_at`
- `classification_status`, `created_at`

Constraints:

- unique `(workspace_id, provider, provider_message_id)`

#### `conversation_summaries`

Columns:

- `summary_id`, `workspace_id`, `conversation_id`, `lead_id`
- `summary_text`, `preferences`, JSONB
- `prompt_version`, `model`, `confidence`, `created_at`

### Handoff

#### `handoffs`

Columns:

- `handoff_id`, `workspace_id`, `lead_id`, `campaign_id`, `workflow_id`
- `conversation_id`, `inbound_message_id`, nullable
- `assigned_agent_user_id`, nullable
- `assigned_agent_crm_id`, nullable
- `reason_code`, `summary`, `latest_inbound_text`
- `preferences`, JSONB
- `status`: `created`, `notified`, `acknowledged`, `resolved`, `cancelled`
- `created_at`, `notified_at`, `acknowledged_at`

Indexes:

- `(workspace_id, status, created_at)`
- `(workspace_id, assigned_agent_user_id, status)`

### Provider status and outbox

#### `provider_message_events`

Tracks Twilio/SendGrid delivery callbacks.

Columns:

- `provider_event_id`, `workspace_id`, `provider`, `provider_message_id`
- `outbound_message_id`, nullable
- `event_type`, `status`, `received_at`, `payload_redacted`

Constraints:

- unique `(workspace_id, provider, provider_event_id)`

#### `outbox_events`

Transactional outbox for RabbitMQ fan-out.

Columns:

- `outbox_event_id`, `workspace_id`, `aggregate_type`, `aggregate_id`
- `event_type`, `payload`, `status`, `attempt_count`
- `available_at`, `created_at`, `published_at`, `last_error`

Indexes:

- `(status, available_at)`
- `(workspace_id, event_type, created_at)`

## Primary query examples this design must support

- Show all leads currently active in a campaign.
- Show why a lead was disallowed from outreach.
- Show the current workflow state and next scheduled action for a lead.
- Show every message sent to and received from a lead.
- Show all handoffs awaiting agent action.
- Show failed CRM syncs or failed provider callbacks.
- Show all decisions made by campaign, channel, and reason code.

## Security and access notes

- Message content, handoff summaries, and lead facts are sensitive lead data.
- Store message content only where it is required for conversation context and
  handoff continuity.
- Redact payloads used only for troubleshooting, logs, and webhook diagnostics.
- Query APIs must enforce workspace isolation and role-based access.
- Operational dashboards should show redacted contact details unless the actor has
  a valid workspace role that permits full lead access.

## Migration notes

- Prefer additive migrations by slice instead of one large migration if review size
  becomes too large.
- Use partial unique indexes where the rule is "one active enrollment" rather than
  one lifetime enrollment.
- Add indexes intentionally around expected dashboards and worker queries.
- Keep enum-like values as strings in the DB and convert to domain enums in
  repository adapters.

## Implementation status and sequencing note

Completed so far:

1. Database migration for sync, campaign, workflow, decision audit, conversation,
   handoff, provider-event, and outbox tables.
2. Repository ports and Postgres adapters for CRM sync tracking and external events.
3. Transactional outbox persistence and RabbitMQ fan-out publisher worker.

The agreed next delivery sequence is captured in
`docs/planning/business-flow-implementation-plan.md`, starting with:

3. Follow Up Boss lead snapshot sync into canonical leads.
4. Outbound planning engine with rules-first message creation.
5. Safe sink delivery for dev/testing.
6. Inbound reply flow.

## Deferred from this design

- MLS/IDX integrations and later listing-context workflows beyond this core nurture-spine design.
- Advanced lead scoring.
- Raw email MIME parsing.
- Slack/SLA escalation workflows.
- Cost analytics.
- Microservices.
