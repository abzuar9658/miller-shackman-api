# Issue 3-A — Report accurate enrollment progress and enforce the daily start cap

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the tenth proposed Jira description, not a published issue or permission to implement.
Continuing the drafts does not approve implementation, production data repair or release.

## 1. Business impact — read this first

**The promise:** An enrollment must show its real progress, record when it actually begins once,
and consume the existing daily start allowance reliably. “Selected,” “engine started,” “nurture
begun” and “message delivered” are different facts; one must not stand in for another.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | An enrollment remains “queued” while its workflow is nurturing, paused or handed off. Its missing start time also makes the daily-start counter miss it, so successive batches can each use the same apparent allowance. |
| Why does that matter? | Operators cannot trust enrollment progress or time-to-start. The intended throttle on new outreach fails, exposing the brokerage to backlog bursts, provider limits and deliverability risk. |
| What changes? | Enrollment progress follows its own workflow; the agreed first real action records a durable, once-only start. Cap-governed starts share authoritative capacity across batches, retries and concurrent callers. |
| What does a cap of two mean? | With no earlier usage or pending claims for the agreed campaign/day, only two cap-governed new enrollments may begin. A third remains visibly deferred, even if another batch or worker tries to start it. |
| Does this limit every message to two per day? | No. This is a new-enrollment start cap, not a message, channel, AI-turn or paused-search touch cap. Already-started eligible journeys keep their existing cadence and send-time protections. |
| What counts as “begun”? | A specific first enrollment action must be approved at R1 and used consistently across standard and paused-search modes. Creating a row, initializing an active state or receiving an engine-start response is not automatically that evidence. It is not a delivery receipt. |
| Which starts share the allowance, and when does the day reset? | R2 must name the covered routes, counted sources and exact day boundary. Existing automatic cap controls are included. Unclear manual/direct-route treatment is not permission to invent exemptions or silently broaden policy. |
| What happens to a cap-held lead? | Keep the lead discoverable with the reason and a usable, approved later-start path. On a later attempt, recheck current eligibility and capacity; do not require retagging, create a second journey or promise an automatic midnight start that has not been built. |
| Will starts slow down after release? | They can: distributing new starts across days is the intended repair. A cap deferral must be distinguishable from an operational failure or a lost candidate. The configured cap is not increased to disguise this effect. |
| Does pausing, resuming or finishing free another slot? | Not for an enrollment that already began that day. Its historical start remains counted once; recovery of that same journey does not count as another start. Never-begun pending capacity needs the explicit R2 release/revalidation rules. |
| Are completion and re-entry changing? | No. Project terminal outcomes that already occur, but do not decide when a standard cadence completes or enable automatic re-entry. Issue 8 and its G1 late-reply contract remain separate. D2's former joint-release volume gate is closed. |
| Can old missing start times be filled with today's time? | No. Repair supported facts from correlated evidence; preserve unknowns. Stamping all old rows today would manufacture history and distort the allowance. Production repair needs separate authorization. |
| Are consent, CRM controls or uncertain-send policy changing? | No. Preserve the separately released baseline and all independent safeguards. Class B changes must not enter this Class A PR. |

**A better badge alone is not the fix.** The same durable facts must support admission, reporting,
lead inspection and safe later processing. A cap-held candidate is not necessarily an enrollment
row yet, and an enrollment's workflow phase is not proof that its execution engine is healthy.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — misleading lifecycle evidence and ineffective new-start volume control; confirm at publication |
| Source / delivery class | Production-state consistency Issue 3 / **Class A: enrollment lifecycle and existing daily-cap repair** |
| Components | Enrollment/workflow projection; once-only start evidence; cap admission and start handoff; scoped progress/reporting and cap-held continuation |
| Repositories | miller-schackman-api and miller-schackman-web; complete start → progress/read → cap-defer → later-start journey |
| Sequence | Tenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A and 2-A. Draft order is not proof that any predecessor shipped. |
| Integration dependencies | Declare the actual release baseline. Preserve 16-A/9-A safeguards; coordinate 1-A hold projection, 2-A/7 same-workflow engine recovery and 17-A identities where their paths intersect. |
| Completion boundary | Consume existing terminal transitions and preserve their enrollment identity. Issue 8 owns new standard-cadence completion and G1 late-reply behavior; it is not required merely to repair start accounting. |
| Not a prerequisite | Shipping 14-B, 13-B or 17-B. Do not introduce their policy changes here or revert a B policy already separately released. |
| Decision ownership | Name implementer, independent reviewer, lifecycle/persistence owner, cap-scope/day owner, API/web owner and release/recovery operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced and rechecked 2026-09-07; retrace the implementation branch. Source investigation counts are historical, not a new production measurement. |
| Closure boundary | Truthful lifecycle/start evidence, hard enforcement for the approved cap scope, usable cap-held continuation and evidence-based historical handling; not a general scheduling or analytics platform. |

**Included:** normal and paused-search enrollment lifecycle, initialization as well as subsequent
transitions, existing capped automatic routes, retries/recovery of those starts, affected campaign
reporting and authorized lead/held-candidate inspection. Every route through shared start machinery
must be inventoried at R2 so the guarantee cannot be bypassed accidentally.

**Excluded:**
- New completion deadlines, post-completion reply routing, automatic dormant re-entry, or new
  manual/CRM-tag enrollment rights. D2 is closed because completion alone does not auto-re-enroll.
- Changing cap values/defaults, eligibility, preflight/veto policy, source priority, message-frequency
  limits or send timing. No weighted scoring, new contact calendar or generic quota/rules engine.
- Unapproved cap exemptions or restrictions for a previously unresolved source. Any genuine policy
  expansion needs a separate Class B decision/release, not a quiet change in this A repair.
- General missing-engine reconciliation, all-cause stall dashboards, new notifications, broad
  historical analytics redesign, bulk backlog activation or blind production backfills.
- New consent/fallback, tag-only CRM control or uncertain-as-sent behavior. A start timestamp must
  not become a second send-permission rule or alter provider-message/occurrence accounting.

**D7:** A and B must not share a PR. The R2 source/day clarification does not authorize changing
who is contacted under the guise of fixing a counter; escalate any policy change separately.

## 3. Current behavior and contract to approve

### 3.1 What the code does today

