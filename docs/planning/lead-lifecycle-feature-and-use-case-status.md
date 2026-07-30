# Lead Lifecycle Feature & Use-Case Status

**Scope:** This document explains what can happen to a lead on the platform after it is fetched into the system, with special focus on the post-`ai_nurture` lifecycle. It is meant to answer four questions clearly:

1. what phases a lead goes through
2. what lead-facing features and use cases exist today
3. how good each phase is in code and tests
4. which edge cases are still missing, weak, or incorrectly implemented

## How to read this

- 🟢 **Strong** — implemented, tested, and close to product-ready for this phase
- ✅ **Closed** — implemented, tested, and no meaningful phase-specific blocker remains
- 🟡 **Partial** — core behavior exists, but important edge cases or product gaps remain
- 🔴 **Critical gap** — current behavior is unsafe or materially conflicts with the intended business flow

## Executive summary

| Area | Status | Notes |
|---|---|---|
| CRM lead fetch / sync into platform | ✅ | Canonical lead sync is broad, well-tested, and has no meaningful Phase 1-specific blocker in approved scope |
| Tag-based entry into nurture | ✅ | CRM-tag and dormant-selector entry now stop safely at the boundary and only start allowed routes in approved scope |
| Contactability / enrollment eligibility | ✅ | Core rules and tests are strong; no meaningful Phase 3-specific blocker remains |
| Lead-state classification and route selection | ✅ | Core precedence, explicit routing-review records, and reply-time rerouting coverage justify closure in approved scope |
| Dormant nurture path | ✅ | Runtime, entry safety, and no-workflow review resolution are now in place |
| Paused-search path | ✅ | Selector start safety, timing-aware scheduling, cadence execution, and workflow rescheduling are all covered in approved scope |
| Human handoff path | ✅ | Inbound and tag-time handoff paths now both create/reuse handoffs and complete CRM and notification side effects in approved scope |
| Blocked / suppression path | ✅ | Suppression mechanics, consent gating, and SMS compliance blocking now align with approved Phase 1 rules |
| Inbound reply handling / continue-AI logic | ✅ | Broad test coverage now includes the remaining skipped-transition and blocked-acknowledgment edge cases |
| Human activity pause | ✅ | Pause flow covers notes, outbound calls/texts, peopleUpdated stage/status/tags; ownership changes remain non-pausing |
| Manual override / resume | ✅ | Core override and resume flows are implemented; remaining gaps are advanced UI-control surfaces |
| Workflow runtime and final pre-send safety | 🟢 | Temporal runtime, long-wait hardening, and final pre-send safety are now in place |

## Lead lifecycle map

The current lead lifecycle is best understood in this order:

1. **Lead is fetched from CRM and mapped into `CanonicalLeadRecord`**
2. **The lead may become a nurture candidate**
   - via configured CRM tag
   - via dormant selector
3. **Eligibility and contactability are checked**
4. **The lead is classified into a lead-state route**
   - `dormant`
   - `paused_search`
   - `human_handoff`
   - `blocked`
   - `review_hold`
5. **A route-specific workflow starts**
6. **Cadence scheduling and outbound execution run through Temporal**
7. **Every outbound send goes through final pre-send safety**
8. **Any meaningful inbound reply triggers a fresh decision**
9. **Human activity, suppression, manual override, and resume can interrupt the workflow**
10. **The lead ends in paused, handoff, human-owned, completed, suppressed, or closed state**

---

## Phase 1 — Lead fetch / CRM sync into platform

**Status:** ✅ Closed

**What exists**
- Follow Up Boss snapshot sync imports leads into canonical lead records.
- Lead mapping captures contactability, tags, assigned agent, activity timestamps, and ownership-related fields.
- Sync can auto-start nurture when a pulled lead already has the configured enrollment tag.
- Incremental and full sync modes exist.

**Main implementation**
- `app/application/use_cases/crm_sync.py`
- `app/infrastructure/crm/follow_up_boss/lead_mapper.py`

**Test coverage**
- `tests/application/use_cases/test_crm_sync.py::test_runs_full_sync_across_multiple_pages`
- `test_sync_starts_matching_campaign_when_pulled_lead_has_configured_tag`
- `test_repeat_sync_for_tagged_lead_is_idempotent_when_already_enrolled`
- `test_sync_reconciles_ownership_change_without_pausing_workflow_or_cancelling_messages`

