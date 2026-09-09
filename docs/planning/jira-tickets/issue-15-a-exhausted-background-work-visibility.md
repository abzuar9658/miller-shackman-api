# Issue 15-A — Show background work that has stopped retrying

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the eighteenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not authorize production access, historical replay, sends or release.

## 1. Business impact — read this first

**The promise:** When a saved incoming event, automation instruction or internal event publication
has stopped being attempted, an authorized operator can find the individual item, understand what
is known to have failed, see its age and affected context, and follow a permitted recovery or
support route. The item does not disappear because nobody opened the lead or a notification failed.
If safe replay cannot be established, it stays visibly unresolved with an owned escalation path.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | A reply or CRM update can exhaust processing; an engine instruction can become permanently undeliverable; an internal event can reach its publish-attempt limit. None has a complete item-level operator journey for this terminal work. |
| Is there no dashboard warning at all? | There is an aggregate “integration events failed” card. It counts some failed rows, mixes retryable and exhausted publications, omits exhausted inbound events and engine signals, and links to settings rather than the affected work. That is not a terminal-work queue. |
| What changes for operators? | Attention and an appropriate detail/support destination show what stopped, why, how long it has been known, which lead or workspace obligation is affected, and what can safely happen next. |
| Does every temporary failure become a new incident? | No. Work still eligible for its ordinary bounded retries remains distinct from work that has stopped. A service outage or overdue worker is not itself proof that each queued item exhausted its attempts. |
| Does this pause every affected lead? | No. This ticket makes failed obligations visible; it does not invent a blanket nurture hold. Existing reply holds, instruction intent, human control, send exceptions and contact safeguards retain their own meanings. |
| Can I click “retry everything” after service returns? | No. A failure may have happened after an external effect or partial progress. Only a specifically authorized, duplicate-safe recovery for the original work is permitted; unsupported cases go to an identified operator/support route. |
| Does “seen” mean fixed? | No. Seen, cause corrected, recovery requested, transport accepted and verified disposition are different facts. Seen items remain available as unresolved work; new failures cannot hide behind an old seen marker. |
| Does an accepted instruction or published event prove the business action happened? | No. Engine acceptance is not application of the command. Broker publication is not downstream processing or customer delivery. The UI must say which obligation actually completed. |
| What if no lead can be identified? | The item still belongs on the authorized workspace operations surface with a safe reference and explicit missing context. Do not fabricate a lead, assignment or clickable journey. |
| Will this send new notifications or contact customers? | No new notification, handoff, fallback or outreach policy is introduced. Local visibility cannot depend on a CRM note, email, notification or the failed event bus succeeding. |
| Will the dashboard look worse initially? | It may enumerate previously hidden failures. Separate newly stopped work, historical discoveries, affected leads and unresolved items; a higher visible count is not by itself a higher failure rate. |

“Stopped background work” or “dead-lettered” describes an operational outcome, not a preselected
new table, broker dead-letter exchange or workflow state. Preserve the three existing work owners;
approve the smallest durable representation and shared presentation contract at R1–R3.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — permanently unprocessed work lacks actionable ownership; confirm at publication |
| Source / delivery class | Production-state consistency Issue 15 / **Class A: exhausted background-work visibility** |
| Components | External-event processing; Temporal signal outbox; transactional event publication; durable failure evidence; scoped reporting/Attention/detail; bounded operator recovery and monitoring |
| Repositories | miller-schackman-api and miller-schackman-web; saved work → stopped outcome → discovery → authorized remedy or escalation → truthful disposition |
| Sequence | Eighteenth draft, following 12-B; all seventeen source issues now have at least one draft. Draft order does not establish dependency integration, implementation or release. |
| Inbound integration | Reuse integrated 9-A receipt/STOP/reply-hold/exhaustion contracts and 16-A durable opt-outs. Native FUB envelope retries and normalized queued inbound messages share storage but are separate processing paths; both need coverage. |
| Instruction integration | Reuse integrated 2-A original-command identity, freshness, accepted/applied and recovery outcomes. 7-A owns missing-engine inspection/reconstruction; 10-A owns native activity failure holds. Do not create another engine restart authority here. |
| Safe replay prerequisites | Any recovery that can reach lead sending needs integrated 17-A committed intent/claim and durable outcome ownership on every affected route. Without that evidence, release visibility with an explicit non-replaying support disposition, not an unsafe retry button. |
| Shared evidence and reads | Reuse 4-A durable operational history/access and existing Attention/acknowledgment/reporting mechanisms. Coordinate 1-A/3-A/5-A/6-A/8-A projections when a permitted business recovery touches their holds, progress or completion. |
| Adjacent policy | Preserve the actual separately released 12-B/13-B/14-B/17-B and inbound timing baseline. None is implicitly enabled or reverted by queue visibility or recovery. G1–G7 and earlier implementation gates are not closed here. |
| Decision ownership | Name implementer, independent reviewer, each queue/runtime owner, API/web owner and release/incident-response operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-08. No live production state inspected; retrace the implementation branch and actual worker configuration. |
| Closure boundary | Every supported stopped obligation is queryable, scoped and actionable, including absent anchors and evidence-poor cases; safe recovery is verified where offered and unsupported replay is explicitly contained. |

**Included:** terminal/exhausted outcomes in the three persisted queues, including existing early
permanent rejection of saved work; retry-versus-terminal classification; interrupted/legacy rows;
failure identity, age, privacy, counts and history; correlation with existing reviews; item-level
API/UI access; bounded supported correction/recovery or escalation; operational coverage and tests.

**Excluded:**
- Changing ordinary attempt limits/backoff, adopting the separate 30-minute inbound escalation
  window, unlimited retries, automatic post-exhaustion replay or new customer/agent notifications.
- A blanket lead/campaign hold, new consent/fallback/tag/uncertainty policy, automatic handoff,
  force-resume, terminal re-entry, new enrollment or reset of send/touch/AI/start identities or budgets.
- Rebuilding review creation on the false assumption that it requires successful notification.
- A universal queue platform, generic rules engine, broker dead-letter infrastructure, or a new
  downstream-consumer delivery guarantee. This is the three source queues, not every background job.
- Native Temporal activity-exhaustion handling owned by 10-A, missing-engine recovery owned by
  7-A, and instruction delivery repair owned by 2-A except their required visibility integration.
- Blind historical replay, raw-payload export, production fault injection, real-customer test
  traffic, or changes to any of the seventeen earlier drafts.

**D7: Class A and Class B must not share a PR.** Improving discoverability does not grant new
contact rights. A necessary policy change must be separated and approved, not hidden in recovery.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

