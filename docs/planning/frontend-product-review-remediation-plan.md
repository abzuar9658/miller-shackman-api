# Frontend Product Review Remediation Plan

Status: proposed
Scope: frontend web app (React + Vite + TypeScript, shadcn/ui, TanStack Query, react-router)
Audience: any engineer or LLM agent executing this plan. The document is self-contained.

## Context

This platform is an AI-assisted real estate lead nurturing product for brokerages.
Users are brokerage admins, managers, and assigned agents. There are two repos:

- Backend: FastAPI app (this repo). API base: `/api/v1`, routes under `app/interfaces/api/v1/`.
- Frontend: separate repo with `src/pages/`, `src/components/`, `src/lib/api/`,
  `src/app/router.tsx`. Dev server runs at `http://localhost:5173`.

All file paths below that start with `src/` refer to the FRONTEND repo.
All file paths that start with `app/` or `tests/` refer to the BACKEND repo.
Line numbers are approximate (correct at the time of review); always re-locate
the referenced code by symbol/component name before editing.

### Frontend verification commands (run in the frontend repo)

- Targeted tests: `pnpm vitest run <test file>`
- Full gate: `pnpm check` (lint + typecheck + tests)
- Key existing test files: `src/app/AdminOperationsRoutes.test.tsx`,
  `src/app/LeadsRoutes.test.tsx`, `src/pages/ReviewQueuePage.test.tsx`,
  `src/pages/HandoffsPage.test.tsx`, `src/pages/AgentMappingPage.test.tsx`

### Backend verification commands (run in the backend repo)

- Full gate: `make check` (ruff + mypy + pytest)

### Execution rules for the implementing agent

1. Work phase by phase. Each phase is independently shippable.
2. After each task, run the targeted tests for the touched pages; run the full
   gate at the end of each phase.
3. Update existing tests when behavior changes (e.g., new confirmation dialogs
   will break click-through tests — updating them is in scope for each task).
4. Do not add new external dependencies without asking.
5. Follow existing UI patterns: `QueueState` for loading/error/empty states,
   `ContextDrawer` for inspection, dialogs from `src/components/ui/`,
   reason-required mutation dialogs as used in `src/pages/LeadDetailPage.tsx`.
6. Do not commit or push without explicit approval from the repo owner.

---

## Phase 0 — Verify and decide (blocks later phases)

### Task 0.1 — Verify "My work" scoping (CRITICAL)

Finding: agent-facing views label data as personal without filtering by the
signed-in user:

- `src/lib/helpers/agentHomeModel.ts` (~lines 37–51): calls `getHandoffs` /
  `getLeads` with no owner filter, then labels results "My handoffs" / "My leads".
- `src/pages/HandoffsPage.tsx` (~line 71): agent default filter is
  `assignmentFilter = 'assigned'`, which matches ANY assigned handoff, not
  handoffs assigned to the current user, even though
  `handoff.assigned_agent_user_id` exists in `src/lib/api/handoffs.ts` (~line 11).

Action: inspect the backend handlers (`app/interfaces/api/v1/handoffs.py`,
`app/interfaces/api/v1/leads.py`) and their use cases to determine whether
results are already scoped by role/token server-side.

- If server-scoped: fix only the frontend labels/filters so they are truthful.
- If NOT server-scoped: (a) add client-side filtering by
  `assigned_agent_user_id === session.user_id` for agent views, and (b) file a
  backend ticket for enforced server-side scoping (client filtering alone is a
  privacy hole). Record the decision in this document.

**DECISION (verified 2026-08-13): server-scoped.** Backend enforces scoping in
the use cases, not the routes:

- `app/application/use_cases/lead_read.py::list_lead_views` — actors without
  `VIEW_WORKSPACE_REPORTING` and with role `ASSIGNED_AGENT` only receive leads
  where `is_actor_assigned_to_lead(actor, lead)` (effective owner user id ==
  actor user id, `app/application/services/lead_assignment.py`).
- `app/application/use_cases/handoff_read.py::list_handoff_views` — same
  pattern; assignment resolves `handoff.assigned_agent_user_id` first, falling
  back to the lead's effective owner.

