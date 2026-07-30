# Master Business Use-Case Completion Status

**Scope:** This is the full use-case-by-use-case completion review across `docs/business-rules/01` through `06`.

- `01` = lead contactability
- `02` = campaign enrollment eligibility
- `03` = campaign start queue and pre-flight veto
- `04` = pre-send safety checks
- `05` = preflight digest notification and veto recording
- `06` = AI nurture classification, routing, and reply handling

**Companion document:** `docs/planning/paused-search-use-case-completion-status.md` still contains the deeper doc-06 notes, but this file is now self-contained and can be reviewed on its own.

## How to read this

- 🟢 **Done** — implemented and tested with no material gap for that use case.
- 🟡 **Mostly done** — core behavior exists, but an edge-case, product-surface gap, or spec/code mismatch remains.
- 🔴 **Blocked** — a critical gap makes sign-off unsafe for that use case.

## Executive summary

| Doc | Business area | Overall status | Main reason |
|---|---|---|---|
| 01 | Lead contactability | 🟢 | V1 destination-only rule implemented and tested |
| 02 | Enrollment eligibility | 🟢 | Dormant-selector missing-timing boundary is now hard |
| 03 | Start queue + pre-flight veto | 🟢 | Queue rules and assigned-agent review surface are in place |
| 04 | Pre-send safety | 🟢 | Core safeguards are strong; SMS compliance no longer blocks in V1 |
| 05 | Digest notification + veto recording | 🟢 | Digest issuance, assigned-agent visibility, and veto recording are in place |
| 06 | Classification + routing + reply handling | 🟡 | Core routing, paused-search execution timing, explicit routing reviews, and the queue surface are in place; remaining gaps are tag-time handoff completion and advanced workflow controls |

---

## 01 — Lead contactability

### 01.1 Do-not-contact blocks both SMS and email — 🟢 Done
- **Done:** `evaluate_contactability(...)` returns `do_not_contact` before any channel-specific checks.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/domain/compliance/contactability.py`, `tests/domain/compliance/test_contactability.py::test_do_not_contact_blocks_both_channels`

### 01.2 SMS opt-out blocks SMS even when consent exists — 🟢 Done
- **Done:** SMS suppression maps to `sms_opted_out` and blocks SMS.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_sms_opt_out_blocks_sms_even_with_confirmed_consent`

### 01.3 Email unsubscribe blocks email even when permission exists — 🟢 Done
- **Done:** Email suppression maps to `email_unsubscribed` and blocks email.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_email_unsubscribe_blocks_email_even_with_confirmed_permission`

### 01.4 Unknown SMS consent with a usable SMS destination allows SMS — 🟢 Done
- **Done:** Unknown SMS consent is allowed when `has_sms_destination=True` and no stronger blocker exists.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_unknown_sms_consent_with_sms_destination_is_allowed`

### 01.5 Unknown SMS consent without a usable SMS destination blocks SMS — 🟢 Done
- **Done:** Missing destination with unknown SMS consent produces `missing_sms_consent`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_unknown_sms_consent_without_sms_destination_blocks_sms`

### 01.6 Unknown email permission with a usable email destination allows email — 🟢 Done
- **Done:** Unknown email permission is allowed when `has_email_destination=True` and no stronger blocker exists.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_unknown_email_permission_with_email_destination_is_allowed`

### 01.7 Unknown email permission without a usable email destination blocks email — 🟢 Done
- **Done:** Missing destination with unknown email permission produces `missing_email_permission`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_unknown_email_permission_without_email_destination_blocks_email`

### 01.8 Explicit denied permission does not override destination presence in V1 — 🟢 Done
- **Done:** In V1, a denied consent/permission status does not block a channel when a usable destination is present. The destination is the permission signal.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_denied_sms_permission_with_destination_is_allowed_in_v1`, `test_denied_email_permission_with_destination_is_allowed_in_v1`

