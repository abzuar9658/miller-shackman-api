# Issue 16-B — Lift an opt-out only through verified resubscription or an audited human action

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the twentieth proposed Jira description, not a published issue or permission to implement.
Approval to continue drafting does not authorize production access, consent changes or release.

## 1. Business impact — read this first

**The promise:** A lead's recorded “stop” stays effective until a legitimate, specifically scoped
decision replaces it. The lead can use a supported START/resubscribe route, or an authorized human
can clear the restriction in the platform with recorded evidence, actor and reason. Support can
explain both the original restriction and its later lifting. Editing a CRM field, resuming nurture
or retrying an old event is not a substitute for that decision.

| Business question | What this ticket means |
| --- | --- |
| What is missing today? | The reviewed product records restrictions but has no verified complete START/resubscribe or audited human-clear journey. 16-A deliberately closes the CRM-field workaround without pretending those replacements already work. |
| What becomes possible? | An approved lead-originated resubscription or permission-checked platform clear can remove the particular restriction it is authorized to replace, without erasing its history. Both entry paths are part of this draft. |
| Does texting START authorize everything? | No. SMS resubscription is not email permission, global do-not-contact clearing, permission for every sender/account, or a campaign restart. Exact source/channel/sender scope requires R1 approval. |
| Can an agent click Resume to clear it? | No. Consent lifting and workflow resume are different actions and permissions. A human clear needs its own approved authorization and evidence contract. |
| Does every successful clear make the lead sendable? | No. Another restriction, provider-side block, missing destination, pending reply, handoff, pause or other safety check may remain. The UI must say what changed and what still blocks outreach. |
| Will the AI restart immediately? | Proposed boundary: lifting does not resume, enroll, send or reset a stopped journey. A journey already legitimately running may use the newly available channel at its next otherwise-permitted action. R3 must approve the exact control-message and post-lift behavior. |
| What happens to an old suppressed workflow? | Its history stays terminal. If re-entry is permitted, use a separate authorized manual-enrollment journey with fresh eligibility checks, not a hidden terminal-to-active transition. |
| Can a human clear a carrier or email-provider block? | Not by changing the local record. Provider restrictions and platform restrictions are different facts. Unsupported or unverified provider restoration remains explicit; no sender rotation or delivery-bypass workaround. |
| What if the lead opts out again? | The new applicable “no” takes effect. An old START, repeated clear request or recovery job cannot undo a later restriction it was never authorized to replace. |
| What if the CRM is stale or unavailable? | Local lifting must be durable independently of a courtesy CRM write. Stale echoes cannot undo a proven lift, but an independent applicable CRM denial must not be silently discarded. R1/R2 define how those are distinguished. |
| Who can see the evidence? | Authorized users in the correct workspace and lead scope, through a usable history/read surface. No raw-message dump, secret exposure or cross-tenant support shortcut. |

This restores a sanctioned capability, not the old unaudited CRM-field workaround. It can increase
future contactability for legitimately lifted leads, so it is a separately gated **Class B** release.
It is not legal-compliance certification or a guarantee that a provider will deliver a message.

## 2. Ticket identity, scope, and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — sanctioned consent-lifting journey; confirm at publication |
| Source / delivery class | Production-state consistency Issue 16, rule 3 and G4; D3 accepted capability loss / D7 release gate; **proposed Class B: new legitimate lifting routes** |
| Repositories / components | miller-schackman-api and miller-schackman-web; inbound/provider evidence → scoped consent decision → durable effective facts/history → operator result and separately authorized next action |
| Sequence | Twentieth draft; first of the two Issue 16 follow-ups. This neither replaces 16-A nor changes the agreed source-issue implementation order. |
| Required preservation foundation | Separately integrated 16-A, including all four refresh paths, concurrency protection and recovery exclusions. A draft is not integrated code. Its preservation-first release must not wait for this feature. |
| Required contact-safety foundation | Separately integrated 9-A receipt/STOP/guard handling and 13-B single consent/pre-send contract for the enabled routes. Do not build another contactability rule or mix an unfinished A fix into this B PR. |
| Dispatch and lifecycle | Any offered subsequent outreach needs integrated 17-A durability on that route. Use integrated 2-A instruction identity/applied-state evidence where resume coordination is involved. Lifting grants no additional engine-restart authority. |
| Related work | Preserve the actually released 12-B carrier evidence, 14-B CRM-control, 17-B uncertainty and 8-A/G1 reply-lifecycle policies. Reuse 11-A ownership, 4-A history and 15-A stopped-work visibility where integrated; do not require their whole backlog for a narrow consent read. |
| CRM boundary | Courtesy notes/custom-field updates and their delivery retries remain the other Issue 16 follow-up. Establish a shared source/version contract with it; local correctness cannot depend on that write succeeding. |
| Owners | Name product/consent owner, implementer, independent reviewer, provider-integration owner, API/web owner and release/recovery operator. R1–R4 remain open. |
| Reviewed baseline | API a761c1b and web 04d4361, traced/rechecked 2026-09-09; no live configuration or production lead state inspected. Retrace the implementation branch. |
| Release authorization | Individual D7 Class B owner sign-off plus operator/brokerage briefing. G4 capability approval is not approval of every proposed role, evidence rule, provider route or post-lift outcome. |

**Included:** lead-initiated SMS START/resubscribe and an explicitly approved email-resubscribe
entry contract; authorized, scoped human clearing; audit and effective-state consistency; retries,
late/conflicting evidence, refresh/recovery compatibility; truthful API/UI history and next steps;
bounded operational containment and release. R1 names the exact launch provider/channel matrix.

**Excluded:**
- Reimplementing 16-A preservation/recovery, changing STOP keywords or the 9-B retry window, adding
  channel fallback, changing unknown-consent policy, or rolling back already released B behavior.
- A blanket “clear all consent” button, arbitrary database edits, bulk unsuppression, deleting
  restriction history, treating renewed interest as consent, or letting an LLM authorize a lift.
- Automatic resume/re-entry, replay of old messages, catch-up sends, restoration of consumed send
  claims, a new cadence, a new confirmation-message program or automatic lead/staff notifications.
- A general preference center, new messaging vendor, raw MIME parsing, general-purpose event-sourcing
  framework, provider-wide consent administration or automatic historical opt-in reconstruction.
- Implementing the separate CRM courtesy-write feature or treating a CRM note/field as lift authority.

**D7:** Class A and Class B must not share a PR. This new lifting slice is classified conservatively
as B because it supplies contact-restoring authority; 16-A remains A preservation/recovery. Missing
A foundations require separate integration, not weakening safeguards to make the new route pass.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

- CanonicalLeadRecord stores SMS/email permission status, sms_opted_out, email_unsubscribed,
  do_not_contact, suppression_types and permission_evidence. These are not interchangeable.
  apply_contact_suppression_to_lead sets channel flags/types or global DNC and provenance; it
  **does not universally set the permission status to DENIED**. A DENIED-only fix misses real blocks.
