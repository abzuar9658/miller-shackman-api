# Issue 4-A — Keep enough automation history to investigate an incident

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the eleventh proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not approve production access, retention changes, data repair or release.

## 1. Business impact — read this first

**The promise:** An authorized operator investigating last week's incident can find the relevant
lead/run and explain the recorded reason for contact, deferral or a hold. Important business
evidence survives independently of the automation engine's history, for an explicitly agreed period.
When evidence is incomplete, say so; do not turn a missing record into a confident explanation.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | The source investigation reports closed engine history disappearing after 24 hours. Application records preserve some decisions, but not every important reason or a complete accessible history across runs. |
| Why does that matter? | Agents often notice problems days later. Support cannot reliably explain why a lead was not contacted, distinguish a deliberate delay from a failure, or establish what the provider actually reported. |
| What changes? | Explicit multi-week engine retention, durable application decision evidence and an authorized route to older records. A later status update must not erase the earlier reason. |
| Does the current deployment definitely still use 24 hours? | Not established by this draft. That is the original incident finding; the live namespace must be inspected at R1. A checked-in image or bootstrap default is not the deployed setting. |
| How long will records remain? | R1 must approve exact, finite engine and application retention periods, their clock origins, privacy rules and storage budgets. “Weeks” is the requirement, not an approved number of days or indefinite storage. |
| Can support still investigate without Temporal? | Yes, within the approved application-evidence window: business reason, time, affected run/touch and known outcome are readable without engine access. Low-level stack traces and a full engine replay are not promised by application history. |
| Does “sent” prove delivery? | No. Planned, permitted, dispatch requested, provider accepted, delivery reported and uncertain are distinct facts. No record is proof of a customer's receipt unless the evidence supports that narrower claim. |
| Does this repair stalled leads? | No. This ticket preserves and exposes the explanation. Scheduling/send-time hold recovery, missing-engine recovery and completion behavior remain in their own tickets. |
| Can yesterday's expired history come back? | Not from increasing retention. Already-closed executions retain their original cleanup timers; already-deleted evidence is recoverable only if a usable retained copy actually exists. Otherwise the gap remains explicit. |
| Why not just use backups? | Backups support recovery, not routine scoped investigation. A backup object existing does not prove that the needed execution is present, readable or safe to restore. |
| What is the cost? | More storage, backup volume and operational responsibility. Minimize retained content, bound queries and monitor growth; do not solve capacity pressure by silently sampling required decisions. |
| Is outreach policy changing? | No. Contact eligibility, cadence timing, consent, agent controls and the separately released uncertainty/CRM rules stay unchanged. A history read never sends, resumes or replays a journey. |

**Retained but inaccessible is not enough.** A record beyond the first 100 results, or attached to
an older workflow for the same lead, must remain discoverable through the supported investigation
path. Conversely, a complete-looking timeline must not hide expired, unrecorded or unreadable data.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — insufficient incident evidence; confirm at publication |
| Source / delivery class | Production-state consistency Issue 4 / **Class A: retained operational evidence** |
| Components | Temporal retention operations; application decision/audit persistence; scoped lead/run history reads; support verification and retention runbook |
| Repositories | miller-schackman-api and miller-schackman-web, plus the actual deployment's approved operational configuration |
| Sequence | Eleventh draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A and 3-A. Draft order does not establish that predecessors shipped. |
| Integration dependencies | Declare the integrated baseline. Reuse 1-A hold evidence, 2-A instruction identity, 3-A enrollment lineage and 17-A send identity/commit guarantees where available; do not build competing records for the same fact. |
| Boundary with later repairs | Issues 5/6/7/8/10/15 own their respective hold, recovery, completion or exhausted-work behavior. This ticket records existing decisions; it does not implement those lifecycle changes. |
| Not a prerequisite | Shipping 13-B, 14-B or 17-B. Preserve a B policy already separately released, but do not import an unshipped policy here. |
| Decision ownership | Name implementer, independent reviewer, infrastructure/retention operator, evidence/persistence owner, privacy/security approver, API/web owner and release owner. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No live namespace, production database or backup was inspected for this draft; retrace the implementation branch. |
| Closure boundary | Multi-week engine retention verified operationally, retained business evidence independent of it, and a complete authorized investigation journey with honest historical limits. A config-only patch is partial delivery. |

**Included:** important planning/scheduling/send decisions across the existing standard cadence,
paused-search, AI continuation and operator send/approval routes; existing workflow/override and
provider-outcome evidence needed to interpret those decisions; older-run retrieval and retention
operations. Inventory the actual producer coverage at R2 rather than assuming every path uses one helper.

**Excluded:**
- New consent/fallback, tag-only CRM control, uncertain-as-sent, notification timing, completion or
  re-entry policy. **D7: Class A and Class B must not share a PR.**
- Automatically fixing, resuming, resending or bulk-replaying historical work; broad incident
  dashboards, new notification infrastructure, general log aggregation or a generic event-sourcing platform.
- Retaining every prompt, message body, provider payload or stack trace indefinitely; a new legal
  compliance certification or tamper-proof/WORM guarantee from an ordinary append-only repository.
- A Temporal service migration, custom archiver or new external dependency without separate design
  and operational approval. Archival is an optional evaluated approach, not a presumed working feature.
- Editing the previous ten ticket drafts or treating their unresolved gates as closed.