### 01.9 Workspace SMS compliance does not block SMS in V1 — 🟢 Done
- **Done:** V1 contactability ignores the workspace SMS compliance state. A usable mobile number is sufficient for SMS contactability.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py` `_evaluate_sms_reasons`, `test_contactability.py::test_sms_contactability_allows_sms_when_workspace_not_approved_in_v1`

### 01.10 Deterministic reason ordering and fail-safe insufficient data handling — 🟢 Done
- **Done:** Missing `do_not_contact` yields `insufficient_data`, and multi-reason ordering is deterministic.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `contactability.py`, `test_contactability.py::test_multiple_sms_blockers_return_deterministic_precedence`, `test_missing_do_not_contact_state_fails_safe`, `test_missing_do_not_contact_state_is_reported_after_channel_reasons`

---

## 02 — Campaign enrollment eligibility

### 02.1 Missing enrollment trigger means not eligible — 🟢 Done
- **Done:** No source returns `missing_enrollment_trigger` with `source=none`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/domain/compliance/enrollment.py`, `tests/domain/compliance/test_enrollment.py::test_missing_enrollment_trigger_not_eligible`

### 02.2 Unsupported enrollment source is excluded — 🟢 Done
- **Done:** Sources outside policy return `unsupported_enrollment_source`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_unsupported_enrollment_source_excluded`

### 02.3 CRM tag + at least one contactable enabled channel is eligible — 🟢 Done
- **Done:** CRM-tag path returns `eligible=True` when any enabled campaign channel is contactable.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_crm_tag_eligible_when_channel_contactable`

### 02.4 Dormant selector + threshold met + reliable activity is eligible — 🟢 Done
- **Done:** Dormant-selector path computes `eligible_at = last_meaningful_communication_at + threshold` when data is complete and old enough.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_dormant_selector_eligible_when_threshold_met_and_data_complete`

### 02.5 Recent meaningful communication blocks dormant-selector enrollment — 🟢 Done
- **Done:** Leads inside the threshold window return `lead_not_dormant`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_dormant_selector_blocked_when_lead_not_dormant`

### 02.6 Incomplete or uncertain CRM activity blocks dormant-selector enrollment — 🟢 Done
- **Done:** `activity_data_complete is not True` returns `activity_data_incomplete`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_incomplete_activity_data_blocks_dormant_selector`, `test_uncertain_activity_data_blocks_dormant_selector`

### 02.7 No contactable enabled campaign channel means not eligible — 🟢 Done
- **Done:** No enabled+allowed channel returns `no_campaign_channels_contactable`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_no_contactable_enabled_channels_blocks_enrollment`, `test_empty_enabled_channels_blocks_enrollment`, `test_missing_contactability_decision_treated_as_not_contactable`

### 02.8 When both CRM tag and dormant selector apply, CRM tag wins — 🟢 Done
- **Done:** Source precedence is deterministic: `CRM_TAG` is evaluated first and wins for auditability.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_both_sources_apply_crm_tag_wins`

### 02.9 At least one contactable channel is enough for mixed-channel eligibility — 🟢 Done
- **Done:** A lead stays eligible when one enabled channel is blocked but another enabled channel is contactable.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_enrollment.py::test_mixed_channels_eligible_if_at_least_one_contactable`

### 02.10 FIFO ordering uses the oldest eligible timestamp first — 🟢 Done
- **Done:** `sort_enrollment_candidates_fifo(...)` sorts eligible candidates by oldest `eligible_at` and skips ineligible items.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py`, `test_enrollment.py::test_fifo_sorts_by_oldest_eligible_at`, `test_fifo_skips_ineligible_and_missing_eligible_at`

### 02.11 Dormant-selector candidates missing timing evidence are rejected at the enrollment boundary — 🟢 Done
- **Done:** If `last_meaningful_communication_at` is missing, `_evaluate_dormant_selector` returns `eligible=False` with `activity_data_incomplete` before the candidate reaches the start queue.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `enrollment.py` `_evaluate_dormant_selector`, `test_enrollment.py::test_missing_last_meaningful_communication_blocks_dormant_selector`, `test_run_dormant_selector_batch.py::test_dormant_candidate_with_missing_last_communication_is_not_started`

---

## 03 — Campaign start queue and pre-flight veto

### 03.1 Inactive campaign holds back all candidates — 🟢 Done
- **Done:** Non-active campaign status appends `campaign_inactive`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/domain/campaigns/start_queue.py`, `tests/domain/campaigns/test_start_queue.py::test_inactive_campaign_holds_back_all_candidates`