- Suppression evidence is a flat per-kind source/time/event mapping. Later writes can replace
  its values; it is not an immutable history of grants, denials and superseding decisions.
  Contactability mapping passes suppression_types and permission statuses to the rule. The baseline
  rule's strict/default paths differ; 13-B owns that correction, not this ticket.
- process_contact_suppression_event deduplicates by workspace/provider/event, applies a restriction
  and coordinates the workflow. It has no symmetric lift use case. The inbound processor applies
  hard-word/classified opt-outs, but has no verified deterministic START-to-lift branch.
- TwilioInboundMessagePayload contains body/from/to/message/account fields, but not OptOutType or a
  complete resubscription-authority envelope. The handler resolves a unique primary phone in the
  workspace, then queues an ordinary inbound event. Twilio/email received_at is currently server
  handler time, not proof of when the recipient made the decision.
- Provider signature helpers verify only when configured; missing verification configuration can
  return without checking. Normalized FUB inbound/suppression request fields are not by themselves
  authenticated provider provenance. A working local webhook fixture is not a trustworthy lift route.
- Email routing can use a reply token with sender matching, thread references, or sender-email
  lookup. Thread-reference branches do not themselves establish the sender as the lead. Routing
  correlation, provider transport authentication and evidence of the lead's resubscription are
  separate checks; none can be substituted for another.
- Lead upsert replaces whole field values; external-event upsert can replace mutable fields such
  as received_at. A duplicate pre-read, current flat evidence mapping or in-memory merge is not
  concurrency-safe consent ordering. 16-A is still a drafted foundation at this reviewed baseline.
- CHANGE_CONSENT_SUPPRESSION_POLICY is a policy capability, not a verified per-lead clear operation.
  Brokerage admins have it; platform super-admin has broad role capability subject to active
  context checks. Managers can have RESUME_OR_REASSIGN_ANY_LEAD without the policy capability.
  No role's possession of Resume or policy-edit permission proves authority for this new action.
- Resume eligibility rejects SUPPRESSED workflows. Some opt-out PAUSED reasons permit a global
  resume-capable actor when other eligibility checks pass; that does not clear a lead restriction.
  Manual enrollment is a separate terminal-re-entry path with its own checks/reason. The baseline
  manager-resume test even treats DENIED-only SMS as contactable under the default rule; it is not
  proof of the approved 13-B safety behavior.
- Lead detail exposes flags, permission statuses and contactability/sendability, but not the full
  permission_evidence mapping as an operator consent history. LeadDetailPage has Resume controls
  and read-only channel panels, not a consent-clear journey. The existing workflow-override audit
  model covers timing/skip actions and requires a workflow; it is not automatically a consent ledger.

**Vendor-document evidence, not deployment evidence:** Twilio's Advanced Opt-Out guide, inspected
2026-09-09, documents OptOutType values START/STOP/HELP and says the provider has already replied
when that field is present. The feature is disabled by default, and keywords/sender types affect
behavior; US toll-free restoration specifically distinguishes START/UNSTOP from YES. This proves
neither that the deployed sender uses the feature nor that every body containing START is valid
consent evidence. Recheck the actual supported configuration in an authorized sandbox at R1/R4.

### 3.2 Scope the decision, not just the boolean

The parent approves **two authorities**: the lead's verified resubscription, or a permitted human's
audited platform action. The following contract makes those useful without inventing broader rights:

1. Identify the workspace, lead, channel/global scope, relevant destination and source/sender
   relationship, and the restriction or proven set of restrictions being superseded. A lift must
   explain **which prior “no” it replaces**. No “latest positive value wins across the whole lead.”
2. Preserve original negative evidence and append the later decision and its relationship to that
   evidence. “Monotonic” means the history/authority cannot be erased by CRM refresh; it does not
   mean every historical block must remain active forever after an authorized lift.
3. A channel lift does not clear the other channel or global DNC. R1/R3 must explicitly decide
   whether global DNC can be cleared by a human in this release, which authority/evidence is needed,
   and whether any lead-originated global route exists. **No SMS/email keyword implicitly clears
   DNC.** Unsupported global clearing is visibly unavailable, not silently authorized or lost.
4. Distinguish platform, CRM-only and provider-side restrictions, including multiple restrictions
   on the same channel. An independent applicable denial remains blocking until separately and
   legitimately superseded. A lift is not permission to delete a provider's block list or ignore a
   later CRM denial. Conversely, a proven stale echo of the superseded restriction must not relatch it.
5. R1 fixes the per-evidence resulting permission status and affected flags/types. Clearing an
   erroneous restriction is not necessarily proof of renewed confirmed consent; genuine renewed
   consent must not be recorded merely as erasure. Do not set everything to CONFIRMED, or use
   UNKNOWN as an unexplained escape hatch. The effective projection must be consistent with the
   approved source decision and retain independently active DENIED/flag/type/DNC facts.
6. Retain the approved unknown-consent and cross-channel policy from 13-B. Insufficient evidence for
   lifting an **existing explicit denial** means that denial remains; it is not a new rule requiring
   every otherwise-unrestricted lead to prove affirmative consent.
7. A provider confirms only what its documented event and configured scope establish. Restoration
   for one sender/service/address/group must not be extrapolated to other relationships, contacts
   or workspaces. R1 settles the mapping to the platform's current lead/channel model; do not invent
   a second general contact model just to assume away scope conflicts.

The exact SMS/email/provider and human/global matrix is a **blocking R1/R3 decision**, not a task
for the implementer to infer from an enum. Both sanctioned entry paths need an end-to-end contract.
Any narrower release needs an explicit owner-approved deferral and operator wording; a hidden or
unsupported email/global path cannot be advertised as delivered simply because SMS lifting works.

### 3.3 Lead-initiated evidence and provider trust

| Candidate input | Required interpretation |
| --- | --- |
| Verified, correctly routed Twilio resubscription event for the approved sender configuration | Normalize the provider's explicit opt-in evidence and approved scope, then apply the same consent-decision boundary as the human route. It must work without an LLM or a live nurture engine. |
| Body START/UNSTOP or a configured alternative without verified provider opt-in metadata | R1 must establish the exact supported normalized entry, identity proof, keyword normalization and provider semantics before it can lift anything. Missing metadata is not automatic proof of either consent or carrier restoration. |
| Verified email resubscription through an approved provider/inbound route | R1 must name the actual user action, event, identity proof and unsubscribe scope, including provider account/group/global distinctions. A generic incoming email, open/click/delivery event or matching thread is not sufficient. |
| HELP, unrelated affirmative wording, quoted/forwarded START, “restart my search,” model-detected interest, or contradictory evidence | No implicit lift. Retain the normal safe inbound disposition or a truthful unresolved-consent reason as approved; do not substring-match or classify willingness into consent authority. |
| CRM consent field becomes permissive, a tag changes, an agent adds a note, or a provider block-list entry is administratively deleted | Not a platform lift by itself. Preserve supported CRM-only updates under 16-A, but do not convert them into a lead-initiated resubscription or audited platform clear. |
| Invalid/unverified request, wrong account/sender/destination, ambiguous lead, unknown scope or unsupported configuration | No consent-state mutation. Reject or retain a scoped unresolved item according to the approved ingress contract, without trusting caller-supplied tenant/source labels. |

