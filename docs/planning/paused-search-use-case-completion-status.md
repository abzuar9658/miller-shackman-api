# Paused Search & AI Nurture — Use-Case Completion Status

**Scope:** maps the seven business use cases from `docs/business-rules/06-ai-nurture-classification-routing-and-reply-handling.md` to the current implementation.

**How to read this doc:**
- 🟢 Done — works end-to-end with no known safety gaps.
- 🟡 Mostly done — core code exists, at least one gap remains.
- 🔴 Blocked — a critical bug prevents correct behavior.
- Code references are to `miller-schackman-api/`.

## Quick summary

| # | Use case | Status | Critical blocker |
|---|----------|--------|------------------|
| 1 | Silent lead → dormant | 🟢 | None for approved Phase 1 scope |
| 2 | Lead waiting → paused-search | 🟢 | None |
| 3 | Accidentally tagged hot lead | 🟢 | None for approved paused-search scope |
| 4 | Dormant reply → paused-search | 🟢 | None |
| 5 | Paused-search reply → handoff | 🟢 | None |
| 6 | Opt-out / block reply | 🟢 | None |
| 7 | Agent disagrees with AI | 🟢 | None |

---

## Use case 1: Silent lead with no known reason → enters dormant path

**Status:** 🟢 Done for approved backend scope

**What is done**
- `ai_nurture` tag is the enrollment gate: `process_crm_tag_campaign_enrollment.py`.
- `route_ai_nurture_lead` calls the LLM classifier and can return `DORMANT`.
- Dormant path auto-starts via `start_selected_campaign_batch` with campaign start rules (cap, preflight, FIFO).
- Dormant first-touch drafting uses the shared outbound pipeline with recent conversation context.
- Pre-send safety is re-checked before every send.
- Duplicate tag events are idempotent (execution tracker note).

**What is still remaining**
- Richer route-history reporting is still future work; today the explicit review record is optimized for operator decisions rather than full historical analysis.

**Risk if signed off now**
- Low. The operator now has an explicit review-hold resolution path; the remaining gap is audit-model completeness rather than runtime behavior.

---

## Use case 2: Lead says they want to wait for rates → enters paused-search path

**Status:** 🟢 Done

**What is done**
- Explicit paused-search profile (`lead.paused_search_active`, `pause_reason_code`, `reengagement_not_before`, etc.) is persisted.
- `PausedSearchReasonCode` taxonomy includes `waiting_for_rates`, `timing_not_right`, etc.
- `PausedSearchTrack`, `PausedSearchTrackVersion`, and reason-to-track mapping exist.
- `start_paused_search_campaign_enrollment` pins a published track version and starts a Temporal workflow.
- `schedule_next_paused_search_action` computes next action from the pinned track + profile.
- Temporal waiting is interruptible; reschedule signals are wired.
- Fresh classification now runs even when an existing paused-search profile is present, and `human_handoff` / `blocked` outrank the old profile.
- Deterministic future-timing text no longer bypasses the LLM router; paused-search routing now depends on structured classification again.
- Dormant-selector paused-search candidates now flow through the same digest/cap/FIFO start controls as dormant candidates.
- Paused-search cadence execution now revalidates the current profile + pinned track timing before a due step executes, so stale reactivation steps are skipped instead of sending.
- Temporal long-wait tests now cover early reschedule interrupts, duplicate reschedules recomputing once, and stale skipped executions recomputing instead of terminating the workflow.
- Classification artifact `applied_status` is now truthful: `APPLIED` only means the lead state actually changed.

**What is still remaining**
- No paused-search-specific blocker remains in this use case. Remaining follow-up is shared with the broader operator-control and reporting work.

**Risk if signed off now**
- Low. Core paused-search routing, start controls, timing execution, and operator/admin surfaces are in place.


---

## Use case 3: Lead is accidentally tagged while already active → human handoff

**Status:** 🟢 Done

**What is done**
- AI classifier can detect active interest and return `HUMAN_HANDOFF`.
- Handoff creation, agent notification, CRM note/tag, and workflow transition are implemented.
- `CRMTagCampaignEnrollmentStatus` includes `HUMAN_HANDOFF` and `BLOCKED` statuses.
- Tag-time routing no longer falls through into dormant start for non-dormant outcomes.
- Fresh `human_handoff` and `blocked` classifications now outrank an existing paused-search profile.