## 3. Current behavior and contract to approve

### 3.1 What is established, and what still needs live evidence

The source Issue 4 reports 24-hour production retention and missing early executions during its
investigation. This draft preserves that incident attribution; it does not claim to have remeasured
the current deployment. The checked-in compose.prod.yaml uses temporalio/auto-setup:1.27.2 without
an explicit namespace-retention or archival policy. The traced Temporal client connection does not
pass a namespace. Neither fact establishes the effective namespace configuration in production.
R1 must identify the actual service/namespace used by starters, workers and signal dispatchers.

Temporal's current documentation defines retention for **closed Workflow Executions**. Updating a
namespace's retention affects executions that close after the update; already-closed executions
keep their existing cleanup timers. Open workflows and long-running run chains require separate
capacity consideration. A visibility listing, a task queue and detailed execution history are not
interchangeable evidence; identify the exact namespace, workflow ID and run ID for inspection.

| Traced application boundary | Existing evidence / precise gap |
| --- | --- |
| Workflow transitions | PostgresWorkflowTransitionRepository.append inserts a transition. State-transition paths already retain reasons/metadata, independently of Temporal. Preserve and reuse this evidence. |
| Cadence planning/send blocks | campaign_cadence_execution builds planning/send block metadata, including pre-send reasons and next-allowed time, and passes it into pause transitions on the applicable branches. It is incorrect to claim all blocked-send reasons are transient. |
| Non-terminal paused-search scheduling holds | schedule_next_paused_search_action returns reason_code/reason_detail. Its non-terminal _save_hold clears the step and next_action_at without appending that reason; other terminal branches do use transitions. 1-A owns the lifecycle repair. |
| Timing-only deferral | _defer_after_timing_block preserves the active journey and reschedules. It may annotate a pending message's status_detail; later successful send paths clear that field. The current snapshot is not a durable sequence of earlier deferral decisions. |
| Send/dispatch outcomes | send_outbound_message returns a pre-send verdict; callers determine whether it reaches history. The dispatcher persists request/message/reconciliation outcomes, but later saves replace failure/status fields. A final row or attempt count alone is not a complete decision/attempt journal. |
| Paused-search send wiring | At this baseline, execute_campaign_cadence_step passes None for the send-request, reconciliation and provider-failure repositories and workflow identifiers on paused-search steps. Do not assume dispatcher coverage reaches this route. Retrace the integrated 17-A baseline; dispatch durability stays owned by 17-A. |
| Lead history read | get_lead_detail_view requests transitions only for latest_workflow. list_for_workflow defaults to 100 rows ordered by created_at descending, without a continuation contract. The cap is in the repository read, not a frontend-only slice. |
| Web history | LeadDetailPage builds its workflow timeline from the returned transitions. Existing history/override panels are useful starting points, but cannot reveal an older run or row that the API did not return. |

The infrastructure plan describes nightly application/Temporal database backups and a 35-day
backup lifecycle. That is a plan, not verification that jobs or restores work in the live system,
and not approval for the operational history window. Backup retention and namespace retention have
different jobs. Do not restore a whole production database merely to investigate one lead.

### 3.2 Make retention explicit and verifiable

1. Approve exact engine and application-evidence durations, units and clock origins at R1. Engine
   history must cover the agreed multi-week support horizon; application evidence must independently
   cover its agreed investigation horizon, even when engine history is unavailable. Define treatment
   of open/long-running journeys, run chains, delayed recording and later corrections.
2. Inspect only approved non-sensitive namespace metadata. Record target environment/service,
   namespace, server/CLI versions, effective retention and relevant archival/read settings before
   and after the authorized change. Do not dump credentials, environment files or raw workflow payloads.
3. Establish a reproducible policy for both fresh provisioning and **existing namespaces**. Merely
   changing an auto-setup default may leave an existing namespace untouched. Reapplying configuration
   must not recreate the namespace, delete history or silently shorten a longer approved window.
4. Distinguish configured, applied and observed. Retain a synthetic closed execution's exact identity
   and close time, inspect its detailed history beyond 24 hours, and collect evidence representative
   of the approved multi-week window. A workflow still open after a day does not prove closed-history
   retention; changing the application clock does not advance the real server's cleanup timer.
5. Inventory pre-change closed executions still under their old timers. If needed, separately approve
   preservation of available evidence before expiry, with a tested secure retrieval route. Increasing
   retention alone is not that preservation mechanism and cannot restore an already-purged run.
6. Prefer the smallest supported solution. Optional archival needs exact-runtime compatibility,
   service and namespace configuration, read support, access/deletion rules and an actual retrieval
   test. Current Temporal documentation calls archival experimental and says it is not supported
   when running Temporal through Docker; this compose deployment must not assume an S3 flag solves it.
   Resolve that limitation against the deployed version or defer archival. The app's storage bucket
   is not automatically a Temporal archive.
7. Assign drift checks, storage/query budgets, backup/restore responsibilities and failure handling.
   Keep evidence readable after worker restart and during an engine outage through application
   storage. Do not silently drop required events, shorten retention or expose a private engine UI
   to ordinary agents as an emergency workaround.

### 3.3 Preserve a useful decision record, not a second workflow engine