The shared starter saves CampaignEnrollment as QUEUED with started_at=None. It creates the
LeadWorkflow and initial transition separately, optionally commits, then invokes Temporal. Its
STARTED result means that start call returned; it does not persist an enrollment start timestamp.
A failed engine start can leave the earlier committed enrollment/workflow present.

Standard cadence begins in QUEUED and transitions to ACTIVE_NURTURE during cadence-step execution,
before outbound preparation. Paused-search callers can initialize a workflow as ACTIVE_NURTURE
before the engine starts. They therefore need not cross that transition on their first execution.
Neither assigning ACTIVE_NURTURE nor hooking only the standard transition establishes one consistent
first-action contract. Future scheduling, an initial hold and successful provider delivery are also
different events and must not be collapsed into a guessed start time.

The shared state-transition use case synchronizes only COMPLETED, SUPPRESSED and CLOSED enrollment
statuses, and only when its optional enrollment repository is provided. Intermediate states are
not mapped. Adding a mapping without tracing initialization, direct saves and production callers
would leave gaps. In start_paused_search_campaign_enrollment, a separate post-pinning path promotes
an existing QUEUED workflow to ACTIVE_NURTURE without passing that repository. This needs coverage
distinct from fresh active initialization; merely adding the mapping will not fix this caller.
Conversely, the existing active-enrollment partial index already includes CANDIDATE and QUEUED:
the stale “queued” symptom does **not** prove uniqueness protection is absent.

The enrollment repository's save is an insert/upsert against the non-terminal workspace/campaign/
lead key, not a targeted lifecycle update by enrollment ID. It ignores enrollment.created_at and
computes datetime.now(UTC) for created_at on every call, in both the insert and conflict-update
values. The stored creation time therefore becomes repository-call time and advances on an upsert
retry. It also copies the incoming started_at and other snapshot values into the conflict update,
so stale saves can overwrite lifecycle/lineage evidence. Existing statement-shape tests do not
prove correct original timestamps, row updates or concurrency behavior in real Postgres.

count_started_today counts enrollment rows for a workspace and campaign whose started_at is in
the supplied clock's midnight-to-next-midnight interval, retaining the supplied timestamp's timezone.
It does not filter by current status, campaign version or source. Starts produced by the traced
missing-writer path are invisible to it.
This is a count of enrollment starts, not provider submissions or unique leads over all history.
The code does not resolve the business document's open brokerage-midnight question.

The dormant selector and the dormant branch of CRM-tag enrollment read that count before deciding
which candidates to start. The domain batch rule correctly limits one supplied list using the
supplied count; it cannot reserve capacity against another batch. A late timestamp write alone
still leaves a window for overlapping or not-yet-executing starts. The CRM-tag paused-search branch
returns through a direct start path before the count; manual and other direct start/track paths
also need explicit coverage decisions rather than an assumption that they use the selector.

The dormant selector's mixed routed candidates share one selection decision, including candidates
routed to paused-search. That control must remain effective across later starts, not just within
one in-memory list. Cap-held results are not by themselves a durable deferred-start queue: a held
tag event or a later selector run needs a real path back to the candidate without relying on another
CRM change. The dormant query excludes leads with any prior enrollment for that campaign or any
workflow; creating placeholder rows without changing the continuation path can strand deferred work.

Campaign reporting groups stored enrollment statuses independently from workflow states. The web
detail page renders both groups, displays the configured cap, and describes selector started_count
as “started immediately.” Those counters do not establish the R1 first-action evidence, remaining
capacity or eventual execution. Broader workflow-only views are not automatically enrollment views;
do not relabel every workflow or historical enrollment as the lead's current run.

### 3.2 Maintain one lifecycle projection and distinct start evidence

Keep the business workflow as the source of operational state. Extend the existing projection or
derive it on read with an approved migration; do not maintain an independent competing lifecycle.
The following is the **proposed mapping to approve**, not a claim it already exists:

| Business workflow phase | Enrollment projection | Start/evidence rule |
| --- | --- | --- |
| ELIGIBLE, where supported | CANDIDATE | Eligibility is not enrollment execution. No fabricated start. |
| QUEUED | QUEUED | Awaiting work; actual-start evidence remains separate from selection or pending capacity. |
| ACTIVE_NURTURE, WAITING_FOR_RESPONSE, RESPONSE_PROCESSING | ACTIVE | Mirrors operational phase, not engine health, provider receipt or proof of the first action. Initialized active and legacy evidence gaps must remain distinguishable. |
| PAUSED | PAUSED | Preserve a recorded start; a pause before the first action does not itself create one. Keep the real hold reason/history accessible. |
| HUMAN_HANDOFF, HUMAN_OWNED | HANDOFF | Keep human-control meaning and permissions; do not free the active-enrollment uniqueness slot or imply campaign completion. |
| COMPLETED, SUPPRESSED, CLOSED | Matching terminal status | Project an actual existing terminal decision and preserve its first end time. An enrollment can end without ever beginning. |

1. Apply the approved mapping at initialization and every relevant state-write path, including
   holds, inbound processing, human control, resume, track changes and existing terminal outcomes.
   A legal workflow transition, its history and its enrollment projection must commit coherently.
   Optional dependencies or a direct save must not silently leave the old projection behind.
2. Target the enrollment owned by the specific workflow, scoped by workspace and validated lineage.
   A delayed activity from a prior run must never update whichever enrollment is currently latest.
   Reject/record missing or inconsistent linkage; do not silently create a replacement enrollment.
3. R1 must name the first real action and evidence for each mode: initial scheduling versus first
   due execution, an initial hold/skip/review, and workflows initialized active before execution.
   Define which of those actions qualifies and why. The same business meaning must hold across modes;
   choosing a convenient enum transition or waiting for confirmed delivery is not a definition.
4. Write started_at once from that action's authoritative time and identity. Repeated first-action
   execution, subsequent touches, replies, pause/resume, engine restart and late evidence do not
   rewrite it or consume another start. A proven historical correction is separately audited.
5. Preserve creation/enrollment/eligibility time, source, actor, pinned campaign version and prior
   start/end evidence during projection updates. updated_at represents the real update, not a new
   enrollment. Preserve terminal absorption and database uniqueness; ordinary save/upsert must not
   resurrect history, merge two runs or null a known start through a stale retry.