- Authenticate the actual request source and bind it to the configured workspace and sender/service
  before treating its fields as authority. Fail closed for positive consent mutations when required
  verification is absent, invalid or unsupported, including nominally successful unverified dev paths.
  Negative-event safety under 9-A/12-B must not be accidentally disabled by this new positive gate.
- Resolve the recipient/destination uniquely within the authorized scope, then revalidate that
  association at application/commit time. Shared/recycled/replaced phone or email, a changed primary
  destination, forwarded thread, provider-account change or lead merge needs explicit handling.
  No inferred lift on all leads sharing an address, nor on another workspace with the same CRM ID.
- Preserve original provider event/message identity, available trusted occurrence evidence, actual
  accepted receipt time, normalization/verification basis and original target scope. Redacted display
  strings are not unique contact identities. Keep needed linkage private; never retain credentials
  or raw signatures as audit evidence.
- Handle an approved control event deterministically rather than asking a model whether it counts.
  Under 9-A, durably account for that event and its own processing protection; do not strand a
  verified START behind an unavailable classifier or release another unresolved reply's guard.
  Unsupported or substantive free text follows the existing safe reply path, not a permissive guess.
- Do not generate a second application acknowledgment when the provider has already confirmed the
  control event. Provider acknowledgment does not prove local lifting committed, and local lifting
  does not prove provider restoration or message delivery. Optional enrichment/CRM failure must not
  roll back an already committed local decision or repeat lead-facing side effects.

### 3.4 Durable history, ordering and a single effective projection

**Audit is part of the mutation, not an optional log line.** Reuse the smallest suitable durable
domain/persistence boundary, but do not pass off the existing mutable evidence blob as a full ledger.

- Record decision identity; original restriction references; previous and resulting effective scope;
  source/verification/evidence reference; occurrence, receipt and applied times with provenance;
  operation/request identity; and result, including rejected/stale/unresolved where appropriate.
  Human actions additionally record server-derived actor, effective permission/role context and
  non-empty reason. Distinguish human correction from asserted renewed consent and from provider fact.
- Preserve history when actor membership changes or a workflow finishes. A lead with no workflow
  can still have a consent decision. Do not fabricate a workflow, classification artifact or handoff
  to fit an unrelated audit schema. R2/R3 fix retention, readable fields and access restrictions.
- Commit effective facts and their authoritative audit decision atomically, or prove an equivalent
  fail-closed reconstruction boundary. There must be no interval in which sends can observe a clear
  that has no durable authority. A failed transaction leaves the old restriction effective; a lost
  response after commit is recoverable by the original operation identity, not by another blind clear.
- Deduplicate repeated provider events and human requests with durable uniqueness/ownership, not a
  pre-read alone. Reuse of an identity with different actor/target/scope/payload must be a conflict,
  not a second operation or overwrite. A duplicate may report its original outcome while also
  reporting the **current** effective restriction; old success is not proof the lead is still clear.
- R2 specifies ordering for each source. Use trusted event order/causality and explicit supersession,
  not worker arrival order, row updated_at, CRM snapshot age, or a caller-controlled clock alone.
  An already-applied older lift cannot clear a newer STOP. A proven superseded old STOP/CRM echo
  cannot erase the lift merely by replaying later. A genuinely new applicable denial still blocks.
- If order, provenance or scope is insufficient/contradictory, do not guess a positive permission.
  Retain known applicable protection and expose an owned unresolved condition. Approve the treatment
  of equal timestamps, delayed first delivery, future times, absent ordering evidence and overlapping
  source scopes. An arbitrary event-ID sort must not manufacture business precedence.
- A human clear acts on the reviewed restriction/version set, not whatever happens to be current
  when a delayed request finally executes. A newer restriction, changed destination or revoked role
  must force revalidation/conflict rather than applying stale authority. No database lock across
  avoidable provider/CRM/LLM calls; trace every reader/writer before choosing the concurrency boundary.
- CRM refresh must still update ordinary CRM-owned fields, preserve other app-owned state and the
  newest agent-activity timestamp, and honor genuinely new restrictions. All four paths consume the
  same effective suppression decision. A blanket OR over historical flags prevents legitimate lifts;
  a blanket “local clear always wins” can suppress a genuine new no. Neither is acceptable.
- Coordinate 16-A historical restoration, live suppression writers, 12-B late carrier evidence,
  inbound retries and the future CRM courtesy-write outbox against the same decision/scope contract.
  Identify a provider callback by its original send/event, not just callback-arrival time. A delayed
  CRM opt-out write must not resurrect superseded local state, and no future permissive write may
  erase a newer denial. Do not require successful CRM synchronization for correct local projection.
- Accepted-but-unapplied events/requests need bounded retry or a discoverable, source-owned failure
  with an authorized remedy. Preserve request scope and revalidate at retry. No “received = lifted,”
  failed request marked successful, unbounded replay or second generic retry owner. R2/R4 specify
  progress, attempt/claim expiry, discovery and lag bounds; reuse 9-A/15-A contracts where applicable.

### 3.5 Consent lifting is not workflow control

The following is the **proposed post-lift boundary for R3 approval**, not permission to invent an
automatic resumption policy:

1. Apply and expose the consent decision without sending, creating enrollment, resetting progress,
   clearing handoff/human ownership, resolving an unrelated review or emitting a resume command.
   Control-event handling may complete only its own inbound-processing obligation under 9-A.
2. Preserve manual pause, human_handoff, human_owned and terminal/successor-run controls. Preserve
   global DNC outside the explicitly authorized clearing scope (§3.2/AC-19); a human DNC clear is
   allowed only if separately approved in the R1/R3 matrix. SMS/email resubscription and channel
   clears never implicitly lift DNC.
   A currently running eligible journey can use its normal next action after all live checks. Do not
   introduce a new mandatory manual pause for every lift or an immediate catch-up action.
3. For an opt-out-paused journey, show remaining restrictions and the existing authorized Resume
   route if eligible. The user separately requests it, records its reason and passes current
   ownership, campaign, contactability and other safety checks. Resume permission is not clear
   permission; clear permission is not resume permission. Keep queued/accepted/applied distinctions.
4. For SUPPRESSED/completed/closed history, do not reopen the old run. If the actual released
   admission rules allow manual re-entry, expose that separate action with its reason/permission,
   fresh CRM/pre-send checks and caps. Otherwise show why no supported continuation exists. Tag
   re-add exceptions remain 14-B's specifically scoped policy, not a general lift-to-enroll shortcut.
