# Issue 16-A — Keep recorded opt-outs when CRM data refreshes

**Status: DRAFT — stakeholder and test-contract review required.**
This is a proposed Jira description, not a published Jira ticket or an implementation report.

## 1. Business impact — read this first

**The promise:** When a lead has told our platform to stop contacting them, a routine update from
Follow Up Boss must not make the platform forget that request.

| Business question | What this ticket means |
| --- | --- |
| What can go wrong today? | We correctly record an SMS opt-out, email unsubscribe, or do-not-contact request. A later CRM update can erase that record because the CRM does not contain the same information. A later send, resume, or enrollment can then encounter incorrect permission information. |
| What changes after the fix is deployed? | The platform retains the recorded restriction and why it exists, even if the CRM field is empty or says contact is allowed. SMS opt-out continues to block SMS; email unsubscribe continues to block email; do-not-contact continues to block both. |
| Why does this matter? | It reduces unwanted outreach, complaint risk, and support work caused by the platform forgetting a lead's request. It repairs an existing safety promise; it does not authorize more outreach. |
| What changes for agents? | Editing a CRM consent field will no longer erase an opt-out recorded by the platform. Resuming or re-enrolling a lead is not permission to clear that restriction. This accepted loss of a CRM-only workaround must be communicated. |
| What stays the same? | Normal CRM updates continue. This ticket does not change when campaigns start, when a paused lead resumes, or whether outreach continues on another channel after an opt-out. Those policies are separate work. |
| What about leads affected already? | Deploying the fix does not recreate information already lost. Evidence-backed recovery is included below and must be approved and verified before affected outreach is re-enabled. |
| Can a lead opt back in through this release? | This ticket does not add that capability. START/resubscribe and an audited human-clear action are approved targets, but complete working routes have not been verified. Do not advertise them as available or bypass the restriction manually. |

**Timing matters:** merging the PR alone changes nothing in a running production deployment.
The preservation fix takes effect when the relevant services/workers run it. Historical repair is
a separate, explicitly authorized operation, not an automatic consequence of merging or deploying.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Bug / High — consent-state integrity; confirm priority when publishing |
| Source | Production-state consistency Issue 16 |
| Delivery class | **Class A: defect repair and evidence-backed recovery** |
| Repository / components | miller-schackman-api / CRM refresh, canonical lead state, persistence, recovery |
| Implementation prerequisite | No preceding issue; begin after this draft's scenarios and testing boundaries are approved |
| Owners | Assign implementer, independent reviewer, and release/recovery operator before execution |
| Reviewed baseline | API revision a761c1b, reviewed 2026-09-05; recheck entry points on the implementation branch |
| Closure boundary | This slice covers preservation and recovery, **not every target in the parent Issue 16** |

**Included:** all four CRM refresh paths; platform-owned channel/global restrictions and provenance;
safe persistence under overlapping writes; existing paused-search preservation; newer agent-activity
timestamp preservation; tested, bounded recovery tooling and its release runbook.

**Explicitly excluded and still tracked in the parent plan:**
- New START/resubscribe or permission-checked human-clear journeys: G4 follow-up, not a dependency
  for retaining existing opt-outs. No unrestricted database-clear workaround.
- New courtesy CRM opt-out notes/custom-field writes and their retry mechanism: separate delivery.
  Local protection must work even when no such CRM write exists or succeeds.
- Channel fallback, carrier-error classification, unknown-consent policy, or new workflow outcomes
  from Issues 12/13; STOP-before-AI and reply-hold changes from Issue 9.
- Issue 14's tag-control changes and removal/relocation of agent-activity writers/readers.
- General CRM reconciliation refactors, a new consent-management UI, and production execution
  without explicit authorization.

**D7 release rule:** do not mix Class A and Class B behavior in this PR. The approved cross-channel
target is not being reopened; it simply must not be smuggled into this preservation fix.

## 3. Current behavior, root cause, and expected contract

Today, inbound/provider processing can save a restriction on the canonical lead (the platform's
internal lead record). CRM refresh then constructs a fresh record. The shared preservation function
carries paused-search fields forward, but not suppression flags, suppression types, or evidence.
The database upsert replaces those values. A paused/terminal workflow can hide the defect; it does
not make the incorrect lead record safe for another journey.