| Work owner | Traced retry and stopping behavior | Visibility limitation |
| --- | --- | --- |
| Native Follow Up Boss envelopes in external_events | Initial envelope attempt_count is 1. The retry worker claims RETRYABLE_FAILURE envelopes, excluding normalized inbound-message events, and increments the count. The handler permits replay only for RETRYABLE_FAILURE; non-permanent failure at count 3 becomes EXHAUSTED, while a classified permanent fetch failure becomes PERMANENT_FAILURE immediately. | Both terminal states stop this normal retry path. An envelope can cover multiple resources and carries no lead_id/crm_lead_id at creation; there is no complete terminal-item operator reader. |
| Normalized inbound-message events in external_events | Enqueue starts at count 0; the queue claims PENDING/RETRYABLE_FAILURE inbound_message.received rows and increments count. Processor exceptions become RETRYABLE_FAILURE, then EXHAUSTED at count 3, with queued_inbound_processing_failed. Invalid stored payload becomes PERMANENT_FAILURE with queued_inbound_payload_invalid. | No item-level exhausted-event surface. The same table does not mean the FUB retry handler can replay this payload or that all stopped rows are classifier failures. |
| Temporal signal outbox | Default maximum is 10 attempts, five-minute lease, 30-second base backoff capped at 15 minutes. Payload errors and missing workflows that cannot be restarted become TERMINAL_FAILURE. Other delivery or restart errors remain FAILED; claims require attempt_count below max_attempts, so FAILED at the limit is no longer attempted. | TERMINAL_FAILURE and exhausted FAILED are distinct storage forms of stopped instructions. Neither is included in the workspace event-failure report. |
| RabbitMQ event publication outbox | Default maximum is 10 attempts with the same lease/backoff defaults. Claims include due PENDING, FAILED and PUBLISHING below the limit. Publish exceptions remain FAILED with another available_at even on the final attempt; no terminal enum is written. | FAILED is both an intermediate retry and exhausted work. The report counts it but cannot identify individual stopped publications, reasons, ages or remedies. |

Native CRM retries use a one-second base delay capped at 60 seconds; queued inbound processing
uses 30 seconds capped at ten minutes. These are current per-path settings, not a shared retry
budget, three extra retries, or a fixed outage-duration promise. Inbound claim queries have no
max-attempt predicate: the handlers write terminal statuses that are excluded by the respective
status filters. Do not classify their live rows using the signal/publisher predicate merely because
all paths carry attempt_count.

External-event workers claim a batch in a database session, then commit/roll back per event. Claims
use FOR UPDATE SKIP LOCKED, but a commit/rollback releases transaction locks for the batch and the
loop still holds previously returned objects. The native retry wrapper rolls back unexpected
handler/commit failure; the queued processor rolls back before saving its failure result. Signal
and publisher workers commit after the whole dispatch/publish batch, not before each external call.
Therefore a rolled-back claim is not necessarily a durable attempt, and a process crash need not
leave a saved DISPATCHING/PUBLISHING row. Conversely, persisted interrupted rows from a committed
claim/legacy path require explicit treatment. A method name or an in-memory attempt count proves
neither durable ownership nor that an external effect did not occur.

Signal status SENT means the dispatcher recorded success, not command application. At this
baseline the missing-engine restart branch even marks SENT without redelivering the original
instruction; 2-A owns that repair. Do not derive a new “action completed” claim from SENT alone.
PUBLISHED records the publisher's completed publish call. The RabbitMQ message uses the original
outbox_event_id as message_id; that alone is not consumer deduplication. The declared topology binds
the CRM-sync queue to crm_sync.requested, not every domain-event type. Neither a publish receipt
nor this ticket proves all event types have a consumer, were processed or reached a customer.

Workspace reporting counts external status FAILED only, not EXHAUSTED/PERMANENT_FAILURE, and
outbox status FAILED without distinguishing remaining attempts. It has no signal-outbox count.
The admin/manager Attention builder sums those counts into one “integration events failed” card,
using last successful CRM sync time or browser time as its timestamp and a settings destination.
Assigned-agent Attention reads lead/handoff state, not these three queues. Neither provides the
required item-level terminal-work list. The source issue's “no reader at all” shorthand is thus too
broad for outbox FAILED: an aggregate reader exists, but it is not actionable terminal visibility.

Attention already separates per-user seen versions from its source items. Its default unseen
filter does not constitute incident resolution. Existing classification/review creation does not
depend on notification success; do not recreate reviews or alter notification policy to add this
surface. Workspace reporting permission and assigned-lead access are different boundaries; sharing
an Attention component does not grant every viewer workspace-wide event or recovery access.

Stored diagnostic fields are not a safe public schema. Signal/outbox last_error contains truncated
exception text. The misleadingly named payload_redacted can contain the queued inbound message
body or a copied FUB envelope. Outbox rows lack an updated_at or terminal timestamp; available_at
is a retry/lease time, not proof of when exhaustion occurred. Native envelope received_at is the
provider occurrence time. None should be blindly displayed as a safe error or actual failure age.

### 3.2 Classify stopped work without inventing failure or permission

Approve this matrix per source at R1; these are required meanings, not prescribed enum names.

| Observed situation | Required disposition |
| --- | --- |
| Due/future work still eligible for normal retry, or a legitimately live claim | Show its correct pending/retrying/in-progress meaning where relevant; do not create a terminal incident or steal a live attempt. Normal bounded processing stays available. |
| Saved inbound EXHAUSTED, including either native envelopes or queued messages | One unresolved stopped-processing obligation with actual source, reason, known count and context. Keep the applicable 9-A reply safety and existing review; exhaustion alone does not imply a new lead state. |
| Saved inbound PERMANENT_FAILURE or signal TERMINAL_FAILURE before the limit | Visible stopped work with the actual early-terminal reason. Do not claim all attempts were consumed or make it retryable merely to use a common UI. |
| Signal or event-publication FAILED at the authoritative attempt limit | Queryable exhausted outcome with no future automatic retry advertised, even if available_at lies in the future. Preserve evidence and normal retry exclusion. |
| Persisted signal DISPATCHING or outbox PUBLISHING at the limit, after its applicable lease expires without a definitive result | Classify as stopped/interrupted with external outcome unconfirmed under R2's ownership checks. No blind extra dispatch, fabricated rejection or successful completion. A late definitive result must reconcile safely. |
| Legacy FAILED, malformed metadata, missing anchors or conflicting count/status/limit history | Use the approved source-specific classification where evidence supports it; otherwise a visible evidence-limited operational exception. Do not label every unknown/old row “ten attempts exhausted.” |
| Correctly processed, legitimately ignored, accepted/published, or already resolved work | Preserve the actual boundary outcome/history. Do not convert intentional unsupported/no-action handling into poison work, or success at one boundary into proof of every downstream action. |
| A terminal instruction is stale or its target is protected, terminal or superseded | Preserve its failed delivery history and current command authority. A reasoned no-longer-applicable disposition needs evidence; the failed command must not be replayed against the latest lead journey. |
| Worker, database, discovery query or monitoring is unavailable | Report unknown/stale coverage through the approved operational path. Do not report an empty healthy queue, invent saved incidents during storage failure, or infer per-item exhaustion from silence. |

Use one authoritative source-specific stopping contract for writers, worker eligibility and reads.
Record/retain the applicable limit or equivalent decision evidence where necessary so a changed
deployment setting cannot silently reclassify or resurrect stopped work. Do not copy magic counts
into frontend filters. The draft preserves ordinary retry policy; exact compatibility handling is R2.

This repair must not manufacture a failed row for an invalid request that was never accepted or
persisted. Such ingress rejection keeps its own response/operational contract. Coverage is of saved
obligations and explicitly observed coverage failures, not a promise to recover unrecorded payloads.

### 3.3 Keep one durable, independently discoverable obligation

