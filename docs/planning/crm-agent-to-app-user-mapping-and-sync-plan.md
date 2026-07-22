# CRM Agent to App User Mapping and Sync Plan

## Status

Status: **Slices 1–7 complete**.
This document started as the implementation plan. Slices 1 through 7 are now
implemented and validated; the remaining slices stay planned work.

## Purpose

This document defines how the platform keeps the **CRM-assigned agent** (the source
of truth for lead ownership in Follow Up Boss) in sync with the **app-created user**
(the source of truth for authentication, permissions, and in-app notifications).

It also describes the product capabilities that become possible once that mapping is
reliable.

## Problem Statement

- Each lead in Follow Up Boss has an assigned agent.
- Brokerage admins create agents as users in this app.
- Today, the two identity spaces are not linked.
- Without a mapping, the app cannot:
  - reliably route handoff notifications to the right person,
  - build an agent-specific dashboard view,
  - enforce permission checks that follow real CRM ownership,
  - safely pause/resume outreach when CRM ownership changes.

## Approved Approach

Build a **first-class CRM-agent-to-app-user mapping layer** that is initially driven by
scheduled pull synchronization. Webhooks are not required for V1, but the design must
allow them to be added later as an optimization without changing the data model.

### Core Principle

- **CRM** is the source of truth for **lead ownership**.
- **App** is the source of truth for **authentication, roles, and permissions**.
- **Mapping layer** is the authoritative bridge between the two.

### Pull-First Strategy

Because CRM webhooks are not registered yet, synchronization is pull-based:

- CRM agent directory sync: low-frequency, admin-configurable.
- Incremental lead sync: detects ownership changes, pauses workflows, creates alerts.
- Daily full reconciliation: catches missed updates and mapping drift.
- Pre-send just-in-time CRM refresh: guarantees safety before any outbound message.

Pull sync is the source of truth refresh mechanism. Webhooks can be added later only
as an acceleration layer, not as a replacement for the reconciliation or pre-send
safety path.

## Why This Is Worth Building

A reliable mapping layer unlocks the following product capabilities:

1. **Agent login value** — agents see their own assigned leads, nurture states, and
   handoff status in a dedicated dashboard view.
2. **Accurate handoff routing** — handoff emails, CRM notes, and in-app notifications
   go to the correct assigned agent.
3. **Agent-specific work queues** — "My handoffs", "Needs my attention", "Paused for
   my review", "Leads I can resume".
4. **Permission checks that follow real ownership** — assigned agents, managers, and
   admins get the right access without relying on loose email matching.
5. **Trustworthy notifications** — pre-flight digests, reply alerts, and ownership
   change alerts reach the right person.
6. **Agent performance and accountability** — handoff response time, AI-managed lead
   outcomes, and reactivation metrics can be computed per real assigned agent.
7. **Better auditability** — every send, handoff, and pause can be tied to a resolved
   app user at the moment the decision was made.
8. **Safer pause/resume** — ownership changes and human activity automatically pause
   AI outreach, and only the correct actor can resume.
9. **Clean future collaboration** — handoff acknowledgment, reassignment, notes, and
   SLA timers can all be built on the same identity bridge.

## Data Model

### `crm_agents`

A read-only-ish mirror of agents/users found in the CRM.

| Column | Purpose |
| --- | --- |
| `id` | internal UUID |
| `workspace_id` | tenant isolation |
| `crm_provider` | e.g. `follow_up_boss` |
| `crm_agent_id` | provider's native agent/user ID |
| `name` | display name from CRM |
| `email` | normalized email from CRM |
| `phone` | optional phone from CRM |
| `is_active` | whether the CRM still reports this agent active |
| `last_synced_at` | last time this row was refreshed |
| `raw_attributes` | small JSON blob for provider-specific fields |

Constraints: `unique(workspace_id, crm_provider, crm_agent_id)`.

### `workspace_agent_crm_mappings`

The explicit bridge between a CRM agent and an app user.