The four required refresh paths are full/incremental CRM sync, a Follow Up Boss people webhook,
pre-send refresh, and on-demand refresh. Fixing only one caller is not sufficient.

**Business contract to approve before tests are written:**
1. A platform-observed restriction survives missing, false, unknown, or apparently permissive CRM
   values. CRM data may add a restriction; it cannot retract a platform-observed one.
2. Preserve channel identity: SMS is not email, and a channel restriction is not global
   do-not-contact. Preserve the consistent flag/suppression-type representation used by consumers.
3. Preserve the recorded provider/source, original event identity, and occurrence time. Do not
   replace platform provenance with CRM provenance or invent missing historical evidence.
4. Keep fresh CRM-owned information updating. Do not retain the entire old record or indiscriminately
   latch every CRM permission-status value. Fresh consent-status information does not override an
   independent platform restriction. Where provenance establishes a restriction was CRM-only,
   retain baseline-supported CRM updates, including clearing that CRM-only restriction. This is
   not a new platform opt-out-lifting route. Ambiguous legacy provenance goes to recovery review,
   not an invented source or silent clear.
5. Keep app-owned paused-search state intact. For last_agent_activity_at retain the newest known
   timestamp; null/older input must not erase it, and a genuinely newer value must win.
6. Preserve these rules when a CRM refresh overlaps a suppression write, not only in serial tests.
   A successfully committed restriction must not be lost when a stale CRM snapshot saves afterwards.
7. Recovery never enrolls, resumes, or sends. Preservation must not create eligibility by losing a
   platform restriction. Existing baseline-allowed CRM updates and tag enrollment remain unchanged;
   neither enrollment nor resume lifts a platform restriction. Keep current human-control rules.

## 4. Business acceptance scenarios — for approval

These are **requirements awaiting review**, not claimed passing tests. Expected results come from
this contract, never by calling the implementation to generate the expected value.