### 03.2 Non-enrollment-eligible candidates are held back — 🟢 Done
- **Done:** `eligible=False` appends `not_enrollment_eligible`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_non_enrollment_eligible_candidates_are_held_back`

### 03.3 Unassigned CRM-tag candidates are held back unless there is an accountable owner — 🟢 Done
- **Done:** Candidates without an assigned agent are blocked unless they qualify for the dormant-selector agentless path.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py::_can_start_without_assigned_agent`, `test_start_queue.py::test_unassigned_leads_are_held_back`

### 03.4 CRM-tag candidates skip pre-flight digest — 🟢 Done
- **Done:** Preflight applies only to assigned-agent `dormant_selector` first-batch candidates.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py::_preflight_applies`, `test_start_queue.py::test_crm_tag_candidate_skips_preflight_digest_before_selection`

### 03.5 Assigned dormant-selector first-batch candidates require digest review — 🟢 Done in the queue rule
- **Done:** Queue logic returns `preflight_digest_pending` until a digest is issued.
- **Not done yet:** Product-surface permissions still make assigned/accountable-agent review clunky.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_assigned_dormant_selector_first_batch_requires_preflight_digest`

### 03.6 Unassigned dormant-selector candidates old enough for the agentless threshold can start — 🟢 Done
- **Done:** Agentless dormant-selector candidates can start when `days_since_last_meaningful_communication >= threshold`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py::_can_start_without_assigned_agent`, `test_start_queue.py::test_old_unassigned_dormant_selector_lead_starts_without_digest`

### 03.7 Unassigned dormant-selector candidates below the threshold are held back — 🟢 Done
- **Done:** Too-young agentless dormant-selector candidates return `missing_assigned_agent`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_start_queue.py::test_unassigned_dormant_selector_below_threshold_is_held_back`

### 03.8 Agentless dormant threshold is configurable — 🟢 Done
- **Done:** Threshold comes from `CampaignStartPolicy.agentless_dormant_threshold_days`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_agentless_dormant_threshold_is_configurable`

### 03.9 Digest pending blocks selection — 🟢 Done
- **Done:** Missing digest state returns `preflight_digest_pending` and `digest_required=True`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_assigned_dormant_selector_first_batch_requires_preflight_digest`

### 03.10 Open veto window blocks selection — 🟢 Done
- **Done:** Candidates remain held with `veto_window_not_expired` until the window closes.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_veto_window_not_expired_holds_back_candidates`

### 03.11 Vetoed leads are held back after the window expires — 🟢 Done
- **Done:** Post-window vetoed leads return `agent_vetoed`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_vetoed_lead_is_held_back_after_window_expires`

### 03.12 Non-vetoed leads start after the veto window expires — 🟢 Done
- **Done:** Once the window expires and no veto exists, the candidate can proceed to selection.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_start_queue.py::test_non_vetoed_lead_starts_after_window_expires`

### 03.13 Duplicate candidates are deduplicated and do not count twice — 🟢 Done
- **Done:** Duplicate `lead_id`s are held with `duplicate_candidate` and excluded from selection.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_duplicate_candidates_are_deduplicated_and_count_once`

### 03.14 Candidates missing `eligible_at` are held back — 🟢 Done
- **Done:** Eligible candidates with `eligible_at=None` return `missing_eligible_at`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_missing_eligible_timestamp_fails_safe`

### 03.15 Daily cap uses FIFO oldest-eligible-first selection — 🟢 Done
- **Done:** Startable candidates are sorted by `_eligible_at(...)`, selected by remaining capacity, and overflow returns `daily_cap_reached`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `start_queue.py`, `test_start_queue.py::test_active_campaign_selects_oldest_candidates_up_to_daily_cap`, `test_started_today_reduces_remaining_daily_capacity`

### 03.16 Multiple blocking reasons are returned in deterministic precedence order — 🟢 Done
- **Done:** Queue rule accumulates reasons in consistent order for auditability.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_start_queue.py::test_multiple_blocking_reasons_are_returned_in_precedence_order`

### 03.17 Dormant-selector leads routed into paused-search should still honor digest review before starting — 🟢 Done
- **Done:** `run_dormant_selector_batch.py` now routes paused-search candidates through the same digest preparation, veto-window, daily-cap, and FIFO selection flow as dormant candidates before any paused-search enrollment starts.
- **Not done yet:** Product-surface permissions still make assigned/accountable-agent review clunky.
- **Evidence:** `run_dormant_selector_batch.py`, `tests/application/use_cases/test_run_dormant_selector_batch.py`

