# Issue 11-A — Show CRM reassignment under the correct agent without waiting for sync

**Status: DRAFT — stakeholder and test-contract review required.**
This is the third proposed Jira description, not a published issue or permission to implement.
Approval to continue drafting does not approve implementation, data repair, or production release.

## 1. Business impact — read this first

**The promise:** When the platform successfully processes a CRM assignment update, the lead belongs
in the correct agent's queue on the next data fetch. It must not disappear between two agents while
we wait for another sync to finish the same job.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | CRM people updates save the CRM assignee but erase the application's resolved owner IDs. A reassigned lead can disappear from both agents' scoped queues; even an ordinary update can make ownership disappear temporarily. A later sync or pre-send refresh repairs it. |
| How long is the gap? | Incremental sync is configured for 300 seconds. That explains the roughly five-minute window; it is not a guaranteed recovery deadline during outages or delayed work. |
| What changes after deployment? | The people update resolves and saves the CRM assignee's application ownership together. For a valid A-to-B reassignment, the next fresh read removes the lead from A's scoped queue and includes it in B's. Lists, counts and lead detail agree. |
| What does “immediate” mean? | Correct after successful webhook processing and commit, on the next server-backed fetch. It does not mean before the CRM delivers the update, nor automatic repaint of an already-open browser. This ticket adds no live push, polling interval or cache-policy change. |
| What if the CRM agent cannot be mapped? | Apply the same existing mapping and manager-fallback rules as sync. Show the actual resolution/fallback status; do not guess an agent or silently keep the previous owner. An unmapped lead with no available fallback remains an ownership gap visible to authorized workspace operators. |
| Does reassignment pause or restart nurture, or notify the new agent? | **No new behavior.** Ownership-only reassignment already does not pause, restart, cancel messages or notify. Preserve that behavior and existing human controls; this is not an automation-control release. |
| Does this change the name used in messages? | Future drafting already uses the current CRM agent name. Preserve that behavior; do not rewrite existing drafts, sent messages or handoff history. |
| Why include history export? | Its optional CRM refresh has the same missing-resolution defect. It must not erase ownership immediately after the webhook fixes it. Preserve the export's permissions, deduplication and best-effort local fallback. |
| What remains unchanged? | Consent, reply holds, cadence timing, enrollment, manual controls and the existing responses to other CRM activity. Removing those activity-based holds is Issue 14's separate Class B release. |
| What are the limits? | This cannot create a missing CRM-to-user mapping, recover a webhook the platform never receives, or guarantee that different CRM snapshots arrive in source order. It projects the fetched snapshot using the existing workspace mapping rules; source freshness and browser refresh timing remain distinct. |

**Merging is not deployment.** All relevant API/worker writers must run the fix. Existing affected
leads need verified catch-up or an explicitly approved bounded repair; deployment alone is not proof
that their ownership was corrected. No historical replay or production data write is authorized here.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — assignment visibility and operator trust; confirm at publication |
| Source / delivery class | Production-state consistency Issue 11 / **Class A: ownership-projection repair** |
| Components | CRM people webhooks; single-lead CRM refresh used by history export; assignment resolution; owner-scoped reads |
| Repositories | miller-schackman-api; frontend regression verification in miller-schackman-web, with presentation fixes only if needed to satisfy the existing read contract |
| Sequence / prerequisites | Third draft after 16-A and 9-A. Integrate Issue 16-A's shared refresh-preservation contract and tests before release. Issue 9-A is earlier safety work, not a new dependency of the assignment resolver. |
| Not blocked by | Issue 14's tag-only automation-control release; no need to wait for or implement it here |
| Owners | Assign implementer, independent reviewer, release operator and workspace mapping administrator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; recheck the implementation branch |
| Closure boundary | Correct projection on supported refresh paths; not universal CRM ordering, mapping administration redesign or the full Issue 14 policy |

**Included:** every people-handler path that saves a fetched person; ownership resolution before
that save; the same repair in the single-lead refresh used by both history-export routes; existing
fallback/legacy-field handling; same-workspace list/count/detail correctness; duplicate/failure and
multi-person coverage; regression proof for full sync and pre-send refresh; bounded rollout guidance.