5. Every subsequent cadence, paused-search, AI-reply, send-now or draft-approval send uses the same
   current consent and durable-dispatch checks. Lifting cannot reissue an accepted/uncertain/sent
   logical touch, unclaim an idempotency key, restore an old outbound draft to “ready,” or reset a
   cadence/AI/contact budget. A new STOP still fences work not yet past the committed send boundary;
   a message already accepted by a provider cannot honestly be promised recalled.

### 3.6 The human and support journey must be complete

- Use the existing lead-detail/action/read conventions. Show the active restriction's channel/global
  and source scope, safe evidence/time, and supported action or named support route. Do not present
  every blocked channel as clearable, or make support query a raw database to understand the result.
- R3 approves a per-role/per-scope matrix: assigned agent on own/other lead, manager, brokerage admin,
  platform support/super-admin, inactive user/member/workspace and cross-workspace actor. Prefer a
  narrowly named per-lead capability or explicitly approved reuse; do not silently reuse the policy
  capability or expand every Resume role. Authorization is server-side and rechecked at application.
- Confirmation must name exactly what will change, request a non-empty reason and required evidence,
  identify the reviewed restriction set, and explain remaining provider/global/workflow limitations.
  The server derives the actor; a client cannot choose actor, grant scope or authoritative timestamp.
  R3 decides evidence requirements, correction versus renewed-consent reasons and any stronger DNC
  approval. No two-person approval or default role grant is assumed in this draft.
- Loading, no permission, no matching restriction, unsupported source, incomplete evidence, stale
  state, verification failure, failed mutation and uncertain response need distinct useful outcomes.
  A timeout triggers a read of the original operation, not a new request that could clear a new STOP.
  Disable accidental duplicate submission, but prove server idempotency independently of the button.
- Refresh effective consent, history, allowed actions and resume/enrollment eligibility after a
  committed result. Clearly distinguish received, pending, applied, rejected, stale, unresolved and
  already-applied outcomes. The exact API/status names remain a design decision. “Platform SMS
  restriction lifted; email/DNC/provider/workflow restriction remains” is not “ready to send.”
- Authorized history readers can inspect original and superseding decisions across reload/restart
  and older history pages, including lead-without-workflow cases. Use current effective ownership
  for assigned-agent scope; reassignment must revoke stale read/action access. Role-limited details
  and safe reasons are preferable to exposing the whole evidence payload or deleting the history.
- A blocked/unsupported action must end in a usable owned remedy, not an inert “contact support”
  label. R3 names who handles missing provider resubscription, ambiguous evidence, CRM conflicts and
  incomplete decisions, and what that person can actually do. Seeing or dismissing an item is not
  authority to clear it. No universal retry/force-clear control is introduced.

### 3.7 Remaining implementation and release gates

All four gates are **open**. Their decisions must be recorded before the affected expectations are
coded. A review draft can be complete while the ticket is not yet ready for implementation/release.

| Gate | Required decision/evidence | Accountable owner |
| --- | --- | --- |
| R1 — Sanctioned source and scope matrix | Name launch SMS/email provider entry points and actual user action; verify sender/account/destination and source authentication; approve keywords/normalization, trusted occurrence evidence, contact-change handling, source/sender/group/global scope, overlapping-denial/CRM-echo treatment and resulting status/flags. Confirm this slice's Class B boundary. No invented email resubscribe callback. | Product/consent owner + provider integration owner + security reviewer |
| R2 — Durable decision and concurrency contract | Choose authoritative retained history and effective projection; restriction-set/version binding; uniqueness/conflicts; trusted order, ambiguous/equal/missing-time treatment; transaction/send boundary; retry/discovery ownership; all refresh/live-negative/callback/recovery integrations. Review at least two minimal designs under §6 before implementing. | API/persistence owner + independent reviewer |
| R3 — Permissions, operator evidence and post-lift journey | Approve role/scope/evidence matrix, any human DNC clearing, read/privacy/retention contract, control-message disposition, no implicit resume/re-entry boundary, current-channel effects and separately authorized next actions. Name real support remedies and API/UI failures, including provider still blocked. | Product owner + API/web/security owners + operations owner |
| R4 — Compatibility, history and bounded rollout | Identify deployed writers/providers/configuration, old queued requests and evidence-limited history; approve migration/containment/rollback and monitoring bounds; prove sandbox ingress/provider behavior without real-customer traffic; separately authorize any bounded production data operation and release. | Release/recovery operator + product owner |

G4 is addressed only to the scope actually built, tested and briefed; drafting this ticket does not
close it. D1's fallback and D2's no-automatic-re-entry decision stay settled. Resolve new evidence or
authority ambiguity with the owner rather than reopening the multi-LLM consensus or guessing policy.

## 4. Business acceptance scenarios — for approval

These are **proposed requirements, not passing tests**. R1/R3-dependent scenarios use the approved
source/role/scope matrix; each row must expand into explicit expected values before implementation.
The implementer may not choose a convenient result because the current code happens to return it.

