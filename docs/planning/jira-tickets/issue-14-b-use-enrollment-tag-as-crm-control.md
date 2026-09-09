# Issue 14-B — Use the enrollment tag to control CRM-side automation

**Status: DRAFT — business, test-contract and release-readiness review required.**
This is the fourth proposed Jira description, not a published issue or permission to implement.
The tag-only policy is already recorded; the implementation clarifications in §3.6 still need review.
Approval to continue drafting is not approval to change production behavior or write tags to the CRM.

## 1. Business impact — read this first

**The promise:** Agents have one predictable CRM-side control: remove the enrollment tag to end
nurture. Ordinary CRM work no longer silently stops the track. Re-add the tag after a tag-ended run
to request a fresh enrollment, subject to the application's remaining safeguards.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | Notes, tag additions, stage/status changes and logged calls/texts can pause nurture, including echoes of the platform's own writes. A separate send-time activity check can also block the next touch. Removing the enrollment tag does not currently end the workflow. |
| What changes for an agent? | Logging a call, sending a manual CRM text or adding a note will no longer stop automation. With the enrollment tag present, the next permitted automated touch still follows its schedule. To stop nurture from the CRM, remove that tag. |
| Is this just filtering out the platform's own activity? | **No.** It intentionally removes activity-based pause/send vetoes for both agent and platform activity. Origin filtering is the superseded alternative, not the scope of this release. |
| What happens when the tag is removed? | Ordinary non-terminal nurture ends with the specific reason enrollment_tag_removed. It is not a temporary pause. Pending campaign messages must not pass the final send check, and no next nurture action remains scheduled. Human handoff/ownership is protected separately. |
| What happens when the tag is re-added? | After an observed tag-removal termination, start one new eligible enrollment at step one, not the old step. Normal routing, start limits, timing and safety checks still apply; re-add is not an instruction to send immediately. Repeated tag events on an existing run do not restart it. |
| Does the tag overrule consent or human controls? | **No. The only CRM-side switch is not the only application safeguard.** Manual pause, authorized resume, human handoff/ownership, unresolved replies, opt-outs/DNC, workspace/campaign controls, timing and frequency restrictions remain effective. A consent-field change or actual lead reply is not a routine-activity exception. |
| What changes in the brokerage's CRM? | Every newly confirmed enrollment must have its configured tag, including automatic dormancy enrollment. Where needed, the platform adds it without replacing other tags. Manual/bulk and paused-search entry paths cannot remain untagged exceptions. |
| What if the CRM write or read fails? | Do not confirm untagged running nurture or send using unverified tag data. A failed/uncertain enrollment-tag write becomes a visible needs-human problem. A failed tag read is not proof the agent removed the tag. Recovery must recheck current intent and safeguards. |
| What will users see? | Lead status/history explains an intentional tag-ended run; a failed tag setup is separately actionable in Attention. Do not label an intentional stop as an unexplained pause or hide a failed enrollment because no workflow was created. |
| Can removing the tag recall a message? | No. Detection relies on CRM delivery and a fresh pre-send check. A message already released to/accepted by the provider may still arrive. The release must document the tested dispatch boundary rather than promise instantaneous recall. |
| What happens to existing leads? | No automatic bulk resume, re-enrollment or retroactive tagging is authorized. Existing untagged and activity-paused leads need a reviewed cutover plan; otherwise the new rule could unexpectedly stop them or restart work an agent intended to keep off. |

**This is a Class B behavior release.** Brief agents before activation, disclose CRM tag writes,
and obtain the owner's explicit release approval. Code merge alone does not deliver that change.

## 2. Ticket identity, scope and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — explicit CRM control and removal of unintended stalls; confirm at publication |
| Source / delivery class | Production-state consistency Issue 14 / **Class B: recorded product-policy change** |
| Repositories / components | miller-schackman-api: CRM ingestion, enrollment, workflow lifecycle and every campaign send boundary; miller-schackman-web: status/history, Attention and control guidance |
| Sequence | Fourth draft after 16-A, 9-A and 11-A; those drafts are not evidence their implementations have shipped |
| Integration prerequisites | Preserve 16-A's durable suppression/evidence and activity timestamps; preserve 9-A's receipt/STOP/reply-hold contract; retain 11-A's assignment projection on refreshed snapshots. Integrate the separately reviewed A work rather than rebuilding it inside this B PR. |
| Owners | Name product/release owner, implementer, independent reviewer, CRM/workspace administrator and recovery operator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; retrace the actual implementation branch |
| Readiness | Core policy settled by Issue 14/D5/D7; approve §3.6 clarifications, test boundaries and cohort-specific rollout before implementation/activation as applicable |

**Included:** tag-removal ingestion and final-send detection; narrow tag-ended re-entry; tag presence
for all enrollment paths; safe CRM-write failure/recovery; removal of routine-activity pause/send
vetoes; retention of activity recording for surviving consumers; readable outcomes; lifecycle,
duplicate/race, integration and protected-behavior tests; agent briefing and bounded cutover runbook.