---

## 04 — Pre-send safety checks

### 04.1 Campaign must be active and workflow must be sendable — 🟢 Done
- **Done:** Non-active campaigns and non-sendable workflow states block immediately.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/domain/campaigns/pre_send.py`, `tests/domain/campaigns/test_pre_send.py::test_inactive_campaign_blocks_sending`, `test_non_sendable_workflow_state_blocks_sending`

### 04.2 Already-sent or provider-accepted messages are blocked — 🟢 Done
- **Done:** `message_status=sent` or `provider_send_status=accepted` blocks duplicate send.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_message_state_reasons`, `test_pre_send.py::test_already_sent_message_blocks_duplicate_send`

### 04.3 Cancelled messages are blocked — 🟢 Done
- **Done:** Cancelled messages return `message_cancelled`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_multiple_blocking_reasons_follow_precedence_order`

### 04.4 Reused idempotency keys are blocked — 🟢 Done
- **Done:** Duplicate send requests return `duplicate_send_request`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_reused_idempotency_key_blocks_duplicate_send`

### 04.5 Stale message versions are blocked — 🟢 Done
- **Done:** Version mismatch returns `message_version_stale`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_stale_message_version_blocks_send`

### 04.6 Uncertain provider status is blocked instead of blindly retried — 🟢 Done
- **Done:** `provider_status_uncertain` prevents re-send and the use case preserves uncertainty instead of retrying.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_uncertain_provider_status_blocks_retry`

### 04.7 Disabled or no-longer-contactable channels are blocked — 🟢 Done
- **Done:** Channel enablement and current contactability are both enforced at the final gate.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_channel_reasons`, `test_pre_send.py::test_disabled_or_uncontactable_channel_blocks_send`

### 04.8 Pre-flight veto blocks send — 🟢 Done
- **Done:** Preflight veto adds `preflight_vetoed` immediately before send.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_preflight_veto_blocks_send`

### 04.9 Active handoff blocks send — 🟢 Done
- **Done:** Handoff appends `handoff_active`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_human_control_reasons`, `test_pre_send.py::test_human_control_conditions_block_send`

### 04.10 Human-owned state blocks send — 🟢 Done
- **Done:** Human-owned workflows append `human_owned`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_human_control_reasons`, `test_pre_send.py::test_human_control_conditions_block_send`

### 04.11 Any lead reply since scheduling blocks send — 🟢 Done
- **Done:** Reply-after-schedule appends `lead_replied_since_scheduled`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_human_control_reasons`, `test_pre_send.py::test_human_control_conditions_block_send`

### 04.12 Recent manual agent activity blocks send — 🟢 Done
- **Done:** Recent human activity appends `recent_human_activity`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_human_control_reasons`, `test_pre_send.py::test_human_control_conditions_block_send`

### 04.13 Ownership change after scheduling does not block send — 🟢 Done
- **Done:** ownership reconciliation is allowed to update assignment without pausing workflow execution or blocking pre-send evaluation.
- **Done:** review and handoff visibility follow the effective owner instead of treating reassignment as a send blocker.
- **Evidence:** `test_crm_sync.py::test_sync_reconciles_ownership_change_without_pausing_workflow_or_cancelling_messages`, `test_send_outbound_message.py::test_sends_message_after_pre_send_crm_refresh_detects_ownership_change`, `test_lead_read.py::test_assigned_agent_list_lead_views_uses_effective_owner_visibility`, `test_handoff_read.py::test_assigned_agent_handoff_visibility_uses_effective_owner`

### 04.14 Outside allowed hours blocks send and returns the next possible send time — 🟢 Done
- **Done:** Quiet hours are enforced with timezone-aware next-window calculation.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py`, `test_pre_send.py::test_outside_allowed_hours_returns_next_window_start`, `test_outside_allowed_hours_uses_policy_timezone`

### 04.15 The strictest frequency limit wins — 🟢 Done
- **Done:** Global, campaign, and channel windows are evaluated and the latest retry time wins.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_frequency_block_until`, `test_pre_send.py::test_strictest_frequency_limit_blocks_and_returns_latest_retry_time`