**Common setup:** synthetic workspace-scoped leads, valid destinations and otherwise eligible
controls; independent literal source IDs/times; known active restriction identities and current
workflow/run; fixed controllable clock; recording provider/CRM/LLM fakes. Exercise actual ingress,
application, persistence and scoped read boundaries as appropriate. No real lead/provider traffic.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Record an SMS opt-out, then deliver an approved, verified newer SMS resubscription; LLM is unavailable. Repeat for a lead with no workflow and one with only terminal history/no live nurture workflow. | Actual provider ingress produces the specifically covered platform SMS lift once; source, original restriction and new decision survive a fresh read. No LLM or live nurture workflow is needed for that control decision; no workflow is created or reopened. | Still permanently latched, waiting for nurture execution, silently cleared without evidence, or classified into opt-in by AI. |
| AC-02 | Deliver approved keyword variants and non-controls: HELP, quoted/forwarded START, substring matches, ordinary interest and contradictory metadata/body. | Literal R1 rules distinguish allowed controls from non-lifting replies; ordinary safe reply handling remains intact. | Broad substring/LLM match, or trusting a provider field whose scope/configuration is unverified. |
| AC-03 | Use the approved email resubscribe user/provider journey with a known unsubscribe scope, including no-workflow and terminal-history/no-live-nurture cases; repeat with an unrelated group/account or generic email engagement event. | Only the explicitly covered email restriction is replaced; SMS/global/other-source restrictions remain. Actual approved email ingress reaches the persisted decision without requiring or creating a live nurture workflow. | Treating email receipt/open/click or deletion from a provider list as universal platform consent, or requiring/reopening nurture to apply the lift. |
| AC-04 | Send invalid signatures, absent required verification config, forged source labels and untrusted normalized requests to each positive mutation entry. | No lift or exposed consent data; clear safe rejection/unresolved result under the approved contract. | A dev/test bypass or caller-supplied provider/workspace field grants contact authority. |
| AC-05 | Valid provider identity but wrong workspace/account/service/sender/destination; two workspaces share CRM IDs or a phone. | Mutation and readable result stay within the correctly bound authorized scope; mismatches cannot lift. | Cross-tenant or cross-sender unsuppression. |
| AC-06 | Ambiguous/shared destination, forwarded email thread, replaced primary contact or contact change between receipt and application. | No guessed identity/scope; revalidation yields the approved conflict/owned unresolved result. A unique unchanged control succeeds. | Lifting all matches or transferring old proof to a new address/number. |
| AC-07 | An R3-authorized human reviews a restriction and confirms its scoped clear with valid reason/evidence. | API/UI show the exact applied change, server-derived actor, original restriction, reason and remaining blockers after reload. Works without a workflow. | Backend-only capability, fake workflow/audit record, hidden clear-all or automatic Resume. |
| AC-08 | Exercise every approved role/scope combination, including assigned other-lead, manager, admin, support and inactive/cross-workspace cases. | Only the explicit matrix permits clearing/reading; denied paths mutate nothing and leak no evidence. | Inferring permission from Resume/policy-edit/UI visibility alone. |
| AC-09 | Missing/blank reason, insufficient evidence, forged actor/time, unknown restriction or reused request key with changed scope/payload. | Validated safe denial/conflict; original request/history remains unmodified. | Client-controlled authority, fabricated consent evidence or broad overwrite. |
| AC-10 | Open clear confirmation, then commit a new STOP, change ownership/destination or revoke actor membership before submission/retry. | Fresh validation prevents stale authority from clearing the new restriction or acting outside current permission. | Applying what the old page allowed to whatever restriction exists now. |
| AC-11 | Repeat the same successful human request after a response loss; then repeat it after a later STOP. | One original decision; duplicate reports original outcome and current effective state. Later STOP stays active. | Second clear, duplicate audit decision, or stale “success” shown as currently sendable. |
| AC-12 | Concurrently deliver the same provider control/retry through duplicate ingress/worker paths. | One effective decision under durable uniqueness; receipt/source evidence is stable and no extra side effects occur. | Pre-read race overwrites provenance, applies twice or produces duplicate acknowledgments. |
| AC-13 | Apply STOP S1, authorized lift L2, then a genuine later STOP S3; replay L2 and stale human requests. | S3 blocks its scope; S1/L2/S3 remain explainable. | Old positive permission clears a new no. |
| AC-14 | Deliver a provably superseded old negative event or old lift out of order, including a callback tied to an older send. | R2's trusted order/supersession gives the same effective result as ordered processing; original history is retained. | Callback/worker arrival time treated as new user intent. |
| AC-15 | Equal/conflicting/future/missing timestamps or insufficient source linkage prevent authoritative ordering. | No guessed positive permission; known applicable restriction remains with an owned unresolved reason. A well-ordered control succeeds. | Arbitrary timestamp/event-ID sort or permanent blanket block on every clean lead. |
| AC-16 | Before and after legitimate lifting, run full/incremental sync, people webhook, pre-send refresh and on-demand refresh with omitted, false and permissive CRM fields. | Before lift: restriction/evidence survives. After lift: legitimate effective result/history survives. Ordinary fields, paused-search state and newest activity still update correctly. | Weakening 16-A, relatching every historical restriction, or freezing the whole lead row. |
| AC-17 | Refresh a proven stale CRM echo of the superseded denial; separately apply an independent/new applicable CRM denial and an ambiguous-source conflict. | Echo cannot undo the proven lift; independent denial blocks; ambiguity remains contained under R1/R2. Proven CRM-only baseline clearing still works. | Ignoring every CRM no after a local lift or blindly copying every stale no back. |
| AC-18 | Same channel has overlapping platform/CRM/provider restrictions and DENIED/flag/type representations; lift one approved scope. | Only proven superseded facts become inactive; effective status/flags/types and all send/read consumers agree. Other denials remain. | Clearing one boolean while a stale duplicate relatches it, or clearing all sources/statuses to CONFIRMED. |
| AC-19 | Channel resubscription arrives with global DNC or other-channel suppression; exercise the approved human/global matrix separately. | Channel action never clears DNC/other channel. Any supported human DNC clear uses its explicitly stronger approved evidence/permission and leaves other restrictions intact. Unsupported routes say so. | SMS START, email resubscribe or a channel-clear permission removes global DNC. |
| AC-20 | Fail persistence before/between required writes; crash or lose response immediately after commit, then reload/retry. | Effective lifting and authority are inseparable; rollback keeps protection, committed operation is recoverable once with truthful current result. | Unlogged interval of sendability, lost history or blind second mutation. |
| AC-21 | Deterministic independent-transaction races: stale CRM/suppression snapshot vs lift; newer STOP vs delayed lift. Test both commit orders. | Fresh Postgres reads and actual send checks honor the same committed authority/order; unrelated fields are preserved. | Last-writer-wins erase/relatch, or a single fake repository presented as race proof. |
| AC-22 | Reload/restart and traverse older consent history, with reassignment and role-limited readers, including lead-without-workflow. | Correct effective state plus original/superseding evidence remain accessible only to authorized current readers; no latest-only dead end. | Whole-payload export, stale-owner access or audit history disappears with workflow completion. |
| AC-23 | Lift consent on manually paused, handoff, human-owned, terminal or successor-run leads; compare an already-running eligible journey. | Protected lifecycle/progress remains unchanged. Active control keeps its existing schedule; no lift-triggered send/start/reset. | Clearing human control, terminal resurrection, or imposing a new pause on every active lifted lead. |
| AC-24 | After a successful lift, explicitly Resume an eligible opt-out-paused journey using the existing authorized route; try without resume permission or with remaining blockers. | Separate reason/authorization/revalidation and truthful queued/accepted/applied status. Denied control remains stopped; Resume alone never lifts consent. | Treating clear permission as resume permission or fabricating applied engine state. |
| AC-25 | After lifting, try automatic and approved manual re-entry from SUPPRESSED history. | Automatic re-entry remains rejected; any permitted manual route records its reason and new run under current caps/checks. Old run stays terminal. | Terminal-to-active rewrite, automatic tag cycling or undocumented broad re-entry authority. |
| AC-26 | Approved START completes while another reply remains unresolved, or an older classifier/expiry worker finishes late. | Only the control event's own 9-A obligation can complete; other guards/reviews and newer negative decisions remain effective. | Lift releases every reply hold, late AI clears consent, or optional classifier failure strands the deterministic control. |
| AC-27 | Provider already acknowledged a control event; optional summary/CRM completion fails or retries. | Durable local decision remains; no new application lead acknowledgment or repeated lead-facing effect. Provider acknowledgment and local applied status remain distinct. | Second “you are subscribed” message, CRM dependency rollback or duplicate inbound side effects. |
| AC-28 | Through standard cadence, paused-search, AI continuation, send-now and draft approval, exercise actual sends before and after lifting with otherwise legitimate controls. | Blocked channel has zero fake-provider calls before lift; a separately permitted next action after valid lift dispatches once through current pre-send/17-A checks. Assert channel and touch identity. | Tests pass only because unrelated guards block everyone, or one outbound path bypasses remaining consent. |
| AC-29 | Commit a newer STOP after lift while outbound work is queued/preparing; also test the documented already-dispatched boundary. | Work not past the approved send boundary observes the new denial; already-accepted contact is reported honestly and future work stays protected. | Stale consent snapshot authorizes another send or a false guarantee of recalling accepted traffic. |
| AC-30 | Lift with old accepted/uncertain/sent messages, pending drafts and consumed steps/AI turns present; retry old commands. | Original touch claims, progress, budgets and actual released uncertainty policy remain; no old-message resend or catch-up send. | Unclaiming/reissuing a touch because consent is now available. |
| AC-31 | Accepted lift work stalls/crashes/exhausts before application; restart discovery and request an authorized bounded retry. | Pending versus applied is truthful; source-owned failure is discoverable with remedy. Retry retains original scope and revalidates current restrictions/authority. | Silent lost request, unbounded replay or retry that clears a newer STOP. |
| AC-32 | Local clear succeeds while CRM is down or a provider still has a known restriction/unknown restoration status. | Local decision/history persists; UI identifies remaining limitation and supported remedy. No provider-block bypass, false restored/delivered claim or trial send to discover consent. | Treating human clear/CRM success as provider proof, sender rotation or suppressing the failure. |
| AC-33 | Run authorized 16-A-compatible recovery over old restrictions with later proven lifts, later STOPs and conflicting evidence; dry-run, apply and repeat. | No writes in dry-run; superseded evidence is not reasserted, newer denials remain and ambiguity is reported. Repeat is stable without send/resume/enroll. | Blind replay of original inbound/suppression use cases undoes lift or repeats external effects. |
| AC-34 | Legacy records lack provenance, old raw START text exists, an unmatched event later finds a lead, or an old clear request crosses cutover. | Inventory/explicit approved adjudication before any positive mutation; no fabricated historical consent or automatic grant to a newly matched contact. Existing clear restrictions remain protected. | Bulk unsuppression from text search, generic retry, current CRM values or inferred identity. |
| AC-35 | UI/API sees loading, empty history, audit unavailable, unauthorized, stale, pending, failed and duplicate-success-with-new-STOP outcomes. | Accurate action/read states and owned next step; no optimistic “ready to send,” secret exposure or ability to bypass the server contract. | Hidden blocker, dead support link, or presenting unavailable history as proof no restriction exists. |
| AC-36 | Rehearse feature disable, old-writer cutover, rollback and restoration with fixture queued work and existing decisions. | New lifts can be contained without disabling negative ingestion, deleting history, relatching proven lifts or allowing unsafe sends; only verified scope is re-enabled. | Rollback through a writer unable to honor decisions, blanket historical replay or data wipe. |