Consequence for Task 1.2: labels are truthful for agents; fix is frontend-only.
Note the agent default `assignmentFilter = 'assigned'` on HandoffsPage can hide
server-visible handoffs whose `assigned_agent_user_id` is null (owner-fallback
scoping) — the agent default should be "all my handoffs", not "assigned".

### Task 0.2 — Decide the fate of OutboundDraftingPage (dead route)

Finding: `src/pages/OutboundDraftingPage.tsx` is not imported in
`src/app/router.tsx` — the page is unreachable. Meanwhile
`src/app/AdminOperationsRoutes.test.tsx` (~line 455) seeds `/outbound-drafting`,
so the test suite exercises a route that does not exist in the production
router (test/router drift that can mask regressions).

Action: check whether `WorkspaceOutboundDraftingTab` is already mounted under
`/settings` (`src/pages/NurtureSettingsPage.tsx`).

- If yes: delete `src/pages/OutboundDraftingPage.tsx` and update the test to
  target the settings route.
- If no: register the route in `router.tsx` (admin-only, matching its 403
  handling) and add a navigation entry in `src/lib/navigation.ts`.

**DECISION (verified 2026-08-13): register the route.**
`WorkspaceOutboundDraftingTab` is NOT mounted anywhere reachable —
`NurtureSettingsPage.tsx` does not import it; the only consumer is the orphan
`OutboundDraftingPage`. Action: add `/outbound-drafting` to `router.tsx` with
`roleAccess.adminOnly` and a navigation entry, keeping the page's own 403
handling. (Stray `}` in its subtitle is fixed in Task 1.4.)

### Task 0.3 — Record backend API gaps needed by later phases

Create tickets (or a tracking list) for:

1. Acknowledgement actor metadata for attention items (who marked seen, when) —
   `AttentionAcknowledgementResponse` only carries `acknowledged_at` today
   (`src/lib/api/attention.ts`).
2. Assigned-lead counts for ACTIVE paused-search tracks (today `assigned_leads`
   is only surfaced for retired tracks).
3. Listing inventory counts per listing source/scope (current listings held,
   last used in a draft).
4. Server-side pagination + sorting params for leads, handoffs, campaigns,
   users, agent mappings.
5. Handoff acknowledge + reassign endpoints (if not already present; the data
   model already has `acknowledged_at` / `notified_at`).
6. Invite-token validation/preview endpoint (workspace name, role, invited
   email) for the invited signup page.
7. SMS compliance evidence fields (registration ID, approval date, approver).
8. Batch endpoints for bulk actions (bulk mark-seen on attention, bulk veto on
   preflight) — needed for Phase 6.

**VERIFIED (2026-08-13): all eight gaps are real; none of these exist in the
backend today.** Evidence: `AttentionAcknowledgementResponse` carries only
`acknowledged_at` (`app/interfaces/api/schemas/attention.py`); `assigned_leads`
appears only on retire-preview/retired-track schemas
(`schemas/paused_search_tracks.py`); no listing inventory count fields; no
pagination/sorting `Query` params on leads/handoffs/campaigns/users/agent
mapping list routes (only fixed `limit` defaults inside use cases); no
acknowledge/reassign routes in `app/interfaces/api/v1/handoffs.py`; only
`POST /auth/invitations/accept` exists (no token preview route); workspace
schema carries only `sms_compliance_state`; no bulk/batch routes in
`attention.py`/`preflight.py`. This list is the backend tracking list; each
item becomes a backend ticket when its consuming phase starts.

---

## Phase 1 — Correctness bugs (frontend-only)

### Task 1.1 — CRM custom-fields JSON silently wipes mappings (DATA LOSS)

File: `src/pages/NurtureSettingsPage.tsx` (~lines 1988–1999 `parseJsonObject`,
textarea ~lines 1631–1643).
Finding: invalid JSON in the CRM custom-fields textarea is coerced to `{}` and
saved, silently erasing all existing custom-field mappings.
Fix: validate JSON on change; show an inline destructive error under the
textarea; disable the section Save button while invalid. Never coerce parse
failure to `{}`.