### 04.16 Mixed-channel sequencing is enforced — 🟢 Done
- **Done:** Another channel sent inside the protected window returns `simultaneous_channel_not_allowed`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_simultaneous_block_until`, `test_pre_send.py::test_simultaneous_channel_protection_blocks_send`

### 04.17 Missing required data fails safe — 🟢 Done
- **Done:** Missing or mismatched contactability decision returns `missing_required_data`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `pre_send.py::_missing_required_data`, `test_pre_send.py::test_missing_required_data_fails_safe`

### 04.18 Multiple blocking reasons follow deterministic precedence — 🟢 Done
- **Done:** Final gate emits reasons in stable rule order.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_pre_send.py::test_multiple_blocking_reasons_follow_precedence_order`

### 04.19 SMS compliance does not block sends in V1 — 🟢 Done
- **Done:** V1 contactability ignores the workspace SMS compliance state, so the pre-send gate never sees SMS compliance as a block.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `docs/business-rules/04-pre-send-safety-checks.md`, dependency on contactability from `01`, `contactability.py`

---

## 05 — Preflight digest notification and veto recording

### 05.1 Only digest-eligible dormant-selector first-batch candidates are included — 🟢 Done
- **Done:** Digest preparation reuses campaign-start evaluation and only includes candidates that are blocked specifically by `preflight_digest_pending`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/application/use_cases/preflight_digest.py::_digest_candidate_blocking_reason`, `tests/application/use_cases/test_preflight_digest.py::test_digest_preparation_includes_only_candidates_requiring_review`

### 05.2 CRM-tag candidates are not included in preflight digests — 🟢 Done
- **Done:** CRM-tag candidates resolve to `digest_not_required` and are excluded from entries.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py`, `test_preflight_digest.py::test_digest_preparation_includes_only_candidates_requiring_review`

### 05.3 Unassigned dormant-selector candidates using the agentless path are not included — 🟢 Done
- **Done:** Agentless candidates are treated as `digest_not_required` and excluded.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py`, `test_preflight_digest.py::test_digest_preparation_includes_only_candidates_requiring_review`

### 05.4 Missing recipient fails safe and prevents digest issuance — 🟢 Done
- **Done:** Missing recipient info returns `missing_digest_recipient`, saves nothing, and sends nothing.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py`, `test_preflight_digest.py::test_missing_recipient_fails_safe_without_sending_digest`

### 05.5 Digest entries are grouped by accountable recipient — 🟢 Done
- **Done:** Notifications are grouped and issued by `recipient_id`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py::_group_entries_by_recipient`, `test_preflight_digest.py::test_digest_preparation_groups_notifications_by_recipient`

### 05.6 Inactive campaigns do not issue digests — 🟢 Done
- **Done:** Campaign inactivity returns `campaign_not_active` and prevents digest issuance.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py`, `test_preflight_digest.py::test_inactive_campaign_does_not_issue_digest`

### 05.7 First digest issuance records durable digest state and veto window — 🟢 Done
- **Done:** Successful issuance persists `digest_sent_at`, `veto_window_expires_at`, notification records, and entries.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `prepare_preflight_digest(...)`, `test_preflight_digest.py::test_digest_preparation_includes_only_candidates_requiring_review`

### 05.8 Duplicate digest issuance returns existing state without resending — 🟢 Done
- **Done:** `already_issued` short-circuits and returns the existing digest.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `preflight_digest.py::_existing_digest_result`, `test_preflight_digest.py::test_duplicate_digest_returns_existing_state_without_resending`

### 05.9 Failed digest issuance can be retried safely — 🟢 Done
- **Done:** Failed status is not treated as already issued; a later attempt can create a new digest/notification flow.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `test_preflight_digest.py::test_failed_digest_can_be_retried_without_guessing_prior_success`

### 05.10 Notification failure does not mark the digest as issued — 🟢 Done
- **Done:** Failed notification persists `FAILED` without `digest_sent_at`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `prepare_preflight_digest(...)`, `test_preflight_digest.py::test_notification_failure_does_not_mark_digest_issued`

### 05.11 Uncertain digest delivery blocks resend until reconciled — 🟢 Done
- **Done:** Uncertain delivery persists `UNCERTAIN` and future prep returns `digest_state_uncertain` instead of resending.
- **Not done yet:** Nothing specific to this backend use case.
- **Evidence:** `preflight_digest.py`, `test_preflight_digest.py::test_uncertain_notification_blocks_resend_until_reconciled`, `test_partial_notification_failure_is_marked_uncertain`