6. Operational phase, pending/confirmed first action, capacity claim and provider outcome remain
   distinguishable. In particular, an active initialization or historical ACTIVE row with unknown
   start time cannot be advertised as verified started, healthy execution or unused capacity.

### 3.3 Enforce the existing cap across time and competing callers

**Scope contract:** approve both “counts toward the budget” and “must pass the start gate.” The
current counter has no source filter; a caller bypass is not evidence of an intended exemption.

| Route to inventory | Verified baseline / required R2 treatment |
| --- | --- |
| Dormant selector, including selected paused-search routes | Uses daily count and one batch selection; retain the existing shared cap/FIFO contract through actual start. |
| CRM-tag route to dormant cadence | Uses the daily count and start rule; retain its existing cap contract and current approved preflight treatment. |
| CRM-tag route to paused-search | Direct branch bypasses the count; resolve covered versus intentionally exempt, citing the approved policy. Do not silently leave a documented covered route open. |
| Manual-admin, assigned-agent manual, selected-track/direct paused-search and track reassignment paths | Inventory actual entry points and distinguish new enrollment from an in-place change. Record counting, enforcement and permission contracts; no new entitlement or exemption is implied. |
| Retry, held-candidate continuation, engine recovery and already-running result | Classify by whether this same enrollment already began, still has pending capacity or has never begun. Transport start/restart is not a new enrollment. |
| New enrollment after a permitted terminal outcome | Use a new enrollment identity under existing re-entry permission/reason rules and the approved source scope. Do not add automatic re-entry or Issue 14's unshipped exception. |

1. Use one authoritative workspace/campaign/day budget for all covered callers. Do not reset it for
   each batch, source, engine mode or newly published campaign version. Count actual starts once
   regardless of their later active/paused/handoff/terminal state. Keep existing cap configuration.
2. Checking capacity and durably owning permission for a new start must be atomic across independent
   workers and distinct leads. Locking each lead or counting rows without a shared serialization
   point cannot protect the last campaign slot, especially when no enrollment rows exist yet.
3. If selection/admission can precede the R1 action, account for pending capacity explicitly or
   enforce at that action before it can proceed. A pending claim is not started_at. Two batches must
   not each admit a full allowance simply because neither has reached its first action yet.
4. Approve the exact transaction/claim design, real commit points and failure recovery. Preserve a
   stable enrollment/claim identity through worker or HTTP retries. Losing an engine-start response
   is not proof no action occurred: do not release/reassign capacity while the original can still
   act. A stale claimant must not start after its capacity was released or overwrite a newer owner.
5. Define safe release for work proven never to have begun, cancellation, expiry and reconciliation.
   Do not invent an arbitrary lease or automatically free an uncertain slot. Pending work must be
   bounded and operationally recoverable rather than consuming capacity forever without explanation.
6. Define one explicit half-open day interval and clock authority for counting, admission, execution
   and UI. A delayed start crossing midnight must obtain valid capacity for its actual approved day;
   yesterday's claim cannot be used to exceed today's limit. Revalidate after long waits/transactions.
   Test timezone and daylight-saving boundaries if the chosen contract is local-calendar based.
7. Publishing a new version or changing a cap does not erase usage. Approve which configured value
   governs pending work when versions/caps change; if usage is already at/above it, no further
   governed new starts. Do not stop an already-started cadence or backdate records to fit the limit.
8. Preserve existing eligibility, campaign/workspace controls, vetoes and FIFO among eligible
   candidates. A capacity claim never overrides later consent, ownership, reply, human-control or
   send-time checks. Starting a new run and sending a touch remain distinct decisions.
9. On unavailable accounting or inconsistent identity, do not substitute zero and launch new work.
   Return an honest recoverable operational outcome, distinct from a proven daily_cap_reached.
   Already-started eligible work must not be charged again or globally disabled to make the cap pass.

Any true change to source coverage or day semantics must be identified and separately authorized
under D7 before it can ship. A narrower agreed repair must describe its scope honestly; it cannot
claim a universal cap while leaving unreviewed direct starts outside the enforcement boundary.

### 3.4 Keep deferred candidates usable without changing enrollment policy

- Preserve cap-held candidate identity, original eligibility/FIFO evidence, source, campaign/batch
  context and a durable reason or reliably reconstructable scoped read. A processed CRM event or a
  toast alone must not be the only record that a candidate was held.
- Provide a tested continuation path: an existing supported selector/worker flow where applicable,
  or a narrowly authorized operator action/procedure where no automatic path exists. Name which
  route has which mechanism; do not claim a daily scheduler exists merely from a use-case name.
- Continuation rechecks current eligibility, membership/ownership, campaign configuration, vetoes,
  independent holds and the current day's capacity. Keep the same pending logical start; do not
  re-enroll an active lead, replay an entire CRM event or ask an agent to remove/re-add the tag.
- Candidate state must remain compatible with selector exclusion rules. If a deferred item has an
  enrollment/workflow row, it needs an explicit same-enrollment continuation path rather than being
  sent back through a query that excludes it. Do not relax the no-automatic-terminal-re-entry rule.
- Retain FIFO evidence through retries/delays and identify deterministic ties. Pending preflight,
  vetoed or now-ineligible work must not consume actual starts or silently prevent later qualifying
  candidates from being considered within the approved queue contract. No weighted priority or new
  bypass of a veto/digest is included.
- Repeated later-start requests must converge on one outcome. Show continued cap deferral, changed
  eligibility, cancellation, start pending, actual beginning or operational failure accurately.
  Day rollover grants potential capacity, not permission to clear a human/safety hold or send at once.

### 3.5 Complete scoped reads and operator feedback

- **Campaign:** show accurate enrollment buckets and distinguish them from workflow/message totals.
  Surface the agreed cap scope/day and actual usage, plus pending capacity if used and cap-held work.
  Remaining allowance must come from the authoritative accounting contract, not subtraction of an
  unrelated active-count or a client-side count. Keep version-display versus governing-cap meaning clear.
- **Lead/run:** authorized users can inspect the current enrollment's phase, actual start or explicit
  missing/unverified evidence, relevant end, source and deferral/hold reason with a supported next
  step. Distinguish previous runs; never label their start as the new enrollment's start.
- **Response:** align selector/manual/continuation API types and copy with what has committed.
  Selected, enrollment created, capacity pending, engine start accepted and actual first action must
  not all become “started immediately.” Return a usable reference and refetch durable progress.