**Important gaps / edge cases**
- No meaningful Phase 1-specific blocker remains in approved scope: sync updates owner mapping without pausing outreach, and downstream read surfaces scope review/handoff visibility from the effective owner.

---

## Phase 2 — Entry into nurture

**Status:** ✅ Closed

**What exists**
- Leads can enter through a configured CRM tag.
- Leads can also enter through the dormant selector batch.
- Matching campaign lookup is implemented.
- Duplicate enrollment behavior is idempotent.

**Main implementation**
- `app/application/use_cases/process_crm_tag_campaign_enrollment.py`
- `app/application/use_cases/run_dormant_selector_batch.py`

**Test coverage**
- `tests/application/use_cases/test_process_crm_tag_campaign_enrollment.py`
- `tests/application/use_cases/test_run_dormant_selector_batch.py`
- `tests/application/use_cases/test_business_flow_harness.py`

**Important gaps / edge cases**
- No Phase 2-specific unsafe start gap remains.
- CRM-tag entry now only starts dormant outreach for a true `dormant` route.
- `paused_search`, `human_handoff`, `review_hold`, and `blocked` outcomes now stop at the entry boundary instead of falling through into dormant workflow start.
- Dormant-selector entry now has focused coverage proving `blocked` and `review_hold` candidates do not start and that review-hold can persist a pending routing review.

---

## Phase 3 — Contactability and enrollment eligibility

**Status:** ✅ Closed

**What exists**
- Contactability decisions for SMS and email use the V1 destination-only rule: a usable mobile number or email address is the permission signal.
- SMS opt-out, email unsubscribe, and do-not-contact still block contactability.
- Workspace A2P/10DLC compliance and raw consent/permission status fields are stored but do not block the V1 decision.
- Enrollment requires at least one enabled, contactable channel.
- Dormant-selector timing and reliable-activity rules exist and reject missing `last_meaningful_communication_at` immediately at the enrollment decision boundary.
- FIFO eligibility ordering exists.

**Main implementation**
- `app/domain/compliance/contactability.py`
- `app/domain/compliance/enrollment.py`
- `app/application/use_cases/run_dormant_selector_batch.py`

**Test coverage**
- `tests/domain/compliance/test_contactability.py`
- `tests/domain/compliance/test_enrollment.py`
- `tests/application/use_cases/test_run_dormant_selector_batch.py`

**Important gaps / edge cases**
- None. This phase is closed.

---

## Phase 4 — Lead-state classification and route selection

**Status:** ✅ Closed

**What should happen**
- Once a lead is eligible, the system should route it in this precedence order:
  1. `human_handoff` or `blocked`
  2. `paused_search`
  3. `dormant`
  4. `review_hold`

**What exists**
- Dedicated route use case: `route_ai_nurture_lead(...)`
- Classification artifacts are stored.
- Paused-search classification can update the lead profile.
- Route result is consumed by the CRM-tag entry path, dormant-selector path, and reply-time continuation path.
- Hard suppression is checked before any classification.
- Fresh classification always runs; an existing `paused_search_active` profile no longer short-circuits the decision.
- A paused-search profile acts as a floor: if the fresh classification returns `dormant` or `review_hold`, the route stays `paused_search` rather than silently clearing the profile.
- `human_handoff` and `blocked` still outrank an old paused-search profile.
- Pending routing reviews are now stored as explicit `lead_routing_reviews` records and exposed through a workspace review queue.

**Main implementation**
- `app/application/use_cases/route_ai_nurture_lead.py`
- `app/application/use_cases/apply_lead_state_classification.py`
- `app/application/use_cases/process_crm_tag_campaign_enrollment.py`
- `app/application/use_cases/run_dormant_selector_batch.py`
- `app/application/use_cases/continue_ai_conversation_after_inbound.py`

**Test coverage**
- `tests/application/use_cases/test_route_ai_nurture_lead.py` — dedicated precedence and fallback tests.
- `tests/application/use_cases/test_process_crm_tag_campaign_enrollment.py` — tag-entry precedence cases.
- `tests/application/use_cases/test_run_dormant_selector_batch.py` — dormant-selector precedence cases.
- `tests/application/use_cases/test_process_inbound_message_event.py` — reply-time rerouting cases.

**Important gaps / edge cases**
- None. This phase is closed.

---

## Phase 5 — Dormant path

**Status:** ✅ Closed

**What should happen**
- A silent lead with no known reason enters light, respectful re-engagement.

