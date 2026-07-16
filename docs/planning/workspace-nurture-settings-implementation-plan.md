# Workspace Nurture Settings Implementation Plan

## Goal

Replace the admin-facing "campaign" mental model with a single workspace-level
"Nurture Settings" experience while keeping the current `campaign` and
`campaign_version` backend model as the execution and audit boundary.

The core product rule is:

- admins manage one workspace nurture policy
- the system publishes immutable versions of that policy
- leads keep following the version they were enrolled into unless explicitly migrated

## Why this change

The current backend already supports richer configuration than the current admin UI
shows. Today a published version already stores:

- enabled channels
- daily start cap
- dormant threshold days
- quiet hours and timezone
- SMS compliance and preflight digest flags
- CRM enrollment tag
- whether assigned agents can manually enroll leads
- prompt version and approved model
- cadence steps with channel, delay, goal, `template_key`, and max attempts

The confusing part is not the backend model. The confusing part is exposing that
model as a campaign page when the product currently behaves like one nurture policy
per workspace.

## Product decision

### Admin-facing language

Use a single workspace surface named one of:

- Workspace Nurture Settings
- AI Nurture Settings
- Lead Nurture Rules

Do not make admins think in terms of campaign creation unless the product later
supports multiple operational programs in the same workspace.

### Internal language

Keep these internal concepts:

- `campaign`: durable policy container
- `campaign_version`: immutable published rule snapshot
- `campaign_enrollment`: one lead enrolled into one published version

This preserves auditability, reporting, and safe versioned execution.

## Non-goals

- removing `campaign` or `campaign_version` from the backend
- switching active workflows to always read mutable workspace settings live
- building a full dynamic rules engine for enrollment in phase one

## Admin UX requirements

The page should optimize for "admin can change any settings easily".

### Editing principles

- one page for the full nurture policy
- obvious sections with plain-language labels
- editable draft state separate from published state
- sticky Save Draft and Publish actions
- inline validation near each field
- reset draft to published action
- no hidden settings spread across unrelated pages
- show plain-language explanations for effects of each setting
- include previews before publish where the setting affects audience or messages

### Page sections

#### 1. Overview

- policy status: active or paused
- published version number
- last published at and by whom
- draft dirty state
- top-level actions: save draft, publish, pause, resume

#### 2. Audience and enrollment

- dormant threshold days
- CRM enrollment tag
- allow assigned agent manual enrollment
- audience preview counts
- why leads are included or excluded
- preview of held-back leads when cap or policy blocks apply

#### 3. Sending behavior

- enabled channels
- daily start cap
- quiet hours start and end
- timezone
- SMS compliance required
- preflight digest enabled

#### 4. Cadence

- ordered list of steps
- per-step channel
- per-step delay
- per-step message goal
- per-step `template_key`
- per-step max attempts
- add, remove, and reorder steps

#### 5. Message controls

The current backend already has `message_goal` and `template_key`, but message
drafting is still LLM-driven. To give admins real control, add step-level message
guidance fields in a later slice:

- template text or structured message guidance
- tone
- required phrases
- blocked phrases
- CTA guidance
- review required before send

#### 6. Lead controls

The policy page should link to lead-level controls because admins also need
exceptions and overrides.

Existing lead-level surfaces already support:

- manual enrollment options and manual enrollment start
- resume eligibility and resume action
- rejected draft review approval and send

Missing lead-level controls that should be added:

- pause lead workflow
- suppress lead from nurture
- unsuppress or re-enroll lead
- reschedule next action
- skip current cadence step
- inspect why a lead was selected, held back, or blocked

#### 7. Reporting and audit

Surface existing reporting and audit data next to settings:

- workflow counts
- enrollment counts
- message counts
- handoff counts
- latest audit entries
- last successful CRM sync

## Backend API plan

Keep existing `/campaigns` routes for compatibility, but add workspace-level alias
routes for the admin UI.

### Read and write aliases

- `GET /workspaces/{workspace_id}/nurture-settings`
- `PUT /workspaces/{workspace_id}/nurture-settings/draft`
- `POST /workspaces/{workspace_id}/nurture-settings/publish`
- `POST /workspaces/{workspace_id}/nurture-settings/pause`
- `POST /workspaces/{workspace_id}/nurture-settings/resume`

These routes should resolve a single canonical nurture policy for the workspace and
delegate to the current campaign use cases.

### New admin helper routes

- `POST /workspaces/{workspace_id}/nurture-settings/audience-preview`
- `GET /workspaces/{workspace_id}/nurture-settings/reporting`
- `GET /workspaces/{workspace_id}/nurture-settings/audit-logs`

### Lead override routes to add

- `POST /workspaces/{workspace_id}/leads/{lead_id}/pause`
- `POST /workspaces/{workspace_id}/leads/{lead_id}/suppress`
- `POST /workspaces/{workspace_id}/leads/{lead_id}/unsuppress`
- `POST /workspaces/{workspace_id}/leads/{lead_id}/skip-current-step`
- `POST /workspaces/{workspace_id}/leads/{lead_id}/reschedule-next-action`

## Single-policy resolution

The new workspace-level routes must not guess by taking the first campaign from a
list. Introduce an explicit way to identify the workspace's canonical nurture
policy.

Preferred approaches:

1. add a stable `campaign_kind` or `system_key` such as `workspace_nurture`
2. or store `default_nurture_campaign_id` on the workspace

Either approach is safer than relying on list order.

## Data and model changes

### Keep as-is for first slice

- `CampaignAdminCampaign`
- `CampaignAdminVersion`
- `CampaignAdminCadenceStep`
- current reporting models

### Add in follow-up slices

- canonical workspace nurture policy identifier
- audience preview response model with included, excluded, and held-back reasons
- optional cadence-step message-governance fields
- lead override use cases and request/response schemas

## Recommended delivery phases

### Phase 1: Rename and expose existing power

- add workspace-level nurture settings read/write aliases
- keep current campaign internals unchanged
- expose all existing version fields in one admin form
- show existing reporting and audit data on the same page

### Phase 2: Audience clarity

- add audience preview endpoint
- show eligible, excluded, and held-back leads with reasons
- make daily cap behavior visible before publish or batch launch

### Phase 3: Lead overrides

- add lead pause and suppress actions
- add re-enroll and reschedule actions
- expose workflow state and selection reasons clearly in lead detail

### Phase 4: Message governance

- add richer step-level template and review controls
- allow sample draft preview per step
- keep LLM drafting, but constrain it with admin-authored guidance

## Acceptance criteria

- admins can manage nurture from one workspace page without needing campaign jargon
- every current version setting is editable from that page
- saving changes creates or updates a draft rather than mutating published behavior
- publishing creates a new immutable version
- active leads continue following their enrolled version by default
- admins can see why leads are selected, excluded, or held back
- admins can pause or override individual leads without editing raw workflow state
- reporting and audit history remain intact

## Recommendation

Implement Phase 1 first and keep the backend campaign/version model. That gives the
product the simple workspace-level mental model you want without losing versioning,
auditability, or room for future multi-campaign support.