AC-28 is a post-lift **separately allowed send**, not a requirement that START itself produce one.
If the launch matrix defers a provider/global/continuation route, record the owner decision and
unavailable behavior explicitly. Do not label its missing positive journey a passing acceptance case.

## 5. Testing boundaries and mandatory red → green workflow

**Proposed boundaries — agree before writing tests:**
- Real supported ingress/normalization/authentication → application consent decision → scoped
  detail/history read for lead-originated and human paths (AC-01–19, AC-22, AC-31–32, AC-35).
- Real Postgres repository/transaction/restart behavior for audit/effective-state atomicity,
  idempotency, ordering and independent concurrent writers (AC-11–22, AC-31, AC-33–34, AC-36).
- Actual four refresh paths, 16-A repair boundary and live suppression/callback consumers for
  shared projection compatibility (AC-13–21, AC-33–34). Include raw omitted-field mapper cases.
- Application/business-flow journeys plus recording external providers for separate resume/manual
  re-entry, reply guards and every actual outbound route (AC-23–30). Temporal integration where
  commands/run boundaries matter; a saved signal alone is not an applied-resume test.
- API role/tenant/history tests and frontend user interactions for the full human/support journey,
  including loading/errors/stale state and post-action reads (AC-07–10, AC-22–25, AC-31–32, AC-35).
- Separately authorized provider sandbox and deployment rehearsal for configuration, actual
  resubscribe-event delivery/acknowledgment and R4 rollback (AC-01–06, AC-27, AC-32, AC-36).

**Allowed fakes:** external provider/CRM/LLM transport, clock and hand-written application-test
repositories. Reuse existing fixtures. A verification test must exercise the actual signature/identity
boundary with synthetic test material, not stub “trusted = true.” Keep secrets out of commands,
logs and evidence. Fakes cannot prove configured provider resubscription or database durability.

**Not acceptance proof:** calling a private helper that deletes a flag; stubbing permission,
contactability, supersession or send decisions; mocked upsert returning the expected record;
deriving expected audit/state from implementation helpers; asserting no send without a legitimate
send control; a UI toast without fresh backend reads; skipped persistence/provider integration.

1. Approve one scenario's explicit source/role/scope, expected/forbidden result and public boundary.
   Write one behavior test and run it against unchanged application code. Capture the meaningful
   business failure before implementing. A good first case is verified resubscription → persisted
   scoped lift/read, with other restrictions intact and no automatic outreach.
2. If the new entry point/audit read does not exist, add only minimal interface/no-op scaffolding
   so the test can run and fail on the absent business effect. Record its revision separately.
   An import/404/collection failure alone is not red evidence of missing consent behavior.
3. Implement the smallest approved change, rerun the same expectation to green, then take the next
   vertical scenario. Do not implement both journeys wholesale and add confirming tests afterwards.
4. Later tests may already pass after a shared correction. Demonstrate their regression value on the
   relevant baseline or isolated sensitivity variant. Baseline controls may pass from the start;
   label them honestly instead of manufacturing red. Unavailable infrastructure, empty selections,
   skipped tests and invalid fixtures are neither qualifying red nor green acceptance.
5. Do not weaken expectations to get green. Explain legitimate fixture corrections; changed business
   expectations need owner approval. Run focused node → file → related target, then broader checks.
6. In an isolated checkout/test database, disable positive-source validation, narrow-scope checking,
   ordering/version fencing, and atomic audit/effective projection one at a time. Relevant tests must
   fail for the intended reason. Similarly disable lift-aware refresh/recovery and verify regression
   detection. Restore changes and rerun; never fault-inject production or leave mutations in the PR.

### Evidence required in the implementation PR