Reuse existing transitions, override audits, messages, requests and provider-event records wherever
they already prove the fact. Fill demonstrated gaps with the smallest approved append-only evidence
mechanism. A new AutomationAudit/MessageDecision table or a new public API is **not** pre-approved.
Do not emit fake state transitions merely to log a decision: that can change lifecycle timestamps,
cap projections or resume behavior. Application history is evidence, not a new send-authority source.

**Minimum logical evidence contract — finalize field placement and coverage at R2:**

| Fact | Required meaning |
| --- | --- |
| Identity and lineage | Stable evidence identity; workspace and lead; actual business workflow/enrollment and campaign/version where applicable. Link the relevant step, paused-search occurrence, AI turn, message/version, request or reconciliation when one exists. No invented message/occurrence for a pre-message hold. |
| Execution correlation | Actual namespace/workflow/run identity when obtained, plus the relevant source event, command or activity/attempt reference. A Temporal restart of the same business workflow is not a new enrollment. If the run ID was never observed, retain that limitation. |
| Time and origin | Authoritative decision time, recording time when different, system/component or authenticated actor, and source/provenance. A late observation or import must not be dated as though it happened now. |
| Decision | Planning, scheduling, send eligibility, deferral, hold or rejection; stable reason codes and a bounded human-readable explanation. Preserve next eligible time/hold condition where known and the minimal versioned decision inputs needed to explain the rule applied then. |
| Outcome | Distinguish decision from dispatch request, actual attempted provider call, provider acceptance, reported delivery/failure and uncertainty. Keep links to authoritative receipts/events; do not infer receipt from a permitted send or a consumed cadence step. |
| Compatibility | Versioned interpretation, stable ordering/tie-breaker and an explicit incomplete/unknown representation. New or unknown reason codes must not crash the reader or disappear. |

- **Coverage:** standard and paused-search planning/scheduling; pre-send refusal and timing deferral;
  allowed decisions and their dispatch outcomes; AI continuation, send-now, approval and existing
  acknowledgment sends where applicable. Reuse existing human-control/inbound/override evidence
  needed to explain the result. Map every in-scope route to its actual writer and reader, including
  short-circuits with no outbound message. Do not substitute logging only the happy-path dispatcher.
- **Historical truth:** later send success, provider callback, status cleanup, track/config change or
  operator correction must not erase the original decision. Link later observations/corrections;
  retain their own source/time. Record which released policy applied without introducing a new policy.
  A decision-time explanation is not a recomputation using today's consent or schedule.
- **Retry identity:** duplicate delivery/replay of one decision converges on one logical record;
  genuinely distinct re-evaluations or provider attempts remain distinguishable. Define those
  identities before coding. Time-only keys, a fresh UUID on each retry or one overwriteable row per
  lead are insufficient. Avoid repeated identical poll noise without hiding a changed decision.
- **Transactions:** business state and required local decision evidence commit coherently through
  the actual application unit of work. When an external action is involved, reuse the established
  durable intent/claim and record known outcomes without pretending Postgres and the provider share
  a transaction. A memory buffer, log line or eventually published event alone is not durable evidence.
- **Failure safety:** failure to save required evidence is explicit and recoverable, not a swallowed
  warning followed by a success claim. It must not bypass an existing hold/consent gate. Never undo
  an already committed suppression or relax a safety decision because secondary export/archival is
  down. If an external call may have succeeded, preserve its original identity/uncertainty; do not
  retry the send with a fresh key merely to obtain an audit record. Any prerequisite dispatch repair
  belongs in 17-A and must be integrated before claiming the affected route is crash-safe.
- **Architecture:** use existing application ports/unit-of-work conventions and adapter-local vendor
  APIs. No business decisions in a generic logging hook, ORM callback or Temporal-only history scraper.
  Optional repositories must not silently bypass the promised evidence in production wiring.
  Shared A/B code paths require a policy-preserving diff against the declared release baseline,
  not a new requirement to ship B first or an excuse to omit paused-search evidence.

### 3.4 Complete the authorized investigation journey

1. Start from a known lead in the existing product, identify current versus historical business runs,
   select the relevant time/run and traverse retained decisions. Provide a bounded, stable page or
   cursor contract; a higher hard limit is not complete retrieval. Keep latest_workflow/current
   status semantics separate from a combined historical timeline.
2. Expose decision time, reason, next-eligible/hold information, source/actor as permitted, and the
   correlated known send outcome. Show separate engine runs when available rather than merging a
   restarted execution or a successor enrollment into the wrong journey. Give support a usable
   opaque reference for deeper authorized investigation; no raw payload download is required.
3. Apply existing workspace/membership/role/current lead-ownership checks **before** filters,
   pagination and counts. Historical actor identity is provenance, not a grant of current access.
   Do not give an assigned agent workspace-wide records or direct Temporal access to make history usable.
4. Reads must work from application records when Temporal is unavailable or an identified run has
   expired. Distinguish loading, no recorded events, known partial coverage, confirmed expiry/deletion,
   unknown provenance, permission denial and transient read failure. A not-found engine response
   alone may be wrong identity/namespace; do not automatically label it “expired” or “never contacted.”
5. Preserve deterministic traversal with equal timestamps, multiple runs, new arrivals and late
   events. Approve snapshot/high-water or refresh behavior so support does not miss older records
   or see duplicates across pages. Bounded reads should not load all message bodies or full engine
   histories for every lead. Reuse existing frontend query/loading/error patterns.