**Excluded:**
- Issue 14's tag removal/re-add lifecycle, dormancy tag writes, removal of human-activity holds and
  send-time recent-activity vetoes. Do not change activity detection to make a mixed update look like
  an ownership-only event. No pause/resume capability is removed by this ticket.
- New reassignment emails, notifications, handoffs or approvals; automatic transfer of an existing
  handoff's accountable human; rewriting queued message content or historical attribution.
- New mapping heuristics, role definitions, fallback-selection policy or cross-workspace identity
  matching. This does not make a disabled or unverified mapping valid.
- Issues 12/13's consent/fallback changes, Issue 17's dispatch/uncertain-send changes, and Issue 15's
  general exhausted-work dashboard. Do not shorten CRM sync/retry intervals as a substitute fix.
- Browser push infrastructure, generic refresh frameworks, bulk historical webhook replay, and a
  general source-version ordering system. Any independently discovered gap needs explicit scope.

**D7 rule:** Class A and Class B must not share a PR. The main plan's business-impact appendix
explicitly classifies Issue 11's remaining mapping defect as A. Older groupings with Issue 14 do not
authorize shipping that policy here.

## 3. Current behavior and business contract

### What the code does today

The people handler fetches the resource, maps each person and preserves app-owned paused-search
fields before upserting. The mapper supplies the CRM agent ID/name, not resolved application IDs.
It does not run the shared assignment resolver. SQL upsert can therefore replace existing owner IDs
with nulls. This occurs before the handler's optional activity/enrollment work and is not limited to
actual reassignments. A returned “ignored/no actionable resources” result does not mean no lead was saved.

Full sync and pre-send refresh already resolve ownership. The single-lead refresh used for history
export does not; it can recreate the same gap. The shared resolver also removes the legacy
mapped_custom_fields assignment ID from refreshed records, preventing stale fallback ownership.

Agent-scoped SQL uses effective_owner_user_id, then assigned_agent_user_id, then the legacy mapped
assignment field. Application access checks follow the same precedence. The CRM-assignee label alone
therefore cannot prove that the right person can see the lead. Frontend queries have a 30-second
stale-time setting, not a guarantee of a fetch every 30 seconds.

### Contract to approve before writing tests

1. **Resolve before saving, not afterward.** For a usable fetched CRM snapshot, persist its CRM
   assignee and complete assignment decision together: assigned agent ID, effective owner ID/source,
   resolution status and resolution timestamp. Reuse the existing resolver. No committed interim
   record may contain the new assignee with owner IDs erased merely because resolution was skipped.
   This is required even without a workflow, matching campaign tag, classification or enrollment.
2. **Ownership is derived, not blindly preserved.** Recompute from that snapshot and the current
   workspace context. Keeping A's IDs when the CRM now names B is not a fix. Preserve stable lead
   identity and Issue 16's app-owned consent/evidence and paused-search data separately.
3. **Keep existing mapping/fallback semantics.** Trust VERIFIED and OVERRIDDEN mappings only;
   preserve CRM-agent activity, active user/membership, eligible role and ambiguity rules. Use the
   configured active MANAGER fallback, otherwise the existing active-manager choice: earliest
   membership creation time, with user ID as the tie-breaker.
   Distinguish a genuinely unmapped/inactive/ambiguous assignment from failure to read the context.
   Do not erase useful diagnostic assignment information or claim every non-resolved decision has
   identical fields: existing fallback-missing decisions can retain an assigned-user reference.
4. **Handle legacy fields consistently.** Resolved refreshes use the shared resolver's removal of
   the legacy assigned_agent_user_id custom field. Do not let a stale custom value give A access
   after a valid reassignment to B, or fabricate an owner for an unmapped lead with no fallback.
   Preserve current compatibility for untouched legacy-only records; no global cleanup is included.
5. **Use one workspace context per people batch.** Load the assignment context once for the
   fetched multi-person event, then apply it to every valid person. Avoid repeating workspace/user
   scans per person or introducing a process-global cache. Later events must observe later mapping
   changes. This does not claim linearizable mapping-admin changes in the middle of one batch.