**What is still remaining**
- No paused-search-specific blocker remains in this use case.

**Risk if signed off now**
- Low.

---

## Use case 4: Dormant lead replies with a known reason → moves to paused-search

**Status:** 🟢 Done

**What is done**
- `process_inbound_message_event.py` handles inbound replies and can trigger `_maybe_reclassify_lead_state_after_inbound`.
- `apply_lead_state_classification` can apply a paused-search profile from the updated conversation.
- A reschedule signal is queued to update the workflow's next action.
- The shared pre-send gate will block future dormant sends if the profile changed.

**What is still remaining**
- No paused-search-specific blocker remains in this use case.

**Risk if signed off now**
- Low.

---

## Use case 5: Paused-search lead replies and is ready now → human handoff

**Status:** 🟢 Done

**What is done**
- Reply classification in `process_inbound_message_event.py` can detect active interest and trigger `HUMAN_HANDOFF`.
- Handoff creation, workflow transition, and agent notification work.
- Pre-send safety stops pending AI messages.

**What is still remaining**
- No paused-search-specific blocker remains in this use case.

**Risk if signed off now**
- Low.


---

## Use case 6: Lead replies with an opt-out or block signal → stop AI

**Status:** 🟢 Done

**What is done**
- Reply classification detects opt-out / stop / unsubscribe signals.
- Suppression state is updated and pre-send checks block all future automated sends.
- Workflow transitions to suppressed/closed as appropriate.
- Channel-level opt-out removes that channel from the track.

**What is still remaining**
- Nothing blocking for this use case.

**Risk if signed off now**
- Low.

---

## Use case 7: Agent disagrees with AI → human override

**Status:** 🟢 Done

**What is done**
- API endpoints exist to set, update, and clear paused-search profile (`lead_paused_search.py`).
- Permission checks (`EDIT_PAUSED_SEARCH_PROFILE_OWN_LEAD`, `EDIT_PAUSED_SEARCH_PROFILE_ANY_LEAD`) are enforced.
- Change history and audit records are written.
- Lead detail UI shows paused-search state, reason, timing, and source.
- Lead detail now shows resolved and superseded routing-review history for operator/support readback.
- Default paused-search subject/body template content is now wired behind the seeded template keys used by the default track strategy.
- Lead detail workflow controls now include timing override, track migration, skip-next-touch, pause, and resume actions.

**What is still remaining**
- No paused-search-specific blocker remains in this use case.

**Risk if signed off now**
- Low.

---

## Cross-cutting gaps that affect multiple use cases

| Gap | Affected use cases | Files to change |
|-----|-------------------|-----------------|
| No paused-search-specific runtime gap remains in the audited scope | — | Remaining release work is `make check`, `pnpm check`, and business-rules doc alignment |

---

## Definition of Done before calling all business use cases complete

- [x] Fix routing precedence so handoff/blocked always beat `paused_search_active`.
- [x] Fix route fall-through so only `DORMANT` enters the dormant start batch.
- [x] Correct artifact `applied_status` so `APPLIED` means truly applied.
- [x] Resolve deterministic future-timing drift (make it review-only or remove as primary source).
- [x] Implement review-hold resolution UI and backend resolution flow for the no-workflow lead-detail path.
- [x] Add reengagement window check to the final execution/send gate.
- [x] Harden Temporal long waits (duplicate signals, early-wake recompute, stale-timer stop).
- [x] Complete frontend track-admin controls (`requires_review_before_publish`, `review_required`).
- [x] Add remaining tests for send-time timing and long-wait edge cases.
- [x] Capture final paused-search template subject/body copy in the seeded/default strategy.
- [x] Surface resolved/superseded routing-review history in lead detail readback.
- [x] Prove compliance/channel blocking at execution time with paused-search cadence and inbound-continuation tests.
- [x] Run `make check` and `pnpm check` and fix all failures.
- [x] Align `06-ai-nurture-classification-routing-and-reply-handling.md` with the final code behavior.

---

## Recommended next steps

No remaining paused-search scope items.