6. History is read-only: inspection or an evidence-only import cannot signal/restart an engine,
   advance a step, clear a hold or submit a message. Link to existing separately permission-checked
   actions if appropriate; do not add “replay this history” as a recovery shortcut.
7. If an export is selected at R3, approve its exact audience, field allowlist, pagination, redaction,
   delivery location and expiry separately. An export must enforce the same current authorization;
   existing CRM conversation-history import/export is not automatically this incident-evidence feature.

### 3.5 Bound privacy, storage and historical claims

- Retain the minimum facts needed to explain a decision: reason codes, necessary non-content inputs,
  opaque references and relevant versions/times. Identifiers and metadata are still tenant data.
  Do not copy credentials, auth/session tokens, raw provider/CRM payloads, unrestricted exception
  strings, message bodies or LLM traces into a new general audit record. Any justified sensitive
  field needs explicit purpose, access and retention approval rather than a free-form metadata escape.
- Set retention and deletion rules for primary evidence, optional archives, exports and backup
  copies. “Append-only” prevents silent historical rewriting; it does not exempt data from approved
  privacy deletion. Specify how redaction/deletion is represented without retaining forbidden content.
- Audit expiry must not erase separate operational suppression, idempotency claims or live-journey
  state, thereby re-enabling contact or a duplicate send. Trace those dependencies before cleanup;
  privacy obligations still require an approved safe deletion/anonymization design.
- Inventory retained versus missing evidence by run/source/time. Record when new writer coverage
  begins; pre-rollout absence is not proof no action happened. Restored/imported evidence carries
  original provenance and recording/import time, and conflicts remain visible rather than guessed away.
- Size normal and high-volume usage, long-lived workflows and retry storms; include database indexes,
  backups and any archive/export lifecycle. Approve query/page/payload bounds and alert thresholds.
  If the budget cannot sustain the required window, escalate it rather than silently discarding evidence.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Retention, runtime and privacy | Name live service/namespaces/versions and owner; approve exact engine/application periods and clock origins, long-running treatment, storage budgets, deletion/redaction/access rules, fresh/existing namespace configuration and optional archival feasibility. No guessed duration or assumed live default. | Retention/storage implementation and operational change |