6. **Failure must not masquerade as a valid unresolved decision.** If CRM/context reads fail, do
   not commit a raw mapped lead that wipes ownership and call it success. Preserve previously
   committed coherent state; use the existing failure/retry machinery with safe diagnostic metadata.
   After recovery, the supported retry must be able to apply the projection. Keep retry budgets and
   permanent/missing-resource handling unchanged; adding general exhaustion UI is not this slice.
7. **Close the export bypass too.** Whenever the history-export single-lead refresh actually runs,
   apply the same assignment decision before saving, whether enrollment dependencies are present or
   absent. CRM refresh remains best-effort: when unavailable, use the previously stored lead under
   existing route permissions; do not claim it was refreshed. A known lead must not be damaged by
   a refresh-context failure. If there is no usable CRM or local lead, retain existing not-found/error
   behavior. Optional enrollment failure must not discard an already valid refreshed lead.
8. **Fresh reads enforce the saved ownership.** After commit, A/B list and count queries, authorized
   lead detail and ownership labels agree. ASSIGNED_AGENT remains owner-scoped; MANAGER,
   BROKERAGE_ADMIN and authorized PLATFORM_SUPER_ADMIN retain existing workspace access. Active
   membership and tenant checks remain intact. A cached screen is not permission for a subsequent
   server request, and a manager's wider view is not proof of agent-specific access.
9. **Preserve workflow behavior.** With only ownership changed, create no pause/resume instruction,
   workflow transition, message cancellation, notification, new enrollment or provider send. Existing
   manual/review/reply holds, handoffs and terminal workflows remain intact. Keep existing
   reconciliation/audit/outbox conventions on paths that use them; do not publish directly to a broker.
   Mixed stage/tag/contact-activity changes retain their baseline consequences until Issue 14 ships.
10. **Retries and other writers must not recreate the null-owner gap.** Duplicate delivery must not
    duplicate business effects. A later sync, pre-send refresh or export processing the same CRM
    assignment must agree on the ownership tuple, although observation/resolution timestamps may
    advance. A delayed notification still fetches its resource; do not treat envelope age as an
    instruction to restore an old owner.