**What exists**
- Dormant leads start through the standard campaign start queue.
- Daily cap, FIFO, and preflight logic are integrated.
- Dormant drafting and send flow reuse the shared cadence pipeline.
- Final pre-send safety is re-checked before provider calls.
- Meaningful inbound replies are rerouted before AI continuation, and a paused-search reroute now pins the paused-search track and queues workflow rescheduling safely.
- Ambiguous silent leads with no workflow now have a dedicated operator resolution action that can resolve review-hold into either dormant start or paused-search start.

**Main implementation**
- `process_crm_tag_campaign_enrollment.py`
- `start_selected_campaign_batch.py`
- `campaign_cadence_execution.py`
- `send_outbound_message.py`
- `continue_ai_conversation_after_inbound.py`
- `lead_review_hold_resolution.py`

**Test coverage**
- `tests/application/use_cases/test_campaign_cadence_execution.py`
- `tests/application/use_cases/test_send_outbound_message.py`
- `tests/application/use_cases/test_process_crm_tag_campaign_enrollment.py`
- `tests/application/use_cases/test_business_flow_harness.py`
- `tests/application/use_cases/test_process_inbound_message_event.py`
- `tests/application/use_cases/test_lead_review_hold_resolution.py`
- `tests/interfaces/api/v1/test_lead_review_hold_resolutions.py`

**Deferred later-phase follow-up**
- Surface resolved/superseded routing-review history alongside the lead timeline and workspace reporting.
- Expose advanced workflow controls such as track migration, skip-next-touch, and timing override in the main operator flow.

---

## Phase 6 — Paused-search path

**Status:** ✅ Closed

**What should happen**
- A lead with a known wait reason should get reason-aware nurture, not generic dormant outreach.

**What exists**
- Paused-search profile is stored on the lead.
- Reason taxonomy and track mapping exist.
- A published paused-search track version is pinned on the workflow.
- Scheduling uses paused-search timing logic instead of normal dormant cadence.
- Reschedule signals can interrupt long waits.

**Main implementation**
- `route_ai_nurture_lead.py`
- `apply_lead_state_classification.py`
- `start_paused_search_campaign_enrollment.py`
- `schedule_next_paused_search_action.py`
- `campaign_cadence_execution.py`

**Test coverage**
- `tests/application/use_cases/test_apply_lead_state_classification.py`
- `tests/application/use_cases/test_run_dormant_selector_batch.py`
- `tests/application/use_cases/test_schedule_next_paused_search_action.py`
- `tests/application/use_cases/test_campaign_cadence_execution.py`
- `tests/infrastructure/test_temporal_lead_nurture_workflow.py`
- `tests/application/use_cases/test_business_flow_harness.py::test_business_flow_harness_runs_crm_tag_to_paused_search_send_to_handoff`

**Important gaps / edge cases**
- Advanced workflow-control surfaces (`track migration`, `skip next touch`, `timing override`) are still separate product-surface work and are not blockers for the approved Phase 6 scope.

---

## Phase 7 — Human handoff path

**Status:** ✅ Closed

**What should happen**
- AI must stop and the lead must move to a human whenever active intent or direct human request appears.

**What exists**
- Inbound replies can trigger human handoff.
- Handoff records are created.
- CRM note, CRM tag, custom fields, and notification flows exist.
- Existing open handoff reuse is supported.
- Lead acknowledgments exist for reply-time handoff when inbound message context is available.
- Tag-time `human_handoff` now creates or reuses the handoff and completes CRM and notification side effects at entry time.

**Main implementation**
- `process_inbound_message_event.py`
- `complete_handoff.py`

**Test coverage**
- `tests/application/use_cases/test_process_inbound_message_event.py`
- `tests/application/use_cases/test_complete_handoff.py`
- `tests/application/use_cases/test_process_crm_tag_campaign_enrollment.py`
- `tests/application/use_cases/test_crm_sync.py`
- `tests/interfaces/api/v1/test_webhooks.py`
- `tests/application/use_cases/test_business_flow_harness.py::test_business_flow_harness_runs_sync_to_handoff_path`

**Important edge cases**
- Existing open handoffs are reused instead of duplicated.
- Completion failures persist a retryable handoff completion record without starting nurture.
- Tag-time handoff does not force a lead acknowledgment when there is no inbound message/thread context, which is acceptable in approved Phase 7 scope.

---

## Phase 8 — Blocked / suppression path

**Status:** ✅ Closed