**Excluded:**
- Issues 12/13's channel fallback and unknown-consent policy implementation; Issue 9-B's 30-minute
  retry/notification window; Issue 17's durable-dispatch migration or uncertain-as-sent policy.
  Their recorded targets are not permission to change those outcomes here.
- A new campaign/tag priority algorithm, global workspace-tag setting, broad consent lift,
  automatic terminal re-entry for other reasons, or removal of authorized dashboard controls.
- Reassignment notifications, a general CRM-origin classifier, a new rules engine, universal
  source-event ordering, and Issue 15's general exhausted-work dashboard. This ticket must still
  make its own tag-setup failures visible; that narrow requirement cannot wait on Issue 15.
- General completion/late-reply policy under Issue 8/G1, bulk historical data mutation, new browser
  push infrastructure or a promise to cancel a message already dispatched externally.

**D7:** A and B must not share a PR. Engineering may use several reviewed B-only slices, but must
not activate veto removal without working tag control, safe enrollment and the D5 briefing.

## 3. Current behavior and contract to approve

### 3.1 What exists, versus what this ticket builds

- The CRM activity use case both advances last_agent_activity_at and requests PAUSED for notes,
  activity, stage and status events. Removing the pause must not remove useful recording/history.
  Ownership-only reassignment is already ignored by that pause detector; do not advertise that as
  newly fixed here or lose 11-A's owner projection.
- Pre-send refresh checks both a changed activity timestamp and fetched activities attributed to
  an agent. Final durable-send revalidation has an additional timestamp comparison. Removing only
  the webhook pause or the refresh helper leaves a second route to the old veto.
- peopleTagsDeleted is absent from the people dispatcher. The current FUB client's
  subscribe_to_events method is unimplemented: adding a handler is not proof a tenant's actual
  webhook registration will deliver deletion events.
- crm_enrollment_tag is nullable and configured on a **campaign version**, not on a global
  workspace setting. Current tag matching trims surrounding whitespace but is case-sensitive;
  active configuration matching currently chooses the first match. Do not silently redesign it.
- CRM-tag enrollment is attempted from people refresh/sync, not only a tag-created notification.
  Therefore a terminal carve-out based on source=CRM_TAG alone would be too broad.
- Automatic terminal re-entry is currently blocked; explicit admin re-entry and track reassignment
  have existing rules. Dormancy enrollment does not currently guarantee a CRM tag write.
  CRMClient.add_tag exists and FUB uses a merge-tags update; it is not a transaction with Postgres.

### 3.2 End the correct run, durably

1. **Bind the control to the enrollment.** For an existing run, resolve the tag from its actual
   enrollment/campaign version, not whichever campaign matches first today. A newer publication or
   unrelated tag cannot silently change the old run's switch. New enrollment keeps the existing
   eligible campaign/routing selection, subject to the configuration clarification in §3.6.
2. **Observe real absence.** Handle enrollment-tag deletion and recheck tag presence from a usable
   current CRM snapshot immediately before every campaign provider send. A missed webhook must not
   leave a de-tagged lead sending. Distinguish a complete empty tag list from an absent/unreadable
   field, missing configuration, unavailable CRM or missing person. Unknown is not confirmed removal.
3. **Terminal means terminal.** This draft proposes CLOSED with enrollment_tag_removed as the
   concrete workflow/transition outcome, distinguishing an agent's stop from completion or consent
   suppression. Keep the linked enrollment's ended status/time coherent, clear the run's next action
   and cadence cursor, and prevent old queued messages/paused-search occurrences from executing.
   Record the affected run, configured tag, observation source/time and event identity when available.
4. **Do not stop a successor.** Persist the stop and its required execution instruction/outbox work
   using existing transaction conventions. Scope instructions, queued work and later callbacks to
   that workflow/enrollment identity. Engine/signal delay does not make a terminal database workflow
   sendable. Retry safely; one logical removal must not create duplicate terminal transitions.
5. **Protect human ownership.** Do not transition HUMAN_HANDOFF or HUMAN_OWNED, overwrite their
   reasons, transfer their accountable human or auto-resume them on tag removal/re-add. They already
   block automation. Missing tag still blocks later campaign sends; permission-checked resume and
   the other applicable checks remain required.
6. **Respect the dispatch boundary.** Revalidate after live refresh against the current locked
   lead/workflow/message state, not a workflow state captured before removal. A stop committed before
   the final dispatch decision must block the call. Explicitly test/describe the remaining external
   call race; no database lock can atomically transact with FUB and the messaging provider.

This applies to standard cadence, paused-search cadence (including supported variants), AI
continuation, operator send-now and draft approval for campaign-linked messages, on SMS and email.
Trace their actual direct and durable paths; optional refresh wiring is not a production bypass.
Do not solve coverage by forcing Issue 17's complete dispatch migration into this ticket. CRM notes,
notifications and messages manually sent in the CRM are not campaign provider sends controlled here.

### 3.3 Re-add starts fresh; it does not clear other restrictions