| R2 — Decision coverage and persistence | Approve route-to-evidence matrix, existing-record reuse versus narrow new storage, required facts/versions, decision versus attempt identities, actual commit/failure boundaries, correlation and prerequisite ownership. No fabricated lifecycle transitions or second send authority. | Evidence-writer/schema implementation |
| R3 — Investigation/read contract | Approve supported lead/run/time/history surface, pagination/order/late-arrival behavior, current ownership/role scope, incomplete/unknown/error copy, safe correlation and any optional export contract. | API/web/read implementation |
| R4 — Cutover and acceptance | Approve preclosed/expired-history handling, exact preservation/import scope separately, migration/worker order, real elapsed-time evidence schedule, monitoring/rollback, release operators and accepted-live criteria. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. Retention durations and
privacy rules need named owners even though this is Class A. They are not permission to change who
gets contacted. A narrower partial delivery must be labeled partial; it cannot close the whole ticket.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic leads, fixed decision
clocks and recording providers; real retention aging needs separately scheduled operational evidence.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | A legitimate touch is deferred by an existing timing rule, then later sends when eligible; engine history becomes unavailable. | Application history still explains the original deferral and next-eligible time, then the later decision/known outcome. A fresh authorized read returns both. | Original reason disappears when status_detail is cleared, or today's settings are presented as the historical reason. |
| AC-02 | An existing paused-search scheduling hold or missing-track/profile outcome occurs before any message exists; include already-durable terminal/pause branches. | Actual outcome/reason and available run/source context remain inspectable without an invented message. Existing state behavior is preserved unless separately changed by its owner ticket. | Only post-message evidence, fabricated IDs, duplicate pause transitions, or smuggling 1-A/5/6 recovery into this ticket. |
| AC-03 | A send is allowed using known decision inputs; subsequently change the track, timing or consent facts. | Retained minimal evidence explains the original allowed decision and its policy/config context, separately from any subsequent revalidation and provider outcome. | Recompute “why sent” from current data, or treating allow as proof a provider call/receipt occurred. |
| AC-04 | Trigger a standard planning/send block that already persists transition metadata. | The existing reason/transition is retained and accessible; any new projection links to it without a second authoritative decision or changed state timestamp. | Claim no evidence existed, duplicate audit/state changes on every poll, or remove working block metadata. |
| AC-05 | Exercise every R2-covered route: standard/paused-search, AI continuation, send-now, approval and applicable acknowledgment. | Each actual decision reaches the agreed durable evidence and authorized read path; legitimate allowed traffic still proceeds under the declared release baseline. | Dispatcher-only coverage advertised as all routes, missing short-circuits, or globally disabling sends to pass negative tests. |
| AC-06 | Create planned, dispatch-pending, provider-accepted, delivery-reported, explicitly failed and uncertain outcomes. | History distinguishes decision, attempted action and evidence-backed outcome, with correct message/touch linkage. | Accepted means delivered, uncertain means definitely unsent, or journey consumption becomes fabricated provider evidence. |
| AC-07 | A duplicate or late provider callback/correction arrives after an earlier uncertain/failed observation. | Preserve earlier evidence and link the later observation with its own time/source; follow the separately released callback policy and idempotency rules. | Rewrite the original timeline as though the later result was known then, or add a new workflow side effect in this A ticket. |
| AC-08 | Lose a decision-recording response and retry/replay it; separately perform a genuinely new evaluation or provider attempt. | One logical record for the duplicate and distinct evidence for each real new event/attempt, with stable correlation. | Fresh UUID on each duplicate, one overwritten record per lead, or suppressing a real second evaluation as a duplicate. |
| AC-09 | Independent database sessions append the same logical event concurrently, then two distinct events with equal timestamps. | Real persistence uniqueness/ordering preserves one duplicate and both distinct facts; complete deterministic retrieval. | Process-local dedupe as concurrency proof or time-only keys collapsing valid events. |
| AC-10 | Fail before/between required state/evidence writes and commit; inspect from an independent session. | Approved local atomicity holds, no partial-success response and a recoverable failure; committed evidence remains after process restart. | State change silently loses required audit, evidence claims an uncommitted decision, or only a memory/log entry survives. |
| AC-11 | A provider may accept a call, then outcome/audit persistence fails or the worker crashes. | Original durable intent/claim and identity survive under 17-A's integrated contract; outcome remains honestly unresolved until supported evidence is recorded. | Fresh-key resend to rebuild history, guessed “not sent,” or claiming audit storage made provider/database writes atomic. |
| AC-12 | Evidence write or optional archive/export is unavailable while a contact block/STOP or independent hold applies. | No fail-open send; required local failures are observable. Already committed protective facts remain effective even if a secondary copy fails. | Swallowed audit failure followed by false success, clearing suppression, or making protection depend on a remote archive. |
| AC-13 | One business workflow has multiple Temporal runs; later a permitted successor enrollment exists; include missing run ID and mismatched tenant/lineage. | Correct run/touch correlation, explicit unavailable identifiers and preserved earlier history; no change to the successor. | Join whichever workflow is latest, invent a run ID or attribute prior-run provider evidence to the new enrollment. |
| AC-14 | Read older evidence after reason-schema/config changes and with a late-recorded event. | Stable reason code plus safe compatible explanation; decision/recorded times and versions remain distinct. | Unknown codes vanish/crash the reader, current policy is backdated or import time replaces occurrence time. |
| AC-15 | A lead has multiple historical workflows and over 100 retained transitions/decisions, including tied times; paginate while new/late events arrive. | Supported traversal finds the older incident once, within declared snapshot/refresh behavior; current status stays separate. | Latest-workflow-only results, raising a hard cap instead of traversal, missing/duplicate page records or loading all histories unbounded. |
| AC-16 | Read/filter/count as owning agent, unrelated agent, approved wider role, inactive member and another workspace; ownership has changed since the incident. | Existing current access rules apply before paging/counts; permitted wider roles can handle unowned leads. Historical actor is provenance only. | Previous assignee retains access by appearing in an audit, cross-tenant/count leakage or blanket engine/admin access for agents. |
| AC-17 | Show no recorded events, known pre-rollout gaps, confirmed expiry/deletion, unknown engine identity, permission denial and failed/loading reads. | Each state is honest and distinct; retained application evidence is usable during Temporal outage. | “No activity” after a failed fetch, NotFound automatically means expired, or absence proves the lead was never contacted. |
| AC-18 | Apply the approved retention procedure to a fresh and an existing namespace; repeat it and introduce configuration drift. | Correct actual namespace/readback, existing history preserved, repeat-safe enforcement and detectable drift; longer approved settings are not silently reduced. | Bootstrap-only change, editing the wrong namespace, recreation/deletion, or config text presented as live proof. |
| AC-19 | Close a synthetic execution after the retention change; inspect detailed history beyond 24 hours and at agreed multi-week checkpoints. | Exact namespace/workflow/run and real close/read times demonstrate retained closed history for the claimed interval; worker restart does not erase it. | Open workflow, list-only visibility, application time-skipping or fabricated aged fixture presented as real retention proof. |
| AC-20 | Compare executions closed before and after the update, including one already purged and one preserved by an approved usable copy. | Old timer limitation is explicit; available copied evidence is retrieved with provenance; missing history remains missing. | Claim a retention increase rescues all already-closed runs, recover purged data without a copy or hide cutover gaps. |
| AC-21 | Test application evidence at approved expiry boundaries, long-lived journeys and permitted privacy deletion; engine history is absent. | Agreed independent window and deletion representation hold; separate operational suppression/idempotency/live state remain safe. | Application evidence expires with Temporal by accident, an early record of an open journey vanishes contrary to R1, or audit cleanup re-enables contact/resend. |
| AC-22 | If archival/export is approved, test an actual scoped retrieval after primary history is unavailable, plus permissions, missing/corrupt copy and storage failure. | Supported runtime/reader proves useful evidence and explicit failures under approved lifecycle rules. If not selected, record it as not in use, not a working fallback. | Bucket/object existence as proof of archive readability, unsupported Docker assumption or using a full production restore for a support query. |
| AC-23 | Supply synthetic sensitive payload/error content to decision producers and exercise reads/any exports. | Approved allowlisted facts only; credentials, raw payloads, message content and LLM traces do not leak into new general evidence or response surfaces. | Unrestricted metadata/exception copying, UI-only redaction or a new sensitive data archive without approval. |
| AC-24 | Inspect/refresh/page history and perform an approved evidence-only import repeatedly. | No send, signal, resume, step consumption, enrollment change or operational-state repair. | Replay engine history to generate missing evidence or reuse a provider callback handler with unintended side effects. |
| AC-25 | Inventory/import synthetic legacy data with exact evidence, partial later evidence, contradictory lineage and no retained copy. | Dry-run classifies provenance/coverage; only supported facts import idempotently, with original/import times and explicit conflicts/unknowns. | Guess first events/reasons, manufacture a complete narrative, overwrite originals or silently repair current business state. |
| AC-26 | Rehearse migration and mixed old/new readers/writers, followed by a compatible rollback. | Evidence/schema interpretation and read access remain compatible; incompatible writers are contained and originals/retention protected. | Rollback erases new evidence, a stale writer nulls prior facts or an old reader mislabels new outcomes. |
| AC-27 | Generate representative multi-week volume, a long-running workflow and repeated retry noise; query an incident beyond unrelated first-page rows. | Approved storage/query/page bounds hold, required events remain complete, scope/filtering precedes limits and growth/drift/write failures reach their named operator. | Unbounded all-history/body fetch, silent sampling/TTL reduction, first-page false emptiness or cost claims without measurement. |
| AC-28 | Demonstrate synthetic defer/hold → later legitimate send → engine history unavailable → authorized API/UI investigation; add the scheduled real-aging checks. | Complete business explanation and truthful known outcome from durable records, no duplicate contact or changed safeguards; distinguish immediately demonstrated behavior from elapsed-time evidence still pending. | Static fixtures/fake engine alone presented as end-to-end retention proof or automatic real-customer contact to create test data. |