1. Anchor identity to workspace, source queue and original source-row identity, retaining provider
   event/idempotency identity and proven workflow/run/enrollment/message/aggregate links. A native
   envelope can concern zero or several leads; a non-lead aggregate is not a lead UUID. Never bind
   an item to the latest workflow or an agent merely because that is convenient for the UI.
2. Reuse the source terminal fact and 4-A/9-A/2-A evidence before adding another incident store.
   If a derived episode/projection is needed, its ownership, deduplication and repair must be
   explicit. Terminal persistence and required local evidence must be atomic, or discoverably
   reconstructable from the authoritative source; failure visibility must not depend on publishing
   a “failed event” through the same failed outbox or on successful notification delivery.
3. Preserve original work and attempt history. Repeated polling, duplicate source events, terminal
   writes, lost responses or projection repair converge on one episode. An authorized recovery
   request stays linked to the original failure; it must not silently delete that episode, reset
   its age, create a replacement business event, or clear its dedupe key to bypass exhaustion.
4. Store/display allowlisted source, failed phase/category, business-readable explanation, original
   work-created/received time with its correct meaning, evidenced terminal observation time,
   discovery/recording time, known count/limit, current recovery status and safe support reference.
   Unknown cause, original terminal time or external effect stays unknown. Do not relabel
   processed_at as successful processing on a failed inbound row, or use available_at, last CRM
   sync or render-time “now” as the failure time. Define age labels and ordering explicitly at R1.
5. Allowlist metadata before serializing responses/logs. No raw last_error, exception stack,
   provider payload, message body, prompt, credential, header, connection string or arbitrary CRM
   URI in the new surface. “Redacted” in a column name and truncation are not sanitization. Retain
   access-controlled diagnostics only under the approved evidence/privacy contract, not a new
   operator raw-payload export. Render user/provider-derived labels as data, never executable markup.
6. Validate current source version/claim/recovery ownership at every terminal update and settlement.
   FOR UPDATE SKIP LOCKED only protects its transaction. Approve same-batch commit/rollback,
   multiple-worker and late-result behavior on real Postgres; stale in-memory records cannot
   overwrite newer success, recovery or terminal evidence. No process-local lock is sufficient.
7. Discover committed terminal rows independently of the failing worker's last logging call,
   future retry eligibility, next lead action or a user click. A source query may supply this
   directly; any asynchronous projection requires monitored repair with complete traversal and
   bounded lag. A final FAILED with no next eligible attempt cannot wait for another claim to
   become visible. If saving terminal evidence fails, expose coverage/recording failure and
   reconcile retained source facts after service recovery without claiming nonexistent history.
8. Read/diagnose malformed source metadata without requiring successful full payload deserialization.
   One poison row must not turn the whole failure inventory into an empty result or starve traversal
   forever. Isolate the affected reference for authorized investigation; unknown workspace/identity
   cannot justify cross-tenant display, guessed payload repair or silent row deletion.
9. Correlate the same inbound-processing failure with 9-A's review and the same failed instruction
   with 2-A's evidence. Do not create a new handoff/review solely for a second display. Distinct
   envelope, child-processing, instruction and publication obligations remain distinct even when
   they affect the same lead or incident; link them rather than collapsing on lead_id. Completing
   one cannot erase unresolved siblings or assert the whole journey repaired.

### 3.4 Make recovery bounded and truthful about its effects

Visibility is mandatory; a universal retry action is not. R2/R3 must approve an action/disposition
matrix for every supported category. Where no safe self-service action exists, identify the actual
authorized support destination, responsible role, safe reference and non-replaying investigation
procedure. “Ask support” with no reachable destination/owner is not a complete operator journey.

| Obligation | Permitted recovery boundary to verify before enabling it | What does not prove recovery |
| --- | --- | --- |
| Native CRM envelope | Correct the cause; use only an explicitly supported, scoped replay/reconciliation of the original envelope and its affected resources. Re-fetching the CRM reads current data, not necessarily the original event snapshot. Preserve already committed child effects and current contact/ownership rules. | Calling handle(replay=True) on EXHAUSTED/PERMANENT_FAILURE currently returns duplicate; re-posting the webhook or clearing its dedupe key is not a recovery implementation. |
| Queued inbound processing | Use its original inbound identity and integrated 9-A processing/review/hold route; prove duplicate-safe partial-progress and 17-A send behavior before any replay. A duplicate receipt is not a newly received reply. | Processor return, queue acceptance, support acknowledgment or resetting attempts alone cannot prove the reply was handled or authorize releasing an independent hold. |
| Engine instruction | Use 2-A exact-command freshness, recovery and accepted/applied evidence, with 7-A reconstruction only where allowed. Preserve protected/successor state and pending original commands. | A new engine, SENT flag, successful start or transport acknowledgment alone cannot mean pause/resume/inbound continuation actually applied. |
| Event publication | Permit only original-identity republication where the event-specific downstream effects and duplicate handling have been verified, or retain a supported reconciliation/escalation path. Treat acceptance followed by lost acknowledgment as possibly published. | PUBLISHED can close the publication obligation when supported by publish evidence; it does not prove a consumer ran or a business action/customer message succeeded. |

For every enabled recovery:
- Require current workspace/role/object authorization, actor and reason, original item/episode and
  an expected current version. Revalidate source disposition, actual side-effect evidence and any
  relevant lead/workflow/hold/successor at submission and before effects, not only when showing a button.
- Preserve original event, command and logical-touch identities, committed provider claims, partial
  progress, pinned mode/configuration and count/history. An exception, expired lease or missing
  receipt is not proof that nothing happened. At-least-once publication or webhook processing is
  not made exactly-once by displaying a retry button or retaining message_id alone.
- Admit one bounded recovery owner/request; duplicate clicks, response loss and concurrent ordinary
  workers find that same request or a truthful conflict/superseded result. R2 chooses explicit
  attempt/lease/timeout/recurrence bounds without changing ordinary retries. Worker restart or a new
  request ID cannot reset budgets indefinitely; renewed exhaustion remains visible and versioned.
- Do not replay the originating business operation to recover its transport. In particular, a
  signal retry must not repeat the inbound reply or operator command that created it, and publication
  retry must not rerun the domain transaction. Unsafe or unprovable duplicates remain contained.
- Keep recovery-pending work in the unresolved inventory even if its source becomes claimable again.
  Show requested, attempted, transport accepted, applied/processed or still blocked at their actual
  boundaries. An evidence-backed superseded/no-longer-applicable disposition is distinct from
  successful execution and needs retained reason/actor/current authority. Seen or manual dismissal
  cannot fake business success or clear a reply/consent/human-control restriction.
- Preserve independent application holds and the actual released B baseline. Recovery permission
  is not resume/force-send/consent-lift permission. Do not retag, start from step one, spend another
  enrollment start, consume an unprocessed touch, replace an uncertain send, or release handoff
  ownership to make the failure disappear. Late results reconcile evidence without overriding newer
  authority; downstream work that remains pending or failed stays separately visible.

### 3.5 Complete the scoped operator journey