- **Counting:** campaign enrollment counts currently count rows, including history, not unique
  current leads. Preserve/label that meaning or explicitly approve a compatible correction. Do not
  sum workflow/enrollment/message buckets into one population or manufacture time-to-start for unknowns.
- **Permissions and reads:** reuse existing reporting versus own-lead permissions, including unowned
  leads for authorized wider roles. Filter before pagination; retain complete traversal and declared
  count semantics for deferred candidates. Do not grant an agent workspace-wide reporting merely to
  expose that agent's lead progress or leak full campaign usage through an unauthorized action.
- **States:** distinguish loading, no enrollments, no deferred work, missing historical evidence,
  permission rejection and failed reads. A failed fetch is not zero usage or a healthy empty queue.
  Refresh affected detail/report/deferred data through existing query patterns, not new live-push
  or guaranteed automatic-start timing. No generic alert/notification platform is required.

### 3.6 Remaining implementation and release gates

| Gate | Required agreement / evidence | Blocks |
| --- | --- | --- |
| R1 — Lifecycle and first-action evidence | Approve the complete mapping and initialization behavior, exact qualifying first action for each supported mode/initial hold or skip, timestamp/evidence authority, never-begun versus historical-unknown representation and immutable lineage/start/end rules. | Lifecycle and start-writer implementation |
| R2 — Cap scope, day and atomic start contract | Approve counted and gated sources/routes, genuine policy-change disposition under D7, exact day/clock and version/cap-change rules, serialization/claim or action-time enforcement, actual commit/engine boundaries, stale-claim fencing, cross-day handling and bounded failure recovery. No silent exemptions. | Cap admission/execution implementation and integration acceptance |
| R3 — Deferred-start and read contract | Approve continuation mechanism per covered route, FIFO/context retention, API/reference/copy, reporting/own-agent permissions, deferred paging/counts, operational failure versus cap-deferral presentation and usable next steps. | API/web/deferred-start implementation |
| R4 — Historical repair and rollout | Approve evidence-based inventory, unknown-current-day accounting/containment, exact production repair scope separately, writer/worker/migration ordering, monitoring, release owners and evidence-preserving rollback. | Production rollout and accepted-live claim |

Approve applicable gates and §4–5 test boundaries before implementation. These are outstanding
decisions/evidence, not a recommendation to guess defaults. A simplified design still has to meet
the promised observable outcome; a different contact rule belongs in separate Class B work.

## 4. Business acceptance scenarios — for approval