### 05.12 Assigned agent can veto within the window — 🟢 Done in backend logic
- **Done:** Backend use case accepts `VetoActorRole.ASSIGNED_AGENT` when `actor_id == entry.recipient_id`.
- **Not done yet:** See 05.19 for product-surface access mismatch.
- **Evidence:** `preflight_digest.py::_actor_can_veto`, `test_preflight_digest.py::test_veto_within_window_records_lead_id`

### 05.13 Manager or brokerage admin can veto within the window — 🟢 Done
- **Done:** Manager/admin roles are explicitly authorized by policy.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `PreflightVetoPolicy`, `_actor_can_veto(...)`, `test_preflight_digest.py::test_manager_or_admin_can_veto_digest_entry`

### 05.14 Veto for a lead not in the digest is rejected — 🟢 Done
- **Done:** Non-member lead veto attempts return `candidate_not_in_digest`.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `record_preflight_veto(...)`, `test_preflight_digest.py::test_veto_for_lead_not_in_digest_is_rejected`

### 05.15 Unauthorized veto actors are rejected — 🟢 Done in backend logic
- **Done:** Backend veto use case returns `unauthorized_veto_actor` for non-recipient assigned agents or unauthorized roles.
- **Not done yet:** Product-surface constraints are stricter than backend logic; see 05.19.
- **Evidence:** `record_preflight_veto(...)`, `test_preflight_digest.py::test_unauthorized_veto_actor_is_rejected`

### 05.16 Late veto attempts are rejected without mutating digest state — 🟢 Done
- **Done:** Vetoes at or after the expiration timestamp return `veto_window_expired` and do not add veto records.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `record_preflight_veto(...)`, `test_preflight_digest.py::test_veto_after_window_expires_is_rejected_without_mutation`

### 05.17 Duplicate veto requests are idempotent no-ops — 🟢 Done
- **Done:** Already-vetoed leads return `duplicate_veto` without saving again.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `record_preflight_veto(...)`, `test_preflight_digest.py::test_duplicate_veto_request_is_idempotent_no_op`

### 05.18 Persisted digest state is consumed by campaign-start evaluation — 🟢 Done
- **Done:** Digest state converts into `CampaignStartContext`, and vetoed leads remain held in later start-queue evaluation.
- **Not done yet:** Nothing specific to this backend use case.
- **Evidence:** `campaign_start_context_from_digest(...)`, `test_preflight_digest.py::test_persisted_digest_state_converts_to_campaign_start_context`, `test_missing_or_uncertain_digest_converts_to_fail_safe_context`

### 05.19 Assigned/accountable agents can actually view and act on their digests in the product — 🟢 Done
- **Done:** Assigned agents can now read only their own digest entries, reach the preflight page through role-aware navigation, and record vetoes against recipient-matched digest entries.
- **Not done yet:** Nothing specific to this use case.
- **Evidence:** `app/application/use_cases/preflight_read.py`, `app/application/services/preflight_actor_resolution.py`, `app/interfaces/api/v1/campaigns.py`, `miller-schackman-web/src/pages/PreflightPage.tsx`

---

## 06 — AI nurture classification, routing, and reply handling

### 06.1 Silent lead with no known reason enters dormant path — 🟢 Done for Phase 5 scope
- **Done:** Tag enrollment gates the flow, routing can return `DORMANT`, dormant starts go through the standard campaign start and pre-send pipeline, and ambiguous silent leads with no workflow now have a dedicated operator review-hold resolution action that can explicitly resolve them into dormant or paused-search.
- **Not done yet:** Review-hold resolution for already-active workflows and a dedicated route-decision audit record still belong to later phases.
- **Evidence:** `app/application/use_cases/process_crm_tag_campaign_enrollment.py`, `app/application/use_cases/lead_review_hold_resolution.py`, `app/interfaces/api/v1/leads.py`, `tests/application/use_cases/test_lead_review_hold_resolution.py`