| Column | Purpose |
| --- | --- |
| `id` | internal UUID |
| `workspace_id` | tenant isolation |
| `crm_agent_id` | FK to `crm_agents` |
| `app_user_id` | FK to app `users` |
| `mapping_status` | `suggested`, `verified`, `overridden`, `disputed`, `unmapped` |
| `resolution_source` | `auto_email_match`, `admin_manual`, `system_unlinked` |
| `resolved_by_user_id` | admin who confirmed or overrode |
| `resolved_at` | timestamp of confirmation/override |
| `created_at`, `updated_at` | audit timestamps |

Constraints:

- `unique(workspace_id, crm_agent_id)`
- `unique(workspace_id, app_user_id)` where status is `verified` or `overridden`

A CRM agent can be unmapped. An app user can be unmapped. A mapping can be verified
or overridden by an admin. Suggested mappings are created by deterministic matching but
require explicit confirmation before they are trusted for automation.

### `workspace_agent_mapping_configs`

Store an app-level fallback owner for unmapped CRM assignments in a dedicated
workspace-level mapping configuration table.

| Field | Purpose |
| --- | --- |
| `unmapped_assignment_fallback_user_id` | preferred active workspace manager who becomes the effective in-app owner when a CRM agent cannot be mapped |

Rules:

- Must reference an active user with an active `manager` membership in the workspace.
- Is configured by a brokerage admin in Settings.
- Is used only as the app's operational fallback owner.
- Does **not** change the CRM lead owner.
- If the preferred fallback manager is missing or inactive, the system selects another
  active workspace manager using a deterministic fallback rule.
- Agent-resolution failures never block outreach on their own; they always route to a
  workspace manager when at least one active manager exists.

### Lead assignment resolution fields

Extend the canonical lead record / lead snapshot to store:

| Field | Purpose |
| --- | --- |
| `assigned_agent_crm_id` | raw CRM agent ID on the lead |
| `assigned_agent_user_id` | resolved app user from the mapping |
| `effective_owner_user_id` | app user who should see the lead in-app and receive notifications; mapped agent when resolved, fallback manager when unresolved |
| `effective_owner_source` | `crm_mapping` or `workspace_manager_fallback` |
| `assignment_resolution_status` | `resolved`, `unmapped_crm_agent`, `ambiguous_crm_agent`, `crm_agent_inactive`, `app_user_inactive`, `unresolved` |
| `assignment_last_resolved_at` | when resolution was last run |
| `assignment_snapshot_fresh_at` | reserved for later refresh/reconciliation work; not yet stored in Slice 3 |

## Mapping Resolution Rules

1. Take `assigned_agent_crm_id` from the CRM lead.
2. Look up the matching `crm_agents` row.
3. If the CRM agent is missing, status = `unmapped_crm_agent`.
4. If the CRM agent is inactive, status = `crm_agent_inactive`.
5. Find the mapping for that CRM agent.
   - If `verified` or `overridden`, return the mapped `app_user_id`.
   - If `suggested` or `disputed`, do not trust it as the lead's assigned app agent.
   - If no mapping exists, status = `unmapped_crm_agent`.
6. If the mapped app user is inactive or missing, status = `app_user_inactive`.
7. If two CRM agents map to the same active app user, status = `ambiguous_crm_agent`.
8. If the assigned app agent is unresolved for any reason, attach
   `effective_owner_user_id = unmapped_assignment_fallback_user_id` and
   `effective_owner_source = workspace_manager_fallback`.
9. If the preferred fallback manager is missing or inactive, select another active
   workspace manager using a deterministic rule such as oldest active `manager`
   membership in the workspace.
10. If there are no active workspace managers at all, status =
    `fallback_manager_missing`; this is a workspace configuration error, not an
    agent-resolution error.
11. Otherwise, when the mapping is verified or overridden and the app user is active,
    set `effective_owner_user_id = assigned_agent_user_id`,
    `effective_owner_source = crm_mapping`, and status = `resolved`.

Important: only `verified` or `overridden` mappings are trusted as the lead's actual
assigned app agent. Suggested mappings are visible to admins but do not become the
assigned app agent until confirmed. If no trusted mapping exists, the workspace
fallback manager becomes the effective in-app owner so outreach and handoff routing can
continue unless another safety rule blocks the lead.

## Synchronization Jobs

### Job 1: CRM Agent Directory Sync

Frequency: admin-configurable, default **1 hour**, minimum **15 minutes**, maximum
**24 hours**.

Responsibilities:

- Pull the complete list of agents/users from Follow Up Boss.
- Upsert into `crm_agents`.
- Mark CRM agents as inactive if the provider reports them as inactive or removed.
- Run deterministic auto-matching by normalized email.
- Create `suggested` mappings for matches that do not already exist.
- Never downgrade a `verified` or `overridden` mapping automatically.
- Emit audit/outbox events for new, changed, and deactivated CRM agents.
- Expose health in the admin UI: last sync, next sync, count of mapped/unmapped.

Admin controls:

- enable/disable the sync
- change interval
- manual "Sync now" button
- view last sync status and error

### Job 2: Incremental Lead Assignment Sync

Frequency: fixed by the platform, default **5–15 minutes**, not exposed to admin
configuration in V1. (Lead ownership freshness must not be loosened by accident.)

Responsibilities:

- Pull leads updated since the last sync cursor.
- Update canonical lead records and `assigned_agent_crm_id`.
- Re-run mapping resolution.
- Update `assignment_resolution_status`, `assigned_agent_user_id`, and
  `effective_owner_user_id`.
- If ownership changes on an active or queued workflow, pause the workflow and
create a handoff/attention record.
- If the new assignment is unresolved, route the lead to the workspace fallback
  manager, keep the lead in the attention queue, and continue automation unless some
  other safety rule blocks it.
- If the preferred fallback manager is unavailable, automatically choose another active
  workspace manager and continue automation.
- Only if the workspace has zero active managers should the system surface a
  configuration error.
- Emit audit/outbox events for ownership changes and resolution changes.

### Job 3: Daily Full Reconciliation

Frequency: once per day during off-hours.

Responsibilities:

- Scan all nurture-relevant leads.
- Re-resolve every assignment against the current mapping table.
- Detect mappings that have become stale, ambiguous, or inactive.
- Find leads whose `assigned_agent_crm_id` points to a CRM agent no longer in the
directory.
- Detect active app users that were unmapped or whose mapped CRM agent changed.
- Create attention items and audit events for any drift.
- Does not send messages; it is purely a safety/reconciliation pass.

### Job 4: Pre-Send Just-in-Time CRM Refresh

Frequency: immediately before every outbound SMS or email.

Responsibilities:

- Lock the lead/workflow row.
- Fetch the latest CRM lead snapshot for this single lead.
- Update `assigned_agent_crm_id` and activity timestamps.
- Re-run mapping resolution.
- Check whether the resolved owner changed since the workflow started.
- Check recent human activity in the CRM.
- Check suppression, opt-out, consent, and quiet hours.
- If the CRM refresh fails, **do not send**. Pause or retry with backoff.
- If the assignment is reassigned or stale, **do not send**.
- If the mapping is unresolved, attach the workspace fallback manager and continue only
  if the fallback is active and all other pre-send checks pass.
- If the preferred fallback manager is unavailable, automatically choose another active
  workspace manager before considering the lead ownership-unresolved.
- Record the CRM refresh and pre-send decision in the audit log.

This is the most important safety rule when operating without webhooks.

## Safety Rules

- Unknown or unresolved CRM mapping does **not** stop outreach by itself. In that case,
  the lead is assigned to the workspace's configured fallback manager inside the app.
- The fallback manager becomes the effective in-app owner for dashboard visibility,
  handoff routing, digests, alerts, and resume ownership until a real CRM-agent-to-app
  mapping is verified.
- If the configured fallback manager is unavailable, the system must automatically pick
  another active workspace manager before treating ownership as a configuration issue.
- Stale CRM snapshot (older than the configured freshness threshold, or failed
  pre-send refresh) = **no automated outreach**.
- Reassigned lead = pause workflow, create handoff/attention record, notify the
  correct new owner if resolved, otherwise notify manager/admin.
- Inactive CRM agent or inactive mapped app user falls back to the workspace manager;
  only if the workspace has zero active managers does ownership become a configuration
  issue.
- Only `verified` or `overridden` mappings are used to identify the lead's real
  assigned app agent. Suggested mappings are admin-visible only.
- Pull sync cadence is not allowed to weaken the pre-send CRM refresh or the
  incremental lead sync.

## Admin UI / UX Plan

### Settings: CRM Agent Directory Sync