These are requirements, not tests already written or passed. Use synthetic leads, fixed clocks,
recording transports and real local/disposable integrations where the claim requires them.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | An admitted standard enrollment performs the approved first real action; repeat for each paused-search mode. | Correct enrollment progress and one started_at tied to that action; fresh reads and the agreed day's count reflect it. | Still queued/null after actual beginning, stamping an unrelated run, or treating provider delivery as the start definition. |
| AC-02 | Create/select an enrollment, accept an engine start, initialize paused-search ACTIVE_NURTURE, schedule a future action, or encounter an initial hold/skip. | For each R1-approved case, qualifying versus not-yet-qualifying evidence is explicit and consistent across modes. No provider delivery or healthy-engine claim from phase alone. | Blind stamp on row creation/ACTIVE initialization, or counting every schedule retry as a new start. |
| AC-03 | Move a started run through active, waiting, response processing, pause, resume, handoff/human ownership and existing terminal outcomes. Separately cover an existing QUEUED workflow promoted to ACTIVE_NURTURE after paused-search track pinning, not just fresh active initialization. | Approved lifecycle mapping remains in step on fresh reads; original start, correct end/reason and human-control restrictions remain. The queued-promotion caller participates in projection without inventing first-action evidence. | Only terminal/initialization synchronization, a stale queued badge after track pinning, a freed handoff uniqueness slot or an invented standard-cadence completion. |
| AC-04 | Pause, suppress, close or otherwise legitimately end an enrollment before any qualifying first action. | Correct phase/terminal projection with no manufactured start; pending capacity follows its approved release/reconciliation contract. | Terminal or pause time copied into started_at, or uncertainty treated as proof the work never began. |
| AC-05 | Repeat the first action, lose its response and retry, or execute duplicate first-action activities concurrently. | One durable first start/evidence identity and one counted start; later retries cannot reset time or add a debit. | Duplicate timestamps/debits, “new engine run = new enrollment,” or fake-only concurrency proof. |
| AC-06 | A prior workflow activity/transition arrives after an authorized successor enrollment exists; include wrong workspace, campaign or enrollment linkage. | Only the correctly identified run can change; stale/mismatched work has an explicit safe outcome and history is preserved. | Update whichever enrollment is latest for the lead, mutate the successor, or silently repair by creating another run. |
| AC-07 | Insert a real enrollment with independently specified creation, enrollment and eligibility times; update it repeatedly and submit an older snapshot after newer progress. | First insert stores the original creation time, not repository-call time; each original timestamp, source/actor, pinned version and known start/end survives updates. Distinct business timestamps need not equal one another. Updates cannot regress lifecycle or merge separate runs. | Replace/reset created_at on insert/upsert, conflate different timestamps, null a known start, overwrite original provenance or resurrect a terminal enrollment. |
| AC-08 | Fail between workflow, transition, enrollment projection and any required first-action/cap writes; read via independent sessions. | Agreed atomic facts commit together or remain unchanged; no success response for partial persistence. Missing projection/linkage fails observably. | A committed workflow with silently stale projection, lost audit or uncounted permission to begin. |
| AC-09 | Cap is two, with three eligible new candidates and no earlier usage; start two, then try the third in a separate same-day batch. | Only two governed starts; the third is cap-held and discoverable with a later-start path. Current day's usage survives batch boundaries. | Each new batch sees zero/two fresh slots, or only testing that a single in-memory list is sliced to length two. |
| AC-10 | One batch contains eligible candidates out of order, a duplicate, a vetoed/blocked item and missing FIFO evidence; some capacity is already used. | Existing eligibility/precedence and oldest-qualifying FIFO determine selection; correct remaining allowance and explicit holds; duplicates do not consume twice. | New scoring, newest-first retries, double debit, missing-timestamp default or bypassed preflight/veto to fill the cap. |
| AC-11 | Independent workers/covered routes contend for the last slot with different leads; repeat from an empty day with no enrollment rows. | Real database serialization admits at most available capacity; losing candidates remain recoverable and unrelated campaign/workspace scopes are isolated. | Per-lead locks or process-local counters presented as a campaign-wide concurrency guarantee. |
| AC-12 | Select/admit work whose first action is delayed; run more batches and direct covered starts before it executes. | Pending capacity or action-time enforcement prevents eventual over-admission; pending and actual-start facts remain distinct and visible. | Unlimited pending engines later begin together because started_at was null during each count. |
| AC-13 | Fail/crash before and after claim/intent commit, engine call/acceptance, first action and outcome commit; include an ambiguous engine response and a stale claimant. | Stable identity and real committed boundaries preserve capacity safety; bounded retry/reconciliation, fenced stale work and visible unresolved outcome. | Blind release after timeout, orphaned reservation forever, external action based on rolled-back permission or stale owner stealing capacity. |
| AC-14 | Exercise just before/at/after approved midnight, delayed work across days and long waits; include relevant local daylight-saving boundaries. | Exactly the half-open agreed day is counted; old pending capacity is revalidated for the actual start day without double debit or overflow. | Rolling-24-hour or server-local guess, backdating to yesterday, or an expired prior-day claim authorizing unlimited starts today. |
| AC-15 | Publish a new campaign version or lower/raise its configured cap while starts/claims exist. | Usage remains shared by campaign; the approved governing-version rule applies to pending work and no extra starts occur when at/above allowance. | Version publication resets usage, config race opens another budget, or already-started cadence is cancelled to fit the new cap. |
| AC-16 | Parameterize the R2 counted/gated route matrix, including both CRM routes, mixed selector routes, manual/direct track paths and recovery. | Every covered path uses the authoritative gate and accounting; any approved exemption/policy deferral is explicit in tests, scope and copy. | Bypass hidden in a direct helper, source omitted from accounting because only selector tests exist, or a new source restriction shipped as A. |
| AC-17 | Starts from today later pause, hand off, complete, close or suppress; subsequent touches/replies also occur. | Each actual start still counts once that day; later phases/touches neither refund nor consume another start. | Count only currently active enrollments, count sends/occurrences, or treat terminal projection as returned capacity. |
| AC-18 | Recover/resume an enrollment that began on a prior day, then recover one whose first action never occurred; include missing historical evidence. | Known-begun same-run recovery retains its original time/progress without new-start debit. Never-begun work obtains valid first-start capacity; unknowns follow R4, not a guessed branch. | Restart resets step one/time, every resume is capped as new, or every queued/unknown legacy row bypasses the gate. |
| AC-19 | An authorized manual re-entry follows an actual permitted terminal outcome; also try automatic selection and unauthorized re-entry. | New run gets a new identity and follows approved source/cap rules; old history is untouched. Automatic and unauthorized re-entry remain refused. | Reopening old enrollment, importing tag-re-add rights not separately released, or treating completion as automatic pool admission. |
| AC-20 | While pending, change consent/DNC, ownership, reply status, human control, campaign/workspace state, eligibility or a veto; then try to begin/send. | Applicable current safeguards and permissions win; the correct hold/rejection is visible and pending capacity is handled safely. | A slot/resume/cap reset authorizes contact despite a later restriction or clears an independent hold. |
| AC-21 | Counting/claim persistence is unavailable or inconsistent; separately execute an already-started otherwise eligible due touch. | Governed new work does not fail open and shows operational failure, not false daily_cap_reached. Existing begun work is not recharged; normal send guards still apply. | Default count to zero, report healthy empty queue, or disable all outreach to make negative tests pass. |
| AC-22 | A dormant candidate is cap-held, then the day advances and the supported continuation path runs, including duplicate requests. | Candidate remains discoverable in original FIFO order and is revalidated/started once with current capacity. Any existing pending row is continued, not excluded forever. | Lost candidate, a second enrollment, reset eligible_at, or relaxation of automatic terminal re-entry exclusions. |
| AC-23 | A CRM-tag candidate is held at the cap and the original event has finished processing; later use its approved continuation path. | Still visible and actionable without another tag/webhook; preserve source/context and start once after current validation. | Remove/re-add tag as a workaround, blindly replay the CRM event or advertise automatic retry when no worker/action exists. |
| AC-24 | Older deferred work now fails eligibility, has a veto/config change or is cancelled; race its stale continuation with a fresh decision. | Correct current reason and safe capacity handling; qualifying work can progress under approved FIFO rules. Stale work cannot override cancellation or reuse reassigned capacity. | Persisted “daily cap” hides a different blocker, starvation via an untraversed blocked prefix, or stale recovery starts disallowed work. |
| AC-25 | Read campaign reporting and lead/run evidence for queued, begun, paused, handoff, terminal, historical and unknown-start examples. | Correct enrollment versus workflow/message buckets, declared row/history semantics, trustworthy cap day/usage and explicit missing start evidence. | Unique-lead assumption applied to enrollment rows, sums of different populations, fabricated duration or ACTIVE treated as a start receipt. |
| AC-26 | Exercise actual API contracts and web feedback for selection, created/pending start, cap deferral, actual beginning, failed start and failed reads. | Truthful response/copy and durable refetch, distinct loading/empty/error states, a usable lead/candidate reference and next step. | “Started immediately” from selection/engine acceptance alone, fixture-only new fields or error rendered as zero usage. |
| AC-27 | Read or continue as owning agent, unrelated agent, permitted wider role, inactive member and another workspace; include an unowned lead. | Existing permission boundaries hold; own-agent progress is usable without workspace reporting or privileged start rights. Scope applies to counts and action feedback too. | Cross-tenant/ownership leakage, widened role to make UI navigation work, or data repair available to any viewer. |
| AC-28 | Put a relevant cap-held candidate beyond unrelated first-page rows; paginate, retry, then refresh after continuation. | Filter before pagination, complete traversal and accurate counts; no duplicate deferred items or vanished unresolved work after a read error. | Limit-before-scope, stale toast as the only evidence, or an empty filtered first page presented as no backlog. |
| AC-29 | Inventory synthetic legacy rows with exact correlated start evidence, only later-message evidence, known never-begun state, missing engine history and conflicting linkage. | Audited dry-run classifies evidence strength; only supported actual times are repairable, unknowns remain explicit, repeat repair is idempotent. | First retained message/created_at/repair time assumed to be the exact first action, wholesale ACTIVE backfill or mutation of the latest unrelated enrollment. |
| AC-30 | Rehearse cutover with legacy unknown starts, pending work and starts already above today's cap; include old/new writers. | Approved scoped containment/accounting prevents extra governed starts; no arbitrary history is fabricated. Old incompatible writers cannot erase new evidence or bypass the gate. | Release reads zero for unknown historical usage, bulk-stamp today, drain the backlog as a test or declare deployment itself repairs history. |
| AC-31 | Replay representative existing/new Temporal histories and duplicate activity/start responses in supported standard/paused-search modes. | Compatible first-action accounting, unchanged pinned journey/timing and idempotent projection; already-begun recovery does not consume again. | Engine reset as migration, initialized ACTIVE skips required evidence, or activity retry doubles a slot/touch. |
| AC-32 | Demonstrate synthetic enrollment → first action → fresh API/UI progress → cap-held third candidate → next-day revalidated continuation, plus a failed-start recovery. | Complete observable journey with real Postgres/Temporal where required and recording providers; legitimate due touch proceeds without duplicate submission or weakened safeguards. | Mocked starter plus static UI used as end-to-end proof, automatic real-customer traffic, or a hidden Class B policy change. |