One row per AC and relevant matrix case; this blank table is not completed evidence.

| AC / source-role-scope case | Exact test/check and command | Baseline/scaffold revision + meaningful red | Fix revision + green/counts | Sensitivity/control evidence | Remaining integration or owner gate |
| --- | --- | --- | --- | --- | --- |
| Implementer fills in | Reproducible invocation/setup | Failed business assertion, not collection | Exit code and pass/fail/skip counts | Disabled protection or baseline control | Explicitly unverified scope |

Independent reviewer compares expectations with this contract, inspects weakened/deleted assertions
and checks both restored contactability and retained protections. “All tests pass” is insufficient.

## 6. Engineering starting points — verify, do not blindly patch

Paths are repository-relative navigation hints at the reviewed baseline, not an edit prescription.
New consent-decision, audit and mutation APIs are requirements, not claimed existing symbols.

| Responsibility | Existing reference |
| --- | --- |
| Canonical and effective facts | API: app/domain/leads/canonical.py; app/domain/compliance/contactability.py; app/application/services/canonical_lead_inputs.py |
| Restriction writers and inbound processing | API: app/application/use_cases/process_contact_suppression_event.py; app/application/use_cases/process_inbound_message_event.py; app/application/use_cases/enqueue_inbound_message_event.py |
| Provider ingress/schema | API: app/interfaces/api/v1/webhooks.py; app/interfaces/api/schemas/inbound.py; app/application/ports/messaging.py — send ports are not consent-administration ports |
| Refresh and mapping | API: app/application/use_cases/crm_sync.py; app/application/services/crm_lead_refresh.py; app/application/services/pre_send_crm_refresh.py; app/infrastructure/crm/follow_up_boss/lead_mapper.py; app/infrastructure/crm/follow_up_boss/webhook_event_people.py |
| Persistence and event history | API: app/infrastructure/persistence/postgres/lead_repository.py; app/infrastructure/persistence/postgres/crm_sync_repository.py; app/application/ports/repositories.py |
| Actor/role and current lead scope | API: app/domain/identity/permissions.py; app/interfaces/api/dependencies/auth.py; app/application/services/lead_assignment.py; app/application/use_cases/lead_read.py |
| Resume, admission and dispatch | API: app/application/use_cases/lead_resume.py; app/application/use_cases/lead_manual_enrollment.py; app/domain/campaigns/enrollment_admission.py; app/domain/workflows/models.py; app/application/use_cases/send_outbound_message.py; app/application/use_cases/revalidate_outbound_send_request.py |
| Existing audit pattern and lead response | API: app/domain/workflows/override_audit.py; app/interfaces/api/v1/leads.py; app/interfaces/api/schemas/leads.py — do not require a workflow merely to reuse its audit |
| Operator UI/client | Web: src/pages/LeadDetailPage.tsx; src/lib/api/leads.ts; src/pages/HandoffsPage.test.tsx — neighboring page-test pattern only |

**R2 design alternatives to evaluate, not implementation approval:**
- Extend suitable existing event/audit persistence with append-only consent-decision records and a
  narrowly protected canonical projection. Advantages: existing tenant/transaction/read conventions,
  fewer new storage concepts, low read overhead. Risk: mutable external-event upserts or workflow-only
  audits may not support immutability, identity and retrieval without careful changes.
- Add a small consent-specific decision/history store and derive/update the same canonical projection
  transactionally. Advantages: explicit scope/supersession and lead-without-workflow audit. Costs:
  migration, indices, compatible writers and additional lifecycle ownership; avoid two authorities.

Prefer the smallest design that proves the full contract; present concrete maintainability, latency
and V1-scope trade-offs and obtain approval before code. Neither “just reset booleans” nor a generic
event-sourcing framework is justified. Keep policy inward and vendor payloads/SQL in adapters;
preserve workspace/RLS constraints. Any migration/dependency needs its own justified approval.

### Existing test starting points and commands

Use Python 3.12/uv in the API repo and pnpm in the web repo. Install only declared dependencies as
needed. The existing regression and UI-pattern targets below **do not prove the new lifting behavior
is implemented**.

<augment_code_snippet mode="EXCERPT">
````bash
uv run pytest tests/application/use_cases/test_process_contact_suppression_event.py -v
uv run pytest tests/application/use_cases/test_process_inbound_message_event.py -v
uv run pytest tests/application/use_cases/test_lead_resume.py -v
uv run pytest tests/interfaces/api/v1/test_webhooks.py -v
uv run pytest tests/interfaces/api/v1/test_leads.py -v
uv run pytest tests/domain/identity/test_permissions.py -v
````
</augment_code_snippet>

Also extend tests/application/services/test_canonical_lead_inputs.py,
tests/domain/compliance/test_contactability.py, tests/domain/campaigns/test_enrollment_admission.py,
tests/application/use_cases/test_crm_sync.py, tests/application/use_cases/test_send_outbound_message.py,
tests/application/use_cases/test_business_flow_harness.py and
tests/infrastructure/crm/test_follow_up_boss_webhook_event_handler.py for relevant matrix controls.

<augment_code_snippet mode="EXCERPT">
````bash
uv run pytest tests/infrastructure/persistence/postgres/test_lead_repository.py -v -ra
uv run pytest tests/infrastructure/persistence/postgres/test_crm_sync_repository.py -v -ra
uv run pytest tests/infrastructure/persistence/postgres/test_reporting_and_rls.py -v -ra
uv run pytest tests/infrastructure/persistence/postgres/test_business_flow_harness.py -v -ra
make lint
make typecheck
make test
````
</augment_code_snippet>

Add focused lead-detail consent-action/history tests as part of this slice; no dedicated lead-detail
test file exists at the reviewed web baseline. The existing handoff-page test below is a neighboring
fixture/rendering pattern, not lifting coverage. Record and run the new test target once created.

<augment_code_snippet mode="EXCERPT">
````bash
pnpm vitest run src/pages/HandoffsPage.test.tsx
pnpm lint
pnpm typecheck
pnpm test
pnpm format:check
````
</augment_code_snippet>

Add exact new test nodes/commands once approved boundaries exist. Confirm Postgres test targets are
local/disposable before invoking their create/drop harness; single-session rollback fixtures do not
prove independent-transaction races. Skips leave required integration unverified. Provider sandbox
checks, real callback configuration and UI checks need authorized test scope; unit fakes are not
substitutes. Do not run these behavioral suites merely to label this documentation draft “tested.”

## 7. Historical compatibility, rollout and rollback

1. **Inventory without granting consent:** name all deployed canonical/suppression/refresh/recovery
   writers, sender/provider configurations, accepted pending inputs, affected legacy evidence and
   read consumers. Distinguish production observations from the code baseline. No bulk text search
   over historical START messages may silently become a consent grant.
