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
| Contactability / enrollment eligibility | ✅ | Core rules are strong and cover the approved V1 decision boundary |
| Lead-state classification and route selection | ✅ | Core precedence, explicit routing-review records, and reply-time rerouting coverage justify closure in approved scope |
| Dormant nurture path | ✅ | Runtime, entry safety, and no-workflow review resolution are now in place |
| Paused-search path | ✅ | Selector start safety, timing-aware scheduling, cadence execution, and workflow rescheduling are all covered in approved scope |
| Human handoff path | ✅ | Inbound and tag-time handoff paths now both create/reuse handoffs and complete CRM and notification side effects in approved scope |
| Blocked / suppression path | 🟡 | Suppression mechanics are strong; CRM fetch failure recovery still needs resolution |
| Inbound reply handling / continue-AI logic | ✅ | Broad test coverage now includes the remaining skipped-transition and blocked-acknowledgment edge cases |
| Human activity pause | ✅ | Pause flow covers primary notes/calls/texts/people events in approved scope; additional FUB event types are a documented non-blocking limitation |
| Manual override / resume | ✅ | Core override and resume flows are implemented; remaining gaps are advanced UI-control surfaces |
| Workflow runtime and final pre-send safety | 🟡 | Temporal and final checks exist, but real pre-send facts and durable uncertain-send reconciliation remain incomplete |

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

**Status:** 🟡 Partial

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
- CRM webhook resource-fetch failures are currently acknowledged and persisted as ignored rather than retried durably; see Gap 6.

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
- No cross-cutting gap is currently tracked for this phase; pre-send checks re-verify eligibility immediately before send.

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
- No cross-cutting gap is currently tracked for this phase.

---

## Phase 5 — Dormant path

**Status:** 🟡 Partial

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
- Workspace SMS compliance (A2P/10DLC) state is stored and configurable, but per the V1 destination-only contactability rule it does not block automated SMS send or continuation (see Phase 3).

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
- Continue-AI and handoff acknowledgment sends now pause safely when contactability blocks the channel.

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
- Production call sites do not populate the global/campaign/channel pre-send facts; see Gap 2.
- Standard dormant UNCERTAIN sends have no callback/timeout reconciliation; see Gap 4.
- Provider failure and activity-crash handling lack a durable exception/reconciliation boundary; see Gaps 5 and 7.

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

1. **Close the cross-cutting safety gaps documented below**
   - especially pre-send fact population, uncertain-send reconciliation, and durable CRM/provider failure recovery.
2. **Decide on cross-campaign and re-entry policy**
   - decide whether one lead may have multiple active campaigns or needs a re-entry cool-down.
3. **Expose advanced workflow controls and routing history**
   - `track migration`, `skip next touch`, `timing override`, and resolved/superseded review history remain operator-surface work.

## Open architectural gaps (cross-cutting, found during Step 7 deep-dive)

These were found while verifying completion, handoff, suppression, and re-entry
(the product-flow step after cadence execution and reply handling). They are not
isolated bugs in one phase — each cuts across enrollment, cadence execution, and/or
send safety. None of these have been fixed yet; this section only documents them so
a decision can be made before implementation.

### Gap 1 — No guard against a lead being active in two campaigns at once

**Where:** `app/infrastructure/persistence/postgres/workflow_repository.py`
(`get_latest_for_lead_for_update`, `get_latest_for_lead`) and
`app/application/services/campaign_enrollment_starter.py` (`start_single_campaign_enrollment`).

`LeadWorkflowRepository.get_latest_for_lead_for_update` is scoped only by
`(workspace_id, lead_id)` — not by `campaign_id`. `start_single_campaign_enrollment`
creates a new `LeadWorkflow` row whenever `CampaignEnrollmentRepository.get_by_lead_and_campaign`
finds no existing enrollment **for that specific campaign**. Nothing checks whether the
lead already has an active `LeadWorkflow` in a *different* campaign before starting a
second one. `execute_campaign_cadence_step` then loads "the latest workflow for this
lead" regardless of which campaign_version_id was passed in, so a second campaign's
cadence execution can silently no-op (cursor mismatch) rather than fail loudly, or in
some orderings can begin driving the wrong workflow row.

**Impact:** A lead can end up FIFO-enrolled into two campaigns simultaneously with no
explicit product decision or rejection path. Behavior in that state is undefined rather
than deliberately blocked or queued.

**Suggested remediation (pick one, needs a product decision):**
- Reject/queue a new enrollment if `get_latest_for_lead` returns a non-terminal workflow
  belonging to a different `campaign_id` (explicit single-active-campaign-at-a-time rule), or