### Task 1.2 — Apply the Phase 0.1 scoping decision

Files: `src/lib/helpers/agentHomeModel.ts`, `src/pages/HandoffsPage.tsx`.
Fix labels and/or filters per the decision recorded in Task 0.1.

### Task 1.3 — Only the first pending rejected-draft review is actionable

File: `src/pages/LeadDetailPage.tsx` (~lines 936, 1552–1618).
Finding: all pending rejected-draft reviews render, but the approve dialog is
wired only to `pendingRejectedDraftReviews[0]`; a second pending review has no
action.
Fix: wire approve/deny per review row so every pending review can be resolved.

### Task 1.4 — Small defects batch

1. `src/pages/OutboundDraftingPage.tsx` (~line 78): stray `}` rendered in the
   subtitle copy (fix wherever the component survives after Task 0.2).
2. `src/pages/DormantPage.tsx` (~lines 280–288): `notConfigured` banner is
   unreachable dead code (early return at ~line 195 already covers it). Remove.
3. Paused-search deep links: `/paused-search/retired/:trackId` opens on the
   Active tab. In `src/components/paused-search/PausedSearchTrackStudio.tsx`,
   derive the initial tab from the route variant.
4. `src/pages/HomePage.tsx` (~lines 1610–1614): campaign summary card footer
   button says "Open settings" and links to `/settings`; change to `/campaigns`.

Phase 1 verification: `pnpm vitest run` for touched pages, then `pnpm check`.

---

## Phase 2 — Decision-loop integrity: entity links + urgency signals (frontend-only)

Highest value-per-line phase. All required data already exists in current API
responses.

### Task 2.1 — Link Preflight digests to leads and campaigns

File: `src/pages/PreflightPage.tsx`.
Findings:
- Digest entries render `display_name` + `recipient_destination` only
  (~lines 682–685); `entry.lead_id` is available but never linked. Reviewers
  make veto decisions without being able to check lead history.
- Rows and drawer show raw `campaign_id` (~lines 427, 779) with no link even
  though route `/campaigns/:campaignId` exists.
Fix: link every digest entry to `/leads/:leadId`; link the batch campaign
reference to `/campaigns/:campaignId` (show campaign name if resolvable from
the campaigns list query).

### Task 2.2 — Link Handoff detail to the lead and related entities

File: `src/pages/HandoffDetailPage.tsx`.
Findings:
- `lead.lead_id` is displayed as plain text (~line 413) — never linked to
  `/leads/:leadId`. This is the most surprising dead end in the app.
- Campaign/workflow/conversation/inbound-message references are raw UUIDs
  (~lines 461–477).
Fix: link the lead ID to lead detail; link campaign ID to campaign detail;
render names instead of UUIDs where the data is resolvable.

### Task 2.3 — Campaign names instead of raw IDs on lead surfaces

Files: `src/pages/LeadWorkspacePage.tsx` (drawer reference facts ~lines
1473–1479), `src/pages/LeadDetailPage.tsx` (header action ~line 1136 links to
`/settings` instead of `/campaigns/:campaignId`).
Fix: resolve and display the enrolled campaign name; link to
`/campaigns/:campaignId`.

### Task 2.4 — Surface review deadlines in the Review Queue

File: `src/pages/ReviewQueuePage.tsx`.
Finding: `PausedSearchReview.review_expiry_at`
(`src/lib/api/pausedSearchOperations.ts` ~line 43) is fetched but never
rendered — reviews can silently expire.
Fix: render relative time-to-expiry per row with an "expiring soon" badge
(e.g., < 24h), and default-sort pending reviews by soonest expiry.

### Task 2.5 — Veto-window countdown on Preflight

File: `src/pages/PreflightPage.tsx` (~lines 431–433, 629–631).
Finding: `veto_window_expires_at` shows only as an absolute timestamp; no
urgency signal, no expiry-based ordering.
Fix: add relative "expires in Xh" text on rows and drawer; default-sort
pending batches by soonest expiry. Also fix the "Leads awaiting review" metric
(~lines 268–271), which currently counts completed digests too.