- **Discover and inspect:** list individual stopped obligations with safe cause, age, source,
  affected context, status and support/action reference. Lead-linked items are reachable from the
  appropriate lead/Attention journey; workspace/non-lead/multi-lead or absent-anchor work has its
  own authorized operational destination. The generic settings card is not the only route.
- **Keep permissions at the source:** filter workspace and permitted lead/workspace scope before
  pagination, counts, detail joins and exports. Honor existing wider-role reporting and assigned-agent
  visibility without inventing manager/team authority or granting service-worker privileges to users.
  Recovery requires its own current authorization. R3 defines safe metadata versus sensitive detail
  scope and a usable role-specific destination; an admin-only link cannot be the manager's remedy.
- **Handle reassignment and absent anchors honestly:** current ownership determines the authorized
  viewer/action, not the incident's historical identity. Do not drop a workspace failure because no
  assigned agent exists, leak sibling leads through a multi-resource envelope, or create a lead from
  untrusted identifiers just to make a link. Removed/inaccessible context is shown as unavailable
  only within a scope the viewer may already inspect.
- **Keep counts meaningful:** distinguish stopped obligations from affected leads, source rows,
  attempts and related incidents. A transient FAILED row is not “gave up,” and a source-row or
  episode list must declare its counted unit. Correlated 9-A/2-A items do not double-count the same
  obligation, while separate child obligations remain discoverable. Explain historical inventory
  additions; no client-only sum of the first page can claim the full unresolved population.
- **Keep seen separate from resolved:** reuse per-user acknowledgment/versioning. Unresolved seen
  work stays available through the all/unresolved view and its unresolved count; a filtered “all
  reviewed” view must not say the system is healthy. A different stopped source item or materially
  renewed failure cannot inherit an old acknowledgment merely because the aggregate count stayed
  the same. Routine polling or an age label ticking is not a new failure version.
- **Traverse and refresh:** define stable complete pagination, source filters and sort/age meanings
  across all three queues and older episodes. A full page from one source cannot starve another.
  Revalidate stale detail/action state; source status changes and lost responses produce truthful
  results after refresh. A latest-workflow-only join or first-100 lead fetch is not complete coverage.
- **Distinguish loading, empty, unavailable, partial and stale:** a failed source read must remain
  visible as a coverage gap, not an empty array. Preserve known items with clear freshness where
  appropriate; acknowledgment failure cannot hide them. If only two queues loaded, label that
  partial result rather than “no failures.” No success toast before a durable recovery request.
- **Verify a remedy or escalation:** show the actual permitted correction destination and status
  after submission. An unauthorized/unsupported replay has a clear reason and owned route, not a
  broken button. Do not imply that operators can edit message payloads or directly update queue rows.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Source and evidence contract | Approve per-source terminal/retrying/live/interrupted/legacy matrix, authoritative attempt-budget semantics, original obligation/episode/child correlation, safe reason/count/time/age fields, protected-state invariants and exact integrated A/B baseline. | Domain/application classification and read-contract implementation |
| R2 — Durable ownership, discovery and safe recovery | Choose source-backed versus retained projection design; approve terminal/evidence commits, current-version/claim fencing, batch rollback and stale/late-result handling, malformed-row isolation, independent post-outage discovery, compatibility and event-specific recovery matrix/bounds. Name required 9-A/2-A/7-A/17-A integrations or explicit disabled-replay routes; verify transport-versus-business success evidence. | Persistence/worker/projection/recovery implementation and integrated safety acceptance |
| R3 — Operator, permissions and presentation | Approve API/UI fields/copy, authorized workspace/assigned/absent-anchor detail and action scope, usable role-specific support/correction route and owner, current-version/reasoned submissions, counts/history/seen/pagination and unavailable/partial handling. | API/web/operator implementation; an unowned support-only route cannot ship as complete |
| R4 — Historical cohort, rollout and operations | Approve separately authorized metadata inventory/correction/replay scope, compatible schema/worker/read ordering, exact cohort/rates/stop criteria, visibility-lag and stale-worker/coverage thresholds, independent monitoring and incident owner, canary evidence and evidence-preserving rollback. | Production rollout and accepted-live claim |

Approve applicable R1–R3 and §4–5 test boundaries before implementation; R4 rollout decisions do
not block unrelated baseline reproduction. This draft chooses no new retry budget, escalation
window, incident schema, bulk-recovery power or historical replay policy by fixture default.

## 4. Business acceptance scenarios — for approval

Each changed behavior requires a demonstrated meaningful failing test before its implementation.
Use synthetic saved events/commands and controlled failures with recording external-port fakes.
**These are not passing tests.** Fill each case's exact categories, limits, scopes and permitted
dispositions from the applicable gates; the baseline defaults below are not new policy choices.

