# Paused Search Test Matrix and Verification Plan

## Purpose

This document is the verification companion to:

- `paused-search-use-case-by-use-case-implementation-plan.md`
- `paused-search-implementation-plan.md`
- `paused-search-execution-tracker.md`

Use it to make sure paused-search implementation does not miss business flows, stale-automation risks, or test coverage gaps.

## Required test layers

Every paused-search change should be evaluated across these layers:

- **Domain/unit tests**: pure rules, timing, routing precedence, validation.
- **Application/use-case tests**: orchestration with fakes.
- **Persistence/API tests**: Postgres repository behavior and API contract behavior.
- **Workflow/integration tests**: scheduling, reschedule, wake-up, stale-timer protection.
- **Frontend/operator tests**: admin and operator workflows, review queue, lead detail visibility.

## Current test anchors

Backend:

- `tests/application/services/test_paused_search_drafting_templates.py`
- `tests/application/use_cases/test_route_ai_nurture_lead.py`
- `tests/application/use_cases/test_lead_paused_search.py`
- `tests/application/use_cases/test_paused_search_track_admin.py`
- `tests/application/use_cases/test_paused_search_track_pinning.py`
- `tests/application/use_cases/test_seed_default_paused_search_tracks.py`
- `tests/application/use_cases/test_schedule_next_paused_search_action.py`
- `tests/application/use_cases/test_lead_review_hold_resolution.py`
- `tests/application/use_cases/test_lead_read.py`
- `tests/application/use_cases/test_lead_pause.py`
- `tests/application/use_cases/test_lead_workflow_overrides.py`
- `tests/application/use_cases/test_campaign_cadence_execution.py`
- `tests/domain/campaigns/test_paused_search_timing.py`
- `tests/infrastructure/persistence/postgres/test_paused_search_track_repository.py`
- `tests/interfaces/api/v1/test_leads.py`
- `tests/interfaces/api/v1/test_paused_search_tracks_admin.py`

Frontend:

- `src/app/AdminOperationsRoutes.test.tsx`
- `src/app/LeadsRoutes.test.tsx`
- `src/pages/LeadDetailPage.tsx`
- `src/pages/ReviewQueuePage.tsx`
- `src/components/settings/PausedSearchTracksCard.tsx`

## Use-case coverage matrix

| UC | Primary tests to own coverage | Required verification |
|---|---|---|
| 1 dormant start | `test_route_ai_nurture_lead`, campaign enrollment / dormant start tests | tag gate, dormant route, duplicate-tag idempotency, no-contact/no-consent stop |
| 2 paused-search entry | `test_lead_paused_search`, `test_paused_search_track_pinning`, `test_schedule_next_paused_search_action`, `test_paused_search_timing` | reason persisted, published track pinned, maintenance/reactivation scheduled |
| 3 tagged hot lead -> handoff | `test_route_ai_nurture_lead`, handoff/enrollment tests | handoff outranks paused/dormant, no nurture start, full handoff side effects |
| 4 dormant reply -> paused-search | inbound reply tests + `test_lead_review_hold_resolution` + paused-search scheduling tests | reply reclassifies, dormant path stops, paused-search path starts, stale touch blocked |
| 5 paused reply -> handoff | inbound reply tests + handoff tests + cadence execution tests | ready-now reply stops AI, pending paused touch cannot still send |
| 6 opt-out/block reply | inbound reply tests + pre-send/cadence tests | suppression persists, future sends blocked immediately, audit reason visible |
| 7 human override | `test_lead_paused_search`, `test_lead_workflow_overrides`, lead read/detail tests | override authority, audit trail, recompute after change |
| 8 draft track create/edit | `test_paused_search_track_admin`, API admin tests, `AdminOperationsRoutes.test.tsx` | invalid draft blocked, audit/event written, UI edit flow works |
| 9 publish/retire/remap | `test_paused_search_track_admin`, repo tests, API admin tests | new leads get new version, old leads stay pinned, retired track remains readable |
| 10 review hold resolution | `test_route_ai_nurture_lead`, `test_lead_review_hold_resolution`, review queue UI tests | ambiguous cases queue, resolution moves lead safely, stale reviews superseded |
| 11 migrate live lead to new version | `test_lead_workflow_overrides`, lead detail operator tests | target version validation, audit recorded, next action recomputed |
| 12 timing/skip/pause/resume overrides | `test_lead_pause`, `test_lead_workflow_overrides`, resume tests, lead detail UI tests | reason required, permissions enforced, resume re-checks eligibility/suppression |
| 13 compliance/channel block | contactability/pre-send tests + cadence execution tests + inbound continuation tests | blocked channel wins over track config, no send through blocked path |
| 14 readback/support visibility | lead read/detail tests + API lead-detail tests + review queue tests + `LeadsRoutes.test.tsx` | team can answer why-path/next-action/source/version from UI/API |
| 15 message strategy/template changes | seed/default-track tests + track admin tests + drafting/render tests + cadence execution tests | new version only affects new leads, template references valid, no silent mid-journey change |