1. Only an observed re-add after the relevant prior run ended specifically for
   enrollment_tag_removed opens this new automatic re-entry exception. Persist enough lifecycle
   evidence to distinguish that cycle from a duplicate notification or continuously present tag.
   A supported fresh-snapshot path may detect it; do not require a notification type the CRM missed.
2. Create one new enrollment/workflow/execution identity through the normal admission/start path.
   Start at the first step of the newly selected eligible track, with normal scheduling and caps.
   Never reuse the old cursor, revive old messages or count an old pending occurrence as the new step.
3. Duplicate additions to an existing non-terminal run are a control no-op. Completed, suppressed
   and other closed runs keep existing re-entry rules; do not add CRM_TAG to a blanket terminal
   allowlist. The dormancy selector must not automatically reapply a deliberately removed tag and
   restart the lead. Existing admin re-entry/track-reassignment rules remain separately authorized.
4. All independent restrictions survive. In particular, tag cycling is not an opt-out clear, reply
   resolution, review dismissal or permission-checked manual/handoff resume. See §3.6 for the exact
   manual/review-hold collision contract proposed for approval; do not infer permission from the tag.
5. Tag termination stops nurture, not receipt or opt-out processing. Persist STOP/consent evidence
   even after termination. A delayed classifier result, engine signal or provider callback must not
   resurrect the old run or bypass a pending reply/human decision. No new late-reply AI window is
   introduced; retain the applicable separately approved inbound/terminal handling.

**Ordering limit:** notifications can be duplicated, delayed or arrive after the CRM snapshot has
changed again. An obsolete deletion must not close a new run with its tag present. Do not invent an
absence→presence cycle from timestamps alone. If an entire remove/re-add cycle was never observed
and the source supplies no trustworthy change history, a current snapshot cannot reconstruct it;
§3.6 requires that limitation and any unresolved ordering cases to be explicit before activation.

### 3.4 Enrollment cannot quietly run without its switch

1. For each eligible new enrollment, confirm the correct configured tag is present in the CRM.
   If absent, merge it into the CRM before confirming enrollment or enabling nurture execution.
   This includes dormancy, manual/bulk and paused-search entry paths; validate existing admission
   restrictions before writing, so a rejected enrollment does not add an on-switch as a side effect.
2. Missing/ambiguous control configuration is an actionable configuration problem, not a guessed
   tag, tag-removed termination or permission to skip the check. The workspace administrator must
   know which actual configured tag agents should remove.
3. Failed or uncertain writes leave a durable, non-sendable needs-human outcome with lead/workspace,
   attempted enrollment/configuration, reason, age and next action. It must be visible even if no
   active workflow exists. Do not report STARTED or ordinary healthy nurture while setup is incomplete.
   Choose the existing review/Attention integration and permitted recovery action before coding.
4. CRM success followed by local failure is not a rollback of the CRM. Retain/recover the attempt
   identity and reconcile current tag presence before another write/start. Echo webhooks, a selector
   retry and a manual retry must not start competing runs or bypass an unresolved setup hold.
5. A retry is not authorization to undo a newer human stop. Recheck the attempt, current CRM tag,
   terminal/review state, consent, ownership and admission. Do not blindly retag after the agent
   removed a successfully written tag. Unknown write outcome stays non-sendable until reconciled;
   no invented timeout or unbounded background retry is approved by this draft.

### 3.5 Remove the old veto without deleting other product behavior

- Routine notes, unrelated tag changes, stage/status updates and logged agent calls/texts must
  neither pause the workflow nor veto its planned/final send. Platform echoes are harmless for the
  same reason; no new author/tag-origin filter is needed to decide whether activity should pause.
- Remove both refresh-time activity inputs, the activity fetch used solely for this veto, and the
  independent final-revalidation comparison. Audit planning/context/dispatch callers too. Do not
  rename the same check or move it into a different preflight step.
- **G5:** retain or relocate the narrow, monotonic activity-timestamp writer. Resume assessment,
  classification and API consumers still read it. Preserve their existing behavior and the field's
  meaning; recorded CRM attribution is not proof of human authorship. Do not retain the send veto
  as a way of keeping recording alive, or remove the field/consumers as incidental cleanup.
- Keep CRM refresh, assignment resolution, conversation/history capture and actual inbound reply /
  unsubscribe processing. A logged CRM activity and a real lead reply are different inputs. Do not
  delete whole webhook handlers that also record conversations or apply suppression.
- Retain the integrated release's consent rules, reply holds, human controls, timing/frequency,
  provider-failure and uncertainty outcomes. A permitted-send positive control must use valid
  consent/contact data rather than silently implement Issues 12/13 or 17 to make it pass.

### 3.6 Remaining clarifications — not new votes on the settled tag-only policy

These are explicit approval gates, not facts claimed to exist in the current application.