**Concurrency boundary:** validate committed projection consistency using independent database
sessions and overlapping writers processing the same current CRM snapshot. No intermediate snapshot
saved before assignment resolution has run may become visible; a genuine non-RESOLVED decision is
different and remains valid under the existing rules. This is not a promise to order different stale CRM
snapshots, or concurrent mapping-admin edits, across all writers. Record any such discovered gap and
its follow-up explicitly; do not claim universal “latest owner wins” without separate evidence/design.

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Use synthetic agents/leads, fixed clocks and literal
expected ownership. Read through real owner-scoped APIs/repositories, not only a fake's saved object.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A owns a lead. Process a peopleUpdated resource assigning it to active, verified B; commit, then read as A and B without running sync or pre-send refresh. | Same lead ID; B is assigned/effective owner with CRM_MAPPING and RESOLVED. B's list/count/detail include it; A's scoped list/count exclude it and direct detail is denied under existing authorization. | Both agents lose the lead, both retain scoped access, only the CRM label changes, or a later sync is required. |
| AC-02 | Keep the assignee unchanged and refresh ordinary person data. Parameterize the supported people event types that save a usable person, including an ownership-only event with no actionable enrollment. | Owner IDs/status stay coherent while legitimate CRM fields update. Projection does not depend on a “processed” activity/enrollment result. | A non-reassignment update clears ownership, or fixing only peopleUpdated leaves other saving paths destructive. |
| AC-03 | Fetch a valid newly seen person assigned to B, without a workflow or matching enrollment tag. | Create one canonical lead with correct ownership on first save; B can read it. No fake workflow is needed for visibility. | Owner resolution waits for campaign/classification work or creates an enrollment merely to display the lead. |
| AC-04 | With an eligible manager fallback, parameterize absent CRM assignee, missing/unverified mapping, inactive CRM agent, inactive app user/membership and ambiguous mapping. Exercise configured fallback and the existing default-manager selection. | Literal expected status and owner/source match the existing rules. Valid VERIFIED and OVERRIDDEN mapped-agent controls remain assigned directly, not routed to a manager. | New mapping heuristics, inactive recipients chosen as fallback, changed selection policy, or every lead routed to a manager. |
| AC-05 | An unmapped CRM assignee has no eligible fallback; the snapshot contains a stale legacy custom assignment to A. Also test an untouched legacy-only record. | Refreshed lead has FALLBACK_MANAGER_MISSING, no fabricated owner and no legacy access for A; authorized operators can find its ownership gap. Untouched legacy compatibility remains. | Guessing an owner, preserving stale A access, hiding the gap from operators, or globally deleting compatibility. |
| AC-06 | Fix a mapping between two separate people events; also change mapping eligibility between events. | The next event uses newly loaded context and updates ownership/status under existing rules, without waiting for full sync. | A process-global context cache keeps stale assignments or resolution silently ignores changed membership. |
| AC-07 | Replay a completed webhook; separately deliver an older notification whose CRM fetch returns today's B assignment. Follow with a same-assignment sync. | One canonical lead, correct B ownership and no duplicate business side effects; no owner flapping. Same-owner sync may advance timestamps without a new ownership change. | Duplicate notifications/transitions, old envelope metadata restoring A, or an assertion requiring all timestamps to remain frozen. |
| AC-08 | A single resource returns several valid people with different mappings and one invalid/missing person ID. | Each valid person resolves correctly in the workspace; invalid entry keeps existing ignore behavior. Assignment context is loaded once for the batch, with user lookups shared rather than repeated per person. | Context loaded for every person, one person's assignment reused for others, or invalid input mutating an unrelated lead. |
| AC-09 | Fail CRM fetch, then context loading, then a projection write; inspect fresh committed reads and recover via the existing supported retry. Include a known missing resource. | No partially mapped ownership is committed; failure is recorded honestly, retry can converge, and existing permanent/missing-resource behavior remains. Previously committed coherent records remain usable. | A context error treated as “unmapped”, successful raw upsert after failure, changed retry policy, or a fake-only rollback claim. |
| AC-10 | Run both authorized history-export routes with a valid fresh reassignment, a newly seen mapped lead and a same-owner refresh. Repeat without enrollment dependencies, then with raised and returned enrollment failures. | Successful refreshes resolve before saving; imported history/lead identity and batch deduplication remain correct. Optional enrollment failure does not erase a valid projection. | Export nulls the webhook's owner IDs, resolver runs only when enrollment is enabled, or import permissions silently change. |
| AC-11 | Export an existing lead when refresh is absent, CRM fetch fails or assignment context cannot be read; separately export a lead unavailable locally and in CRM. | Existing local fallback/not-found contract remains; known ownership is not damaged and failure is not reported as successful refresh. | Export outage caused solely by optional refresh, a raw unmapped save, invented owner, or false fresh-data claim. |
| AC-12 | Interleave webhook with sync, pre-send refresh and history-export writes using the same current B snapshot; observe after commits from independent sessions. | All persisted snapshots contain the coherent B decision and stable lead identity; no null/old owner introduced by a bypass. Record the distinct-source ordering limitation in §3. | An intermediate null-owner commit, a later raw writer undoing projection, or claiming global source ordering from same-snapshot tests. |
| AC-13 | Refresh a lead with a recorded opt-out/DNC and evidence, an active paused-search profile, and an unresolved-reply/manual hold. Include overlap with Issue 16's suppression write. | Correct owner projection without losing any applicable consent/evidence, paused-search fields or independent guard; affected prohibited sends still make zero recording-provider calls. | “Preserve ownership” replaces real reassignment, or the resolver/merge order undoes the earlier safety fixes. |
| AC-14 | Use ownership-only reassignment on active nurture, paused, handoff/human-owned and terminal leads. Separately exercise an otherwise permitted due message after projection. | No new workflow transition, signal, cancellation, notification, enrollment or provider call from reassignment itself. A later permitted touch still works on its existing schedule; held/terminal cases stay protected. | Reassignment starts/resumes/pauses nurture, sends an announcement, rewrites a queued message, or blocks every otherwise healthy lead. |
| AC-15 | Combine reassignment with a stage/tag/contact-activity change; read as authorized workspace roles, unrelated agent, inactive member and another workspace. | Ownership still projects; other activity consequences and all role/tenant rules retain baseline behavior. Distinguish fallback assignment from manager-wide visibility. | Removing existing activity holds inside this A fix, cross-tenant access, new agent permissions, or treating a mixed event as ownership-only. |
| AC-16 | After the committed A-to-B update, explicitly refetch/reload the agent lead list and detail using real API responses; retain one unchanged-owner control. | B's queue/count and ownership labels agree; A no longer receives the lead on fresh requests. Existing empty/loading/error behavior is retained. | Static frontend fixtures accepted as end-to-end proof, faster sync/cache changes hiding the backend defect, or a promise of unbuilt live browser push. |