AC-18–22/25–28 include operational rehearsals and later observations, not permission to mutate
production or run multi-week jobs now. Exact periods, fields and route expectations come from R1–R3.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Decision → authorized history:** real application scheduling/planning/send flow, followed by
  fresh agreed lead/run history reads after status changes and without Temporal access (AC-01–08/13–17).
- **Persistence and failure:** migrated real Postgres, independent sessions and controlled crash/
  transaction boundaries for append/dedupe, stale writes, ordering, access and retention cleanup.
  The repository contract is an agreed seam for those storage invariants; SQL text assertions alone
  do not prove them (AC-09–13/15–16/21/25–27).
- **Provider/engine boundary:** real application activities and supported Temporal test/replay
  environment where retries/run correlation matter; recording provider ports for controlled allowed,
  rejected and ambiguous sends. Do not replace the safety/identity rule under test (AC-05–13/24/28).
- **Retention operations:** approved fresh/existing namespace procedure against a disposable service,
  followed by metadata readback and scheduled real-age closed-history observations on the authorized
  deployment. Optional storage retrieval must be real if archival is claimed (AC-18–22/26–28).
- **Operator journey:** existing API permission/contract and frontend route tests, then a synthetic
  API-to-UI demonstration of older-run discovery, reasons and partial/error states (AC-13–17/23–28).
  No new browser tooling/dependency project is authorized by this draft.

**Allowed fakes:** hand-written external CRM/LLM/provider transports, fixed decision clocks and
repository fakes for fast application tests. Fakes must not fabricate the audit expected by the
test or replace the decision, scope check, duplicate rule or failure boundary being tested. They
do not prove real database atomicity, archival retrieval or actual elapsed server-retention time.

1. Begin with AC-01 after seam approval: run an existing timing deferral through its later eligible
   send, then assert that the original explanation is still accessible through the agreed history
   read. Demonstrate the business failure on unchanged code, not an import error for a proposed table
   or method. The existing get_lead_detail_view is a candidate public boundary: expect the original
   deferral reason/time in its returned history after the send. Missing evidence should fail that
   positive expectation; asserting its absence only characterizes the defect and is not this red test.
   Do not require a new no-op history port solely to manufacture red. AC-02's pre-message hold and
   AC-15's older-run retrieval are separate next slices.
2. One scenario → meaningful red → smallest complete fix → the same test green. Do not implement
   the whole writer/read/retention system and retrofit tests, or prewrite every imagined test first.
   Minimal seam scaffolding is recorded separately and is not itself the defect's red result.
3. Keep already-working transition metadata, successful due sends, safety checks and permissions as
   positive/unchanged controls. A live retention setting already meeting the approved value is a
   verified baseline, not an excuse to manufacture a failure or skip application-evidence gaps.
4. Independently remove the durable reason write; restore status overwrite; bypass dedupe/transaction
   scope; collapse business and engine runs; restore latest-only/100-row reads; drop authorization;
   copy raw errors; or label a permitted send delivered. Each critical test must fail for the intended
   protection. Restore and rerun; no mutation ships. Incidentally fixed cases need sensitivity evidence.
5. Independently review literal reason/time/outcome expectations against approved scenarios and the
   actual released policy. Do not derive the expected event from the same production mapper, weaken
   a privacy assertion to match stored payloads or mock away a post-provider crash.
6. Record exact commands/revisions, failure assertions, exit codes, pass/fail/skip counts and remaining
   integration gaps. Time-skipping tests can validate application date logic, not server retention.
   Assign the future real-age checks to an owner/date; pending observations are not passing tests.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills every applicable case | Reproducible invocation | Business assertion and revision | Revision, exit code and counts | Intended protection failure or justified baseline pass | Named limitation and owner/checkpoint |