| Gate | Proposed boundary / decision needed | Who closes it |
| --- | --- | --- |
| R1 — Which tag, including existing runs? | Use the current run's bound campaign-version tag; use normal campaign selection for a new run. Preserve current matching semantics. Identify nullable tags, conflicting configuration and changed-version cohorts; approve their configuration/cutover rather than creating a global default or silently switching existing runs to a new tag. | Product owner + CRM administrator; implementation mapping before code, actual cohort plan before activation |
| R2 — Tag cycling on a manually/review-paused lead | Proposed: removal ends the old non-human-owned run, but its independent manual/review restriction survives. Re-add cannot clear it; a new run may become sendable only after the existing permission-checked review/resume requirement is satisfied. Approve the exact held-state/API/UI outcome and recovery action before implementation. Human handoff/ownership protection is already settled and is not reopened here. | Product owner + engineering reviewer |
| R3 — Setup-failure review and recovery | Name the durable review surface for a failed/unknown tag write, including a lead with no workflow, and the authorized recovery role/action. Proposed default: no automatic start merely because an echo or later sync sees the tag while review is unresolved. Specify bounded retry ownership and any notification expectation; do not borrow Issue 9-B's 30-minute policy. | Product owner + operations + engineering reviewer |
| R4 — Source ordering and unobserved cycles | Verify actual deletion payloads/subscriptions and what source ordering/change evidence is available. Approve the current-snapshot detection limit above and a safe disposition for conflicting evidence. A known old event must not stop a successor; uncertainty must not authorize a guessed re-enrollment. If the required guarantee exceeds the provider evidence, escalate a scoped design/decision rather than assert exactly-once control. | Engineering reviewer + product/release owner |

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Use synthetic leads, controlled clocks and recording
transports. Observe committed status/history and actual provider calls through the real use cases.
R1–R4 must be resolved before their cases are claimed implementation-ready or passed.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | With the configured tag present, process notes, unrelated tag add/delete, stage/status changes, reassignment and agent-logged calls/texts; include platform write echoes. | No activity-caused pause, transition, cancellation or send veto. A due, otherwise permitted touch still sends once on schedule. Ownership/history updates still occur where applicable. | Origin filtering presented as the fix, self-pauses, lost conversation history, or all sends disabled to make a negative test pass. |
| AC-02 | Advance last_agent_activity_at after scheduling and provide a newer agent-attributed CRM activity; exercise planning, direct sending and final durable revalidation. Also make the activity-only endpoint unavailable while the person/tag read succeeds. | Neither activity source vetoes the touch; no activity fetch is required solely for that veto. Lead refresh and remaining safety checks still run. | Removing only one comparison, replacing it with a differently named activity hold, or bypassing CRM tag verification. |
| AC-03 | Remove the correct tag from ordinary active/queued nurture and process a usable deletion snapshot. Inspect after commit and after execution catches up. | One CLOSED run with enrollment_tag_removed, coherent ended enrollment/history, no next action, and no executable old pending touch. Outcome reads as ended, not temporarily paused. | Workflow/enrollment disagreement, generic cadence_step_blocked, an old queued send remaining eligible or a missing engine signal making the DB state sendable. |
| AC-04 | Miss the deletion webhook; attempt the next campaign send with the tag absent. Parameterize standard and paused-search cadence, AI continuation, send-now and draft approval, SMS/email where supported. | Fresh tag check stops the correct run and makes zero recording-provider calls. Validate every actual direct/durable branch, including configured paused-search variants. | Checking only schedule time, relying only on webhook delivery, cached pre-removal workflow state, or a missing optional dependency permitting a send. |
| AC-05 | Observe removal and terminalization, then observe the tag re-added with normal eligibility satisfied. | Exactly one fresh enrollment/workflow at step one of the selected track; new execution identity, ordinary timing/caps and retained old history. | Resuming the old cursor, dispatching its queued messages, bypassing caps or promising immediate sending. |
| AC-06 | Repeat additions, people refreshes and syncs while the tag remains on a non-terminal run. | Same enrollment and cursor; no restart, auto-resume or duplicate initial touch. Ordinary data refresh still works. | A new enrollment for every observed tag, treating a refresh timestamp as a new control cycle, or blocking legitimate first enrollment. |
| AC-07 | Deliver duplicate/concurrent add and remove events; inject a database failure between lifecycle writes, then retry. Use independent database sessions. | Atomic committed outcome, durable deduplication and at most one non-terminal run. Recovered retries produce no duplicate terminal transition/start or lost stop. | Fake-only concurrency proof, a partially closed run, duplicate execution or a dedupe marker preventing unfinished work from recovering. |
| AC-08 | After a confirmed fresh run, deliver an obsolete removal notification; separately remove an unrelated tag and process a multi-person resource. | Fresh evidence and run identity prevent closing the successor or another person's run. Preserve workspace/person isolation and approved R4 disposition. | Applying a deletion event to whichever workflow happens to be latest, closing every tag-matched campaign, or inventing event ordering from envelope time alone. |
| AC-09 | Use different campaign tags, a published replacement version, whitespace/case variants, and a missing configured tag. | Check the actual enrollment-bound tag, preserve matching/selection semantics, and expose unresolved configuration under R1 without sending. | A global guessed tag, another campaign's tag keeping this run alive, silently changing case semantics, or treating missing configuration as a human removal. |
| AC-10 | Re-add tags to completed, suppressed or differently closed runs; run dormancy selection after a tag-ended run without a real re-add. Include existing authorized admin/track-reassignment controls. | No new automatic terminal exception beyond tag-ended re-add; no selector-driven undo of removal. Existing explicit re-entry rules remain intact. | Blanket CRM_TAG/DORMANT_SELECTOR terminal admission, automatic tag repair restarting an agent-stopped lead, or disabling sanctioned explicit actions. |
| AC-11 | Manually pause/review-hold a tagged lead; send duplicate tag events, then remove/re-add under the approved R2 contract. Test unauthorized and authorized recovery. | A tag cannot clear the independent restriction. After required authorized action and valid tag/eligibility, the permitted continuation/new-run route works as agreed. | Silent resume, loss of the hold at terminalization, a permanently unusable authorized recovery path, or new permissions. |
| AC-12 | Remove/re-add the tag while HUMAN_HANDOFF or HUMAN_OWNED; later request authorized resume with tag missing, then present. | Human state/reason/accountability is not overwritten by tag events; no automatic restart. A missing tag prevents campaign sends, and present tag alone does not substitute for authorized resume. | Tag cycling bypassing handoff, closing it as a routine tag removal, or transferring its human owner. |
| AC-13 | Process STOP/DNC/recorded suppression or an unresolved reply around removal/re-add; deliver a delayed classifier result after termination. | Receipt/evidence and applicable channel/workflow restrictions survive; no prohibited send or resurrection. An otherwise allowed processed reply still follows its integrated-release contract. | Tag presence treated as consent, dropping STOP because the run ended, clearing reply hold by elapsed time, or silently adding Issue 13 fallback. |
| AC-14 | Record newer CRM activity, then apply an older event and a fresh CRM snapshot; inspect resume assessment, classification input and API fields. | last_agent_activity_at advances monotonically and remains available to its surviving consumers; consent/evidence/ownership remain correct. It does not become a send veto. | Removing its only writer, regressing the timestamp, erasing opt-outs/owner IDs, or migrating unrelated consumers without approval. |
| AC-15 | Automatically enroll an eligible dormant lead without the configured tag; retain unrelated CRM tags. | Correct merge-tag write succeeds before enrollment is confirmed/execution enabled. One enrollment, visible CRM control, no overwritten unrelated tags. | Healthy running nurture before write confirmation, a guessed tag, duplicate start from the echo or changed dormancy threshold. |
| AC-16 | Exercise manual, bulk and paused-search/track-start entry paths with tag present and absent; include an admission-rejected lead. | Every confirmed new enrollment has its switch. Existing explicit entry/assignment permissions remain; rejected admission does not write an on-switch. | A manual or paused-search bypass, unauthorized enrollment, or tag-write success treated as authorization despite failed admission. |
| AC-17 | Make enrollment-tag write fail permanently, fail transiently or time out with unknown remote outcome; include no workflow yet. | Durable non-sendable needs-human result with reason/age/next action on the approved surface. No false STARTED result, provider call or invisible unfinished enrollment. | Logging and continuing, disappearance because no workflow exists, unlimited retries, or an invented notification deadline. |
| AC-18 | Let the tag write succeed, then fail local persistence; race its echo with retry. Separately remove the successful tag before recovery. | Reconcile one attempt; no competing run, duplicate first touch, review bypass or blind re-tag after the newer stop. Recovery follows R3 with fresh admission/safety checks. | Claiming the CRM write rolled back, treating every echo as a fresh user request, or recovery overriding human intent. |
| AC-19 | Fail the CRM read, return a missing person or omit required tag data; compare a usable snapshot with an explicitly empty tag list. | Unverified/missing data blocks provider calls with honest failure/configuration evidence. Confirmed tag absence follows tag-ending behavior; recovery cannot silently assume presence. | A failed fetch falsely recorded as enrollment_tag_removed, defaulting missing data to an empty list, or sending with stale cached tag presence. |
| AC-20 | Commit removal before final dispatch validation; then test the separate race where provider dispatch was already released/accepted. Retry the old request after a fresh enrollment and deliver late callbacks. | First case makes zero provider calls. Already-released outcome is reported honestly; no resend, successor cancellation or old-run resurrection. Record the tested boundary/limitation. | Unqualified recall/exactly-once claims, stale request dispatch against the new run or callbacks restarting nurture. |
| AC-21 | End a paused-search run with a pending occurrence/timer; re-add into its valid route. Delay an old engine instruction until the new run exists. | Old occurrence cannot execute; new run begins with the correct first occurrence/schedule. Profile/assignment rules stay coherent and old instructions cannot stop the new run. | Orphan active assignment preventing valid re-entry, duplicate occurrence, old cursor reuse or requiring Issue 17's whole migration without scope approval. |
| AC-22 | Read lead status/history and Attention via real APIs, then refetch the UI after tag-ended stop and failed setup. Test assigned agent, authorized operator, unrelated agent and another workspace. | Intentional end has its specific explanation and no ordinary Resume for the terminal run. Setup failure is actionable even without a workflow; independent holds still display. Existing role/tenant rules and empty/loading/error behavior remain. | Generic unexplained pause, intentional stop automatically treated as a failure, healthy-looking setup failure, a misleading restart control or cross-tenant access. |
| AC-23 | Rehearse cutover against synthetic legacy cohorts: untagged active, old activity pause, manual/review hold, handoff, suppressed and terminal. | Inventory/dry-run distinguishes cohorts; only the explicitly approved subset is changed by a separately authorized operation. Controls and history survive, and new checks cannot be bypassed for an unreviewed cohort. | Blanket tagging/resume, interpreting all missing tags as past deliberate removals, or silently leaving old workers enforcing a different policy. |
| AC-24 | Verify the actual deletion-event registration and adapter payload in an approved CRM sandbox; remove/re-add a synthetic lead's tag and use sink messaging. | Evidence covers registration/delivery, CRM merge semantics, persisted end/fresh-start and fresh UI reads. Also demonstrate the missed-webhook pre-send safeguard. | Handler-unit success offered as proof of tenant subscription, mocked CRM success claimed as vendor validation, or real customer outreach. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — approve before implementation:**
- **CRM event → lifecycle:** public webhook/actual handler, normal domain/application admission,
  transition and execution-outbox path; recording CRM/engine transports and fresh API/repository reads.
