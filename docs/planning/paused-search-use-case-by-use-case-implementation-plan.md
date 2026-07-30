# Paused Search Use-Case-by-Use-Case Implementation Plan

## Purpose

This document translates the slice-based paused-search implementation plan into a use-case-by-use-case delivery plan.

Use it alongside:

- `paused-search-implementation-plan.md`
- `paused-search-use-case-completion-status.md`
- `docs/business-rules/06-ai-nurture-classification-routing-and-reply-handling.md`
- `paused-search-initial-reason-workflows.md`

## How to use this document

- The slice plan explains **how the platform is built**.
- This document explains **which business flow each piece of work must satisfy**.
- A use case is only done when routing, persistence, workflow behavior, operator visibility, audit, and tests all work together.

For this document, "complete" means the plan covers both:

- the **core lead-journey use cases**
- the **supporting admin and operator use cases** required to run paused-search safely in production

## Use-case map

| # | Use case | Main slices |
|---|---|---|
| 1 | Silent lead -> dormant path | 2, 3, 7 |
| 2 | Lead waiting -> paused-search path | 1, 2, 3, 4, 5, 7 |
| 3 | Accidentally tagged hot lead -> human handoff | 2, 3, 5, 7 |
| 4 | Dormant reply -> paused-search | 1, 2, 5, 6, 7 |
| 5 | Paused-search reply -> human handoff | 1, 2, 5, 6, 7 |
| 6 | Opt-out / block reply -> stop AI | 2, 5, 7 |
| 7 | Agent disagrees with AI -> human override | 1, 2, 4, 6, 7 |
| 8 | Admin creates or edits a paused-search track draft | 4, 7 |
| 9 | Admin publishes, retires, or remaps a paused-search track | 4, 7 |
| 10 | Ambiguous AI routing goes to review hold and gets resolved | 2, 3, 6, 7 |
| 11 | Existing paused-search lead is migrated to a new published track version | 4, 6, 7 |
| 12 | Operator overrides timing, skips next touch, pauses, or resumes | 1, 5, 6, 7 |
| 13 | Channel or compliance rules block a scheduled paused-search touch | 5, 7 |
| 14 | Team reviews why a lead is on the current path and what happens next | 1, 2, 4, 5, 6, 7 |
| 15 | Admin updates paused-search message strategy and templates safely | 4, 7 |

## Use case 1 — Silent lead with no known reason enters dormant path

**Business goal:** when a lead is silent and no known pause reason exists, the system should start the dormant journey safely after the configured tag is present.

**Implementation work**
- Let the classifier return `dormant` as a distinct outcome.
- Keep the configured `ai_nurture` tag as the hard start gate.
- Route to dormant only when no higher-priority paused, handoff, blocked, or review outcome exists.
- Draft the first dormant touch from recent approved conversation context.
- Re-run pre-send checks immediately before send.

**Done when**
- tagging a silent lead starts dormant automatically
- duplicate tag events do not create duplicate workflows
- no-contact / no-consent / human-owned leads do not start

## Use case 2 — Lead says they want to wait for rates or timing enters paused-search path

**Business goal:** when the system knows why the lead is waiting, it should place that lead into the correct paused-search reason and pinned track.

**Implementation work**
- Persist paused-search profile fields such as active state, reason, and timing.
- Let the classifier return approved paused-search reason codes.
- Route paused-search above dormant when the tag is present.
- Pin the lead to the currently published track version for that reason.
- Schedule maintenance and reactivation using the pinned track plus lead timing.
- Seed the initial seven default reason workflows and templates.

**Done when**
- a lead waiting for rates, inventory, financial prep, or timing is routed into paused-search
- the correct reason-specific workflow is pinned and scheduled
- long waits survive workflow rescheduling and restarts

## Use case 3 — Accidentally tagged hot lead goes to human handoff

**Business goal:** a lead who is active now must never drift into dormant or paused-search just because the nurture tag was applied.

**Implementation work**
- Let the classifier return `human_handoff` as a higher-priority outcome.
- Make tag-time routing stop on handoff instead of falling through to nurture.
- Trigger the full handoff path: pause AI, create handoff record, notify agent, write CRM note/tag, and preserve audit history.
- Ensure any queued nurture action is cancelled or blocked before send.

**Done when**
- an accidentally tagged hot lead never enters dormant or paused-search
- full handoff side effects occur directly from the routing decision
- the assigned agent can see why AI stopped