AC-29–30 are recovery/rollout rehearsals, not approval for production writes. Exact first-action,
source and day expectations must be filled from R1/R2 before tests are written. Existing positive
controls can already pass; skipped integrations remain missing evidence rather than a green result.

## 5. Testing boundaries and mandatory test-first workflow

**Proposed public boundaries — approve before implementation:**
- **Enrollment action → progress and count:** real application start/first-action/transition flow,
  observed through approved enrollment/report reads and the repository's agreed accounting contract.
  Cover both initialization styles, holds, terminal-before-start and retry (AC-01–08/17–19).
- **Selection/admission → actual capacity enforcement:** covered public use cases/entry points,
  successive batches, direct routes, deferred continuation and a fixed day clock. Do not test only
  a pure helper given an artificially correct started_today_count (AC-09–24).
- **Persistence/concurrency:** real migrated Postgres with independent sessions/transactions and
  deterministic barriers for the last slot, no-existing-row race, write rollback, immutable fields,
  stale ownership and day/cap changes. Repository tests are appropriate for these explicitly agreed
  persistence invariants; SQL text inspection is insufficient (AC-05–18/24/27–30).
- **Durable execution:** actual Temporal test environment and replay for first-action evidence,
  accepted/lost start responses, delayed execution, activity retries and supported old histories.
  Use real application activities where their state/commit behavior is the claim (AC-01–02/12–14/18/31–32).
- **Operator journey:** API permissions/contracts and existing frontend route/API tests, then a
  synthetic API-to-UI demonstration of progress, cap-held discovery and the permitted later-start
  path. No new browser/dependency project is authorized by this draft (AC-22–28/32).
- **Safety and useful work:** legitimate due/future work, current consent/reply/human controls,
  preflight/FIFO, immutable send identities and existing uncertainty/CRM policy on the declared
  release baseline (AC-10/16–24/31–32).

**Allowed fakes:** fixed clocks, recording external CRM/LLM/messaging transports and hand-written
repository fakes for fast application scenarios. They must model the agreed public contract without
deciding the expected result themselves. Do not mock the first-action rule, capacity/eligibility
decision, permission check or identity protection being tested. Literal expected counts/times come
from approved scenarios, not another call to the production mapping/count helper.

1. After R1 boundary approval, begin with AC-01: execute the actual first action on the unchanged
   code and demonstrate the missing start/projection through the agreed read boundary. It must fail
   for the business defect, not for a missing proposed method/enum. Cover initialized-active
   paused-search and the existing-QUEUED post-pinning promotion as separate next slices rather than
   assuming the standard transition fix covers both.
2. Add AC-09 as the cap regression: real usage from earlier starts must constrain a subsequent
   batch. A pre-seeded fake count or selecting two of three in one batch does not reproduce the
   production missing-writer defect. Then address independent-session concurrency and delayed starts.
3. One scenario → meaningful red → smallest complete fix → same test green. Continue vertically;
   do not implement the entire feature before retrofitting tests or write all speculative tests first.
4. Record minimal seam scaffolding separately. Missing imports/services, setup failure, skipped tests
   and fake transport success are not meaningful red. Retain already-working selection/uniqueness/
   safety controls; justify a passing baseline instead of manufacturing a failure.
5. Independently break the start write; bypass the shared gate; remove serialization/fencing;
   restore stale whole-row overwrite; refund a terminal start; reuse yesterday's capacity; target the
   successor run; lose a deferred tag candidate; render engine acceptance as actual beginning; remove
   read scope. Each critical test must fail for its intended protection. Restore and rerun; no
   mutation ships. Incidentally fixed cases need sensitivity evidence, not invented red history.
6. Review expectations independently against R1/R2 and unchanged product rules. Do not loosen a
   timestamp/cap assertion to match a convenient caller or mock away a commit/engine race. If the
   source/day/first-action expectation is genuinely ambiguous, escalate it before implementing.
7. Attach exact commands, revisions, exit codes, pass/fail/skip counts and limitations. Repeated
   process-local tests do not prove database serialization; an integration-named file can still use
   fake sessions. Run required real integrations, or leave the corresponding acceptance claim open.

| AC / parameterized case | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / unchanged control | Integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills every applicable case | Reproducible invocation | Business assertion and revision | Revision, exit code and counts | Intended failure when protection is broken, or justified baseline pass | Named remaining limitation |

## 6. Engineering starting points — navigation, not a prescribed design