## Edge-case matrix that must be proven

| Risk | Minimum proof |
|---|---|
| Duplicate tag events | no duplicate workflow / enrollment |
| Existing paused profile + new blocked/handoff signal | blocked/handoff wins |
| Existing paused profile + weak dormant/review signal | paused-search remains pinned until stronger evidence |
| Long wait reschedule | updated timing invalidates stale timer |
| Reply arrives before due paused step sends | reply path reclassifies before send |
| Operator migration to wrong target | invalid/unpublished/retired target rejected unless explicitly supported |
| Resume after suppression or human ownership | rejected until rules allow resume |
| Publish new track while leads are mid-journey | only new leads get new version automatically |
| Review-hold replaced by newer evidence | old pending review becomes superseded |
| Channel blocked at send time | track step does not bypass contactability/pre-send rules |

## Minimum verification per PR

For any PR touching paused-search logic, require:

- targeted backend unit/use-case tests
- targeted Postgres/API tests if persistence or admin endpoints changed
- targeted Temporal/cadence tests if timing or reschedule behavior changed
- targeted frontend tests if admin/operator UI changed
- update to this matrix if a new use case or new test seam was introduced

## Command checklist before signoff

Backend minimum:

- `uv run pytest tests/application/services/test_paused_search_drafting_templates.py`
- `uv run pytest tests/domain/campaigns/test_paused_search_timing.py`
- `uv run pytest tests/application/use_cases/test_route_ai_nurture_lead.py`
- `uv run pytest tests/application/use_cases/test_lead_paused_search.py`
- `uv run pytest tests/application/use_cases/test_paused_search_track_admin.py`
- `uv run pytest tests/application/use_cases/test_schedule_next_paused_search_action.py`
- `uv run pytest tests/application/use_cases/test_lead_review_hold_resolution.py`
- `uv run pytest tests/application/use_cases/test_lead_read.py`
- `uv run pytest tests/application/use_cases/test_lead_pause.py`
- `uv run pytest tests/application/use_cases/test_lead_workflow_overrides.py`

When relevant also run:

- `uv run pytest tests/application/use_cases/test_campaign_cadence_execution.py`
- `uv run pytest tests/application/use_cases/test_process_inbound_message_event.py`
- `uv run pytest tests/infrastructure/persistence/postgres/test_paused_search_track_repository.py`
- `uv run pytest tests/interfaces/api/v1/test_leads.py`
- `uv run pytest tests/interfaces/api/v1/test_paused_search_tracks_admin.py`

Frontend minimum when UI changed:

- `pnpm vitest run src/app/AdminOperationsRoutes.test.tsx`
- `pnpm vitest run src/app/LeadsRoutes.test.tsx`

Full confidence gates before rollout:

- `make check`
- `pnpm check`

## Definition of done for verification

Paused-search is not ready to sign off until:

- all 15 use cases have at least one owning backend test path
- every operator/admin use case has visible UI or API proof
- stale-automation risks are covered by reply-time, reschedule, and pre-send tests
- version pinning and migration behavior are proven explicitly
- compliance/channel blocking is proven at execution time, not assumed from config
- rollout commands pass or any remaining failures are documented as unrelated