**What exists**
- Hard suppression is checked before route start.
- Explicit inbound opt-out overrides exist.
- Contact suppression events can pause or suppress workflows depending on remaining usable channels.
- Lead suppression evidence is stored on the lead.
- Unknown or denied channel permission blocks automated outreach.
- SMS requires an explicitly approved workspace compliance state before automated send or continuation.

**Main implementation**
- `process_contact_suppression_event.py`
- `process_inbound_message_event.py`
- `contactability.py`

**Test coverage**
- `tests/application/use_cases/test_process_contact_suppression_event.py`
- `tests/application/use_cases/test_process_inbound_message_event.py`
- `tests/application/use_cases/test_plan_outbound_message.py`
- `tests/application/use_cases/test_send_outbound_message.py`
- `tests/domain/compliance/test_contactability.py`

**Important gaps / edge cases**
- No Phase 8-specific blocker remains.
- An AI-derived `BLOCKED` route from tag-time classification now stops safely before workflow start.
- Continue-AI and handoff acknowledgment sends now pause safely when contactability or SMS compliance blocks the channel.

---

## Phase 9 — Inbound reply handling and continue-AI behavior

**Status:** ✅ Closed

**What exists**
- Duplicate inbound events are idempotent.
- Reply classification can lead to continue-AI, handoff, review pause, not-interested completion, or suppression.
- Continue-AI can send the next reply or pause when rerouted.
- The reply path can reroute a lead into paused-search.

**Main implementation**
- `process_inbound_message_event.py`
- `continue_ai_conversation_after_inbound.py`

**Test coverage**
- `tests/application/use_cases/test_process_inbound_message_event.py`
  - handoff
  - opt-out
  - continue-AI
  - reroute-to-paused-search
  - review notification
  - audit persistence

**Important gaps / edge cases**
- No meaningful Phase 9-specific blocker remains.
- Continue-AI now keeps conversation status aligned with the real workflow state when the transition is skipped.
- Lead handoff acknowledgments now short-circuit before LLM drafting when contactability already blocks the channel.

---

## Phase 10 — Human activity pause

**Status:** ✅ Closed

**What should happen**
- Manual human activity in CRM should pause AI outreach.

**What exists**
- CRM note creation (`notesCreated`) pauses the workflow.
- Outbound Follow Up Boss calls and texts (`callsCreated`, `textMessagesCreated`) pause the workflow; inbound calls and texts are ignored so lead replies are not misclassified.
- Meaningful `peopleUpdated` changes (stage, tags, and `contacted` status) pause the workflow; pure reassignment changes do not.
- `peopleStageUpdated` and `peopleTagsCreated` are handled through the same people-event path.
- Pause transition and Temporal pause signal are implemented.
- Duplicate events are idempotent.

**Main implementation**
- `process_crm_human_activity_event.py`
- `app/infrastructure/crm/follow_up_boss/webhook_event_mappers.py`
- `app/infrastructure/crm/follow_up_boss/webhook_event_people.py`

**Test coverage**
- `tests/application/use_cases/test_process_crm_human_activity_event.py`
- `tests/interfaces/api/v1/test_webhooks.py` — notes, outbound calls/texts, and `peopleUpdated` `contacted` change
- `tests/infrastructure/crm/test_follow_up_boss.py` — people resource fetches request `fields=allFields`

**Important gaps / edge cases**
- `lead_reassigned` is intentionally ignored as a pause trigger.
- Ownership changes should keep the workflow moving, but review and handoff surfaces must follow the effective owner.
- Additional FUB event types such as `appointmentsCreated`, `emailsCreated`, and `tasksCreated` are not yet mapped to human-activity pause. They are not Phase 10 blockers because the pause mechanism and the primary FUB activity channels are covered.

---

## Phase 11 — Manual override and resume

**Status:** ✅ Closed

**What exists**
- Operators can set, update, or clear a paused-search profile.
- Permissions distinguish own-lead vs any-lead editing.
- Change history and audit records are written.
- Resume eligibility and resume request flows exist.
- Resume checks workflow state, permissions, suppression rules, and current contactability.
- Backend override APIs exist for timing override, paused-search track migration, and skipping the next touch.
- Review-hold decisions can be worked from a shared workspace review queue and resolved from lead detail for no-workflow leads.
- Lead detail UI exposes paused-search editing and resume for eligible workflows.

**Main implementation**
- `lead_paused_search.py`
- `lead_resume.py`
- `lead_workflow_overrides.py`
- `lead_review_hold_resolution.py`