- **Every send journey → provider boundary:** use the actual entry points in AC-04 and both direct
  and durable implementations. Assert recording-provider counts, run identity and saved outcome;
  merely asserting a helper was called does not prove tag control or veto removal.
- **Enrollment → CRM write → recovery:** each admission/start path, failed/unknown writes, echo
  races, review visibility without a workflow, and authorized recovery with current restrictions.
- **Persistence/execution:** local/disposable real Postgres for atomic lifecycle/outbox writes,
  deduplication, rollback, fresh-session reads and controlled concurrent stop/start/dispatch.
  Use the existing Temporal test boundaries for timer/signal/paused-search behavior where affected.
- **API/UI and vendor contract:** real permission-scoped read results rendered by existing route
  tests plus a targeted synthetic integrated demonstration. Separately verify the actual CRM
  registration/payload/merge contract with approval; never send to real leads for acceptance.

External CRM/LLM/provider/notification transports and clocks may be faked. Hand-written repository
fakes are appropriate for fast application cases, but cannot prove SQL locking, rollback, uniqueness
or a real subscription. Do not mock the business rule, transition, admission or permission result.

1. Agree one scenario/boundary, add one behavioral test and run it against unchanged implementation.
   A useful first red is a tag-removed lead whose due send still reaches the recording provider.
   Another is a tagged lead whose ordinary CRM note still pauses it. Record the actual failing
   business assertion, make the smallest change, then rerun that test before the next slice.
