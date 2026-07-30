# Business Flow Implementation Plan

## Purpose

This document turns the approved V1 business-flow design into an execution plan.
It defines the delivery order, slice boundaries, and validation expectations so
we can build the backend in business-priority order without mixing outbound and
inbound work prematurely.

See also `docs/planning/business-use-case-readiness.md` for the living checklist
of what is done versus what remains before real business-use-case testing.

## Approved Business Sequence

The agreed business sequence is:

1. Pull leads from the CRM into Postgres on a repeatable sync job.
2. Map CRM leads into `CanonicalLeadRecord` so explicit business rules can run on
   normalized internal facts instead of provider-specific payloads.
3. Run outbound decision and message-creation logic against canonical leads and
   persist planned outbound messages.
4. Send outbound messages through safe development sinks first.
5. Tackle inbound reply handling after the outbound foundation is working.

## Core Delivery Principles

- Business rules decide sendability, channel choice, suppression, and workflow
  state. The LLM may draft language but must not decide whether outreach is allowed.
- Sync must be idempotent. Re-reading a lead is safe because canonical leads upsert
  on `(workspace_id, crm_provider, crm_lead_id)`.
- Repeated CRM polling should use an incremental watermark after the initial full
  sync. Occasional full reconciliation remains safe and desirable.
- Outbound message quality matters most, so the planner must use approved facts,
  structured context, and validators that reject invented content.
- Keep the outbound planner open for future external context sources, but do not
  implement MLS/property matching in V1 without explicit approval.
- Use sink providers in development so end-to-end outbound behavior is testable
  without contacting real leads.

## Slice Sequence

### Slice 1 — Follow Up Boss lead snapshot sync

Status: complete.

Goal: create a reliable internal mirror of CRM lead snapshots.

Deliverables:

- application use case to run a CRM sync job
- initial full sync plus incremental sync using a stored watermark/window
- paginated Follow Up Boss lead fetch
- map each person payload into `CanonicalLeadRecord`
- upsert canonical leads into Postgres
- update `crm_sync_jobs` with counts, status, failures, and sync window metadata
- fake-based tests for pagination, upsert behavior, incremental window handling,
  partial failures, and final job status

Out of scope:

- webhook ingestion
- campaign enrollment
- outbound planning
- inbound flow
- activity/history enrichment beyond what is already available in the lead payload

Business result:

- the system can pull leads from Follow Up Boss and persist canonical internal lead
  records with sync-job tracking

### Slice 2 — Outbound planning engine

Status: complete.

Goal: implement the highest-value product logic safely and explicitly.

Deliverables:

- high-level use case that loads a canonical lead and assembles the approved
  outbound planning context before calling the low-level planner
- rules-first sendability evaluation over canonical leads
- channel selection using contactability and pre-send rules
- structured outbound planning context and message brief assembled only from
  approved internal facts and safe canonical lead summaries
- constrained LLM drafting with validation and safety rejection paths
- persisted planned outbound messages with idempotency, model metadata,
  prompt version, confidence, and safety flags
- tests proving no-send scenarios block before drafting and drafts cannot invent
  unsupported facts or bypass channel safety

Out of scope:

- real provider delivery
- inbound replies
- generic property/listing matching in this slice, which is handled separately by later V1 listing-source work

Business result:

- the system can decide the next safe outbound message and persist it for delivery

### Slice 3 — Safe outbound delivery in development

Status: complete.

Approach: add config-selectable in-process sink providers (`sms_provider="sink"`,
`email_provider="sink"`) that implement the existing `SMSProvider` and
`EmailProvider` protocols, capture sent messages in memory, and return synthetic
provider message IDs. This reuses the existing `send_outbound_message` use case
without adding new persistence or delivery workers.

Goal: exercise the full outbound loop without risking live sends.

Deliverables:

- sink SMS provider for development/testing
- sink email provider for development/testing
- provider factory support for `sms_provider="sink"` and `email_provider="sink"`
- configuration documentation for sink mode
- delivery path from planned outbound message to provider adapter
- provider result handling and status transitions
- tests proving real provider interfaces are honored while dev sends stay local

Out of scope:

- persisted delivery journal beyond existing `outbound_messages` table
- provider webhook callbacks
- background delivery worker
- inbound reply flow

Business result:

- the outbound flow can be executed end-to-end in development without contacting
  real leads

### Slice 4 — Inbound reply flow

Goal: process replies, pause AI safely, and prepare handoff behavior.

Deliverables:

- inbound webhook ingestion with idempotency
- inbound message persistence and conversation linkage
- reply classification and structured extraction
- pause/handoff trigger paths
- tests for duplicate events, opt-out handling, and human-handoff triggers

Implemented in this slice:

- normalized Follow Up Boss inbound webhook route under `app/interfaces/api/v1/webhooks.py`
- `Conversation`, `InboundMessage`, `ConversationSummary`, and `Handoff` domain models
- repository ports and Postgres adapters for inbound records
- structured LLM reply classification with confidence validation
- `process_inbound_message_event(...)` orchestration with duplicate-event handling
- safe pause/handoff decision paths without introducing Temporal yet

Business result:

- the system can safely react to inbound replies and stop outbound automation when
  appropriate

### Slice 5A — Explicit workflow state persistence

Goal: make lead workflow state queryable and auditable before introducing Temporal
orchestration.

Implemented in this slice:

- canonical `WorkflowState`, `LeadWorkflow`, and `WorkflowTransition` domain models
- transition guard logic for inbound-triggered `paused` and `human_handoff` states
- repository ports and Postgres adapters for `lead_workflows` and `workflow_transitions`
- inbound use-case wiring that locks the current workflow and appends transition history
- handoff records now receive workflow and campaign identifiers when a workflow exists
- tests for transition guards, repository mapping, pessimistic locking, and inbound handoff transitions

Business result:

- inbound replies now pause the persisted workflow mirror and record why the state changed,
  while still succeeding safely when no workflow exists yet

### Slice 5B — Minimal Temporal signal MVP

Goal: introduce Temporal as a narrow durable signal orchestrator without building full
cadence timers yet.

Implemented in this slice:

- `LeadNurtureWorkflow` registered on the existing Temporal worker
- signals for inbound replies, handoff creation, pause requests, resume requests, and close
- Temporal activities that call application-layer workflow transition use cases
- safe resume behavior requiring an actor and reason before a resume transition is attempted
- worker registration tests covering the lead nurture workflow and transition activities

Business result:

- Temporal now has a concrete, minimal seam for durable workflow signals while core
  business state transitions remain in application/domain code

### Slice 6 — Campaign enrollment + workflow start

Goal: convert selected leads into persisted campaign enrollments and running Temporal
`LeadNurtureWorkflow` executions.

Implemented in this slice:

- canonical `CampaignEnrollment` domain model with source and status enums
- `CampaignEnrollmentRepository` port and Postgres adapter with upsert on the unique
  `(workspace_id, campaign_id, lead_id)` constraint
- `TemporalWorkflowStarter` port in the application layer
- `TemporalClientWorkflowStarter` implementation using the existing Temporal client
- `start_selected_campaign_batch(...)` use case that creates:
  - a `queued` campaign enrollment record
  - a `queued` lead workflow record with a deterministic Temporal workflow id
  - an initial workflow transition for `campaign_enrollment_started`
  - a Temporal `LeadNurtureWorkflow` execution
- duplicate-enrollment skip behavior and per-lead failure reporting when Temporal fails
- fake-based tests for the use case and Postgres-adapter tests for the repository

Business result:

- authorized callers can now start a batch of selected leads into a campaign, and the
  persisted workflow mirror plus Temporal execution are created together

### Slice 7 — Persisted campaign execution config + first cadence step

Status: complete.

Goal: move the first nurture step from hardcoded workflow input into persisted
campaign/version/cadence-step config so Temporal can execute a real campaign step.

Implemented in this slice:

- ORM models and repository mapping for the already-existing `campaigns`,
  `campaign_versions`, and `campaign_cadence_steps` tables
- canonical `CampaignExecutionConfig` and `CampaignCadenceStep` domain models for
  loading execution-ready campaign config by `campaign_version_id`
- workflow transition guard expansion for `queued -> active_nurture` and
  `active_nurture -> waiting_for_response`
