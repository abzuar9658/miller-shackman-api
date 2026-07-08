# Business Flow Implementation Plan

## Purpose

This document turns the approved V1 business-flow design into an execution plan.
It defines the delivery order, slice boundaries, and validation expectations so
we can build the backend in business-priority order without mixing outbound and
inbound work prematurely.

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
- property/listing matching

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

Start the next slice only after explicit approval:

1. decide whether the next slice should be campaign enrollment or durable cadence execution
2. if cadence execution is next, add only one simple wait/send/wait loop through Temporal
3. keep pre-send safety checks inside application/domain use cases
4. keep provider delivery idempotent through existing outbound message records
5. avoid provider callback workflows until cadence execution is proven
6. run `ruff`, `mypy`, targeted tests, and full `pytest`