**Common setup:** synthetic leads with valid destinations and a fixed clock; known workspace and
CRM identity; platform events with distinct source IDs/times. Hold unrelated eligibility and safety
conditions constant. For AC-01–03, test **each of the four refresh paths**, using CRM fields omitted
and explicitly false; also test apparently permissive consent status. For sync, include full and
incremental operation. Raw webhook/mapper cases must really exercise omitted-field mapping.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Record a platform SMS opt-out, then refresh from stale/empty CRM consent. | Re-read lead retains SMS block, its suppression type, and original evidence. | SMS becomes allowed because the CRM forgot the opt-out. |
| AC-02 | Record a platform email unsubscribe, then run the same refresh cases. | Re-read lead retains email block, its suppression type, and evidence. | Email becomes allowed or the block changes into an SMS/global restriction. |
| AC-03 | Record platform do-not-contact, then refresh with false/missing DNC. | Global block and evidence remain; both channels are blocked. | Either channel becomes allowed. |
| AC-04 | Platform SMS restriction exists; CRM adds email/DNC restriction or conflicting provenance. | Existing platform restriction/evidence survives; new restrictions are honored without misattributing their source. | One source overwrites another's established opt-out evidence or drops a restriction. |
| AC-05 | A fresh lead has no platform restriction; CRM adds a restriction. Separately refresh a fully eligible, unrestricted control lead. | New CRM restriction is honored; unrestricted control remains unrestricted and can complete its ordinary allowed send. | Fix ignores new CRM restrictions, suppresses everyone, or blocks every send. |
| AC-06 | Refresh ordinary CRM fields on a lead with a paused-search profile and an agent-activity timestamp. Try null, older, and newer timestamps. | Supported CRM field updates still apply; paused-search profile remains; newest known agent timestamp wins. | Returning the whole old record freezes CRM updates, or preserving consent erases other app-owned state. |
| AC-07 | Repeat/reorder stale refreshes; separately make CRM fetch fail or return no lead. | Restriction/evidence remains stable; failure does not save an unrestricted replacement; existing pre-send fail-closed behavior remains. | Duplicate/failed refresh clears consent or invents a successful refresh. |
| AC-08 | On an otherwise eligible journey, apply restriction, perform refresh, and attempt the blocked channel through the real send use case. | Zero fake-provider calls on the blocked channel; persisted lead and blocked outcome identify the actual restriction. DNC produces zero calls on both. Matched unrestricted controls dispatch once. | A test passes only because of an unrelated pause, missing destination, or mocked send decision. |
| AC-09 | Begin refresh with an unrestricted read; commit an opt-out in another transaction; let the stale refresh save. Also test the opposite order. | Fresh database read retains the committed restriction and evidence in both orders; test uses deterministic barriers. | Last-writer-wins erases the opt-out, or a single-session fake is presented as concurrency proof. |
| AC-10 | Two workspaces share a CRM lead identifier; refresh or repair only workspace A. | A changes as required; B is untouched. | Restriction or event evidence crosses workspace/provider identity boundaries. |
| AC-11 | Seed proven historical opt-out events with erased lead flags, including an ignored lead_not_found event whose lead now exists. Dry-run, apply, refresh, and apply again. | Dry-run writes nothing; apply restores restriction/provenance under §7's selection rule; valid existing provenance is retained; refresh retains it; second apply makes no additional consent-state change. | Replay clears another restriction, loses evidence, sends contact, or depends on the original event being processed again. |
| AC-12 | Repair input includes duplicate, multiple same-restriction, unrelated delivery, unresolved identity, and insufficient-evidence cases; reorder inputs, interrupt, and retry a bounded run. | Proven matches restore safely with the same selected provenance under §7; unrelated events do not suppress; unresolved cases are reported without guessing; restart is safe and totals reconcile. | Choosing evidence by batch order, treating every failure as an opt-out, fabricating evidence, or declaring incomplete recovery successful. |
| AC-13 | Refresh/repair paused, handed-off, terminal, and unrelated clean leads; read lead detail afterwards. | Workflow/human-control rules remain unchanged; lead-detail API exposes retained flags and channel sendability reasons; clean controls remain clean. | Consent restoration resumes nurture, clears a handoff, or creates messages/enrollments as a repair side effect. |
| AC-14 | Refresh an otherwise eligible tagged lead with no platform restriction. Separately change a proven CRM-only restriction to an allowed value, as supported by the baseline. | Existing tag-enrollment behavior still works without duplicate enrollment; CRM-only fields still update. A matched platform-restricted lead retains its restriction under the same CRM input. | Blanket preservation disables valid CRM updates/enrollment, or CRM-only clearing is misused to clear a platform opt-out. |

AC-08 is about blocking the opted-out channel, **not** introducing cross-channel fallback. Establish
the permitted control's current baseline behavior first. Do not change workflow policy or disable
production safety guards to obtain a convenient test setup.

## 5. Testing boundaries and execution rules

**Proposed boundaries — approving this ticket approves these, not a particular implementation:**
- Application journeys: real suppression application → each real refresh entry point → repository
  read; real send use case with refreshed state and recording provider fakes; current tag-enrollment
  orchestration for the positive control (AC-01–08, AC-13–14).
- Infrastructure: actual Follow Up Boss mapper/webhook adapter with synthetic raw payloads;
  real Postgres repository round-trip and independent transactions in a disposable database
  (AC-01–04, AC-06–10). The single-session rollback fixture alone cannot prove AC-09.
- Recovery: a callable, bounded repair boundary with dry-run/apply behavior, tested against fixture
  histories and real persistence (AC-10–13). Its implementation/name is not claimed to exist today.
- Read surface: lead-detail API plus a small staging UI check of existing sendability panels
  (AC-13). No new API/UI capability is required just to display existing flags/reasons.

**Allowed fakes:** external CRM transport, LLM output for a known classification, SMS/email provider,
clock, and application-test repositories. Reuse hand-written repository fakes for fast tests, but
use real persistence for durability/race/recovery claims. A fake LLM supplies inputs; real opt-out
application logic must process them. Cover hard-word, classified-reply, and provider-observed
origins already supported; AI failure ordering belongs to Issue 9, not this ticket.

**Not allowed as acceptance proof:** stubbing preservation, contactability or send decisions;
mocking upsert into returning the expected object; private-helper-only tests; snapshot assertions
copied from the implementation; a zero-send assertion with no legitimate-send control.