### 06.2 Lead says they want to wait for rates and enters paused-search — 🟢 Done
- **Done:** Paused-search profile persistence, reason taxonomy, track pinning, Temporal workflow start, and next-action scheduling all exist. Fresh classification now runs even when an existing paused-search profile is present, the old profile only wins when the fresh classification is `dormant` or `review_hold`, and deterministic future-timing text no longer bypasses the structured LLM route.
- **Done:** Dormant-selector paused-search starts now honor the same digest/cap/veto start controls as dormant starts.
- **Done:** Cadence execution now revalidates the current paused-search profile + pinned track timing before a due step executes, so stale reactivation steps are skipped instead of sending.
- **Done:** Classification artifacts now mark `APPLIED` only when the paused-search state really changed.
- **Done:** Frontend/admin surfaces now expose draft-level `requires_review_before_publish` and per-step `review_required` controls, and held drafts are visibly blocked from publish.
- **Evidence:** `route_ai_nurture_lead.py`, `apply_lead_state_classification.py`, companion doc

### 06.3 Accidentally tagged hot lead goes to human handoff instead of nurture — 🟡 Mostly done
- **Done:** The classifier can produce `HUMAN_HANDOFF`, handoff creation/notification flows exist, tag-time CRM enrollment no longer falls through into dormant start for non-dormant routes, and fresh `HUMAN_HANDOFF`/`BLOCKED` classifications now outrank an existing `paused_search_active` profile.
- **Not done yet:** Tag-time `HUMAN_HANDOFF` still does not complete the handoff side effects.
- **Evidence:** `route_ai_nurture_lead.py`, `process_crm_tag_campaign_enrollment.py`, companion doc use case 3

### 06.4 Dormant lead reply with a known reason moves the lead to paused-search — 🟢 Done for Phase 5 scope
- **Done:** Inbound reply processing can reclassify and apply a paused-search profile, the shared pre-send gate blocks stale dormant sends, and the reply-time reroute path now passes workflow/track/outbox dependencies so the active dormant workflow is pinned to the correct paused-search track and queues reschedule behavior before stale continuation is paused.
- **Not done yet:** Route-decision auditing is still reconstructed from artifacts and workflow state rather than a dedicated decision record.
- **Evidence:** `app/application/use_cases/continue_ai_conversation_after_inbound.py`, `app/application/use_cases/process_inbound_message_event.py`, `tests/application/use_cases/test_process_inbound_message_event.py`

### 06.5 Paused-search lead reply with renewed intent triggers human handoff — 🟡 Mostly done
- **Done:** Reply-time classification can trigger `HUMAN_HANDOFF`, pending AI messages are stopped by pre-send/handoff logic, and a fresh `HUMAN_HANDOFF`/`BLOCKED` classification now outranks an existing `paused_search_active` profile during reply continuation.
- **Not done yet:** Reply-time routing and lead-state routing are still split, so audit records and decisions can diverge.
- **Evidence:** companion doc use case 5, `route_ai_nurture_lead.py`

### 06.6 Opt-out or block reply stops AI outreach — 🟢 Done
- **Done:** Suppression/block paths stop future automated outreach and workflow progression.
- **Not done yet:** Nothing blocking for this use case.
- **Evidence:** companion doc use case 6

### 06.7 Agent disagrees with AI and overrides the lead state — 🟡 Mostly done
- **Done:** Backend APIs and permissions exist to set/update/clear paused-search state, history/audit is recorded, `applied_status` now reflects real lead-state changes, and no-workflow `review_hold` outcomes can be resolved directly from lead detail.
- **Not done yet:** Advanced workflow controls still are not exposed in one operator flow, and resolved routing-review history is not yet surfaced in lead detail/reporting.
- **Evidence:** `apply_lead_state_classification.py`, `lead_review_hold_resolution.py`, paused-search lead endpoints/UI, companion doc use case 7

---

## Cross-cutting blockers before calling all business use cases complete

1. Complete tag-time human handoff side effects directly from the enrollment path.
2. Expose advanced paused-search workflow controls in the main operator flow.

## Definition of “100% complete” for this document

This document is now **100% use-case enumerated** across docs `01`–`06` because every concrete business use case/rule path from those docs has an explicit status entry here.

That does **not** mean the product is 100% complete.

Current implementation sign-off is still blocked mainly by:

- tag-time human handoff completion still lags the safer routing decision
- advanced workflow-control surfaces and routing-review history are still incomplete

## Recommended next fixes

1. Complete tag-time human handoff side effects where the enrollment path already routes to `human_handoff`.
2. Expose advanced workflow controls (`track migration`, `skip next touch`, `timing override`) in the main operator UI.
3. Surface resolved/superseded routing-review history in lead detail and reporting.