2. Minimal interface/no-op scaffolding may make a new case runnable; record it separately. An import
   error, broken fixture, missing database, no collected test or skip is not meaningful red.
3. Replace old activity-pause expectations deliberately, with independent review of the new policy.
   Keep passing safeguards and positive controls. If a shared fix makes another case green already,
   prove sensitivity against baseline or an isolated mutation instead of inventing a failure.
4. Sensitivity checks must catch: removing the live tag check; retaining either activity veto;
   allowing all terminal CRM-tag re-entry; proceeding after failed tag write; losing the timestamp
   writer; using old workflow context; and clearing a protected hold. Restore all mutations and rerun.
5. Assert literal expected outcomes, not values computed by the production rule under test. Keep a
   permitted tagged send, legitimate fresh re-entry and authorized recovery as positive controls;
   “nothing ever sends/enrolls” is not a successful implementation.

| AC / variant | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Remaining integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each row | Exact invocation | Business assertion, not setup failure | Revision, exit code, pass/fail/skip counts | Observed protection/positive control | Explicit unverified claim |

## 6. Engineering starting points — navigation, not a prescribed implementation

References below are grouped by repository and use repository-relative paths for portability.
Retrace current callers and signatures; do not assume the draft adds any of these missing behaviors.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — CRM people and activity ingress | app/infrastructure/crm/follow_up_boss/webhook_event_handler.py; webhook_event_people.py; webhook_event_mappers.py in the same directory; app/application/use_cases/process_crm_human_activity_event.py |
| API — tag config, admission and starts | app/domain/campaigns/execution.py; app/domain/campaigns/enrollment_admission.py; app/application/use_cases/process_crm_tag_campaign_enrollment.py; app/application/services/campaign_enrollment_starter.py |
| API — other enrollment entry points | app/application/use_cases/run_dormant_selector_batch.py; lead_manual_enrollment.py; start_selected_campaign_batch.py; start_paused_search_campaign_enrollment.py in the same directory |
| API — live refresh and direct sends | app/application/services/pre_send_crm_refresh.py; app/application/use_cases/send_outbound_message.py; plan_outbound_message.py; plan_next_outbound_message.py in the use_cases directory |
| API — final dispatch boundary | app/application/use_cases/refresh_outbound_send_request.py; revalidate_outbound_send_request.py; dispatch_outbound_send_requests.py in the same directory; app/interfaces/workers/outbound_send_dispatch_worker.py |
| API — rules, state, CRM port/adapter | app/domain/campaigns/pre_send.py; app/domain/workflows/models.py; app/application/ports/crm.py; app/infrastructure/crm/follow_up_boss/client.py |
| API — surviving activity consumers | app/application/use_cases/lead_resume.py; app/application/services/llm/lead_state_classification.py; app/interfaces/api/v1/leads.py; app/interfaces/api/schemas/leads.py |
| Web — state/reason and Attention readers | src/lib/presentation/operations.ts; src/lib/helpers/leadPresentation.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/journey/leadJourney.ts; src/pages/LeadDetailPage.tsx; src/app/LeadsRoutes.test.tsx |