## Use case 4 — Dormant lead replies with a known reason and moves to paused-search

**Business goal:** a dormant lead who replies with "we are waiting for rates" or a similar known reason should stop dormant treatment and move into paused-search.

**Implementation work**
- Re-run classification on meaningful inbound replies.
- Allow reply-time classification to create or update paused-search profile state.
- Reschedule the workflow using the paused-search reason and pinned track.
- Prevent stale dormant messages from sending after the lead has changed paths.
- Expose routing-review and correction controls when reply meaning is ambiguous.

**Done when**
- dormant outreach stops after the reply changes the lead into paused-search
- the lead receives the correct paused-search treatment instead of stale dormant touches
- operators can review and correct unclear reroutes

## Use case 5 — Paused-search lead replies and is ready now so AI hands off

**Business goal:** when a paused-search lead becomes active again, AI should stop and hand the lead back to a human immediately.

**Implementation work**
- Re-run classification on inbound replies for paused-search leads.
- Let current active-interest or human-request signals outrank the existing paused-search profile.
- Trigger the full handoff side effects from the reply path.
- Stop or invalidate the current paused-search timer and next scheduled step.
- Preserve one consistent audit trail for why the lead moved from paused-search to handoff.

**Done when**
- a ready-now reply stops paused-search automation immediately
- the assigned agent is notified with context
- no stale paused-search touch can still send afterward

## Use case 6 — Lead replies with opt-out or block signal so AI stops

**Business goal:** channel-level or full suppression must stop future automation immediately.

**Implementation work**
- Detect opt-out, stop, unsubscribe, and blocked outcomes from replies.
- Apply suppression state durably.
- Re-check suppression before every send.
- Remove blocked channels from the active path or stop the workflow entirely, depending on the signal.
- Ensure compliance decisions outrank all nurture logic.

**Done when**
- future sends are blocked immediately after opt-out
- the workflow moves into suppressed or closed behavior correctly
- audit records show which signal caused the stop

## Use case 7 — Agent disagrees with AI and overrides the lead state

**Business goal:** humans must be able to correct AI classifications and live workflow behavior without editing raw data manually.

**Implementation work**
- Expose lead-level actions to set, update, clear, or replace paused-search state.
- Expose advanced controls for timing override, track migration, skip-next-touch, and manual pause/resume.
- Require role-based permissions and audit records for every override.
- Recompute the next workflow action after each approved override.
- Keep human truth authoritative until new reviewed evidence changes it.

**Done when**
- an operator can correct a wrong reason or timing safely
- an admin or manager can migrate a lead to a new published track version
- the workflow recomputes cleanly after each override action

## Use case 8 — Admin creates or edits a paused-search track draft

**Business goal:** admins should be able to define paused-search strategy without filing an engineering request for every cadence change.

**Implementation work**
- Expose draft create and update flows for track key, display name, allowed channels, phase timing, steps, and default reason codes.
- Validate the draft before publish so incomplete or invalid tracks cannot become active accidentally.
- Store immutable version snapshots rather than mutating live strategy in place.
- Record admin audit history for each draft creation or edit.

**Done when**
- an admin can create and edit a paused-search draft safely
- invalid track structure is rejected before publish
- audit history shows who changed the strategy and when

## Use case 9 — Admin publishes, retires, or remaps a paused-search track

**Business goal:** strategy changes should affect new leads safely without silently mutating live leads already in flight.

**Implementation work**
- Publish a draft into an immutable active version.
- Retire previously published versions while keeping pinned historical versions readable.
- Replace reason mappings to point each reason code to the newly published version.
- Support track retirement without corrupting leads already pinned to older versions.

**Done when**
- new leads use the latest published version automatically
- old leads remain on their pinned version until explicitly migrated
- retiring a track clears future default mapping without breaking historical readability

## Use case 10 — Ambiguous AI routing goes to review hold and gets resolved

**Business goal:** when AI is unsure, the system should stop and ask a human instead of guessing.

**Implementation work**
- Create or refresh a pending routing review when classification lands in `review_hold`.
- Show the pending review in a workspace review queue.
- Allow an authorized human to resolve the review into paused-search, dormant, handoff, blocked, or another approved outcome.
- Supersede stale pending reviews when newer evidence replaces them.

**Done when**
- ambiguous or low-confidence cases land in a visible review queue
- one review decision can safely move the lead into the correct path
- stale pending reviews are superseded instead of accumulating confusion