**Test coverage**
- `tests/application/use_cases/test_lead_paused_search.py`
- `tests/application/use_cases/test_lead_resume.py`
- `tests/application/use_cases/test_lead_workflow_overrides.py`
- `tests/application/use_cases/test_lead_review_hold_resolution.py`
- `tests/interfaces/api/v1/test_lead_review_hold_resolutions.py`

**Important gaps / edge cases**
- Track migration, skip-next-touch, and timing-override controls are not yet exposed in the lead-detail UI; the backend APIs and tests are in place.
- Resolved/superseded routing-review history is not yet surfaced back into lead detail or reporting; review records are persisted.
- These are UI/product follow-up items and are not Phase 11 backend blockers.

---

## Phase 12 — Workflow runtime and final send safety

**Status:** ✅ Closed

**What exists**
- Temporal lead nurture workflow supports schedule, wait, execute, pause, resume, close, inbound interrupt, and reschedule.
- Outbound send path re-checks conditions at send time.
- Quiet hours, frequency limits, duplicate-send protection, and channel contactability are covered.

**Main implementation**
- `app/infrastructure/workflows/temporal/lead_nurture.py`
- `campaign_cadence_execution.py`
- `send_outbound_message.py`
- `app/domain/campaigns/pre_send.py`

**Test coverage**
- `tests/infrastructure/test_temporal_lead_nurture_workflow.py`
- `tests/application/use_cases/test_dispatch_temporal_signals.py`
- `tests/application/use_cases/test_send_outbound_message.py`
- `tests/application/use_cases/test_campaign_cadence_execution.py`
- `tests/domain/campaigns/test_pre_send.py`

**Important gaps / edge cases**
- No critical runtime/send-safety blocker remains in this phase.
- Remaining follow-up is operator history/control surface work, not Temporal/runtime safety itself.

---

## Key lead use cases and current status

| Use case | Status | Notes |
|---|---|---|
| Lead is fetched and stored in platform | 🟢 | Good CRM sync coverage |
| Tagged silent lead enters dormant nurture | 🟢 | Entry safety, explicit review records, and no-workflow review resolution are now in place |
| Tagged lead with known wait reason enters paused-search | 🟢 | Strong backend path with protected start controls and pinned paused-search execution |
| Tagged hot lead goes to human handoff | 🟢 | Tag-time handoff now creates or reuses the handoff and completes the required CRM and notification side effects |
| Lead replies asking for person | 🟢 | Strong handoff flow |
| Dormant lead replies with known timing reason | 🟡 | Reroute exists, full migration story still imperfect |
| Paused-search lead replies and is ready now | 🟡 | Usually works, but routing systems are split |
| Lead replies with opt-out | 🟢 | Strong suppression behavior |
| Agent creates manual activity in CRM | 🟢 | Pause works for notes, outbound calls/texts, and meaningful peopleUpdated changes |
| Lead is reassigned | 🟢 | Workflow continues; effective owner drives dashboard and handoff visibility |
| Manager or agent manually updates paused-search state | 🟡 | Supported with shared review queue; advanced workflow controls still remain separate |
| Manager resumes an eligible paused/handoff lead | 🟢 | Resume flow is implemented and tested |

## Biggest lifecycle gaps before calling this production-grade

1. **Complete tag-time human handoff side effects**
   - the routing decision is safe now, but enrollment-time `human_handoff` still does not perform the full handoff workflow.
2. **Expose advanced workflow controls**
   - `track migration`, `skip next touch`, and `timing override` still are not surfaced in the main operator flow.
3. **Surface routing-review history**
   - resolved/superseded review records are persisted, but they are not yet shown in lead detail or reporting.

## Overall verdict

This is **not just a toy project** anymore. The platform already has real structure in these areas:

- CRM sync and canonical lead modeling
- workflow state machine
- outbound cadence execution
- final pre-send safety checks
- inbound reply handling
- handoff side effects
- paused-search track modeling

However, the remaining weak spots have narrowed from broad routing/review gaps down to tag-time handoff completion, advanced workflow controls, and review-history visibility.

So the honest read is:

- **runtime foundation:** real
- **business route integrity:** materially safer, with explicit routing reviews and a shared pending-review queue now in place
- **manual control / review model:** materially real, with remaining gaps concentrated in advanced workflow controls and review-history visibility

If the goal is to make the platform feel like a genuine lead-nurturing system, the next engineering priority should be to finish tag-time handoff completion and close the remaining advanced operator-control/history gaps.