### Task 2.6 — Age + urgency ordering on Attention

File: `src/pages/AttentionPage.tsx`.
Fix: sort the queue by severity then age; badge preflight-kind items whose
veto window expires soon; make the existing `ageLabel` visually prominent.

### Task 2.7 — Deep-linkable selection state

1. Preflight: put the selected digest in the URL (`/preflight/:digestId`) so a
   batch can be shared/bookmarked. Register the route in `src/app/router.tsx`.
2. Paused search: routes `/paused-search/active/:trackId` and
   `/paused-search/retired/:trackId` exist, but opening/closing tracks in
   `PausedSearchTrackStudio.tsx` never updates the URL. Sync selection to the
   route in both directions.

Phase 2 verification: targeted vitest for Preflight/Handoffs/ReviewQueue/
Attention/Leads routes, then `pnpm check`.

---

## Phase 3 — Safety ceremony and audit trail (mostly frontend)

Rule to apply everywhere: consequence-proportional confirmation, always with a
captured reason. The pattern already exists in the codebase — paused-search
publish (server preview + warning confirmation in
`src/components/paused-search/PausedSearchTrackStudio.tsx` ~lines 259–278) and
device revocation (`src/pages/UsersPage.tsx` ~lines 1023–1057).

### Task 3.1 — Add confirmation dialogs to consequential actions

| Action | File | Current state |
|---|---|---|
| Campaign publish / pause / resume | `src/pages/CampaignDetailPage.tsx` (~lines 275–317) | fires immediately on click |
| Dormant publish | `src/pages/DormantPage.tsx` (~lines 259–267) | fires immediately; no preview/diff |
| Paused-search retire | `PausedSearchTrackStudio.tsx` (~lines 397–401) | instant on icon click |
| Disable account / disable workspace access | `src/pages/UsersPage.tsx` (~lines 939–973) | one click, no confirm |
| Agent mapping unlink | `src/pages/AgentMappingPage.tsx` (~lines 583–595) | no confirm, no impact statement |
| Listing source disable | `src/pages/ListingSourcesPage.tsx` (~lines 1469–1474) | bare Switch |

For each: add a confirmation dialog stating the impact. For paused-search
retire, include the count of currently assigned leads (needs Task 0.3 item 2;
until then state that active cadences will stop). For mapping unlink, state
that lead ownership/handoff routing will lose this mapping.

### Task 3.2 — Replace hardcoded audit reasons with reason-required dialogs

Findings:
- `src/pages/CampaignDetailPage.tsx` (~lines 142, 161): pause/resume send
  `reason: 'Paused from campaign detail.'` — the audit log never captures why.
- `src/pages/NurtureSettingsPage.tsx` (~lines 227–261): pause/resume nurture
  fire immediately with hardcoded reasons.
Fix: prompt for a required reason in the confirmation dialog (mirror the
pattern in `LeadDetailPage.tsx`) and pass it to the mutation.

### Task 3.3 — Remove redundant double-confirmation on Lead detail

File: `src/pages/LeadDetailPage.tsx` (`getLeadActionConfirmationCopy` ~lines
3057–3101; `handleConfirmedLeadAction` ~lines 1000–1031).
Finding: for `override_timing`, `migrate_track`, `skip_next_touch`, and
`pause_workflow`, a generic confirm dialog opens whose confirm button only
opens the real dialog (which already requires a reason and has Cancel).
Fix: remove the pre-confirmation step; open the real reason-required dialog
directly.

### Task 3.4 — Distinguish Retire vs Delete in paused-search list

File: `src/components/paused-search/PausedSearchTrackList.tsx` (~lines 139,
163).
Finding: Retire and Delete both use the `Trash2` icon; icon-only actions with
different blast radii sit adjacent.
Fix: distinct icons + text labels or a labeled dropdown menu per row.

### Task 3.5 — SMS compliance state change becomes a confirmed action