AC-04 uses an available fallback to exercise existing failure statuses. AC-05 deliberately uses no
trusted mapped user. Other fallback-missing combinations must retain the existing resolver's actual
field semantics; do not silently redesign them to fit a blanket “all IDs must be null” assertion.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — approve before implementation:**
- **Ingestion → ownership read:** actual people handler and public webhook route with a recording
  CRM transport; real mapping/resolution and owner-scoped list/count/detail APIs. Include commit
  and fresh reads. An assertion that the resolver was called is not sufficient (AC-01–09/15).
- **Single-lead refresh/export:** both existing export entry points, real refresh/resolution and
  import orchestration; successful, local-fallback and unknown-lead cases (AC-10–11).
- **Persistence:** local/disposable real Postgres for upsert, legacy-field cleanup, rollback,
  restart/fresh-session reads and controlled overlapping writes. Include genuine owner-filter SQL;
  fake-session SQL strings or in-memory filtering do not prove these claims (AC-01/05/09/12–13).
- **Existing product flows:** full sync, pre-send refresh, human-activity processing and a due-send
  positive control with recording transports. Inspect workflow/signals/messages and protected
  data, not merely handler return values (AC-07/12–15).
- **Frontend/read experience:** existing role-aware route tests plus a synthetic integrated
  API-to-UI refetch demonstration. No live-push requirement (AC-16).

**Allowed fakes:** external CRM/LLM/provider/notification transports, fixed clocks, and hand-written
repository fakes for fast application cases. Do not mock the resolver, authorization decision or
owner-filter SQL in the tests that claim those behaviors. Supply literal expected users/statuses;
do not generate the expected result by calling the production resolver again.

1. Approve one acceptance scenario and its boundary. Add one behavioral test and run against
   unchanged application code; record the actual business-assertion failure, then implement the
   smallest fix and rerun that same test. Continue one scenario at a time, not all code then tests.
2. Minimal interface/no-op scaffolding may make a new boundary runnable, but record it separately.
   Import errors, failed fixtures, missing database, empty selection or skips are not meaningful red.
3. Baseline controls can pass immediately. If one shared fix makes another defect case pass,
   demonstrate sensitivity against baseline or an isolated mutation rather than inventing a red.
4. Disable resolution separately on the people and export paths; preserve-old-owner instead of
   recomputing; retain the stale legacy assignment. Each relevant test must fail for the intended
   business reason. Restore the implementation and rerun; no test mutation belongs in the PR.
5. Review expectation changes independently. Keep positive controls for an unchanged assignment,
   a valid reassignment, an existing fallback and an otherwise permitted send. “All green” is not
   enough if the suite works by hiding all leads or stopping all outreach.

| AC / parameterized case | Actual test + command | Baseline revision + meaningful red | Fix revision + green | Sensitivity / existing control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each row | Exact reproducible invocation | Business assertion, not setup error | Exit code and pass/fail/skip counts | Observed failure when protection is removed, or justified control | Explicit remaining limitation |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are repository-relative at the reviewed baseline; retrace callers before editing. Keep
provider mapping/SQL in adapters and business resolution in the existing domain/application layer.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — people processing and dispatch | app/infrastructure/crm/follow_up_boss/webhook_event_people.py; app/infrastructure/crm/follow_up_boss/webhook_event_handler.py |
| API — webhook dependency wiring | app/application/ports/crm_webhook.py; app/interfaces/api/dependencies/follow_up_boss_webhook.py; app/interfaces/workers/crm_webhook_retry_worker.py |
| API — shared assignment decision | app/application/services/lead_assignment_resolution.py; app/domain/lead_assignment.py |
| API — single-lead refresh/export | app/application/services/crm_lead_refresh.py; app/interfaces/api/v1/crm_history_imports.py; app/interfaces/api/dependencies/crm_history_imports.py |
| API — working resolver callers | app/application/use_cases/crm_sync.py; app/application/services/pre_send_crm_refresh.py |
| API — persistence and reads | app/infrastructure/persistence/postgres/lead_repository.py; app/application/use_cases/lead_read.py; app/interfaces/api/v1/leads.py |
| API — protected behavior | app/domain/leads/canonical.py; app/application/use_cases/reconcile_lead_assignment.py; app/application/use_cases/process_crm_human_activity_event.py |
| Web — ownership/read regression | src/app/LeadsRoutes.test.tsx; src/app/providers.tsx |