## 6. Engineering starting points — navigation, not a prescribed design

Paths below are relative to the explicitly named repository at the reviewed baseline. New history
pagination, decision records and preservation commands are not claimed to exist. Retrace actual
production dependencies/commit points before changing a shared writer or read contract.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — workflow evidence and persistence | app/domain/workflows/models.py; app/application/use_cases/apply_workflow_state_transition.py; app/application/ports/repositories.py; app/infrastructure/persistence/postgres/workflow_models.py; app/infrastructure/persistence/postgres/workflow_repository.py |
| API — planning, scheduling and sending | app/application/use_cases/schedule_next_paused_search_action.py; app/application/use_cases/campaign_cadence_execution.py; app/application/use_cases/send_outbound_message.py; app/application/use_cases/dispatch_outbound_send_requests.py |
| API — message/provider evidence | app/application/use_cases/process_provider_delivery_callback.py; app/infrastructure/persistence/postgres/outbound_message_repository.py; app/infrastructure/persistence/postgres/outbound_send_request_repository.py; app/infrastructure/persistence/postgres/outbound_send_reconciliation_repository.py; app/infrastructure/persistence/postgres/provider_message_event_repository.py |
| API — authorized reads and contract | app/application/use_cases/lead_read.py; app/interfaces/api/v1/leads.py; app/interfaces/api/schemas/leads.py; app/domain/identity/permissions.py |
| API — Temporal identity and activity wiring | app/infrastructure/workflows/temporal/starter.py; app/infrastructure/workflows/temporal/worker.py; app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/lead_nurture.py |
| API — deployment and backup starting points | compose.prod.yaml; app/core/config.py; scripts/prod_backup.sh; docs/planning/production-infrastructure-plan.md |
| Web — lead history and API consumer | src/pages/LeadDetailPage.tsx; src/lib/api/leads.ts |

**Compare at least two approaches before coding:**
- **Recommended starting point: explicit engine retention plus existing application evidence with
  narrow gap-filling and paginated reads.** Reuses working transitions/provider records, bounds
  content and keeps the incident path independent of Temporal. Lowest V1 operational complexity;
  requires an explicit producer/identity matrix so direct/pre-message paths are not overlooked.
- **Alternative: the same durable business evidence plus separately approved engine archival.**
  May retain deeper execution diagnostics outside primary storage, but adds runtime compatibility,
  storage lifecycle/security, lookup/retrieval and failure operations. Resolve the current Docker
  support limitation before selecting it. It does not replace business decision writes or scoped
  application access; adopt only if deeper history justifies the extra maintenance/cost.

Neither “increase one config value only” nor “copy every engine event into a generic audit table”
meets the complete requirement. Compare latency/storage/maintenance using the R1 budget, obtain
approval, use additive migrations if needed and keep vendor-specific work behind existing boundaries.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_lead_read.py; tests/interfaces/api/v1/test_leads.py
- tests/application/use_cases/test_schedule_next_paused_search_action.py
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_send_outbound_message.py
- tests/application/use_cases/test_dispatch_outbound_send_requests.py
- tests/application/use_cases/test_process_provider_delivery_callback.py
- tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_workflow_repository.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_postgres_e2e.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/infrastructure/test_temporal_starter.py; tests/infrastructure/test_temporal_worker.py
- Web: src/app/LeadsRoutes.test.tsx

Check the actual fixtures: an infrastructure directory or fake-session SQL assertion is not proof
that a test uses real Postgres. Extend the smallest approved test node/file first. For changed API
code use Python 3.12/uv focused pytest, then relevant suites, make lint, make typecheck and make test.
For web changes use focused Vitest, then pnpm test, pnpm typecheck and pnpm lint. Namespace retention
and real storage checks need their own exact approved commands and recorded elapsed-time evidence.

## 7. Existing records and evidence-preservation plan

- Deliver a scoped dry-run inventory/runbook for available application records, exact engine runs,
  pre-change cleanup risk, usable retained copies and unrecoverable/unknown gaps. Prefer safe counts
  and approved opaque references; no general raw history or credential dump into tickets/logs.
- Separate evidence access from recovery: first retrieve/verify a copy in an isolated authorized
  environment with external sends/signals disabled. Do not overwrite the live database or run restored
  workflows to “see what happens.” A backup may not contain the needed run or all required stores.
- Import only supported historical facts with original identity/provenance and a separate import
  time; dedupe repeated imports and preserve contradictions. Do not replay business handlers merely
  to create audit rows. No inferred first action, invented hold cause or fabricated provider receipt.
- Missing history is a real limitation, not a migration failure to hide. State the coverage start,
  known unavailable periods and follow-up owner. This ticket cannot fix a past evidentiary gap by
  increasing retention today, nor infer the original reason from the lead's current status.
- Production inventory, preservation, export, restore or import needs separately approved exact
  environment/workspace/run scope, operator, commands, content handling and limits. This draft
  authorizes none of those operations. Operational-state repair remains in the relevant owner ticket.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test-contract gates, declare covered routes and actual
   integrated A/B baseline, and approve finite durations/privacy/budgets. Confirm exactly which
   service/namespace every production client uses and which records/read paths satisfy the promise.