At R2/R3, record which recovery operations are enabled for each source/category. A replay-only
subcase may be explicitly approved as not applicable for a support-only category; its acceptance
must instead demonstrate disabled replay and the owned non-replaying escalation journey. This
does not waive visibility, authorization, no-side-effect or ordinary positive controls. Record that
approved applicability separately from a required integration test that was skipped or blocked.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Fail a native FUB envelope initially and through its remaining allowed retries until count 3; include a multi-resource/no-lead envelope. | One EXHAUSTED processing obligation is queryable through the approved API/Attention path with native source, safe cause, evidenced age/count and authorized context/support route. | Only a log, waiting for another retry/user click, label it a queued classifier failure, fabricate a lead, or reset the first failure time. |
| AC-02 | Enqueue a normalized inbound reply, claim/process it through three failed attempts, then perform fresh operator reads. | Same original inbound identity and visible exhausted item; integrated 9-A processing hold/review remains effective and correlated without duplicate review creation. | Exhausted row vanishes from every list, background visibility clears the reply hold, duplicate inbound message or another automatic touch while that hold applies. |
| AC-03 | Persist an invalid queued inbound payload and an existing native permanent fetch failure before the maximum; separately reject a malformed never-accepted ingress request. | Saved PERMANENT_FAILURE items are visible as early-terminal work with correct cause and known attempts; ingress rejection retains its own response, not an invented persisted event. | Pretend three attempts occurred, retry poison automatically, silently discard saved failures or promise to recover a payload never saved. |
| AC-04 | Deliver an invalid/unsupported stored signal and a not-found target that is not restartable. | Each TERMINAL_FAILURE has a discoverable original-command item/reason; protected, missing or superseded targets keep their actual state and scope. | Signal silently abandoned, auto-restart a protected target, mutate the latest journey or treat all terminal signals as budget exhaustion. |
| AC-05 | Fail a signal's delivery and separately its permitted restart through the authoritative maximum, default 10, leaving FAILED and a future available_at. | Stopped instruction is visible within the approved visibility bound after committed final failure, without another retry or user-triggered discovery; no promised next retry or extra ordinary claim. Exact command and unresolved application evidence remain. | Only TERMINAL_FAILURE queried, an eleventh attempt, false “retry scheduled” from available_at or engine restart alone marked command applied. |
| AC-06 | Fail event publication through its default ten allowed attempts and read the individual item and scoped counts. | Exhausted publication is distinguishable from transient FAILED, with source/reference, safe reason, age and owned remedy; original domain fact remains intact. | Aggregate settings card is the sole result, another automatic publish, failure notification required for visibility or business transaction replayed. |
| AC-07 | Fail each path transiently, then succeed within its existing budget; include due/future work and the first permitted successful attempt. | Existing backoff/eligibility and legitimate processing/publication/instruction delivery work; no unresolved terminal incident is created for each intermediate failure. | Every FAILED means dead, all workers disabled to pass negative cases, premature terminalization or changed ordinary attempt limits. |
| AC-08 | Provide legitimate live signal/outbox leases at the final count, then persisted expired DISPATCHING/PUBLISHING rows with unknown external result; deliver a late result. | No premature stealing while live; expired stopped/interrupted work is visible with unconfirmed effect, versioned ownership and safe evidence reconciliation. | Lease expiry proves rejection/no-send, force extra dispatch, permanent invisibility because status is not FAILED, or stale result overwrites a newer authoritative disposition. |
| AC-09 | Compare queued inbound count-zero claims, native initial count-one attempts, rolled-back attempts and legacy inconsistent/unknown status/limit combinations. | Source-specific R1 classification/count labels use committed evidence; unsupported legacy states remain evidence-limited and owned. | One global threshold applied to every table, in-memory count asserted durable, or every old FAILED row described as ten failed network calls. |
| AC-10 | Fail before/after claim, final-status, required evidence and commit boundaries; lose a successful commit response and restore the database. | Independent sessions prove the atomic or source-reconstructable result, stable original episode and honest recording/coverage failure; retained terminal facts become discoverable after service recovery. | Uncommitted record advertised as saved, failed secondary projection hides a committed source forever, or repeat external effect merely to recreate evidence. |
| AC-11 | Claim a batch, commit/roll back its first item, and concurrently process a remaining item in another worker; race terminal recording with newer recovery/success. | Real Postgres proves current ownership/version checks prevent stale batch objects overwriting the newer result; each stopped obligation and original attempt evidence stays truthful. | SKIP LOCKED claimed to last after commit, process-local lock used as concurrency proof, contradictory terminal/success state or duplicate side effects introduced by recovery. |
| AC-12 | Stop the source worker after a committed terminal failure, fail an asynchronous projection if chosen, and run the approved inventory/repair without any user action or retry-eligible item. | Source-backed reads or monitored repair discover the same original item; independent coverage observes stalled projection/worker status under R4 bounds. | Another dispatch, notification, next_action_at, successful worker log or lead click is required to notice stopped work. |
| AC-13 | Put a malformed enum/payload/anchor in a persisted row before valid terminal items from each source and traverse the inventory. | Safe metadata classification/isolation with explicit limits; authorized valid items remain reachable and the malformed reference has an owned investigation route. | Full payload coercion aborts every list, poison row starves all later work, fabricated context or raw payload dump to diagnose it. |
| AC-14 | Observe the same failed source repeatedly and through 9-A/2-A views; also create separate failed envelope/child/signal/publication obligations affecting one lead. | One episode per original obligation and explicit correlation with existing review evidence; distinct pending siblings remain visible with meaningful counted units. | Duplicate review for another surface, collapse all items by lead, or fixing publication automatically resolves the inbound reply or failed command. |
| AC-15 | Use synthetic legacy items with unknown terminal time/cause, future available_at, native provider occurrence time and queued terminal processed_at; refresh with a later clock. | Correctly labelled created/received/observed/discovered times, stable evidenced age and explicit unknowns; generic safe cause when detail is not known. | Browser time/last CRM sync/backoff due time invented as exhaustion time, processed_at called success, or maximum count presented as measured external calls. |
| AC-16 | Store synthetic sensitive markers in last_error, queued body, FUB envelope and provider-shaped data; include markup in a display label. | Public responses, new logs/exports and UI expose only approved safe metadata; no synthetic confidential marker leaks and labels render inertly. | Raw fields exposed because named payload_redacted, length truncation treated as sanitization, or arbitrary CRM/credential URLs made actionable links. |
| AC-17 | Read list/detail/count/history and submit recovery as assigned agent, unrelated agent, manager, permitted administrator, inactive member and another workspace. | Server enforces declared workspace/object/role scope before pagination and independently on actions; safe valid role-specific routes work. | UI-only filters, service bypass exposed to users, cross-tenant identifier/count leakage, wider resume rights or an admin-only dead end for managers. |
| AC-18 | Reassign a linked lead; remove or deny access to its anchor; include non-lead aggregate, multi-lead envelope and no assigned agent. | Current permitted viewers change appropriately; stable source identity and authorized workspace support retain orphan/non-lead work without leaking siblings. | Failure disappears when owner is null, UUID assumed to be lead_id, guessing an assignment, or old agent keeps action rights from cached detail. |
| AC-19 | Create enough stopped work to cross pages in all sources, including older failures behind many unrelated leads and simultaneous new arrivals. | Stable complete traversal and declared counts/sort semantics; source and tenant scope apply before limits, no source starvation, history remains reachable under 4-A. | First-100 leads or one source page treated as complete, missing oldest failures, double-count from joined resources or stale total asserted exact. |
| AC-20 | Fail one source/detail/history read, stale another, and fail acknowledgment data; also exercise genuine empty and loading states. | UI distinguishes partial/stale/unavailable/empty and preserves known items safely; unavailable seen data cannot hide failures or imply healthy coverage. | Rejected request caught as empty array, two loaded sources called “all clear,” or stale detail still authorizes recovery. |
| AC-21 | Mark an item seen, keep it unresolved, replace it with different stopped work at the same aggregate count, then produce renewed exhaustion after a permitted recovery attempt. | Per-user seen and unresolved counts remain distinct; all/unresolved view retains work and new/materially renewed failure gets correct identity/version. | Old aggregate seen marker hides new work, polling age creates endless new alerts, or “all reviewed” is presented as repaired automation. |
| AC-22 | Correct a supported native envelope cause and request approved recovery; separately offer no safe replay for a permanent/ambiguous case. | Original envelope/resource effects stay deduped under current data/rules; actual supported action yields evidence or stays pending. Unsupported case has disabled replay, clear reason, safe reference and usable owner/support destination. | handle(replay=True) returning duplicate is called fixed, repost/delete-dedupe workaround, current CRM data claimed to be an original snapshot or unowned “ask support.” |
| AC-23 | Recover an exhausted queued reply after correction with prior partial classification/CRM effects and a possibly accepted AI response; also recover a proven unattempted eligible case. | Integrated 9-A/17-A retain receipt, STOP/hold, original send claim and accurate reply outcome; no repeat possible send, and a genuinely permitted first effect still works. | New event/idempotency key, lost-receipt means unsent, automatic hold release from retry request, or blocking every legitimate recovery to pass no-duplicate tests. |
| AC-24 | Recover a failed instruction after a permitted same-journey engine restart; include a stale pause/resume for a protected or successor run. | Integrated 2-A/7-A preserve the original command and prove accepted versus applied/no-longer-applicable; no newer authority is overwritten. | SENT/new engine equals applied, instruction recovery repeats its originating inbound action, reopens a terminal run or starts at step one. |
| AC-25 | Recover an eligible publication with prior broker acceptance followed by lost acknowledgment; exercise actual routing and the affected consumer's duplicate handling where replay is offered. | Original event identity retained, event-specific side effects remain safe, and publication completion is labelled at its real boundary; downstream pending/unknown/failure is not erased. | message_id alone claimed dedupe proof, generic republication without consumer safety evidence, or PUBLISHED means all business effects/customer delivery succeeded. |
| AC-26 | Double-submit recovery, lose its response and race it with workers, a late successful result and another operator; restart the runtime while recovery fails again. | One authoritative bounded request with stable reference/history; truthful pending/conflict/settlement and visible recurrence without counter resets or hidden extra attempts. | New request IDs/process starts create unlimited retries, stale recovery overwrites success, or resetting source count deletes exhaustion history. |
| AC-27 | During recovery race STOP/DNC, unresolved replies, manual pause, handoff/human ownership, workspace controls, completion, reassignment and successor creation. | Current permission and safety are revalidated at relevant effect boundaries; original claims/progress and independent holds remain; evidence-only recovery does not mutate nurture. | Technical retry grants force-send/resume/consent lift, retagging/new enrollment bypass, repeated uncertain touch or Class B outcome change. |
| AC-28 | Successfully complete only publication/transport acceptance, leave a child obligation failed, and separately record an evidenced no-longer-applicable disposition. | Boundary-specific completion, related unresolved work and reasoned supersession are distinct and retained; manual seen/dismissal is not business success. | Queued/accepted means reply handled/command applied, parent resolution clears every child, or marking seen writes PROCESSED/SENT/PUBLISHED. |
| AC-29 | Make existing notification/CRM update fail or omit its destination while source work becomes terminal; separately stop workers/discovery and later restore services. | Required local visibility survives secondary failures; independent monitoring identifies stale coverage/worker progress with R4's chosen thresholds and owner, not fictitious per-item exhaustion. | New mandatory notification, recreate classification review on delivery success, silence means healthy, or an outage starts blanket holds/replays. |
| AC-30 | Inventory synthetic legacy terminal/interrupted/unknown/successful/superseded rows and rehearse compatible old/new worker, schema, reader and rollback combinations. | Approved evidence-strength/cohort treatment and contained unsafe replay; durable failure/history/claims and usable scoped read/support survive rollout/rollback. Unknown historic dates/effects stay unknown. | All historic FAILED rows replayed, limit change silently resurrects work, fabricated original times, or downgrade removes evidence/read access under new terminal states. |
| AC-31 | For each queue, demonstrate saved work → actual stopping condition → fresh API/client/Attention detail → the approved remedy or support-only route → refreshed disposition; also demonstrate disabled replay/escalation for an unsupported category. | Complete human journey using real Postgres and real engine/broker at claimed boundaries plus recording external-port fakes; reasons, ages, permissions and independent unresolved work agree. An enabled recovery proves its actual result; a support-only category proves owned non-replaying escalation and honest unresolved status, not pretend execution. | Manually inserted terminal fixtures or mocked helper success plus screenshot offered as complete proof, nonexistent action endpoint, disabled replay without an owned route, or a fake transport asserted real integration. |
| AC-32 | Run ordinary native/queued inbound processing, transient signal/publish recovery, legitimate cadence/paused-search/AI/operator work and existing reviews beside the feature. | Working positive controls and all existing STOP/consent/human-control/timing/progress/uncertainty protections remain under the declared released A/B baseline. Visibility changes no contact, notification or automatic replay policy. | All useful work disabled, duplicate review/lead/touch/start, changed ordinary retry budget or a Class B rule hidden in this Class A PR. |