- Explicitly support multiple concurrent campaigns per lead by scoping
  `get_latest_for_lead_for_update` and cadence execution by `(lead_id, campaign_id)`
  instead of lead-only.

### Gap 2 — Global/campaign/channel frequency-limit fields are defined but never populated

**Where:** `app/domain/campaigns/pre_send.py` (`PreSendFacts`), and every call site that
constructs it: `app/application/use_cases/plan_outbound_message.py::_select_channel`,
`app/application/use_cases/campaign_cadence_execution.py` (`PlanNextOutboundMessageContext`,
`OutboundSendContext` construction), `continue_ai_conversation_after_inbound.py`.

`PreSendFacts` carries `last_global_outreach_at`, `last_campaign_outreach_at`,
`last_channel_outreach_at`, `other_channel_sent_at`, `lead_replied_since_scheduled`,
`recent_human_activity`, `handoff_active`, and `human_owned`. `evaluate_pre_send_safety`
correctly uses all of them (frequency-limit blocking, simultaneous-channel blocking,
human-control blocking). But **every production call site leaves these at their dataclass
defaults** (`None`/`False`) — none of `execute_campaign_cadence_step`,
`plan_next_outbound_message_for_lead`, or `continue_ai_conversation_after_inbound` looks up
the lead's last outreach timestamps, current handoff/human-owned state, or "replied since
scheduled" status before building the context. There is no test that exercises a real
frequency-limit block via the actual cadence path — `tests/domain/campaigns/test_pre_send.py`
only tests the pure function.

**Impact:** The documented "no more than one automated outreach attempt within 24 hours
across all channels" rule (AGENTS.md, Messaging Rules) and "no simultaneous SMS and email"
rule are not enforced in the real send path at all. The only things actually preventing a
double-send today are workflow-state gating (`WAITING_FOR_RESPONSE` cursor logic) and the
per-cadence-step idempotency key — not the frequency-limit policy that exists specifically
for this purpose.

**Suggested remediation:** Wire real lookups (e.g. `OutboundMessageRepository` query for
most-recent sent message globally / per-campaign / per-channel, `Handoff`/workflow-state
lookups for `handoff_active`/`human_owned`, last-inbound-message timestamp for
`lead_replied_since_scheduled`) into the context builders in `campaign_cadence_execution.py`
and `continue_ai_conversation_after_inbound.py` before constructing `PreSendFacts`, as
defense-in-depth alongside the existing workflow-state checks.

### Gap 3 — No cool-down/gap enforced after a workflow reaches a terminal state

**Where:** `app/application/services/campaign_enrollment_starter.py`,
`app/infrastructure/persistence/postgres/dormant_candidate_selector.py`.

Once a `LeadWorkflow` reaches `COMPLETED`, `SUPPRESSED`, or `CLOSED`, nothing prevents
immediate re-enrollment into a different campaign (or the same campaign, once a new
enrollment row is created). The dormant-candidate selector's "already enrolled" exclusion
is scoped to `(workspace_id, campaign_id, lead_id)` only, so a lead who just completed
Campaign A is immediately selectable for Campaign B on the very next selector run.

**Impact:** Combined with Gap 1, a lead could be re-enrolled and get simultaneous or
back-to-back campaign membership with no explicit minimum gap — this may be acceptable
for V1's FIFO-only design, but it is not a deliberate decision recorded anywhere.

**Suggested remediation:** Decide whether V1 needs a minimum re-entry cool-down after
terminal states, and if so enforce it in the enrollment eligibility check
(`evaluate_campaign_enrollment`) using the lead's most recent terminal `LeadWorkflow`.

### Gap 4 — Dormant/cadence path has no reconciliation for UNCERTAIN provider sends (unlike paused-search)

**Where:** `app/application/use_cases/campaign_cadence_execution.py`
(`_pause_after_block`, called for `SendOutboundMessageStatus.UNCERTAIN` on the plain
dormant/cadence path), `app/application/use_cases/process_provider_delivery_callback.py`.

For the **paused-search** path, an `UNCERTAIN` send is tracked via `RecurringOccurrence`,
and there is a full reconciliation story: `process_provider_delivery_callback` auto-resolves
the occurrence and wakes the workflow via `BLOCKED_REVIEW_COMPLETED` once the provider
confirms delivery, and `timeout_uncertain_paused_search_occurrence` fails it out after 24h
if the provider never confirms. For the **plain dormant/cadence** path, an `UNCERTAIN` send
result goes straight to `_pause_after_block`, which transitions the workflow to `PAUSED`
with `pause_reason="cadence_step_blocked"` — there is no occurrence-equivalent record, and
`process_provider_delivery_callback`'s auto-resume logic is gated on
`occurrence_repository is not None` / matching `RecurringOccurrence`, so it never fires for
a dormant-path message.