A card or section under workspace settings labeled **CRM Agent Sync**.

Fields:

- sync enabled toggle
- sync interval (dropdown: 15 min, 30 min, 1 hr, 2 hr, 4 hr, 6 hr, 12 hr, 24 hr)
- preferred fallback manager selector
- last successful sync timestamp
- next scheduled sync timestamp
- sync status badge (`healthy`, `pending`, `error`, `disabled`)
- error message from last failed sync
- manual "Sync now" button
- summary counts: total CRM agents, mapped, unmapped, conflicted, inactive

### Settings: Agent Mapping tab

A dedicated tab called **Agent Mapping**.

Primary table columns:

- CRM agent name
- CRM email
- CRM status (active/inactive)
- App user match
- Mapping status (verified, suggested, overridden, disputed, unmapped)
- Affected leads count
- Last synced
- Actions

Filters:

- all
- unmapped
- suggested
- verified
- overridden/disputed
- inactive CRM agents
- inactive app users
- with affected leads
- without affected leads

Row actions:

- **Confirm match** — for suggested mappings, promote to verified.
- **Choose app user** — open a picker to map to an existing app user.
- **Invite new app user** — create an invitation for the CRM email if no app user
  exists.
- **Unlink mapping** — mark as unmapped, require reason.
- **View affected leads** — opens a side panel or page filtered to leads owned by this
  CRM agent.

Bulk actions:

- confirm all suggested mappings that have exact email match and no conflicts
- export unmapped agents with affected lead counts

Suggested-match UX:

- When a CRM agent matches an app user by exact normalized email, show it as a
  suggested mapping with a one-click "Confirm" button.
- If two CRM agents match the same app user, mark as disputed and require admin
  resolution.
- If a CRM agent has no matching email, show "Invite" or "Choose user" options.

## Slice-by-Slice Implementation Plan

### Slice 1 — Mapping data model and repositories

Status: **Complete**

Implemented:

- Alembic migration `0040_create_crm_agent_mapping_tables.py`
- `crm_agents`, `workspace_agent_crm_mappings`, and `workspace_agent_mapping_configs`
- domain models and repository ports for CRM agents, mappings, and fallback config
- Postgres repository implementations and focused repository tests

Goal: add the database layer and repository ports before any sync logic or UI.

Deliverables:

- Alembic migration for `crm_agents` and `workspace_agent_crm_mappings`
- Persist `unmapped_assignment_fallback_user_id` in `workspace_agent_mapping_configs`
- SQLAlchemy models with workspace isolation, RLS, and constraints
- Repository ports in `application/ports`
- Postgres repository implementations
- Domain enums for mapping status, resolution source, and assignment resolution status
- Unit tests for the repository layer against a real Postgres test database
- Seed test data and factory helpers

Out of scope:

- CRM adapter changes
- Sync jobs
- API routes
- UI

Validation:

- `ruff`, `mypy`, pytest repository tests
- migration sanity checks

### Slice 2 — CRM agent directory pull

Status: **Complete**

Implemented:

- canonical CRM agent-directory seam: `CRMAgentDirectoryEntry` and `CRMAgentDirectorySource`
- Follow Up Boss `list_agents()` support with pagination against `/users`
- workspace-aware normalized-email matching lookup
- `sync_crm_agents_for_workspace(...)` with suggested/unmapped creation, admin-lock preservation, and CRM-agent deactivation
- focused adapter, repository, and use-case validation

Goal: pull agents from Follow Up Boss and populate the mapping table with suggested
matches.

Deliverables:

- New CRM adapter method: `list_agents(workspace_id)` returning canonical CRM agent
  records
- Follow Up Boss implementation of `list_agents`
- Use case: `sync_crm_agents_for_workspace`
  - upsert CRM agents
  - run deterministic email matching
  - create suggested mappings
  - never downgrade verified/overridden mappings
  - emit audit events
- Fake CRM adapter support for tests
- Unit tests for the use case using fakes
- Repository method to find app users by normalized email for matching

Validation:

- fake-based tests for matching logic
- `ruff`, `mypy`, pytest

### Slice 3 — Lead assignment resolution during lead sync

Status: **Complete**

Goal: update lead sync so that after storing the CRM lead, the app resolves the
assigned CRM agent to an app user and stores the resolution status.