### Mandatory red → green workflow

1. Review the scenario and expected/forbidden outcomes first. Write **one behavioral test**, run it
   against unchanged application code, and capture the meaningful failure before implementing it.
   **New recovery boundary:** write the test first; if the callable does not exist, add only minimal
   interface/no-op scaffolding so the test runs and fails on the missing business effect. Record
   that scaffolding revision separately; an import error is not the qualifying red result.
2. Implement the smallest correction for that scenario; rerun the same expectation until green.
   Continue one scenario at a time, rather than building the whole fix and backfilling tests.
3. For shared fixes, later path tests may already pass. Prove their regression value by running
   them against the baseline with only the test addition, or by the isolated sensitivity check.
   Unchanged-behavior controls may pass from the start; do not manufacture a failure.
4. Import failures, invalid fixtures, collection errors, unavailable infrastructure, skipped tests,
   and an empty selection are not red evidence of the business defect or green acceptance.
5. Do not weaken expectations to obtain green. Explain/review genuine fixture corrections;
   changing a business expectation requires owner approval.
6. Sensitivity: in an isolated checkout/database, disable the restriction-preservation behavior,
   then the concurrent-write protection, and verify their tests fail for the intended reason.
   Disable repair application and verify the restoration check fails. Restore the fix and rerun.
   Never perform deliberate breakage in production or leave mutation changes in the PR.

### Evidence required in the implementation PR

Create one row per acceptance ID and relevant parameterized case; the following is a blank format,
not completed evidence. For an already-passing control, label it "baseline regression control."

| AC / case | Actual test name and command | Baseline revision + red failure | Fix revision + green result | Sensitivity result or justified N/A | Integration/remaining gap |
| --- | --- | --- | --- | --- | --- |
| To be filled by implementer | Exact reproducible invocation | Business assertion that failed | Exit code and passed/failed/skipped counts | What was disabled and what failed | Explicitly state unverified behavior |

Reviewer must compare test expectations with this ticket independently of the patch and inspect
changed/deleted assertions. "Tests added" or "all tests pass" without this evidence is insufficient.

## 6. Engineering starting points — verify, do not blindly patch

Paths below are relative to the **miller-schackman-api** repository. They are navigation hints at
the reviewed baseline, not a required file-edit list or permission to bypass other callers.

| Responsibility | Existing entry point / reference |
| --- | --- |
| Canonical representation/shared preservation | app/domain/leads/canonical.py — CanonicalLeadRecord; preserve_app_owned_lead_state |
| Sync and on-demand refresh | app/application/use_cases/crm_sync.py; app/application/services/crm_lead_refresh.py — refresh_lead_from_crm; app/interfaces/api/v1/crm_history_imports.py |
| People-webhook mapping | app/infrastructure/crm/follow_up_boss/webhook_event_people.py — handle_people_event; lead_mapper.py in the same directory |
| Pre-send refresh and actual sending | app/application/services/pre_send_crm_refresh.py — refresh_lead_for_pre_send; app/application/use_cases/send_outbound_message.py |
| Suppression/evidence writers | app/application/use_cases/process_contact_suppression_event.py — apply_contact_suppression_to_lead; app/application/use_cases/process_inbound_message_event.py |
| Persistence and historical evidence | app/infrastructure/persistence/postgres/lead_repository.py — upsert; external_events, inbound_messages, provider_message_events |
| Visible result | app/interfaces/api/v1/leads.py — existing lead flags and sendability response; web repository's LeadDetailPage sendability panels |

Keep policy in the domain/application layers; provider payloads and SQL stay in adapters. Preserve
workspace scoping and existing transaction/audit conventions. The current upsert replaces complete
field values: an in-memory merge by itself does not establish concurrency safety. Trace all writers
before choosing locking, an atomic update, or another minimal persistence solution. Do not hold a
database lock across avoidable external network calls. No schema migration or new dependency is
assumed; justify one if genuinely necessary and review its rollout separately.

### Existing tests and commands

Use Python 3.12 and uv. Install declared dependencies with uv sync if needed. Run from the API
repository. Start with one new scenario's exact pytest node, then its file, then the related suite.
The following are existing file-level starting points, **not evidence that new coverage exists**:

<augment_code_snippet mode="EXCERPT">
````bash
uv run pytest tests/application/use_cases/test_crm_sync.py -v
uv run pytest tests/application/use_cases/test_process_contact_suppression_event.py -v
uv run pytest tests/application/use_cases/test_process_inbound_message_event.py -v
uv run pytest tests/application/use_cases/test_send_outbound_message.py -v
uv run pytest tests/infrastructure/crm/test_follow_up_boss_webhook_event_handler.py -v
````
</augment_code_snippet>

Extend the existing sync preservation and pre-send-refresh tests, but add separate on-demand
refresh coverage: no direct refresh_lead_from_crm test reference was found at the reviewed baseline.
Use tests/application/use_cases/test_business_flow_harness.py for multi-step fixture conventions.
Place new recovery tests alongside the implemented boundary and list their exact commands in the PR.

<augment_code_snippet mode="EXCERPT">
````bash
uv run pytest tests/infrastructure/persistence/postgres/test_lead_repository.py -v -ra
uv run pytest tests/infrastructure/persistence/postgres/test_business_flow_harness.py -v -ra
uv run pytest tests/interfaces/api/v1/test_leads.py -v
make lint
make typecheck
make test
````
</augment_code_snippet>

Use the existing local Postgres harness and isolated test database. Confirm its target is local/test
before running: it creates/drops a temporary database and requires the corresponding permissions.
It can skip when Postgres is unavailable; **skipped persistence tests leave this ticket unverified**.
Do not paste database URLs, credentials, raw lead bodies, or provider payloads into evidence.
Real-provider behavior requires separate authorized sandbox validation; fakes do not prove it.

## 7. Historical recovery contract — part of this Class A slice

Deliver tested recovery tooling plus an executable runbook; inventing a command in this draft would
misrepresent current capability. Add the actual command and safe arguments to the runbook before
implementation review, and satisfy AC-10–13.

- **Scope/defaults:** dry-run by default; explicit workspace and bounded lead/event scope; explicit
  apply mode. Report candidate, already-correct, changed, unresolved, and failed counts, linked to
  source event identities in an access-controlled audit report. No broad unbounded production run.
- **Verified evidence shapes:** suppression-specific external_events carry provider/event type and
  lead/CRM identity. Include previously ignored lead_not_found events if they now match uniquely
  within the same workspace/provider. Inbound opt-outs can also be represented by inbound_messages
  and external_events processing audit; do not omit hard-word/classifier-recorded opt-outs.
- **Evidence limits:** provider_message_events are delivery history, not universally suppression
  events. Accept only provider-specific, explicit opt-out evidence after verifying its mapping.
  An arbitrary delivery failure is not an unsubscribe. Do not rerun an LLM over historical messages
  to invent past decisions. Inventory retained evidence; do not assume every lost opt-out is recoverable.
- **Proposed provenance selection for approval:** keep existing valid platform provenance for each
  restriction. If missing, select the earliest verified occurrence across the complete scoped
  history for that lead/restriction; break equal-time ties by source provider then stable source
  event ID. Select before applying batches, not by input arrival order. Preserve original event
  records and report supporting references. Missing/contradictory selection evidence is unresolved,
  not fabricated. AC-11–12 must pin the chosen evidence with literal expected identities/times.
- **Application:** monotonically reassert proven restrictions with original source/time; retain all
  other restrictions, newer activity, and unrelated fields. Repeating or interrupting the operation
  must be safe. Never delete original history or clear consent. Flag conflicting authorized-lift
  evidence for review rather than silently undoing a proven later lift.
- **Isolation:** do not blindly replay whole webhook/inbound use cases: deduplication may skip them,
  and lifecycle/CRM/provider side effects may run again. Repair consent state without sending,
  enrolling, resuming, or rerunning unrelated business actions.
- **Unresolved cases:** report missing evidence and ambiguous/missing identity explicitly. Keep the
  affected outreach excluded from re-enablement pending review; no guessed opt-out or guessed opt-in.

## 8. Production rollout, acceptance, and rollback