File: `src/pages/NurtureSettingsPage.tsx` (~lines 1430–1448).
Finding: `sms_compliance_state` can be flipped to "Approved" via a bare select
with no evidence or confirmation — a compliance gap.
Fix now (frontend-only): confirmation dialog summarizing the consequence of
each state change. Later (after Task 0.3 item 7): capture evidence fields
(registration ID, approval date) in the same dialog.

### Task 3.6 — Replace `window.confirm` dirty-check in paused-search editor

File: `PausedSearchTrackStudio.tsx` (~line 159).
Fix: use the design-system dialog for the unsaved-changes confirmation,
consistent with the rest of the app.

Phase 3 verification: update all affected page tests for the new dialogs, then
`pnpm check`.

---

## Phase 4 — Show the data the API already returns (frontend-first)

### Task 4.1 — Campaign outcomes on the Campaigns list

File: `src/pages/CampaignsPage.tsx`.
Finding: the queue shows only configuration. The reporting API already returns
`enrollment_counts`, `workflow_counts`, `message_counts`, `handoff_counts`
(`CampaignOperationsSummaryResponse`, `src/lib/api/reporting.ts` ~lines 77–88).
Fix: add compact outcome metrics (sent / handoffs / enrolled) to each row and
to the drawer. Also: render WHY a campaign matched the "Review policy" saved
view (`matchesSavedView('review_policy')` ~lines 558–565) as explicit badges
(draft version / SMS compliance unverified / preflight disabled).

### Task 4.2 — Campaign detail: template content and derived rates

File: `src/pages/CampaignDetailPage.tsx`.
Findings:
- Cadence steps (~lines 441–470) show `template_key`, delay, max attempts but
  never the message content, although `prompt_text`, `sms_template`,
  `email_template`, and `template_profile` exist on `CampaignVersionResponse`
  (`src/lib/api/campaigns.ts` ~lines 33–75). Admins publish what they cannot read.
- Reporting panel (~lines 540–562) shows flat counts, no rates.
Fix: expandable template/prompt preview per cadence step; add delivered % and
handoff % to the reporting panel.

### Task 4.3 — Lead workspace: actionable columns

File: `src/pages/LeadWorkspacePage.tsx`.
Findings:
- No column sorting; no time-in-state; `next_action_at`
  (`LeadWorkflowResponse`, `src/lib/api/leads.ts` ~line 181) — when the AI acts
  next — is fetched but never displayed.
- `suppression_types` (`leads.ts` ~line 149) never rendered behind the
  `do_not_contact` badge (~line 863).
- Per-channel counts (`inbound_message_count`, `outbound_message_count`,
  `leads.ts` ~lines 313–317) collapse into one string, hiding one-way
  conversations.
Fix: add sortable "Last activity" and "Next action" columns; show
time-in-state; split inbound/outbound counts; show suppression types in the
safety cell/drawer.

### Task 4.4 — Lead detail: delivery outcomes on the timeline

File: `src/pages/LeadDetailPage.tsx` (timeline rendering ~lines 4529–4541).
Finding: `OutboundMessageResponse` carries `provider_send_status`,
`provider_delivery_status`, `delivered_at`, `failure_reason` (`leads.ts`
~lines 249–253) but the timeline shows none of it — agents cannot tell whether
an email delivered or bounced.
Fix: status chip (delivered / bounced / failed) with `failure_reason` on
outbound timeline entries.

### Task 4.5 — Agent mapping: surface disputed state and resolution audit

File: `src/pages/AgentMappingPage.tsx`.
Findings:
- `overridden_count`, `disputed_count`, `active_agents`, `inactive_agents`
  exist in the summary (`src/lib/api/workspaces.ts` ~lines 103–113) but only 4
  metrics render; "disputed" is the state admins most need.
- `resolved_by_user_id` / `resolved_at` (`workspaces.ts` ~lines 97–98) not
  shown on rows.
- No warning when two CRM agents map to the same app user.
Fix: add disputed/overridden metric cards, show resolver + resolved-at on
verified rows, add a duplicate-mapping warning badge.

### Task 4.6 — Shared UUID → name resolution