Deliverables:

- Update `CanonicalLeadRecord` to carry first-class assignment-resolution fields
- Update lead sync use case to call a dedicated assignment-resolution service
- Store `assigned_agent_crm_id`, `assigned_agent_user_id`, `effective_owner_user_id`,
  `effective_owner_source`, `assignment_resolution_status`, and
  `assignment_last_resolved_at` on the lead record
- Update `is_actor_assigned_to_lead` and lead/handoff readers to use
  `effective_owner_user_id` for in-app ownership, with a legacy fallback for older
  rows that still only have the old custom-field representation
- Add a domain rule for assignment resolution
- Tests for resolved, unmapped-with-fallback, inactive-with-fallback, ambiguous, and
  fallback-missing cases

Implemented:

- pure domain rule module: `app/domain/lead_assignment.py`
- application resolver/context loader: `app/application/services/lead_assignment_resolution.py`
- lead sync wiring in `app/application/use_cases/crm_sync.py`
- worker wiring in `app/interfaces/workers/crm_sync_worker.py`
- lead persistence migration `0041_add_lead_assignment_resolution_fields.py`
- lead repository/model support for the new fields
- removal of the misleading `mapped_custom_fields["assigned_agent_user_id"]`
  population from the Follow Up Boss lead mapper
- updated ownership/reader tests, new resolver tests, sync wiring tests, worker tests,
  and mapper expectation updates

Validation:

- fake-based tests for resolution rules
- update existing tests that reference lead ownership
- `ruff`, `mypy`, pytest

### Slice 4 — Pull-based lead assignment reconciliation

Status: **Complete**

Goal: detect assignment changes from incremental lead sync and pause workflows or
surface alerts when ownership changes or becomes unresolved.

Deliverables:

- Dedicated reconciliation use case: `reconcile_lead_assignment_change(...)`
- CRM sync now compares the previous persisted lead with the newly resolved lead on
  every synced snapshot
- Compare previous and current `assigned_agent_user_id` and `effective_owner_user_id`
- If ownership changed, pause active workflows, queue a Temporal pause signal, and
  cancel pending outbound messages for that lead
- If only the resolution status changed but effective ownership stayed the same,
  emit a reconciliation event without pausing the workflow
- Emit `lead.assignment_reconciled` events and reuse `workflow.transitioned` when a
  pause occurs
- Surface attention through existing paused-workflow + lead-resolution state rather
  than introducing a new attention-record table in this slice
- Tests using fakes for reconciliation behavior, CRM sync wiring, and worker wiring

Validation:

- fake-based tests for ownership change detection
- `ruff`, `mypy`, pytest

Implemented:

- `app/application/use_cases/reconcile_lead_assignment.py`
- CRM sync integration that fetches the previous lead, upserts the resolved lead,
  then reconciles ownership drift
- worker wiring for `PostgresTemporalSignalOutboxRepository` and
  `PostgresOutboundMessageRepository`
- `lead.assignment_reconciled` event type and `crm_ownership_changed` workflow
  transition reason
- pending outbound-message cancellation on ownership drift
- focused tests covering pause/signal/cancel/event behavior

### Slice 5 — Pre-send CRM refresh

Status: **Complete**

Goal: before any outbound SMS or email, refresh the individual lead from the CRM and
re-run all ownership, consent, suppression, and activity checks.

Deliverables:

- Add a pre-send use case or extend the existing pre-send safety path
- Lock lead/workflow row with `SELECT FOR UPDATE`
- Fetch latest CRM lead snapshot
- Re-resolve assignment
- Re-check recent human activity, opt-outs, suppression, consent, quiet hours,
  frequency limits
- If anything fails or is stale, block send and record reason
- Retry/backoff policy for CRM refresh failures
- Tests for stale snapshot, reassignment, unresolved mapping with fallback,
  fallback-manager-missing, and CRM outage

Validation:

- fake-based tests for each failure mode
- `ruff`, `mypy`, pytest

Implemented:

- single-lead canonical snapshot seam: `CanonicalLeadRefreshSource` in
  `app/application/ports/crm_sync.py`