**Design review before coding:** compare (a) a small shared tag-control orchestration used by
ingestion and final refresh, with existing transitions/admission/outboxes, against (b) explicit
path-local orchestration sharing a pure control decision. The first reduces divergent lifecycle
handling but needs careful dependency/transaction design; the second has less wiring but more
duplicate failure/retry logic to keep consistent. Both still require live CRM data and a final locked
decision. Recommend the smallest shared boundary justified by actual callers, not a generic event
engine; record latency, locking and maintenance trade-offs and obtain approval.

Use the existing CRM merge port and transaction/outbox patterns. Keep provider objects in adapters.
Review all commit points, workflow/occurrence identity, latest-versus-requested-run lookups, and
dedupe marking before side effects. Do not hold database locks across CRM/LLM calls or claim a local
rollback undoes a remote write. Do not replace an explicit missing dependency with fail-open behavior.

**Existing test starting points, not claimed coverage:**
- API domain: tests/domain/campaigns/test_enrollment_admission.py; test_pre_send.py in that directory.
- API application: tests/application/use_cases/test_process_crm_human_activity_event.py;
  test_process_crm_tag_campaign_enrollment.py; test_run_dormant_selector_batch.py;
  test_start_selected_campaign_batch.py; test_send_outbound_message.py;
  test_revalidate_outbound_send_request.py; test_dispatch_outbound_send_requests.py;
  test_lead_pause.py; test_lead_resume.py; test_business_flow_harness.py in that same directory.
- CRM/API/worker boundaries: tests/infrastructure/crm/test_follow_up_boss.py;
  test_follow_up_boss_webhook_event_handler.py in that directory;
  tests/interfaces/api/v1/test_webhooks.py; test_lead_manual_enrollments.py in that directory;
  tests/interfaces/workers/test_outbound_send_dispatch_worker.py.
- Real persistence/execution: tests/infrastructure/persistence/postgres/test_business_flow_harness.py;
  test_workflow_repository.py; test_campaign_enrollment_repository.py;
  test_temporal_paused_search_workflow_postgres_e2e.py in that same directory.
- Web: src/app/LeadsRoutes.test.tsx; src/lib/journey/leadJourney.test.ts, plus affected Attention tests.

Use Python 3.12/uv: one exact pytest node, its file, related suites, then make lint, make typecheck and
make test. For changed frontend behavior run relevant Vitest tests, then pnpm test, pnpm typecheck
and pnpm lint. Record real commands/counts. Integration skips are gaps, not passes; confirm targets
are local/disposable before using database/Temporal infrastructure. No behavioral tests ran to draft
this ticket.

## 7. Existing records, activation and recovery

1. **Inventory before activation.** Count bounded workspace/campaign-version cohorts: tagged active,
   untagged active (including historic dormancy/manual starts), old activity pauses, genuine manual /
   review holds, human handoff/owned, consent-blocked and other terminal runs. Include queued sends,
   unresolved tag attempts, nullable tags, changed configurations and pending old activity signals.
2. **Approve the treatment of each cohort.** Missing tag alone cannot distinguish old enrollment
   without a write from a deliberate CRM stop. Do not infer historical intent or bulk add tags.
   Approve explicit tagging, intentional ending, continued containment or a named human review as
   appropriate. No cohort may remain actively sending through an unreviewed tag-check bypass.
3. **Do not auto-resume historic pauses.** Removing the old pause cause does not authorize resuming
   every currently paused lead. Distinguish its actual reason and current restrictions; any recovery
   is a separately approved, bounded action using the normal safety/permission checks.
4. **Provide an executable runbook, not an imaginary tool.** Name environment, workspace/lead
   scope, operator, dry-run, approved commands, audit/idempotency guarantees and verification. If a
   repair/recovery command must be built, review/test that scope first. This draft authorizes none
   of the CRM writes, data repair, webhook replay or deployments described in the runbook.
5. **Reconcile before enabling.** Confirm Issue 16 recovery/protections and Issue 9 reply holds on
   affected leads; verify control tags, pending attempts and actual subscription configuration.
   Coordinate API/worker rollout so no old writer or delayed activity-pause instruction can restore
   the retired behavior. Never cancel a genuine manual/handoff instruction as legacy activity cleanup.

## 8. Class B release, communication and rollback