- application orchestration to:
  - schedule the first cadence step onto the persisted workflow mirror
  - transition the workflow into `active_nurture` when the step becomes due
  - plan and send the first outbound message using the persisted cadence-step channel
  - transition the workflow into `waiting_for_response` after send
  - pause the workflow if planning or send-time safety blocks the step
- Temporal activities for first-step scheduling and execution
- `LeadNurtureWorkflow` now loads the persisted first step, waits until due, blocks
  send on pause/handoff/inbound signals, and records execution snapshot metadata
- fake-based application tests, repository mapping tests, and worker registration
  coverage for the new cadence-step path

Business result:

- a started lead nurture workflow can now execute the first persisted campaign cadence
  step through the existing planning and send-time safety rules instead of stopping at
  workflow creation

### Slice 8 — Workspace contact policy persistence

Status: complete.

Goal: replace the hardcoded workspace send-policy assumptions with persisted workspace
contact policy so SMS compliance and quiet-hour checks use the real source of truth.

Implemented in this slice:

- a dedicated `workspace_contact_policies` persistence seam and migration
- canonical `WorkspaceContactPolicy` domain model plus repository port and Postgres
  adapter
- timezone-aware quiet-hour evaluation using the workspace default timezone
- first-step cadence execution now loads persisted workspace contact policy instead of
  constructing a test-only default in-process
- repository, domain, and application tests for SMS compliance blocking and persisted
  quiet-hour enforcement

Business result:

- cadence execution now honors persisted workspace contact policy rules before any SMS
  or email send is attempted

### Slice 9 — Multi-step cadence loop

Status: complete.

Goal: extend `LeadNurtureWorkflow` from a single persisted first step into a real
multi-step wait/send/wait cadence loop.

Implemented in this slice:

- generalized application orchestration from first-step-only helpers into:
  - `schedule_next_campaign_cadence_step(...)`
  - `execute_campaign_cadence_step(...)`
- workflow transition guard expansion for `waiting_for_response -> active_nurture`
- pause semantics now preserve the current cadence cursor while still clearing pending
  send time, which allows an explicit resume to retry the blocked step cleanly
- successful cadence execution now advances the persisted workflow cursor to the next
  cadence step when one exists
- final-step behavior intentionally keeps the workflow alive in
  `waiting_for_response` after the last send so inbound replies and handoff signals can
  still arrive; the workflow does not auto-complete without a defined post-final wait
  policy
- Temporal activities and worker registration now use generic next-step scheduling and
  execution activity names
- direct workflow tests cover both:
  - looping through multiple cadence steps
  - retrying after a blocked step once the workflow is unblocked

Business result:

- a started lead nurture workflow can now progress through all published cadence steps
  instead of stopping after the first send

### Slice 10 — Business-flow harnesses on fake and real Postgres persistence

Status: complete.

Goal: prove the first critical end-to-end business path both at the application layer
and against a freshly migrated Postgres database.

Implemented in this slice:

- a thin application-level harness for:
  `sync -> enrollment -> first cadence send -> inbound reply -> human_handoff`
- a real Postgres-backed harness that boots a temporary migrated database and runs the
  same business path through the production repository adapters
- real-schema fixes uncovered by the harness:
  - Alembic fresh-database bootstrap now supports this repo's longer revision ids
  - workflow-transition inserts now persist the JSON metadata column correctly
  - campaign-enrollment upserts now target the real partial unique index used by the
    migrated schema
- repository-focused regression coverage for the workflow-transition and
  campaign-enrollment persistence seams involved in the harness path

Business result:

- the first real business loop is now executable both with fast in-memory fakes and
  against a fresh Postgres schema, which closes the highest-priority integration gap

### Slice 11 — Handoff completion

Status: complete.

Goal: finish the business-side handoff path so interested leads reliably reach the
assigned human with the correct CRM context.

Implemented in this slice:

- notify the assigned agent when a handoff is created
- write a handoff summary and reason back to Follow Up Boss
- update the configured CRM handoff tag and/or custom field mapping
- persist notification/writeback status for retries and auditability
- add fake-based tests and extend the real Postgres harness to verify the handoff side
  effects