2. **Rehearse:** demonstrate AC-28 with real database/engine boundaries where required, plus duplicate
   and crash handling, older-run paging, current ownership changes, safe retention cleanup and
   evidence-limited historical cases. Use synthetic leads/recording providers, never customer traffic.
3. **Apply safely:** stage compatible schema/writer/API/web changes and the approved retention
   operation. Preserve existing namespaces and data; obtain metadata-only readback. Contain incompatible
   writers rather than letting them overwrite evidence. Do not restart/reset every lead workflow.
4. **Handle the cutover gap:** carry out only separately approved §7 preservation/import. Record old
   closed executions' unchanged timers, already-missing records and per-producer coverage start.
   Deployment is not retroactive reconstruction; backups/archives are fallbacks only after retrieval proof.
5. **Verify now and later:** immediately prove durable application reasons after later status changes
   and without engine access. Then complete the owned beyond-24-hour and multi-week closed-history
   checkpoints. Record merged, deployed, application-verified and retention-observed separately;
   do not call the full ticket accepted live while its claimed retention interval is unverified.
6. **Observe and brief:** monitor effective-retention drift, database/backup growth, write failures,
   unknown/missing correlation, duplicate noise, history query latency/error rates and any archive
   retrieval/deletion failures. Tell operators how to find older runs and interpret incomplete
   evidence. Wider history visibility is not evidence that a new incident occurred at release time.

**Rollback:** use a compatible reader/writer rollback or forward fix while preserving committed
evidence, original identities and approved retention. Never “roll back” by dropping audit records,
recreating a namespace, reducing TTL automatically or resending to regenerate receipts. Preserve
contact safeguards and current operational state; authorize any temporary writer containment and
make resulting coverage gaps explicit. Privacy-driven deletion or deliberate retention reduction
requires its own approved scope/cutover, not an incidental config reset.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact, Class A scope and unchanged behavior; applicable R1–R4
  and §4–5 test boundaries close with named owners before their implementation/release.
- [ ] Exact multi-week engine retention is applied to the actual fresh/existing namespace path and
  verified through metadata plus real closed-execution observations for the claimed interval.
- [ ] Every approved producer durably records/reuses the required reason and correlation; retries,
  later outcomes and corrections preserve historical truth without creating another business state machine.
- [ ] Authorized users can traverse older runs and records beyond 100, distinguish current state
  from history and investigate without Temporal. Scope, paging, late events and error/gap states work.
- [ ] Sensitive content is minimized at write/read boundaries; storage/query budgets and approved
  deletion rules are proven without destroying separate suppression/idempotency/live-state safeguards.
- [ ] Every applicable scenario has meaningful red/green or justified unchanged-control/sensitivity
  evidence, exact commands and real integrations where required. Skips and future observations stay open.
- [ ] Historical preservation/limitations, compatible rollout and rollback are rehearsed and scoped;
  no automatic replay, production restoration, real-customer test send or invented missing evidence.
- [ ] Independent review confirms no A/B policy mix, generic audit platform or unproved archival
  fallback. Merged/deployed/application-verified/retention-observed/accepted-live states are distinct.

## 10. Source references and review record

- [Main issue plan — Issue 4 and its business-impact appendix](../production-state-consistency-issues.md)
- [D1–D7 consensus — strict ship classes](../production-state-consistency-review-consensus.md)
- [Infrastructure plan — deployment and backups, not verified live settings](../production-infrastructure-plan.md)
- [Issue 1-A — scheduling-hold evidence and separate recovery](issue-1-a-visible-scheduling-holds.md)
- [Issue 2-A — distinct instruction delivery/application evidence](issue-2-a-reliable-instruction-delivery.md)
- [Issue 3-A — enrollment lineage and no invented start history](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [Issue 17-A — separate dispatch durability and identity](issue-17-a-durable-outbound-dispatch.md)
- [Temporal Server — retention and already-closed cleanup timers](https://docs.temporal.io/temporal-service/temporal-server#retention-period)
- [Temporal self-hosted namespace management](https://docs.temporal.io/self-hosted-guide/namespaces)
- [Temporal archival — compatibility, configuration and retrieval limitations](https://docs.temporal.io/self-hosted-guide/archival)

**Draft preparation (2026-09-08):** The bounded trace distinguishes the source incident's reported
24-hour setting from uninspected live configuration; existing durable block transitions from
unrecorded/overwriteable decisions; and a latest-workflow/100-row read limit from actual deletion.
Independent product-reader and technical/test-contract reviews completed. The reader found no
blocking product gaps. Technical review confirmed the baseline defects covered by AC-01/02/15;
its test-seam and paused-search coverage concerns are clarified in §3.1/3.3/5. Existing defects are
requirements to fix, not proof the draft is implemented. No B-release prerequisite or fake test seam
was adopted. Documentation checks verified 44 source/test/document references, 20 per-document
local links, AC-01–28, ten numbered sections, R1–R4, consistent tables and eleven indexed drafts.
The prior ten drafts remain unchanged: aggregate SHA-256
68cf400a07e448585b5db1ae1e0ecb1f692d4cbf32dabafd593657f1fda14f51.
No application code changed or behavioral tests ran; production retention/access, Jira publication
and implementation are not authorized by this draft. R1–R4 remain open.