1. **Before release:** name the release/recovery operator; inventory affected workspaces/leads,
   queued sends, evidence availability, and any old services/workers that can still overwrite rows.
   Record the exact existing operational controls that keep affected sending disabled during repair.
2. **Deploy preservation first:** update all relevant writers; verify no old process can erase
   restored state. Deployment/migration must not automatically resume leads or bulk restart campaigns.
3. **Rehearse recovery:** run against representative synthetic/local or authorized staging data.
   Inspect dry-run results, then apply, refresh, and repeat. Confirm AC-09–14 and audit totals.
4. **Authorize production separately:** approve exact target/environment, bounded scope, operator,
   runbook command, and evidence access. Apply/reconcile only that scope. A documented zero-affected
   result is acceptable; an incomplete inventory is not. Record unresolved exclusions.
5. **Targeted stakeholder acceptance:** with sandbox/sink messaging and test leads, record each
   restriction, refresh from stale CRM, reload lead detail, and check SMS/email/DNC reasons. Attempt
   the blocked channel and inspect captured sends: none. Repeat with an otherwise identical clean
   lead: its normal permitted send still works. Check ordinary CRM field changes still appear.
6. **Re-enable only verified scope:** prove queued work rechecks the restored restrictions; no blanket
   resume/re-enrollment. Preserve pauses, handoffs, caps, and existing enrollment rules. Communicate
   the CRM-field limitation and the lack of a delivered opt-back-in route before operator acceptance.
7. **Observe and stop safely:** monitor restriction regressions on refresh, refresh/repair failures,
   blocked-channel send attempts, and recovery discrepancies using existing logs/audit surfaces.
   Attach bounded observation results and an owner, not an invented dashboard or guaranteed zero risk.

**Rollback:** keep restored consent facts and audit evidence. Do not undo suppressions as a rollback.
If older code can erase them, stop/contain affected refresh writers and sending before reverting;
record the exact containment/rollback procedure and verify it in staging. Production rollback or
data changes require approval; this ticket does not grant blanket permission.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4 outcomes, exclusions, and accepted CRM-field limitation.
- [ ] Reviewer approves §5 testing boundaries and identifies the first meaningful failing scenario.
- [ ] Owner/reviewer approves §7's proposed provenance selection before recovery expectations are coded.
- [ ] Implementer/reviewer assigned; branch baseline and existing working behavior recorded.

### Ready to merge
- [ ] Every acceptance ID maps to concrete tests/checks; red/green and sensitivity evidence attached.
- [ ] Relevant regression, real-persistence, concurrency, recovery, lint, and type checks pass;
      skips/failures are disclosed and required integration checks are not waived as "green."
- [ ] Independent review confirms unchanged safeguards and no Class B behavior hidden in the patch.
- [ ] Recovery tooling/runbook includes exact dry-run/apply/verification and containment commands.
- [ ] Targeted API/UI acceptance evidence and limitations are recorded; no unsupported re-subscribe
      capability or automatic CRM courtesy write is claimed.

### Production acceptance complete — not merely merged
- [ ] Updated writers are deployed and verified; production recovery is explicitly approved/executed,
      or a complete inventory establishes no affected records. Unresolved scope remains excluded.
- [ ] Restored state survives refresh; affected queued work cannot bypass it; no unintended restart/send.
- [ ] Operator briefing, recovery/observation evidence, and release-owner acceptance are recorded.
- [ ] Deferred parent targets have named follow-up owners before claiming Issue 16 as a whole complete.

**Evidence status at drafting:** code/document trace only. No new tests or implementation have been
written, no runtime pass has been claimed, and no production/Jira operation has been performed.

## 10. References and decision precedence

- [Source Issue 16 and business-impact/readiness appendix](../production-state-consistency-issues.md)
- [Consensus — D3 capability loss and D7 Class A/B gate](../production-state-consistency-review-consensus.md)
- [Business-rule summary](../production-state-business-rule-changes.md)
- Parent workspace AGENTS.md and CLAUDE.md: product/layering rules and current owner decisions.

The numbered contract here is the proposed executable scope; source documents retain deferred
targets and historical discussion. If implementation reveals a conflict in expected business
behavior, stop that part and ask the owner. Do not choose an outcome merely because it makes tests pass.