2. **Close R1–R3 and prepare compatible storage/readers first:** keep lifting disabled for unsupported
   scopes. Retain 16-A's negative protection; verify schema/backfill plans never manufacture renewed
   consent, clear denials, create fake event times or replace original evidence. Rehearse rollback.
3. **Coordinate every writer:** old preservation code that blindly retains/reasserts a restriction
   can undo a new lift; old whole-row writers can erase a new STOP or the lift authority. Compatible
   deployment or explicit containment must cover webhooks, workers, refresh, repair and later CRM
   outbox work. Do not enable positive mutations while any incompatible active writer can clobber them.
4. **Rehearse the actual provider and human journeys:** synthetic/local tests plus an explicitly
   authorized provider sandbox prove configured SMS/email resubscribe receipt, evidence, acknowledgment
   and scope. Then use a permitted test user to clear a fixture, reload history, inspect remaining
   blockers, and separately Resume/re-enter only where permitted. Capture no real-customer traffic.
   Confirm blocked controls never dispatch and an independently allowed post-lift control sends once.
5. **History/recovery is a separate authorization:** 16-A repair remains evidence-backed restoration,
   now with lift-aware exclusion/order. Dry-run by default, explicit workspace and bounded cohort,
   inspect known restrictions/lifts/new denials/conflicts and reconcile totals before approved apply.
   Missing evidence stays reported/contained; do not recreate consent by running an LLM or replaying
   the whole inbound pipeline. A retrospective human adjudication records its real actor/time/basis,
   not a fabricated past lead resubscription. No automatic enrollment, resume or sends during repair.
6. **Brief operators before enablement:** name supported provider/channel/scope and roles; explain
   the reason/evidence requirement, provider-versus-platform distinction, retained CRM limitation,
   possible future channel use by an already-running journey, and separate Resume/manual-enrollment
   actions. State unavailable routes honestly. D3 capability loss and D7 release sign-off still apply.
7. **Enable only verified scope and observe:** R4 records measurable ingress-to-decision and failure
   discovery bounds, unresolved/stale/conflicting counts, duplicate outcomes, refresh regressions,
   negative-event protection and post-lift send failures, with an operator and actual monitoring route.
   Missing telemetry is not a healthy zero. Unexpected clearing or clobbered authority triggers
   containment of affected positive mutations and sending while evidence is retained.

**Rollback:** disable new lift entry/application where necessary, without disabling STOP/negative
ingestion, deleting consent history or automatically undoing valid decisions. Contain affected sends
and incompatible refresh/recovery writers before returning to older code that cannot honor the
decision contract. Inventory requests already accepted or in flight; retain their identity and
truthful disposition. Re-enable only after authoritative state and all writers are verified. Exact
commands, target/scope, operator and recovery validation belong in the implementation runbook, not
invented here. Production data changes or provider configuration changes require separate approval.

## 8. Definition of done and review gates

### Ready for implementation
- [ ] Product owner approves §1–4 outcomes, exclusions and explicit Class B boundary; R1–R3 decisions
      are recorded with actual launch source/role/scope matrix and first meaningful failing scenario.
- [ ] 16-A/9-A/13-B and route-specific 17-A/2-A prerequisites are integrated/verified as required;
      no dependency is assumed delivered merely because a draft exists.
- [ ] Public test boundaries, design choice and no implicit resume/re-entry contract are approved.
- [ ] Implementer, reviewer, provider/API/web owners and release/recovery operator are assigned.

### Ready to merge
- [ ] Every AC/matrix case has red/green/control/sensitivity or explicit authorized integration evidence;
      required skips/failures are not reported as passes and missing routes are not hidden.
- [ ] Both sanctioned paths have complete ingress/action, durable authority, effective-state, audit,
      permission, failure, history and operator-result behavior for the approved launch scope.
- [ ] Real persistence/concurrency/refresh/recovery compatibility and all subsequent send-route
      protections pass; APIs/UI show scope and remaining limitations without granting extra authority.
- [ ] Relevant tests, lint and type checks pass; independent review verifies no hidden A/B mixing,
      weaker STOP handling, provider bypass, broad role grant or automatic outreach side effect.
- [ ] R4 runbook names exact compatible deployment/containment/rollback and bounded recovery checks;
      unresolved provider/history/continuation scope has explicit ownership and release containment.

### Production acceptance complete — not merely merged
- [ ] Individual Class B owner release sign-off and applicable brokerage/operator briefing recorded.
- [ ] Compatible services/workers and actual provider configuration are verified; only supported,
      approved scopes are enabled and targeted end-to-end acceptance evidence is attached.
- [ ] Any historical operation was separately approved, bounded and reconciled, or inventory proves
      none is required. No bulk consent grant, untracked new send or automatic journey restart occurred.
- [ ] Effective restrictions/lifts remain stable through refresh/retry/recovery; newer denials still
      win where applicable; history, failed/pending decisions and remedies are usable by scoped users.
- [ ] G4's delivered and explicitly deferred portions are recorded; the separate CRM courtesy-update
      follow-up still has an owner before claiming the whole parent Issue 16 complete.

**Evidence status at drafting:** source/document trace and documentation validation only. No new
application code or behavioral tests, provider-configuration change, production access, consent
mutation or Jira publication. Review findings do not constitute implementation or release approval.

## 9. References and decision precedence

- [Issue 16 rule 3, G4 and business-impact guide](../production-state-consistency-issues.md)
- [Consensus — D3 and final D7 release boundary](../production-state-consistency-review-consensus.md)
- [Grouped business-rule register](../production-state-business-rule-changes.md) — its “permanently”
  shorthand does not revoke the explicitly sanctioned lift paths; it is not the issue-level class map.
- [16-A — preserve opt-outs and recover proven lost restrictions](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [9-A — STOP and unresolved-reply protection](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [9-B — separate receipt-based retry/escalation policy](issue-9-b-reply-retry-window-and-escalation.md)
- [13-B — consistent consent and fallback](issue-13-b-consistent-consent-and-channel-fallback.md)
- [12-B — carrier opt-out evidence](issue-12-b-carrier-opt-out-handling-and-fallback.md)
- [17-A — durable dispatch](issue-17-a-durable-outbound-dispatch.md)
- [2-A — reliable instruction delivery](issue-2-a-reliable-instruction-delivery.md)
- [Twilio Advanced Opt-Out guide](https://www.twilio.com/docs/messaging/tutorials/advanced-opt-out)
  — public documentation inspected 2026-09-09, not deployed-configuration proof.
- Parent workspace CLAUDE.md and AGENTS.md: current owner/product and architecture rules. Where older
  notes conflict, use recorded owner decisions and the final consensus; do not restore obsolete A2P,
  unknown-consent or CRM-activity gates.

Earlier nineteen drafts remain unchanged. This contract supplies the separately reviewed lifting
scope; it does not amend their approvals by implication. Escalate an unresolved business outcome to
the named owner, and distinguish a proposal, implemented behavior and observed production fact.