Affected: `CampaignDetailPage.tsx` audit actors (~line 603 `compactId`),
`CampaignsPage.tsx` drawer created-by (~line 535), `LeadDetailPage.tsx`
override audits (track version IDs ~lines 4204–4215) and routing review
history (`reviewed_by_user_id` dropped, ~lines 4229–4292),
`ListingSourcesPage.tsx` terms reviewer (never displayed),
`PreflightPage.tsx` veto actor (~lines 720–724).
Fix: one shared helper/hook that resolves user IDs via `getWorkspaceUsers` and
track version IDs via `listPausedSearchTracks`, applied across these pages.

### Task 4.7 — Listing sources: scopes and compliance visibility

File: `src/pages/ListingSourcesPage.tsx`.
Findings:
- Only the first 3 scopes render (`slice(0, 3)` ~line 1390) with no "+N more" —
  hidden paused scopes look healthy.
- Scopes cannot be edited or deleted; the update mutation sends only
  `{enabled}` (~lines 400–419) although `UpdateListingSearchScopeRequest`
  supports all fields.
- `requires_auth` toggle (~lines 770–779) has no credential flow behind it.
- Terms reviewer identity stored (~line 500) but never displayed.
Fix: show all scopes or "+N more" expander; add scope edit + delete; display
terms reviewer/date on the card; either hide `requires_auth` or mark it
"credentials not yet supported".

### Task 4.8 — Live navigation badges

Files: `src/components/layout/AppShell.tsx` (~lines 104–106),
`src/lib/navigation.ts` (badge model ~line 11).
Findings: the `'count'` badge type exists but is unused; Attention shows a
static always-on amber dot regardless of queue contents; Handoffs, Preflight,
Review queue show nothing.
Fix: light polling or reuse of existing queries to show live counts on
Attention, Handoffs, Preflight, Review queue; the Attention indicator must
disappear when the queue is empty.

### Task 4.9 — Users page: operational context

File: `src/pages/UsersPage.tsx`.
Fix: show invitation sent date + staleness flag in the Operational note
column; add a CRM-mapping indicator column (mapped/unmapped) linking to Agent
Mapping; surface extension-device `last_seen_at` (already shown in the manage
dialog ~line 1141) at the row level as "last active" proxy until a proper
last-login field exists.

Phase 4 verification: targeted vitest per page, then `pnpm check`.

---

## Phase 5 — Structural UX (frontend-only)

### Task 5.1 — Restructure Lead detail into navigable sections

File: `src/pages/LeadDetailPage.tsx` (~4,800 lines; reference panels ~lines
2974–3051).
Finding: one giant scroll — ~10 cards, 6 reference panels, ~12 dialogs; action
cards are buried two-thirds down; timelines render unbounded.
Fix: tabs or sticky section nav (Overview / Actions / Timelines / Audit);
collapse or "show more" pagination for `activity_log`,
`workflow_transitions`, `paused_search_history`. Consider extracting sections
into components while doing this (the file size alone is a maintenance risk).

### Task 5.2 — Nurture settings: dirty tracking + navigation + dead code

File: `src/pages/NurtureSettingsPage.tsx`.
Findings:
- Five independent save forms with 30+ `useState` hooks (~lines 76–138); Save
  buttons always enabled; no unsaved-changes protection on navigation.
- ~350 lines of dead legacy UI behind `legacyDormantSettingsShouldRender()`
  hardcoded to `false` (~lines 734–1168, 1885–1887), plus an Overview
  "Unsaved changes" indicator (~lines 449–455) tied to that dead draft state.
Fix: per-section dirty tracking (Save disabled when clean, badge when dirty);
navigation guard when any section is dirty; sticky anchor nav (Automation /
AI models / SMS / CRM sync / Handoff); delete the legacy block and the
misleading indicator.

### Task 5.3 — Dormant page hardening

File: `src/pages/DormantPage.tsx`.
Fix: dirty-navigation guard (`isDirty` exists ~line 226 but nothing blocks
route changes); replace free-text timezone input (~lines 384–392) with a
validated IANA select; persist the last selector-run result on the page
instead of a transient toast (~lines 179–182); warn when running the selector
while `preflight_digest_enabled` is off; replace bare-text loading states
(~lines 187–193) with `QueueState`/`Skeleton` patterns.

