# Workspace Nurture Settings Frontend Mapping

## Goal

Wire the admin UI to the new workspace-level nurture settings routes without
exposing campaign terminology in the frontend.

## Routes to use

- `GET /api/v1/workspaces/{workspace_id}/nurture-settings`
- `PUT /api/v1/workspaces/{workspace_id}/nurture-settings/draft`
- `POST /api/v1/workspaces/{workspace_id}/nurture-settings/publish`
- `POST /api/v1/workspaces/{workspace_id}/nurture-settings/pause`
- `POST /api/v1/workspaces/{workspace_id}/nurture-settings/resume`

Do not call the old `/campaigns` routes from the new admin page.

## Response shape

### GET detail response

Top-level fields:

- `status`
- `nurture_settings`
- `settings`
- `cadence`

### PUT / publish / pause / resume response

Top-level fields:

- `status`
- `nurture_settings`
- `settings`
- `cadence`
- `reasons`

## Frontend model mapping

### Policy summary

Map `nurture_settings` to the page-level policy state:

- `nurture_settings.nurture_settings_id` -> internal policy id
- `nurture_settings.name` -> page title or hidden fixed label
- `nurture_settings.status` -> active or paused badge
- `nurture_settings.active_settings_version_id` -> active published version id
- `nurture_settings.created_at` -> created metadata
- `nurture_settings.updated_at` -> last updated metadata
- `nurture_settings.created_by_user_id` -> created by metadata

### Editable settings form

Map `settings` into the editable form state:

- `enabled_channels`
- `daily_start_cap`
- `dormant_threshold_days`
- `quiet_hours_start`
- `quiet_hours_end`
- `timezone`
- `sms_compliance_required`
- `preflight_digest_enabled`
- `crm_enrollment_tag`
- `allow_assigned_agent_manual_enrollment`
- `prompt_version`
- `approved_model`

Useful metadata from `settings`:

- `settings.settings_version_id` -> current draft or active version id
- `settings.revision` -> show as version number in UI
- `settings.status` -> `draft` or `published`
- `settings.published_at` -> published timestamp
- `settings.created_at` -> draft creation timestamp
- `settings.created_by_user_id` -> last version author

### Cadence editor

Map `cadence` to the ordered step editor:

- `cadence[].step_id` -> stable row key
- `cadence[].step_order` -> sort order
- `cadence[].channel`
- `cadence[].delay_hours`
- `cadence[].message_goal`
- `cadence[].template_key`
- `cadence[].max_attempts`

## Form submit payload

The `PUT /nurture-settings/draft` request body should contain only editable
settings fields:

- `enabled_channels`
- `daily_start_cap`
- `dormant_threshold_days`
- `quiet_hours_start`
- `quiet_hours_end`
- `timezone`
- `sms_compliance_required`
- `preflight_digest_enabled`
- `crm_enrollment_tag`
- `allow_assigned_agent_manual_enrollment`
- `prompt_version`
- `approved_model`
- `cadence_steps`

Important:

- do not send `name`
- do not send `nurture_settings_id`
- do not send `settings_version_id`
- do not send `revision`

`cadence_steps` entries should send:

- `channel`
- `delay_hours`
- `message_goal`
- `template_key`
- `max_attempts`

## Recommended page sections

### Overview

- title: `Workspace Nurture Settings`
- status badge from `nurture_settings.status`
- version label from `settings.revision`
- last published at from `settings.published_at`

### Audience and enrollment

- dormant threshold
- CRM enrollment tag
- allow assigned agent manual enrollment

### Sending behavior

- enabled channels
- daily start cap
- quiet hours
- timezone
- SMS compliance required
- preflight digest enabled

### Cadence

- editable ordered list from `cadence`
- add step
- delete step
- reorder step

### Automation model

- prompt version
- approved model

## Action wiring

### Load page

- call `GET /nurture-settings`
- if `404` with `nurture_settings_not_found`, initialize empty form state and let
  first save create the workspace policy

### Save draft

- call `PUT /nurture-settings/draft`
- replace local policy, settings, and cadence state from the response

### Publish

- call `POST /nurture-settings/publish`
- replace local state from the response

### Pause

- call `POST /nurture-settings/pause` with `{ "reason": string | null }`

### Resume

- call `POST /nurture-settings/resume` with `{ "reason": string | null }`

## Error handling

### Multiple policies configured

If the API returns `409` with:

- `multiple_nurture_policies_configured`

show a blocking admin error because the workspace has ambiguous legacy state.

### Validation or permission failures

- show `detail` or `reasons` values inline where possible
- otherwise show a top-level error banner

## UI migration notes

- rename UI labels from `Campaign` to `Nurture Settings`
- remove campaign id from the new page route if present in frontend routing
- keep old campaign screens only for backward compatibility or internal admin use

## Next backend slice after UI wiring

The next highest-value endpoint is:

- `POST /api/v1/workspaces/{workspace_id}/nurture-settings/audience-preview`

That will let the page explain which leads qualify and why.