AC-30 authorizes synthetic rehearsal only, not production access or replay. Already-correct
positive/protected controls may pass on the baseline; changed behavior still needs meaningful red.
Required skipped integrations are missing evidence, never a green acceptance result.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Persisted source → worker outcome → operator read:** native FUB handler/retry, normalized
  inbound queue/processor, signal dispatcher and event publisher through actual public application
  entry points and fresh API results. Cover ordinary retry controls and each real stopping form,
  not only a new classification helper (AC-01–09/12–15/31–32).
- **Durable ownership/evidence:** real migrated Postgres with independent sessions for claims,
  batch commit/rollback, terminal/projection atomicity, source version, duplicate/race/late result,
  RLS and historical compatibility. Direct storage assertions are appropriate at this explicitly
  approved persistence boundary; operator acceptance still needs public reads (AC-08–19/26/30).
- **Recovery effects:** original inbound application path with recording CRM/LLM/provider fakes;
  integrated 2-A/7-A and real Temporal for command acceptance/application; real RabbitMQ for
  publication/routing plus the affected actual consumer path when republication is offered. Inject
  acceptance-before-ack loss, partial progress and legitimate first attempts; fake transport alone
  proves neither actual delivery nor safe consumer effects (AC-22–28/31–32).
- **Human journey:** agreed API/client/component/route boundaries for list/detail/count/history,
  role/current-ownership checks, safe labels, pagination, seen versions, error states, supported
  correction/submission and unsupported escalation. No fixture-only action/read contract or direct
  database edit presented as operator acceptance (AC-14–22/28–31).
- **Independent operational coverage:** exercise source reads/projection repair and the chosen
  liveness observation with a stopped producer/worker, storage outage and no user wake-up. Distinguish
  unavailable coverage from a known terminal item; rehearse monitoring and rollback separately from
  new business behavior (AC-10/12–13/20/29–31).

**Allowed fakes:** controlled clocks and hand-written recording CRM/LLM/messaging/notification/
transport fakes at external ports, plus repository fakes for narrow application decisions. Do not
fake terminal classification, safe replay, deduplication, outcome ownership or permissions that are
the subject of the test. Existing fake/monkeypatch tests are starting points, not evidence of real
database locks, durable attempt accounting, broker routing or Temporal command application.
Expected categories/counts/times come from approved scenarios, not the same production helper.

1. Agree applicable R1–R3 and the seams. Start with one of AC-01/02/05/06 on the unchanged baseline:
   exhaust real source work and demonstrate the absent or misleading individual operator result.
   A saved EXHAUSTED/FAILED fixture alone is setup, not proof of the worker-to-reader journey.
2. If a proposed API/projection does not exist, add only the smallest non-working public seam needed
   to express the agreed expectation. An import error, missing new enum or fake preprogrammed to
   return an incident is not meaningful red. Record baseline reproduction separately from seam setup.
3. Take one vertical case from meaningful red to minimal green, then add the next failure/control.
   Do not bulk-write speculative private-helper tests or implement a universal queue framework first.
4. Run the single test, affected file/package and adjacent safety/positive controls. Use real
   Postgres/Temporal/RabbitMQ where those guarantees are claimed; a skipped integration stays open.
   Prove partial-batch and acknowledgment-loss behavior, not just a happy-path terminal update.
5. Demonstrate critical sensitivity: locally remove the exhausted-FAILED predicate, live-claim or
   current-version guard, tenant filter, original identity protection, safe metadata allowlist or
   accepted-versus-applied check and show its test fails. Pair no-replay assertions with a legitimate
   allowed action, transient retry or a clearly usable unsupported-replay escalation path.