**Required agent briefing:**
> To end nurture from the CRM, remove this campaign's enrollment tag. A note, logged call, manual
> text, stage/status change, reassignment or unrelated tag no longer stops the next automated touch.
> Re-adding the tag after a tag-ended run requests a fresh start, not continuation from the old step.
> Opt-outs, reply processing, dashboard pauses and human handoffs still apply. The platform now adds
> the configured tag when enrolling an eligible lead without it, including automatic dormancy starts.
> Removing a tag cannot recall a message already released to the messaging provider.

Fill in the actual configured tag per campaign/workspace; do not distribute a guessed universal name.
Tell administrators where setup failures appear and who can recover them. More visible problems can
reflect previously hidden stalls or setup failures; distinguish detection from new failures and do
not promise a particular week-one count or blanket reduction in Attention items.

Before activation, record:
- Named owner's **explicit yes for this B release**, R1–R4 decisions, test evidence and the D5
  briefing/disclosure delivered to affected brokerages/agents.
- Approved cohort plan and staged rollout/containment procedure; real webhook registration evidence,
  CRM-write permissions, complete sender coverage and API/worker version compatibility.
- Synthetic sandbox/sink demonstration: note does not pause; removal ends; missed webhook blocks;
  re-add starts fresh; manual/handoff/STOP/reply protections survive; failed setup is actionable.
- Safe operational measures: receipt/commit timing, tag-ended outcomes, configuration/read/write
  failures, deduplicated attempts, blocked old requests and unexpected restarts. No raw messages,
  contact details, credentials or unrestricted CRM payloads in logs/evidence.

**Rollback:** first contain enrollment and outbound execution for the approved affected scope, using
verified existing controls; coordinate any broader workspace pause with the release owner. Reverting
to old code loses the new tag-stop guarantee and may restore activity pauses. Do not present it as a
transparent safe reversal. Preserve terminal history, consent, human holds and remote tag-write
evidence; do not bulk remove platform-added tags, recreate old workflows or clear reviews to roll
back. Approve/communicate the resulting control model and compatible worker/DB versions explicitly.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4, including R1/R2/R3's exact behavior and the R4 evidence/limitation.
- [ ] Implementer/reviewer and integrated A prerequisites recorded; no assumption that earlier drafts
      are merged or deployed. G5 activity recording retained without retaining the veto.
- [ ] Test boundaries and first meaningful red approved; smallest complete transaction/recovery
      design reviewed. No open state/re-entry outcome is left for an implementer to guess.

### Ready to merge
- [ ] Every acceptance ID/variant maps to actual tests, red/green or justified existing-control
      evidence and relevant sensitivity checks. Real Postgres/execution tests prove claimed races.
- [ ] Every enrollment path has its switch; every campaign send path checks it. Routine activity
      cannot pause/veto; protected human/consent/reply states remain effective.
- [ ] Tag-ended lifecycle, fresh re-entry, paused-search linkage, failed/unknown CRM-write recovery
      and timestamp recording work across persistence, API and UI; no unbounded invisible failure.
- [ ] Permission/tenant tests and healthy-send/re-entry controls pass. No neighboring A repair or
      unrelated B policy slipped into the PR; no fake integration result is represented as real.
- [ ] Applicable product/help/business-rule guidance updated to distinguish CRM control from other
      safeguards. Existing historical decision records are not rewritten as runtime success claims.
- [ ] Runbook, actual rollout/rollback steps, cohort decisions, CRM registration/permissions and
      remaining integration limitations are recorded. No unbuilt recovery command is advertised.

### Production acceptance complete — not merely merged
- [ ] Owner release sign-off and agent/brokerage briefing recorded; intended control tags disclosed.
- [ ] All affected API/worker paths run compatible behavior; old activity instructions cannot undo it.
- [ ] Actual CRM registration, tag writes and synthetic end-to-end results verified with safe messaging.
- [ ] Existing cohorts safely reconciled or contained with a named operator follow-up; no unapproved
      tagging/resume/replay and no unresolved cohort quietly sending through a bypass.
- [ ] Agents can distinguish ended nurture from manual/handoff holds and setup failures, and the
      approved recovery route works without bypassing permissions or safeguards.

**Evidence status at drafting:** source/code trace and document review only. No application changes,
new behavioral tests, runtime pass, Jira publication, commit, deployment or production data operation.

## 10. References and decision precedence

- [Issue 16-A — preservation/recovery prerequisite](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — inbound safety and reply holds](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 11-A — ownership projection, not automation policy](issue-11-a-project-crm-reassignment-immediately.md)
- [Source Issue 14 and business-impact/readiness appendix, including G5/G7](../production-state-consistency-issues.md)
- [D5 change management and D7 ship-class gate](../production-state-consistency-review-consensus.md)
- [Pre-send target — includes separately released consent/uncertainty policies](../../business-rules/04-pre-send-safety-checks.md)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product, layering and design review.

The dated approved tag-only rules supersede old “human activity always pauses AI” language. Do not
reopen origin filtering or quietly adopt adjacent policies because they share the same source file.
Escalate material new product conflicts explicitly; a draft's existence is not release authorization.