Business result:

- a handoff now reaches the assigned human through the notification seam, writes the
  configured CRM context back to Follow Up Boss, and records durable completion state
  for retries and auditability

### Slice 12 — CRM human-activity pause detection

Status: complete.

Goal: ensure human ownership always wins when an agent acts in the CRM.

Implemented in this slice:

- consume CRM activity/update signals that indicate meaningful human action
- map those signals into explicit pause reasons in the workflow layer
- stop pending AI sends and pause active nurture safely
- require explicit resume after a human-activity pause
- add tests for note/activity/reassignment/status-change pause scenarios

Business result:

- meaningful CRM human activity now pauses active nurture, records the explicit pause
  reason in workflow history, and signals Temporal so stale AI sends do not proceed

### Slice 13 — Opt-out and unsubscribe event completion

Status: complete.

Goal: complete the real suppression paths for SMS and email.

Implemented in this slice:

- ingest SMS opt-out keywords from provider/CRM events
- ingest email unsubscribe events from provider/CRM events
- persist channel or global suppression state with evidence
- stop affected workflows and prevent future sends immediately
- add duplicate-event and idempotency coverage

Business result:

- real suppression events now mutate persisted lead facts, stop unsafe nurture execution,
  and expose an explicit webhook/use-case seam for SMS opt-out, email unsubscribe, and
  do-not-contact handling

### Slice 14 — Daily dormant selector + pre-flight digest flow

Status: complete.

Goal: wire the intended V1 dormant-lead operating loop without introducing a rules
engine.

Implemented deliverables:

- `DormantCandidateSelector` port and Postgres query that selects the oldest reliable
  dormant leads not already enrolled in the campaign, ordered by
  `last_meaningful_communication_at` and capped by a configurable buffer.
- `CampaignExecutionRepository.get_active_for_campaign(...)` so the selector can load
  the published campaign version directly from `campaign_id`.
- `run_dormant_selector_batch(...)` orchestration use case that:
  - loads active campaign execution config and workspace contact policy
  - evaluates each candidate through contactability and enrollment rules
  - issues a pre-flight digest when the campaign requires it and the lead has an
    assigned agent
  - enforces the campaign daily cap via the existing FIFO start-queue evaluator
  - starts the selected batch through `start_selected_campaign_batch`
- Postgres `PreflightDigestRepository` that persists the batch-level digest aggregate
  (entries and notification records as JSONB) alongside per-lead vetoes in the
  `preflight_vetoes` table, with idempotent veto inserts and full round-trip loading.
- Minimal API routes:
  - `POST /workspaces/{workspace_id}/campaigns/{campaign_id}/dormant-selector-runs`
  - `POST /workspaces/{workspace_id}/campaigns/{campaign_id}/batches/{batch_id}/preflight-vetoes`
  - both enforce manager/brokerage-admin role checks and commit the unit of work.
- Added the missing `CampaignModel`, `CampaignVersionModel`, and
  `CampaignCadenceStepModel` SQLAlchemy models so the campaign execution repository
  resolves against the actual Postgres schema.
- Migration `0013_align_preflight_digest_schema.py` that aligns the pre-flight digest
  persistence with the batch-level aggregate (JSONB entries/notification records and
  a `digest_id` reference on vetoes).
- Unit tests for the orchestration using fakes, plus Postgres integration tests for the
  new repository and selector.

### Slice 15 — Provider delivery callbacks

Status: complete.

Goal: reconcile outbound message state with real provider delivery outcomes.

Implemented deliverables:

- webhook ingestion for Twilio SMS message-status callbacks and SendGrid event webhook
  delivery callbacks
- provider-specific payload/signature validation at the interface boundary, with strict
  verification when Twilio/SendGrid signing configuration is present
- canonical provider delivery callback use case that maps provider statuses into internal
  delivery statuses
- outbound message delivery summary fields for provider name, delivery status, status
  timestamp, and delivered timestamp
- `provider_message_events` persistence for audit-friendly callback history and duplicate
  provider-event handling
- duplicate callbacks return safe success without repeating side effects
- late callback safety prevents delivered messages from regressing to older accepted or
  failure states