6. Independently review expectations against source, gates and integrated A/B behavior. Attach
   exact revisions, commands, meaningful red/green, counts/skips, sensitivity and integration gaps.
   No new dependency, browser project, live provider traffic or production fault injection is
   authorized by this draft. A document validation result is not a behavioral test result.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Fill during implementation | Not run in this draft | Required before change | Required | Required where applicable | Explicit, never hidden as pass |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. A shared stopped-work read
contract, retained episode and scoped replay API are proposals, not claimed existing symbols.
Trace all writers/readers, migrations, worker wiring and adjacent integrated tests before coding.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — queue facts and internal ports | app/domain/crm_sync.py; app/domain/events.py; app/domain/workflows/temporal_signal_outbox.py; app/application/ports/repositories.py; app/application/ports/event_bus.py |
| API — native CRM failure and retry | app/infrastructure/crm/follow_up_boss/webhook_event_handler.py; app/infrastructure/crm/follow_up_boss/webhook_event_parsers.py; app/infrastructure/crm/follow_up_boss/webhook_event_mappers.py; app/application/use_cases/retry_external_events.py; app/interfaces/workers/crm_webhook_retry_worker.py |
| API — queued reply ingestion and processing | app/application/use_cases/enqueue_inbound_message_event.py; app/application/use_cases/process_queued_inbound_message_events.py; app/application/use_cases/process_inbound_message_event.py; app/interfaces/workers/inbound_message_worker.py; app/interfaces/api/dependencies/inbound.py |
| API — command and publication dispatch | app/application/use_cases/dispatch_temporal_signals.py; app/application/use_cases/publish_outbox_events.py; app/interfaces/workers/temporal_signal_dispatcher_worker.py; app/interfaces/workers/outbox_publisher_worker.py |
| API — persistence/claims and original records | app/infrastructure/persistence/postgres/crm_sync_repository.py; app/infrastructure/persistence/postgres/temporal_signal_outbox_repository.py; app/infrastructure/persistence/postgres/outbox_event_repository.py; app/infrastructure/persistence/postgres/models.py; app/core/database.py |
| API — transport versus consumer | app/infrastructure/events/rabbitmq/publisher.py; app/infrastructure/events/rabbitmq/topology.py; app/interfaces/workers/crm_sync_worker.py; app/application/ports/temporal.py |
| API — reporting and permission/read contracts | app/application/use_cases/reporting.py; app/application/ports/reporting.py; app/infrastructure/persistence/postgres/reporting_repository.py; app/interfaces/api/v1/reporting.py; app/interfaces/api/schemas/reporting.py; app/domain/identity/permissions.py; app/application/use_cases/lead_read.py |
| API — existing acknowledgment, action and send boundaries | app/application/use_cases/attention_acknowledgements.py; app/interfaces/api/v1/attention.py; app/application/use_cases/lead_resume.py; app/application/use_cases/lead_review_hold_resolution.py; app/application/use_cases/dispatch_outbound_send_requests.py |
| Web — discovery, versions and client transport | src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/attentionVersions.ts; src/lib/api/reporting.ts; src/lib/api/attention.ts; src/types/reporting.ts |
| Web — operator journey and presentation | src/pages/AttentionPage.tsx; src/pages/LeadDetailPage.tsx; src/lib/presentation/operations.ts; src/components/operations/AttentionItem.tsx; src/app/router.tsx |

**Two engineering approaches to review before coding:**
- **Recommended: source-backed stopped-work projection through one small read contract.** Keep
  original work in its source, add only missing terminal/evidence/recovery metadata, and present
  an authorized combined list/detail through existing operational mechanisms. It avoids another
  delivery queue and makes committed failures readable even if a projection worker is down. Costs:
  source-specific legacy classification, cross-source pagination/count consistency, query/index
  performance and retained recovery history must be solved explicitly, not in browser helpers.
- **Alternative: a durable materialized operational projection linked to the original rows.** Reuse
  existing evidence/review mechanisms where suitable, with atomic source writes or independent
  monitored repair. A uniform projection can simplify reads and pagination under larger load, but
  adds write/reconciliation complexity and possible visibility lag. It is not another authority for
  processing status or replay, and cannot be fed only through the event bus whose failures it lists.

Both need truthful source classification, stable identity/history, authorization and explicit safe
recovery/escalation. Choose at R2 after checking existing integrated contracts and actual query
needs. Neither approves a generic task manager, new broker queue or speculative recovery framework.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_retry_external_events.py
- tests/application/use_cases/test_process_queued_inbound_message_events.py
- tests/application/use_cases/test_process_inbound_message_event.py
- tests/application/use_cases/test_dispatch_temporal_signals.py
- tests/application/use_cases/test_publish_outbox_events.py
- tests/application/use_cases/test_reporting.py
- tests/application/use_cases/test_attention_acknowledgements.py
- tests/infrastructure/crm/test_follow_up_boss_webhook_event_handler.py
- tests/infrastructure/persistence/postgres/test_crm_sync_repository.py
- tests/infrastructure/persistence/postgres/test_temporal_signal_outbox_repository.py
- tests/infrastructure/persistence/postgres/test_outbox_event_repository.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/infrastructure/events/test_rabbitmq_publisher.py
- tests/interfaces/workers/test_crm_sync_worker.py
- tests/interfaces/api/v1/test_reporting.py; tests/interfaces/api/v1/test_attention.py
- tests/application/use_cases/test_business_flow_harness.py
- tests/infrastructure/persistence/postgres/test_business_flow_harness.py
- Web: src/lib/api/reporting.test.ts; src/components/operations/operations.test.tsx; src/app/LeadsRoutes.test.tsx

Existing terminal-state and retry tests do not establish an end-to-end operator inventory, safe
manual replay or complete external delivery. Locate newly integrated 9-A/2-A/17-A and Attention
coverage before adding tests; do not create duplicate helpers solely for this draft's terminology.

## 7. Historical inventory and bounded correction

Production reads/changes require separately approved access and scope. Rehearse on synthetic data.

- Inventory allowlisted workspace/source/original row and correlation IDs, current status,
  evidenced attempts/limit, work/observation/discovery timestamps, lease/retry fields, protected
  context and existing review/recovery references. Do not inspect raw payloads or credentials when
  metadata suffices. This draft asserts no live counts or maximum incident age.
- Classify each source under R1: terminal/exhausted, still retrying, live claim, interrupted at the
  limit, properly completed/ignored, superseded or evidence-limited. A historical FAILED query
  alone is neither a complete inventory nor authority to label/replay every result.
- Inventory and evidence projection are separate from replay. Approve the exact cohort, dry-run
  report, conditional write/version checks, batch/rate limit, operator, stop criteria and any later
  recovery. Preserve original source rows, attempt/episode history and dedupe/possible-send claims.
  Adding visibility must not make the normal workers pick up a previously terminal backlog.
- Keep original failure/receipt/effect time only where evidence supports its meaning, with actual
  discovered/corrected time distinct. A source without a retained terminal timestamp must not get
  a fabricated one from a due time or migration time. Unknown history and partial external effects
  remain explicit; 4-A cannot recover payloads/history that no usable copy retained.
- Proven correlation may attach a safe lead/workspace reference without executing the original
  CRM/reply/command operation. Missing or conflicting anchors require owned investigation, not
  guessed identity, new enrollment or a send to find out whether an old attempt worked.