Paths are relative to the named repository at the reviewed baseline. New first-action, cap-claim,
deferred-read or recovery APIs are not claimed to exist. Inventory real production wiring before
changing a shared signature; no optional dependency may silently retain the broken behavior.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — enrollment model, admission and start rule | app/domain/campaigns/enrollment.py; app/domain/campaigns/enrollment_admission.py; app/domain/campaigns/start_queue.py; app/domain/workflows/models.py |
| API — starter and lifecycle | app/application/services/campaign_enrollment_starter.py; app/application/use_cases/apply_workflow_state_transition.py; app/application/use_cases/campaign_cadence_execution.py; app/application/services/paused_search_track_assignment.py |
| API — automatic start routes | app/application/use_cases/run_dormant_selector_batch.py; app/application/use_cases/process_crm_tag_campaign_enrollment.py; app/application/use_cases/start_selected_campaign_batch.py |
| API — manual/direct/paused-search paths | app/application/use_cases/lead_manual_enrollment.py; app/application/use_cases/start_paused_search_campaign_enrollment.py; app/application/use_cases/start_selected_paused_search_track.py |
| API — enrollment persistence and selector exclusions | app/application/ports/repositories.py; app/infrastructure/persistence/postgres/campaign_enrollment_repository.py; app/infrastructure/persistence/postgres/workflow_models.py; app/infrastructure/persistence/postgres/dormant_candidate_selector.py |
| API — initial and uniqueness schema references | alembic/versions/0007_create_workflow_decision_tables.py; alembic/versions/0067_enforce_active_paused_search_workflow_overlap.py; alembic/versions/0085_enforce_single_active_workflow_per_lead.py |
| API — Temporal activity/start boundaries | app/infrastructure/workflows/temporal/activities.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/infrastructure/workflows/temporal/starter.py |
| API — reporting and permission boundaries | app/application/use_cases/reporting.py; app/application/ports/reporting.py; app/domain/reporting.py; app/infrastructure/persistence/postgres/reporting_repository.py; app/domain/identity/permissions.py |
| API — existing operator entry/read surfaces | app/interfaces/api/v1/campaigns.py; app/interfaces/api/v1/leads.py; app/interfaces/api/v1/preflight.py; app/interfaces/api/v1/reporting.py; app/interfaces/api/schemas/campaigns.py; app/interfaces/api/schemas/reporting.py |
| Web — campaign progress and contracts | src/pages/CampaignDetailPage.tsx; src/lib/api/campaigns.ts; src/lib/api/reporting.ts |
| Web — own-lead and preflight journeys to coordinate | src/pages/LeadDetailPage.tsx; src/pages/PreflightPage.tsx; src/lib/api/leads.ts |

**Compare at least two approaches before coding:**
- **Recommended starting point: extend the existing enrollment projection and authoritative start
  gate.** A single lifecycle mapping plus targeted identity-safe updates preserves existing reads
  and uniqueness. Use the smallest real database serialization/claim mechanism that bridges
  admission to the approved first action; reuse existing state/ports where possible. This limits
  migration scope and keeps reporting inexpensive, but every state writer/caller and commit boundary
  must participate. A timestamp assignment or count inside a per-lead lock is not sufficient.
- **Alternative: derive enrollment phase from its workflow and retain separate durable first-start
  accounting.** Removes duplicated phase writes, but requires migrating all readers/filters and
  partial-index/admission assumptions, handling historical joins and proving scoped query cost.
  It does not remove the need for immutable start evidence, atomic cap ownership or deferred-start
  recovery. Prefer it only if the owner accepts the broader migration and it materially simplifies
  the product rather than introducing another competing projection.

Obtain design approval first. Keep SQL/Temporal details in adapters; avoid long network work under
campaign locks or receipt activities that deadlock on them. Define commit-before-execution handoff
and recovery against the actual callers, including their commit callbacks. Use additive approved
migrations, not edits to old migrations, and preserve one-active-workflow/enrollment constraints.

**Existing test starting points, not claimed new coverage:**
- tests/application/use_cases/test_start_selected_campaign_batch.py
- tests/application/use_cases/test_run_dormant_selector_batch.py
- tests/application/use_cases/test_process_crm_tag_campaign_enrollment.py
- tests/application/use_cases/test_campaign_cadence_execution.py
- tests/application/use_cases/test_schedule_next_paused_search_action.py
- tests/application/use_cases/test_lead_pause.py; tests/application/use_cases/test_lead_resume.py
- tests/application/use_cases/test_lead_paused_search.py; tests/application/use_cases/test_business_flow_harness.py
- tests/application/use_cases/test_reporting.py; tests/application/use_cases/_campaign_enrollment_fakes.py
- tests/domain/campaigns/test_start_queue.py; tests/domain/campaigns/test_enrollment_admission.py
- tests/domain/workflows/test_workflow_transitions.py
- tests/infrastructure/persistence/postgres/test_campaign_enrollment_repository.py
- tests/infrastructure/persistence/postgres/test_dormant_candidate_selector.py
- tests/infrastructure/persistence/postgres/test_reporting_and_rls.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_postgres_e2e.py
- tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py
- tests/infrastructure/test_temporal_lead_nurture_workflow.py
- tests/interfaces/api/v1/test_lead_manual_enrollments.py; tests/interfaces/api/v1/test_reporting.py
- Web: src/app/AdminOperationsRoutes.test.tsx; src/app/LeadsRoutes.test.tsx; src/lib/api/reporting.test.ts

The current enrollment repository tests use a fake session and inspect statement shape. Add real
row/transaction tests rather than claiming their directory name proves Postgres coverage. Revisit
fakes that key only by workspace/lead/campaign: they cannot represent multiple historical enrollments
for one lead faithfully. Locate/add exact lifecycle/claim/deferred-route tests after boundary approval.
Run Python 3.12/uv: an exact pytest node, its file, related suites, then make lint, make typecheck
and make test. For web changes run focused Vitest targets, then pnpm test, pnpm typecheck and pnpm
lint. Record integration targets and skips. No live CRM/provider sends are authorized by this draft.

## 7. Existing records and evidence-based repair

- Deliver a scoped dry-run inventory/runbook linking each enrollment to its actual workflow and
  retained transitions/actions/messages. Separate never-begun pending work, supported exact first
  action, begun with unknown original time, terminal records and inconsistent/missing linkage.
- Correct phase from valid workflow evidence without asserting a start time it cannot prove.
  Initialization timestamps, the earliest retained message and later ACTIVE/WAITING phases may
  establish limited facts, not the exact original first action. Record evidence strength, original
  value, correction time, actor/reason and unresolved cases; do not guess from absent engine history.
- Start/end/provenance repair must be idempotent, tenant/run scoped and race-safe against live state
  changes. Prefer targeted conditional updates through an approved procedure. Do not re-run
  enrollment, send a message, reset cadence progress or signal every engine merely to repair a row.