**Simplest sufficient design:** pass the existing workspace assignment context/resolver to the two
missing refresh paths, using their normal composition roots. Compare explicit orchestration at
those paths with a small shared refresh helper; explain maintenance/latency trade-offs and obtain
the required design approval. Do not create another mapping algorithm, an ownership table, a generic
event framework or dependency without evidence it is necessary. Optional dependencies must not
silently turn an enabled production refresh into the old unsafe raw save.

Review all commit points, including enrollment callbacks and the export route's best-effort path.
Resolve before any save that may commit. A failure handler that records a retry without undoing a
partial destructive save is not sufficient. Reuse Issue 16's persistence safeguards; do not hold
database locks over CRM/LLM calls or change consent logic to simplify this repair.

**Existing test starting points, not claimed new coverage:**
- tests/domain/test_lead_assignment.py
- tests/infrastructure/crm/test_follow_up_boss_webhook_event_handler.py
- tests/application/use_cases/test_crm_sync.py
- tests/application/use_cases/test_reconcile_lead_assignment.py
- tests/application/use_cases/test_process_crm_human_activity_event.py
- tests/application/use_cases/test_lead_read.py
- tests/application/use_cases/test_send_outbound_message.py
- tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_lead_repository.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- tests/interfaces/api/v1/test_webhooks.py; tests/interfaces/api/v1/test_leads.py
- tests/interfaces/api/v1/test_crm_history_imports.py
- Web: src/app/LeadsRoutes.test.tsx

Use Python 3.12/uv: run one exact pytest node, its file, related suites, then make lint, make typecheck
and make test. Record actual commands and test counts. Run relevant frontend Vitest route tests;
if frontend code changes, also run pnpm test, pnpm typecheck and pnpm lint. Verify integration targets
are local/disposable. Skipped Postgres tests are missing evidence, not a pass. No real-lead sends.

## 7. Existing affected records and recovery boundary

- Provide a bounded workspace inventory/runbook distinguishing owner IDs erased by refresh from
  genuinely unmapped agents, inactive users, missing fallback, and untouched legacy records. A null
  effective owner alone is not proof of the defect or authority to assign someone.
- Verify whether ordinary post-release sync has corrected affected records by fresh owner-scoped
  reads and resolution status, not by a “sync succeeded” banner or by waiting five minutes. A
  timestamp alone is insufficient. Record exclusions and remaining mapping-admin actions.
- Do not blindly replay people webhooks or invoke full sync as a purported ownership-only repair:
  those paths also process activity, history and enrollment. Any manually triggered catch-up needs
  an explicit scope and side-effect review. Natural scheduled processing retains existing behavior.
- If catch-up is insufficient, obtain approval for a bounded ownership-only repair using the same
  resolver and trustworthy current CRM/mapping facts. No such command is claimed to exist. A new
  repair capability requires its own reviewed test-first boundary, dry-run, idempotency and tenant
  tests before execution. Do not guess historical ownership or rewrite handoff/message attribution.
- This ticket delivers the runbook, not automatic historical mutation. Production repair requires
  named environment/workspace/lead scope, operator, commands and verification. Do not declare live
  acceptance complete with affected records neither corrected nor covered by an explicit containment
  plan and named operator follow-up. Assigning follow-up work is not permission to invent a lead owner.

## 8. Production rollout, acceptance and rollback

1. **Before release:** assign the operator; approve the next-fetch contract and unchanged automation
   policy. Confirm Issue 16 integration and identify all API/worker versions capable of snapshot
   writes, including webhook retry and history-export entry points.