- Any supported recovery follows §3.4's per-source matrix with required integrated protections.
  Unsupported/ambiguous work stays contained with reason and owner. A valid no-longer-applicable
  disposition retains its evidence and is not falsely counted as successful processing/delivery.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test gates with named owners and actual A/B dependency
   versions. Verify effective per-path limits, workers, database policies, source/read/action wiring,
   compatibility and monitored inventory coverage; no new numeric policy is inferred from this draft.
2. **Safe rehearsal:** run AC-31 for each source, transient-success controls, terminal-after-commit
   discovery, partial-batch concurrency, live/expired claims, possible prior external acceptance,
   unsupported replay and meaningful role/error/seen states. No deliberately broken production
   service or real-customer test message is authorized.
3. **Compatible cutover:** stage approved additive evidence/classification/read support and source
   writers, with independent repair if needed. Enable recovery only after its protections exist.
   Prevent old workers from misreading new dispositions, clearing evidence or resuming terminal
   work; preserve real Temporal history compatibility wherever command/recovery behavior changes.
4. **Bounded activation:** use the approved synthetic/canary cohort and verify each committed
   terminal form reaches the correct operator surface within the chosen bound. Inventory old work
   separately; no automatic historic replay or new lead hold as a feature-enable side effect.
5. **Operator acceptance:** show reasons, truthful ages/counts, missing-context support, seen versus
   unresolved, pending versus completed and a still-unsafe recovery. Demonstrate an actual owned
   correction/escalation destination, not just queue counts. Explain newly visible historical work.
6. **Monitor and respond:** track new terminal work by source/category, unresolved count/oldest known
   age, discovered legacy/evidence gaps, recovery pending/failed/renewed outcomes, duplicate/stale
   write rejection, partial read/projection lag and ordinary successful processing. Observe worker/
   inventory liveness independently of the failing worker's logs; name thresholds, owner and response
   at R4. Monitoring does not itself introduce new customer/agent notification or replay policy.

**Rollback:** stop unsafe new classification/projection mutations or recovery through the approved
scoped control and contain incompatible workers. Preserve original source dispositions, incident/
attempt history, dedupe/send/command claims, application holds and all current protected states.
Keep compatible readers and an owned support route; do not delete terminal rows, lower counts,
clear seen/evidence, requeue every failure or broaden send rights to make dashboards green.
Already-started external effects may settle and cannot be undone. A forward-compatible repair may
be safer than reverting to a worker that does not understand persisted terminal/recovery state.
Retain independent coverage of unresolved/contained work and separately approved follow-up.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact and Class A scope; applicable R1–R4 and test-boundary
  decisions close with exact contracts/owners before their implementation or release.
- [ ] Native and queued inbound terminal work, both signal terminal forms, exhausted publication
  and supported interrupted/legacy cases have correct source-owned, durable, queryable outcomes.
- [ ] Normal bounded retries and live claims remain valid; commit/rollback, late results,
  source/projection repair and concurrent recovery preserve truthful identity, state and history.
- [ ] Actual scoped list/detail/count/Attention/lead/support paths show safe reasons and truthful
  age/context, complete traversal, seen versus unresolved and unavailable/partial coverage.
- [ ] Every category has an approved usable remedy or owned escalation. Enabled recovery is
  bounded, original-identity and duplicate-safe, with permissions/protections and actual success
  evidence; unsupported replay is explicitly disabled, not a hidden incomplete feature.
- [ ] Existing reviews and distinct related obligations remain intact; no invented nurture hold,
  notification/contact policy, unsafe replay, released claim or false downstream-delivery promise.
- [ ] Meaningful red-first/green, sensitivity, working positive controls and real integration
  evidence at claimed boundaries are attached; skips/limitations are explicit.
- [ ] Historical treatment, compatible canary, independent monitoring and evidence-preserving
  rollback are rehearsed and separately authorized for production reads/actions.
- [ ] Independent product and technical reviewers accept the implemented journey; merged and
  accepted-live evidence remain separate. This draft checks none of those implementation boxes.

## 10. Related records and draft review record

- [Source Issue 15 — work that fails permanently disappears](../production-state-consistency-issues.md#issue-15--work-that-fails-permanently-disappears-from-every-queue)
- [Business-impact contract — show background work that stopped retrying](../production-state-consistency-issues.md#15--show-background-work-that-has-stopped-retrying)
- [D1–D7 consensus and separate ship classes](../production-state-consistency-review-consensus.md)
- [9-A — inbound receipt, deterministic STOP, reply hold and exhaustion](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [2-A — original command and accepted/applied evidence](issue-2-a-reliable-instruction-delivery.md)
- [17-A — durable sends and retained possible-acceptance claims](issue-17-a-durable-outbound-dispatch.md)
- [7-A — independent missing-engine discovery and reconstruction](issue-7-a-missing-engine-recovery.md)
- [10-A — source native-activity exhaustion, not a new queue owner here](issue-10-a-exhausted-engine-failure-visibility.md)
- [4-A — durable, scoped operational evidence](issue-4-a-retained-operational-evidence.md)
- [16-A — durable contact restrictions through refresh](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [1-A — scheduling holds and permitted recovery](issue-1-a-visible-scheduling-holds.md)
- [3-A — original enrollment and first-action accounting](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [5-A — durable send-time holds](issue-5-a-durable-send-time-holds.md)
- [6-A — explicit returned cannot-proceed outcomes](issue-6-a-visible-cannot-proceed-outcomes.md)
- [8-A — separate completion and G1 late-reply contract](issue-8-a-completion-lifecycle.md)
- [12-B — separately approved carrier opt-out behavior](issue-12-b-carrier-opt-out-handling-and-fallback.md)
- [13-B — separately approved consent and fallback policy](issue-13-b-consistent-consent-and-channel-fallback.md)
- [14-B — separately approved tag-only CRM control](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [17-B — separately approved uncertain-send accounting](issue-17-b-continue-cadence-after-uncertain-send.md)

Draft source trace completed against API a761c1b and web 04d4361 on 2026-09-08. It distinguishes
native CRM versus queued inbound attempts; early-terminal versus exhausted FAILED outcomes; source
facts versus derived reviews; committed attempts versus rolled-back work; engine/broker acceptance
versus business completion; and the existing aggregate warning versus missing item-level visibility.

Independent technical/source and fresh-reader reviews completed. Review findings clarified
status-based inbound retry exclusion, the approved asynchronous visibility bound and the
support-only acceptance route. A focused reader recheck found no remaining material contradiction
in those clarifications; it did not waive integration evidence or any R1–R4 decision.

Documentation validation passed (exit code 0): ten numbered sections, all 32 scenario IDs, R1–R4,
review-only/test-first guards, table/whitespace checks, 72 existing source/test references, 19 local
draft links (including heading anchors) and 38 index links. The index covers eighteen drafts and
seventeen source issues. The earlier seventeen drafts retain their recorded aggregate SHA-256:
cf1b196c5cccd3d8a07764ec4bf4b7dfb7200ad631730219c6dec0c586ad347e.
No implementation or live behavior is claimed.

Stakeholder review and R1–R4 remain open. No application code or prior ticket draft was changed;
no behavioral tests, production access, Jira publication, implementation or release was performed
for this draft.