- `FollowUpBossCRMClient.get_lead_snapshot(...)` reusing the existing canonical mapper
- `PreSendCRMRefreshContext` data class carrying the refresh source and all
  repositories needed for re-resolution
- `send_outbound_message` now accepts an optional `crm_refresh_context` and calls
  `_refresh_lead_for_pre_send(...)` before the final provider call
- callers updated: `campaign_cadence_execution`, `lead_draft_review`, and the API
  dependency bundle
- refresh results merge into `OutboundSendContext` and re-run pre-send gating
- focused tests: send-path refresh success, CRM-not-found rejection, and adapter
  snapshot mapping

### Slice 6 — Admin mapping API

Status: **Complete**

Implemented:

- brokerage-admin-only CRM agent mapping admin use case
- workspace-scoped API routes for listing CRM agents, listing mapping rows, upserting
  mappings, unlinking mappings, manual CRM agent-directory sync, and derived sync
  status
- Pydantic request/response schemas for mapping rows, summaries, mutation results, and
  sync results
- Postgres repository lookup by mapping id for mutation routes
- permission and workspace-context checks around all admin mapping actions
- focused use-case, API, and repository validation

Deferred from the original larger endpoint list:

- invite-new-user-from-CRM flow
- persisted sync schedule/settings endpoints
- affected-leads counts and side panel

Goal: expose endpoints that the settings/agent-mapping tab will consume.

Deliverables:

- `GET /api/v1/workspaces/{workspace_id}/crm-agents` with filters and pagination
- `GET /api/v1/workspaces/{workspace_id}/crm-agent-mappings` with filters and
  pagination
- `POST /api/v1/workspaces/{workspace_id}/crm-agent-mappings` — create or confirm
  mapping
- `PATCH /api/v1/workspaces/{workspace_id}/crm-agent-mappings/{mapping_id}` —
  override or update status
- `DELETE /api/v1/workspaces/{workspace_id}/crm-agent-mappings/{mapping_id}` —
  unlink (soft-delete semantics, set to unmapped)
- `POST /api/v1/workspaces/{workspace_id}/crm-agent-mappings/{mapping_id}/invite`
  — invite a new app user from the CRM email
- `POST /api/v1/workspaces/{workspace_id}/crm-agent-directory-sync` — manual sync
  trigger
- `GET /api/v1/workspaces/{workspace_id}/crm-agent-directory-sync/status` — sync
  status and settings
- `PATCH /api/v1/workspaces/{workspace_id}/crm-agent-directory-sync/settings` —
  update interval, enabled flag, and fallback manager
- Pydantic request/response schemas
- Permission checks: only workspace admin or brokerage admin can modify
- Tests for endpoints using fakes and in-memory permission helpers

Validation:

- API tests
- `ruff`, `mypy`, pytest

### Slice 7 — Admin mapping UI

Status: **Complete**

Implemented:

- dedicated brokerage-admin route: `/agent-mapping`
- sidebar navigation item under Controls
- typed frontend API client functions for mapping list, upsert, unlink, and manual sync
- Agent Mapping page with summary metrics, search/status filters, mapping table,
  confirm/save actions, unlink action, sync-now action, loading/error/empty states, and
  safety copy that keeps backend rules authoritative
- route test covering render and suggested-match confirmation

Deferred from the original larger UI list:

- invite-new-user flow
- affected-leads side panel
- richer persisted sync-health history

Goal: build the agent-mapping tab and the CRM sync settings card in the React
frontend.

Deliverables:

- Settings page section: **CRM Agent Sync**
- New tab: **Agent Mapping**
- Mapping table with filters and row actions
- Confirm/choose/invite/unlink flows
- Affected leads side panel
- Mapping health summary badges
- Loading, empty, error, and permission-denied states
- TanStack Query hooks, API client updates, Zod validation
- Role-aware visibility (only brokerage admin / manager / admin roles)
- Storybook or route tests for major interactions

Validation:

- `pnpm lint`, `pnpm typecheck`, `pnpm test`
- manual browser inspection

### Slice 8 — Agent-facing dashboard views

Goal: once mapping is reliable, give agents a reason to log in.

Deliverables:

- **My Leads** page: leads assigned to the logged-in agent, with nurture status,
  last message, reply status, handoff status, AI state