## Use case 11 — Existing paused-search lead is migrated to a new published track version

**Business goal:** when strategy changes, the team needs a safe way to move a live lead to the new version intentionally.

**Implementation work**
- Expose a migrate-to-track-version action for authorized actors.
- Validate that the target version exists and is appropriate.
- Recompute the next scheduled step after migration.
- Write an override audit record showing old version, new version, actor, and reason.

**Done when**
- an authorized actor can move a lead from one pinned version to another
- the workflow reschedules cleanly after migration
- migration history is auditable

## Use case 12 — Operator overrides timing, skips next touch, pauses, or resumes

**Business goal:** operators need safe escape hatches when the real-world situation changes faster than the default workflow.

**Implementation work**
- Expose timing override, skip-next-touch, manual pause, and manual resume controls.
- Require reason capture and role-based permission checks for every action.
- Recompute the workflow after timing and skip changes.
- Re-run resume eligibility checks before allowing automation to continue.

**Done when**
- operators can adjust a lead's next action without editing raw workflow data
- resume cannot bypass suppression, human ownership, or other send blockers
- every override leaves a clear audit trail

## Use case 13 — Channel or compliance rules block a scheduled paused-search touch

**Business goal:** even if a paused-search workflow is valid, a specific scheduled touch must still be blocked when channel policy says no.

**Implementation work**
- Run contactability and pre-send checks immediately before each paused-search send.
- Respect do-not-contact, opt-out, missing permission, email unsubscribe, and SMS compliance rules.
- Cancel, defer, or suppress the next action according to the reason for the block.
- Make the block reason visible to operators.

**Done when**
- a scheduled paused-search touch cannot send through a blocked channel
- compliance rules win over track configuration every time
- operators can see why a touch was blocked

## Use case 14 — Team reviews why a lead is on the current path and what happens next

**Business goal:** the team should not need to reverse-engineer workflow state from raw records.

**Implementation work**
- Show the current lead state, paused-search profile, pinned track version, next action time, and next step.
- Show whether the current state came from AI, operator action, or workflow override.
- Surface review-hold, migration, and override history in lead detail or reporting.
- Make route decisions and next scheduled action queryable for support and operations.

**Done when**
- an operator can answer "why is this lead here?" from the product
- support can inspect the current path and next action without reading raw database rows
- route and override history is visible enough to debug business behavior

## Use case 15 — Admin updates paused-search message strategy and templates safely

**Business goal:** the business should be able to change message timing and message intent per reason without breaking live journeys.

**Implementation work**
- Treat message goals and template keys as part of the versioned track strategy.
- Ensure new template or cadence changes apply to new published versions only.
- Keep existing leads pinned to the old message strategy unless explicitly migrated.
- Validate that template references exist and match the intended channel behavior.

**Done when**
- an admin can change the message strategy for `financial_prep`, `waiting_for_rates`, or any other existing reason without engineering
- new leads receive the updated strategy after publish
- existing leads do not silently change behavior mid-journey

## Recommended implementation order

1. Build the shared classifier, routing, and paused-search persistence foundation.
2. Finish use cases 1 and 2 first because they establish the two main journey types.
3. Finish use cases 3 and 6 next because they are the highest-risk safety stops.
4. Finish use cases 4 and 5 next because reply-time rerouting is where stale automation risk appears.
5. Finish use cases 8, 9, and 15 next so admins can control strategy safely.
6. Finish use cases 10, 11, and 12 next so operators can resolve ambiguity and manage live workflows.
7. Finish use case 14 to make path visibility and support readback operationally usable.
8. Keep use case 13 enforced throughout because compliance blocking is not optional follow-up work.
9. Finish use case 7 as part of the override-control layer because human correction depends on the earlier foundations.

## Definition of done for the overall plan

The paused-search implementation is complete only when all fifteen use cases can be demonstrated end-to-end with:

- correct classifier outcome
- correct route decision
- correct workflow start or stop behavior
- correct audit trail
- correct operator visibility
- correct pre-send protection against stale automation
- focused tests for normal path plus edge cases

## Completeness boundary

This document is now intended to cover the full paused-search business scope for V1 planning:

- core lead journeys
- reply-time rerouting
- handoff and stop conditions
- admin strategy changes
- review-hold handling
- live workflow overrides and migration
- compliance and channel blocking
- support and reporting readback

Anything beyond this boundary should be treated as a separate future planning track rather than an unspoken gap in paused-search scope.