2. **Rehearse in a safe environment:** synthetic A-to-B reassignment, ordinary update, unmapped
   fallback, missing fallback, export refresh, context failure/retry and a fresh role-scoped UI read.
   Use sink/sandbox transports and real persistence; show an otherwise permitted touch still works.
3. **Deploy all affected writers:** record rollout order. Mixed versions can still erase owner IDs;
   do not call the fix live while an old writer remains capable of doing so. A deployment must not
   bulk enroll, resume or replay leads. Any justified migration needs compatible rollback planning.
4. **Verify existing records separately:** run the approved inventory/verification procedure and
   record corrected, genuine-mapping-gap and unresolved counts. Authorize any manual repair as §7
   requires; closing a review ticket does not authorize it.
5. **Accept the user journey:** demonstrate B's list/count/detail after commit without intervening
   sync, A's fresh-request denial, fallback visibility, unchanged nurture controls and export parity.
   Explain that this release neither pushes a browser update nor emails the new agent.
6. **Observe:** use safe metadata to track refresh/context failures, unexplained owner-ID loss,
   resolution/fallback counts and receipt-to-commit timing. Separate CRM delivery and UI-fetch
   delays from projection latency. Do not log raw CRM payloads, contact details or credentials.

**Rollback:** contain affected snapshot writers before reverting to a version that erases ownership;
coordinate any wider pause with the release owner. Preserve known correct ownership, consent and
audit data. Do not restore guessed old owners, clear holds or replay workflows as a rollback shortcut.
Document actual commands and remaining visibility limitations; production rollback requires approval.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4, including fallback semantics, next-fetch timing, unchanged activity
      behavior, export parity and the source-ordering limitation.
- [ ] Issue 16 shared-state contract verified; implementer/reviewer and baseline recorded.
- [ ] Reviewer approves §5 test boundaries and first meaningful failing reassignment scenario.
- [ ] Smallest complete dependency/transaction design approved; no silent resolver bypass.

### Ready to merge
- [ ] Every acceptance ID and relevant event/export variant maps to actual checks with meaningful
      red/green and sensitivity evidence, not mocked-success screenshots or resolver-call assertions.
- [ ] Real Postgres proves committed ownership, legacy cleanup, rollback and scoped list/count/detail;
      integration skips are recorded as gaps. Relevant backend and frontend regression checks pass.
- [ ] Full sync/pre-send/export/webhook agree on ownership; Issue 16's restrictions and independent
      holds survive. No Class B policy, new notification or workflow-control behavior slipped in.
- [ ] Role/tenant isolation and no-campaign/new-lead cases pass; no new ownership source of truth.
- [ ] Runbook names the operator, exact verification/rollout/rollback steps, unresolved limitations
      and any separately scoped historical repair; no unbuilt command is advertised as available.

### Production acceptance complete — not merely merged
- [ ] Required writer versions deployed; no remaining old path can reproduce the ownership erasure.
- [ ] Synthetic end-to-end reassignment and export/read demonstrations recorded without real sends.
- [ ] Existing affected records corrected or covered by explicit containment and named operator
      follow-up, with approved mapping actions and no unapproved replay, guessed owner or data repair.
- [ ] Stakeholder accepts the next-fetch behavior and unchanged automation policy; Issue 14 remains
      a separately signed-off release, not marked delivered by this ticket.

**Evidence status at drafting:** code/source trace and document validation only. No application
implementation, new behavioral tests, runtime pass, Jira publication, deployment or data operation.

## 10. References and decision precedence

- [Issue 16-A — shared preservation prerequisite](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — earlier inbound-safety work](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Source Issue 11 and the business-impact/readiness appendix](../production-state-consistency-issues.md)
- [Consensus — D7 release boundary](../production-state-consistency-review-consensus.md)
- Parent workspace AGENTS.md / CLAUDE.md: product, ownership, layering and design-approval rules.

The source plan describes the wider target; this draft defines the proposed executable A slice.
Escalate newly discovered product conflicts or broader ordering defects explicitly. Do not change
expected outcomes to fit an implementation, or treat a draft's existence as release authorization.