- **My Handoffs** page: handoffs assigned to the agent, with acknowledgment and
  next-action UI
- Role-aware sidebar updates so agents see only their own queues
- Dashboard badges and quick filters

Validation:

- frontend tests for role-based access
- API integration tests for agent-scoped queries
- `pnpm check` and `make check`

### Slice 9 — Handoff notification routing

Goal: route handoff emails and in-app notifications to the resolved app user.

Deliverables:

- Update handoff creation use case to use `effective_owner_user_id`
- Send handoff email to the mapped app user when resolved, otherwise to the fallback
  manager
- If fallback is missing, notify manager/admin fallback chain and write CRM note if
  policy allows
- Update pre-flight digest routing to the resolved agent or fallback manager
- Add fallback/escalation rules for unmapped handoffs
- Tests for resolved, unmapped, and fallback cases

Validation:

- fake-based tests for handoff routing
- `ruff`, `mypy`, pytest

### Slice 10 — Scheduled job wiring and observability

Goal: make the sync jobs run on a schedule and make them observable.

Deliverables:

- Temporal scheduled workflow or Celery beat schedule for agent directory sync,
  incremental lead sync, and daily reconciliation
- Admin-configurable interval for agent directory sync persisted in workspace settings
- Observability: last run, next run, success/failure counts, error messages
- Alerting when a sync fails repeatedly or unmapped agents exceed a threshold
- Worker entry points and `make` target updates if needed
- Operational runbook snippet

Validation:

- integration tests for schedules using Temporal test server or Celery test harness
- `make check`

## Failure Modes and Handling

| Scenario | Behavior |
| --- | --- |
| CRM agent directory sync fails | Retry with exponential backoff. Do not block existing verified mappings. Surface error in admin UI. |
| Incremental lead sync fails | Retry. If repeated failures, daily reconciliation catches drift. Pre-send refresh still blocks stale sends. |
| Lead assigned to unmapped CRM agent | Keep CRM ownership unchanged, assign the workspace fallback manager as `effective_owner_user_id`, create an attention item, and continue outreach unless another policy blocks the lead. |
| Lead assigned to inactive CRM agent | Fall back to the workspace manager, create an attention item, and alert admin. |
| Mapped app user is inactive | Status = `app_user_inactive`. Fall back to the workspace manager and alert admin. |
| Two CRM agents map to one app user | Status = `ambiguous_crm_agent`. Use the fallback manager until admin resolution. |
| Preferred fallback manager missing or inactive | Automatically choose another active workspace manager and continue outreach. Surface a warning to admin so the preferred fallback can be repaired. |
| Workspace has zero active managers | Ownership fallback cannot be resolved. Surface a configuration error and escalate to admin immediately. |
| CRM agent email changes | New email updates `crm_agents`. Existing verified mapping stays unless admin unlinks. Suggested match re-evaluated. |
| App user email changes | Matching is re-run during next agent sync. If the verified mapping no longer matches, mark as disputed and require admin review. |
| Ownership changes between syncs | Detected at next incremental sync or at pre-send refresh. Workflow paused. Attention item created. |
| CRM refresh fails at pre-send | Do not send. Record `crm_snapshot_stale` or `crm_refresh_failed`. Retry later. |

## Out of Scope

- Real-time webhook-based sync in V1 (webhooks may be added later).
- Automatic creation of app users from CRM agents without admin action.
- Bidirectional sync that writes app users back to the CRM.
- Advanced matching beyond normalized email in V1.
- Role-specific automation permissions beyond owner/manager/admin.
- Agent-level reporting dashboards in Slice 1–7 (enabled in Slice 8–10).
- Custom timezone per agent.

## Validation and Definition of Done

For each slice:

1. Business rules are explicit and tested.
2. Failure behavior is defined and tested.
3. Audit events are created.
4. Permissions are checked.
5. External actions are idempotent.
6. No infrastructure SDK leaks into domain or application code.
7. `ruff` and `mypy` pass.
8. Targeted tests pass.
9. Documentation (this plan and any inline comments) is updated.
10. Pull request includes rollback plan and security review if touching permissions.

## Immediate Next Step

Begin **Slice 8 — agent-facing dashboard views** when the product is ready to extend
role-specific agent value beyond the current shared work surfaces.