**Impact:** A dormant-path lead whose provider send comes back `UNCERTAIN` (e.g. missing
`provider_message_id`) is paused indefinitely and requires manual resume even if the
provider's later delivery callback confirms the message actually sent successfully. The
paused-search path does not have this problem; the dormant path does.

**Suggested remediation:** Either extend `process_provider_delivery_callback` to also
auto-resume plain dormant workflows paused for `UNCERTAIN` sends (symmetric with the
paused-search occurrence logic), or explicitly document that dormant-path `UNCERTAIN`
sends always require manual operator resolution.

### Gap 5 — Provider retry is a single in-process retry only; no durable exception queue

**Where:** `app/application/use_cases/send_outbound_message.py` (`_send_sms`, `_send_email`).

`_send_sms`/`_send_email` retry exactly once, inline, with a fixed 0.1s sleep, and only for
`ProviderFailureKind.TEMPORARY`. There is no exponential backoff, no durable/cross-process
retry, and no separate "exception queue" for sends that exhaust retries — a `FAILED` result
just pauses the workflow (`_pause_after_block`), which is indistinguishable in the data
model from any other policy-based pause. AGENTS.md's Reliability Guidelines call for
"exponential backoff," a "maximum retry count," and moving "unresolved failures to an
exception queue" as a distinct concept from a generic paused workflow.

**Impact:** Not unsafe (failures do stop the workflow rather than silently drop the
message), but there is no way to distinguish "paused because of a transient provider outage
that should be retried later" from "paused because of a policy/business-rule block" without
reading `pause_reason` metadata by hand, and no durable retry-with-backoff exists outside
the single inline retry.

**Suggested remediation:** Decide whether V1 needs a distinct exception-queue surface (e.g.
a queryable view over `PAUSED` workflows with `pause_reason="cadence_step_blocked"` and a
`FAILED` message with `failure_kind=TEMPORARY`/`UNCERTAIN`), or whether the existing
pause-and-manually-resume flow is considered sufficient for V1 scope.

### Gap 6 — CRM webhook resource-fetch failures are recorded as ignored, not retryable

**Where:** `app/infrastructure/crm/follow_up_boss/webhook_event_handler.py` and
`app/infrastructure/crm/follow_up_boss/webhook_event_mappers.py`.

The webhook envelope is accepted and routed to a mapper, but mapper resource fetches return
`(0, 1)` when Follow Up Boss returns no resource. The handler then persists the envelope as
`IGNORED` and the API returns success. There is no retryable status, retry scheduling, or
operator queue for a transient CRM/API outage. The same pattern applies when a resource
payload is incomplete enough that all child records are skipped.

**Impact:** A webhook can be acknowledged successfully while its lead activity, suppression,
or human-pause side effects never happen. A later full CRM sync may eventually repair the lead
snapshot, but it does not guarantee replay of the missed event or preservation of the event's
original ordering relative to outbound work.

**Suggested remediation:** Distinguish `IGNORED` unsupported/irrelevant events from
`RETRYABLE_FAILURE` fetch/parse failures. Persist the failure reason and retry metadata, return
an appropriate non-success response when safe, and replay through a durable worker with bounded
backoff. Keep provider event idempotency so replay cannot duplicate side effects.

### Gap 7 — Temporal activity failures can strand a workflow without a durable operator-visible retry state

**Where:** `app/infrastructure/workflows/temporal/lead_nurture.py` and
`app/application/use_cases/campaign_cadence_execution.py`.

The cadence activity uses `RetryPolicy(maximum_attempts=1)` because replaying an external
provider side effect could duplicate a send. That protects against blind duplicate dispatch,
but if the activity or process fails after the provider call and before the message/workflow
state is durably recorded, Temporal does not retry the activity and the workflow has no built-in
exception record to reconcile the uncertain operation. The in-process provider retry does not
solve process crashes or database outages.

**Impact:** A workflow can remain in an active or waiting state with an outbound operation whose
actual provider result is unknown, without a durable retry/exception item or automatic
reconciliation path. Operators cannot reliably distinguish a provider outage, process crash,
database failure, or successful-but-unrecorded send.

**Suggested remediation:** Introduce an explicit durable dispatch boundary: persist an outbound
send request and idempotency key transactionally, dispatch it from a worker, reconcile provider
status by idempotency key/provider message id, and only then advance the Temporal workflow. If
that architecture is deferred, persist an explicit `UNCERTAIN` exception record before allowing
the workflow to wait and expose it for bounded operator reconciliation.

---

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