### Task 5.4 — Handoffs: acknowledge, aging, reassignment

Files: `src/pages/HandoffsPage.tsx`, `src/pages/HandoffDetailPage.tsx`.
Findings: `acknowledged_at` / `notified_at` exist (`handoffs.ts` ~lines 19–20)
but no acknowledge action exists anywhere; manager copy promises
"reassignment" (~line 251) but none exists; metric cards are volume-only with
warning tone whenever > 0 (~lines 216–237).
Fix (frontend-ready parts): badge unacknowledged rows; add an "oldest waiting"
aging metric; make tone thresholds meaningful. Acknowledge/reassign actions
land when the Task 0.3 item 5 endpoints exist — if they already exist, wire
them now. On the detail page, show recent conversation context (last N
messages) instead of only `latest_inbound_text` (~line 240) if a conversation
endpoint exists; refetch resume eligibility when the resume dialog opens; add
a retry affordance on eligibility error (~lines 390–394).

### Task 5.5 — Attention queue operability

File: `src/pages/AttentionPage.tsx`.
Fix: bulk "mark all filtered as seen"; render the queue even when the
acknowledgements query fails (treat all as unseen + warning banner) instead of
the all-or-nothing error (~lines 282–295); distinct empty-state copy for the
default "Unseen only" view ("All items reviewed — switch to All"); keep the
drawer open after marking seen (~lines 156–158). "Seen by {user} at {time}"
lands when Task 0.3 item 1 ships.

### Task 5.6 — Review queue operability

File: `src/pages/ReviewQueuePage.tsx`.
Fix: scope `pausedSearchReviewMutation.isPending` per row (~line 253) instead
of disabling all rows; add a status filter + decided-history view using the
existing `status` param of `listPausedSearchReviews`; expose the richer
`migrate` / `terminalize` resolutions for policy-kind reviews
(`pausedSearchOperations.ts` ~lines 195–199); make an error in the routing
query not hide the paused-search queue (independent loading states).

### Task 5.7 — Auth and shell polish

1. `src/pages/SignInPage.tsx`: gate the demo-credentials panel
   (`DEMO_EMAIL`/`DEMO_PASSWORD`, ~lines 19–20) behind an env flag
   (`import.meta.env`); map raw API `error.message` to friendly copy; add a
   "forgot password" affordance (link or "contact your admin" until a reset
   flow exists).
2. `src/components/layout/AppShell.tsx`: gate the hardcoded "Seeded demo
   preview" pill (~lines 300–302) behind the same env flag; surface sign-out
   failures with a toast (`handleSignOut` ~lines 163–170 currently swallows
   errors).
3. `src/lib/navigation.ts`: implement `defaultRouteForRole` (~lines 145–150,
   currently a stub returning `/`) — e.g., agents land on `/attention` or
   `/handoffs`.
4. `src/pages/CompleteInvitedSignupPage.tsx`: show password requirements
   inline; friendly error mapping; validate token on load + show invite
   context when the Task 0.3 item 6 endpoint exists.