- Before enabling the repaired gate for an affected campaign/day, approve how known starts,
  uncertain historical usage and pending work are reconciled or conservatively contained. Unknown
  usage must not read as a fresh empty budget. Do not choose an arbitrary count or blanket “started
  today” backfill. Where evidence is insufficient, name the containment and follow-up owner.
- Rehearse partial repair failure, repeated execution, concurrent new starts, day rollover and
  already-over-cap data. Existing excess is evidence, not a reason to delete starts or refund slots.
  Preserve safe ongoing journeys; any temporary operational restriction requires scoped approval.
- Any production inventory/repair operation needs approved environment/workspace/campaign/row scope,
  operator, exact commands, limits and verification. Report safe counts and needed identifiers, not
  raw contact/message content, provider payloads or credentials. No repair tool is claimed to exist.
- Deployment fixes future writes; it does not reconstruct missing history. Live acceptance requires
  verified treatment of affected in-scope records or explicit containment with an owned follow-up,
  plus a usable route for genuine cap-held candidates. General engine recovery remains Issue 7.

## 8. Production rollout, acceptance and rollback

1. **Before release:** close applicable R1–R4/test-contract gates, record exact covered sources/day/
   first-action meaning and actual integrated A/B baseline. Confirm permissions, all writers, startup
   paths, schema/index changes and the cap-held continuation mechanism; no unseen bypass is accepted.
2. **Safe rehearsal:** demonstrate AC-32 plus sequential/concurrent last-slot, delayed/cross-day
   start, failed/ambiguous engine response, stale upsert, terminal-before-start and evidence-limited
   historical cases. Use real disposable Postgres/Temporal and recording providers where required.
3. **Compatible cutover:** stage approved additive schema and writer/API/web/worker changes. Drain
   or contain incompatible old paths that can null timestamps, skip accounting or misreport pending
   work. Prove running-history compatibility; do not blanket-restart workflows or discard constraints.
4. **Historical handling:** run only separately authorized §7 repair/containment. Verify fresh scoped
   evidence and cap use before allowing new governed starts. Track repaired, unknown, pending and
   still-blocked records separately, without turning all old work into today's starts.
5. **Operator acceptance:** show accurate phase/start evidence, truthful configured-versus-remaining
   capacity, cap deferral and later continuation, including own-agent and wider-role experiences.
   Explain reduced new-start throughput as the restored cap, not guaranteed fewer total messages or
   a guaranteed start time. Unknown history must remain visible rather than cosmetically “fixed.”
6. **Observe:** monitor governed actual starts versus allowance, pending capacity age/recovery,
   cap-held count/age/continuation, projection drift, null or rewritten known start times, rejected
   stale/duplicate work and unexplained start failures. Break down by approved scope without exposing
   tenant data. Verify legitimate ongoing nurture still works; result counters alone are not proof.

**Rollback:** contain incompatible new-start writers/continuation first using an approved operational
procedure. Preserve lineage, start/end evidence, pending ownership, workflow history and constraints.
Do not restore a false zero count, clear claims while old actors can still run, erase repaired facts
or present pending work as started to satisfy old UI. Keep already-started safe work and scoped status
inspection usable under a compatible rollback/forward-fix plan. No schema drop, bulk replay or
production mutation is authorized without the same scope/approval discipline as recovery.

## 9. Definition of done and evidence to attach

- [ ] Stakeholder approves business impact, Class A scope and unchanged behavior; applicable R1–R4
  and §4–5 test boundaries close with named owners before their implementation or release.
- [ ] Initialization and all supported progress/terminal paths maintain the correct enrollment
  projection; first start is evidenced once, with immutable lineage and truthful unknown history.
- [ ] Covered new starts cannot exceed the approved campaign/day allowance through sequential or
  concurrent batches, direct callers, delayed execution, retries, version changes or stale ownership.
- [ ] Pending versus actual-start capacity, no-refund behavior and already-started recovery are
  correct; independent eligibility, send, human-control and re-entry protections remain intact.
- [ ] Authorized users can inspect progress/usage and discover/continue cap-held work through the
  approved end-to-end path. Permissions, counts, pagination, copy and error states are verified.
- [ ] Every applicable scenario has recorded meaningful red/green or unchanged-control/sensitivity
  evidence and exact commands. Required real database/Temporal and API-to-UI evidence is attached;
  skipped/missing integrations remain blockers to their corresponding claim.
- [ ] Historical inventory/repair, compatible rollout and rollback are rehearsed; production scope
  is separately approved. No fabricated start times, blanket re-enrollment or real-customer test send.
- [ ] Independent review confirms no mixed A/B policy, speculative framework or duplicate source
  of truth. Merged code, historical repair and accepted-live business outcome are recorded separately.

## 10. Source references and review record

- [Main issue plan — Issue 3 and its business-impact appendix](../production-state-consistency-issues.md)
- [D1–D7 consensus — D2 closure and strict ship classes](../production-state-consistency-review-consensus.md)
- [Existing enrollment eligibility and FIFO intent](../../business-rules/02-campaign-enrollment-eligibility.md)
- [Existing start queue, hard cap and unresolved day boundary](../../business-rules/03-campaign-start-queue-and-preflight-veto.md)
- [Issue 1-A — visible scheduling holds](issue-1-a-visible-scheduling-holds.md)
- [Issue 2-A — instruction evidence and same-workflow recovery](issue-2-a-reliable-instruction-delivery.md)
- [Issue 9-A — reply/opt-out safety](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 16-A — opt-out preservation](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 17-A — separate send durability and identity](issue-17-a-durable-outbound-dispatch.md)

**Draft review (2026-09-08):** Independent product-reader review found no material gaps. The
technical/test-contract review found the draft ready for stakeholder review with two clarifications,
now included: repository-call-time replacement of created_at on insert/upsert, and the separate
existing-QUEUED paused-search promotion path. AC-03/07 and the test-first guidance cover those cases;
creation, enrollment and eligibility times are preserved individually, not assumed equal.
Document/reference checks passed with exit code 0: 66 source/test paths, all draft/index links,
table/whitespace checks, AC-01–32, ten main sections, four gates and ten indexed drafts. The prior
nine drafts match their recorded aggregate SHA-256 baseline; API/web source worktrees remain clean.
These reviews do not close R1–R4 or approve implementation/publication. No application code or
earlier ticket changed, and no behavioral tests, production repair or release ran for this draft.
Implementation and integrated acceptance evidence remains outstanding.