- failed/bounced/undelivered/dropped callbacks update delivery failure information without
  triggering unsafe duplicate sends
- fake-based application/API tests plus Postgres repository tests for callback
  reconciliation and delivery-event persistence

### Slice 16 — Transactional outbox + RabbitMQ fan-out

Status: complete.

Goal: make important asynchronous events production-real without leaking queue logic
into the domain.

Completed deliverables:

- Postgres transactional outbox writes alongside state changes
- worker/publisher that fans out outbox events to RabbitMQ
- idempotent publish and retry behavior
- event-driven hooks for notifications, reporting, and non-critical async work

Implemented notes:

- added explicit `EventBus`, `OutboxEventRepository`, and `OutboxEventPublisher`
  ports
- added canonical domain event and outbox event models/enums
- mapped the existing `outbox_events` table into SQLAlchemy and implemented append,
  claim-with-lease, mark-published, and retryable-failure persistence
- added a RabbitMQ topic-exchange publisher that emits a canonical JSON event envelope
  with the outbox event id as the broker message id
- added an outbox publisher worker entrypoint for polling and publishing pending events
- emit events from outbound send, provider delivery reconciliation, inbound reply
  processing, handoff/opt-out paths, campaign enrollment, and workflow transitions
- covered the behavior with fake-based application tests, Postgres repository tests, and
  publisher envelope tests

### Slice 17 — Campaign admin and publishing APIs

Status: complete.

Goal: expose the minimum operational controls required to manage campaigns safely in
V1.

Planned deliverables:

- create/edit draft campaigns and cadence configuration
- publish campaign versions
- pause campaigns and launch eligible batches
- enforce role-based permissions for admin/manager/agent operations
- audit campaign configuration changes and launches

Implemented notes:

- added explicit campaign admin domain DTOs and use cases for draft create/update,
  version publish, campaign pause, and batch-launch audit recording
- added a write-side campaign admin repository and dedicated campaign admin audit
  repository
- added `campaign_admin_audit_logs` migration/model for queryable business audit
  history
- added admin API endpoints for draft create/update, publish, and pause with
  role/capability checks
- updated dormant selector runs to use permission evaluation and record launch audit
  entries/events
- emit campaign draft, publish, pause, and batch-launch events through the
  transactional outbox seam
- covered behavior with fake-based use-case tests, API tests, and a real Postgres
  repository/audit test

### Slice 18 — Reporting, RLS, and pilot-operational readiness

Status: complete.

Goal: close the final visibility and tenant-isolation gaps before calling V1 ready.

Planned deliverables:

- reporting and operational views for workflow/message/handoff status
- audit visibility for major business decisions and failures
- deployed PostgreSQL row-level security validation
- final readiness validation across sync, workflow, messaging, and handoff operations

Implemented notes:

- added explicit reporting read models, permission-checked reporting use cases, and
  workspace-scoped reporting API routes
- added Postgres reporting queries for workspace operations, campaign operations, and
  campaign admin audit visibility
- added PostgreSQL row-level security policies for tenant-owned business-flow tables,
  plus workspace/service session-context helpers for routes, webhooks, workers, and
  Temporal activities
- validated the reporting repository and RLS behavior against real Postgres
- expanded the real-Postgres business-flow harness to cover delivery reconciliation,
  admin audit visibility, and reporting visibility on top of the existing
  sync -> enrollment -> send -> inbound -> handoff path

## Slice-plan status

Slices 14–18 of the backend business-flow plan are now complete and verified.

## Execution Rules

- Do not start a later slice before the current slice is implemented, tested, and
  reviewed.
- Keep CRM-specific details in the Follow Up Boss adapter layer.
- Keep message planning logic explicit in application/domain code, not hidden in
  prompts.
- Any future external context source must enter the planner through a normalized,
  approved context model rather than raw provider payloads.
- Prefer fakes for use-case tests and repository-focused tests for persistence.
- End every slice with green `ruff`, `mypy`, targeted tests, and a full `pytest`
  run before moving on.

## Immediate Next Step

No remaining slices in this plan.

If follow-up work is needed, create a new approved slice or plan before continuing.