5. `src/pages/NotFoundPage.tsx`: replace internal copy ("not part of the
   current review slice") with user-facing copy and add 2–3 recovery links
   (Home, Leads, Attention).
6. `src/pages/HomePage.tsx`: make attention-digest strings
   (`HomeAttentionDigest` ~lines 1249–1280) clickable deep links; link
   `OwnerWorkloadCard` rows (~lines 1564–1599) to filtered views; surface the
   computed-but-unrendered `leadAlerts` and `finished` inventory
   (`src/lib/helpers/adminHomeModel.ts` ~lines 120–122, 201–208); remove
   "demo workspace" wording from error copy (~line 403).

Phase 5 verification: targeted vitest per page, then `pnpm check`.

---

## Phase 6 — Scale and performance (backend-dependent)

Prerequisites: Task 0.3 items 4 and 8.

### Task 6.1 — Server-side pagination and sorting

Every list currently fetches the full dataset and filters client-side:
`getLeads` (used by `LeadWorkspacePage`, `HomePage`, `AttentionPage`),
`getHandoffs`, campaigns, users, agent mappings, attention synthesis
(`src/lib/helpers/adminAttentionItems.ts` runs 5 parallel full-list fetches,
~lines 51–66).
Fix: adopt pagination/sorting params as they land; move Home dashboard
aggregates to the reporting endpoint (`getWorkspaceOperationsReport`) instead
of client-side full-list computation (`adminHomeModel.ts` ~line 94).

**STATUS (2026-08-14): blocked on Task 0.3 item 4.** No pagination/sorting
`Query` params exist on any list route yet. The Home dashboard already sources
workflow/message/handoff/event counts from `getWorkspaceOperationsReport`; the
remaining client-side full-list computation (lead inventory `notEnrolled` /
`blocked` and needs-human alerts in `adminHomeModel.ts`) has no report-side
equivalent today, so it stays until the reporting endpoint grows those counts.

### Task 6.2 — Per-row mutation pending state (can be pulled earlier; frontend-only)

Global pending flags freeze whole tables during one row's save:
- `src/pages/AgentMappingPage.tsx` `isWritePending` (~lines 247, 425)
- `src/pages/ListingSourcesPage.tsx` `isUpdating` / `isScopeUpdating`
  (~lines 596–597)
- `src/pages/ReviewQueuePage.tsx` (~line 253) — covered by Task 5.6
- `PausedSearchTrackStudio.tsx` `pendingAction` (~lines 334–339)
Fix: key pending state by row/entity ID.

**DONE (2026-08-14).** Pending state is now keyed by entity ID via
`mutation.variables`: AgentMappingPage rows lock individually (`isRowSaving`
by `agent_record_id`; `isActionLocked` removed), ListingSourcesPage keys
source updates/crawl requests by `sourceId` and scope toggles by `scopeId`
(`pendingScopeId`), and PausedSearchTrackStudio passes `pendingTrackId`
instead of a catalog-wide `pendingAction` flag.

### Task 6.3 — Bulk actions on queues

When batch endpoints exist: bulk veto on preflight (with per-lead reasons or a
shared reason), bulk mark-seen on attention, bulk approve/reject on
paused-search reviews. Design each with an explicit confirmation summarizing
scope ("Mark 14 items as seen").

**STATUS (2026-08-14): blocked on Task 0.3 item 8** — no batch endpoints exist.

### Task 6.4 — Table virtualization

If pagination is deferred for any list, add row virtualization for the lead
workspace table and campaigns list as a stopgap.

**STATUS (2026-08-14): deferred.** No virtualization library is installed and
current seeded data volumes (~40 leads) render without measurable jank. Revisit
when a real workspace approaches hundreds of rows and Task 6.1 pagination has
not yet landed.

---

## Suggested execution order and sizing

| Phase | Content | Est. effort | Dependencies |
|---|---|---|---|
| 0 | Verify scoping, dead route, file API tickets | 0.5–1 day | none |
| 1 | Correctness bugs | 1–2 days | Phase 0 decisions |
| 2 | Links + urgency signals | 2–3 days | none |
| 3 | Confirmations + audit reasons | 2–3 days | none (retire count needs API) |
| 4 | Surface existing data | 3–4 days | none (mostly) |
| 5 | Structural UX | 3–5 days | some Task 0.4 endpoints |
| 6 | Scale | ongoing | backend pagination/batch APIs |

Phases 1–3 close every P0. Phases 2 and 3 can run in parallel with backend
ticket work from Phase 0. Phase 6 is gated on backend and real usage volume.

## Definition of done (per phase)

1. All tasks in the phase implemented; findings re-verified against the code.
2. Existing tests updated for changed behavior; targeted vitest suites pass.
3. `pnpm check` passes in the frontend repo (and `make check` in the backend
   repo if backend code was touched).
4. Any deviation or newly discovered issue recorded in this document under the
   relevant task.

