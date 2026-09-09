# Issue 13-B — Apply one consent rule and use the other usable channel

**Status: DRAFT — business, test-contract and release-readiness review required.**
This is the fifth proposed Jira description, not a published issue or permission to implement.
D1 is settled: a channel-specific no blocks that channel, not automatically the whole relationship.
The readiness gates in §3.7 remain; approval to continue drafting is not Class B release approval.

## 1. Business impact — read this first

**The promise:** A lead's explicit no is honored on that channel regardless of how a message is
sent. If the other channel is usable, the same intended message can go there instead, subject to
all other safeguards. Agents can distinguish that continuation from a lead who cannot be contacted.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | A CRM SMS permission of DENIED can block standard cadence but be ignored by paused-search cadence, AI replies, operator send-now and draft approval. General consent-based channel switching is absent. The route taken changes whether the same lead gets contacted. |
| What changes? | Explicit opt-out, unsubscribe or DENIED consent blocks its channel on every lead-send path. A usable other channel carries the same logical message, re-rendered appropriately. A successful fallback completes that touch once; it is not a skipped step or an extra campaign. |
| Does SMS STOP end all nurture? | **Not by itself under the approved D1 policy.** SMS stops; email may continue when otherwise permitted. The same rule applies to an email unsubscribe with usable SMS. There is no special terminal outcome merely because a lead typed a hard keyword rather than clicked an unsubscribe link. |
| Will STOP immediately trigger an email? | Not merely because the opt-out arrived. Record the restriction first and finish required inbound handling. Only an otherwise authorized, due outbound intent may use fallback; do not replay the SMS already sent or manufacture an extra opt-out response. |
| What if neither channel is usable? | Hold ordinary nurture for human review with the specific reason no_usable_channel, explain both channel blockers, and notify the assigned agent through the agreed existing notification path. Do not silently skip the touch or call missing contact data a global opt-out. See G2. |
| What if the lead is globally do-not-contact? | Neither channel sends. Global do-not-contact ends ordinary nurture under the existing suppression lifecycle; it is not a recoverable missing-channel problem. Human-handoff accountability must not be erased as a side effect. |
| What does unknown consent mean? | UNKNOWN, including an absent permission field normalized to unknown, does not block either channel. It is not changed to CONFIRMED and is not permission to ignore stale/missing safety data or any explicit no. No workspace A2P/10DLC approval gate is introduced in V1. |
| Can an agent force the denied channel? | No. Send-now and approve-and-send cannot override consent. Existing authorization and review requirements remain; channel-specific rendering and approval behavior must be agreed under R2. |
| Does fallback bypass another restriction? | No. Manual pause, human handoff/ownership, unresolved replies, campaign/workspace controls, channel configuration, timing, frequency, current-message checks and the integrated release's CRM controls still apply. A usable email address is not an instruction to resume a human-owned lead. |
| Will failed SMS delivery always try email? | No general provider-failure fallback is added. A non-opt-out permanent rejection on standard cadence remains a provider-failure review hold. The existing configured paused-search exception needs the explicit G3 decision; carrier-opt-out recognition is separate Issue 12-B work. |
| What will users see? | The blocked channel and reason, the channel actually used for the same touch, or an actionable hold explaining why nothing can send. One denied channel must not be presented as global do-not-contact when the other is usable. |
| What about old paused/suppressed leads? | This release is not permission to bulk restart them. Inventory and approve recovery separately; preserve opt-outs, human controls, unresolved replies, sent/uncertain messages and historical evidence. |

**This changes live contact behavior.** Owner release sign-off and brokerage/agent communication
must explicitly cover email-after-SMS-STOP, the reverse-channel case and unknown consent. The
recorded product decision is not a legal-compliance assurance for every brokerage or jurisdiction.

## 2. Ticket identity, scope and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — consistent consent enforcement and explicit channel continuation; confirm at publication |
| Source / delivery class | Production-state consistency Issue 13 / **Class B: recorded product-policy change** |
| Repositories / components | miller-schackman-api: canonical contactability, planning/final sending, inbound/suppression lifecycle, cadence/AI accounting and reads; miller-schackman-web: channel/status/history, review controls and Attention |
| Sequence | Fifth draft after 16-A, 9-A, 11-A and 14-B. Draft order is not evidence that any prerequisite has shipped. |
| Integration prerequisites | Integrate separately reviewed 16-A suppression preservation/recovery and 9-A receipt/STOP/reply-hold protections. Keep 11-A ownership projection and the actual release's 14-B CRM controls intact; do not rebuild those tickets here. |
| Related releases | Issue 12-B consumes this consent/fallback rule after recognizing carrier opt-out. Issue 17-A owns the all-journey durable-dispatch migration, subject to D6/G6 sizing; Issue 17-B owns uncertain-as-sent behavior. Neither is silently included. |
| Owners | Name product/release owner, implementer, independent reviewer, brokerage/CRM administrator and recovery operator |
| Reviewed baseline | API a761c1b and web 04d4361, reviewed 2026-09-05; retrace the actual implementation branch |
| Readiness | D1/unknown-consent/no-A2P policy settled. Verify the settled G2 state/provenance mapping and align stale guidance; resolve G3 and R1–R3, approve test boundaries/design, then obtain the separate D7 release authorization. |

**Included:** one explicit-denial rule and consistent consumers; consent-based channel selection
and re-rendering for every applicable lead-send journey; current-state enforcement at actual
dispatch; channel-scoped inbound/suppression continuation; correct logical-touch accounting;
visible no-channel review and authorized recovery; role-safe API/UI evidence; tests and cutover.

**Excluded:**
- Issue 12's provider-code recognition, new carrier error taxonomy or its release approval.
- Issue 17's broad dispatch migration, uncertain-as-sent/callback policy, and Issue 9-B's 30-minute
  retry/notification window. Preserve the integrated versions' outcomes; do not implement their
  targets just because the pre-send rule document also describes them.
- New consent-lifting/resubscribe features under G4, consent-source expansion to unverified native
  CRM fields, courtesy CRM status writes, global campaign/channel configuration redesign, or a new
  workspace SMS approval setting. Unknown consent does not require collecting a new consent field.
- Issue 8/G1 completion/late-reply policy, automatic terminal re-entry, catch-up campaigns, broad
  historical data repair, a generic rules engine, or a universal notification/dashboard overhaul.
- Messages sent manually outside the platform, staff notifications and CRM notes as outreach
  fallback candidates. Existing lead-facing handoff acknowledgments are addressed narrowly below.

**D7:** no Class A repair may be hidden in this B PR. If safe fallback requires a broader dispatch
repair, name the separately scoped A dependency and block activation until it is integrated. Several
B-only slices are possible, but do not activate a partial policy that still depends on the journey.

## 3. Current behavior and contract to approve

### 3.1 What exists, versus what this ticket builds

- evaluate_contactability has a default/strict split. Default ignores the permission-status fields;
  strict SMS blocks DENIED, not UNKNOWN, while strict email also blocks unknown. Production requests
  strict mode at final durable revalidation for SMS only. Tightening every call to strict would
  therefore introduce an unapproved unknown-email blocker rather than implement the decided rule.
- Standard cadence uses durable requests. Paused-search deliberately withholds that repository;
  AI continuation and operator send paths also send directly. A green test of the durable checker
  cannot prove those paths safe. Optional dependencies and test-only wiring must not create bypasses.
- Planning and some callers reject an uncontactable requested channel before send_outbound_message.
  Several send contexts allow only the authored channel. The durable checker also requires the
  saved message channel to equal the cadence step channel and validates its queued payload.
  A fallback cannot work merely by changing the provider selected at the bottom of the send helper.
- Inbound opt-out currently terminalizes ordinary nurture; suppression-event handling pauses when
  any channel remains contactable and suppresses otherwise. Both have execution side effects.
  Changing final consent checks alone leaves these old lifecycle outcomes preventing continuation.
- Contactability facts are derived, not always raw CRM fields. In particular, the canonical input
  helper can derive do_not_contact from having no destination when the stored DNC value is absent.
  That convenience value is not evidence of an explicit global stop for the G2 lifecycle decision.
- Paused-search already has configured **provider-failure** fallback and occurrence accounting.
  That is not general consent fallback. Its setting cannot silently become either a prerequisite
  for D1 or authorization to use any channel for any failure. G3 remains an owner decision.

### 3.2 One consent rule; distinct reasons for not sending

1. A supported platform-observed opt-out, CRM sms_opted_out/email_unsubscribed fact, or mapped
   channel permission DENIED blocks that channel. Cover hard keywords and accepted classifier
   opt-outs, unsubscribe events and refreshed CRM facts. Normalize at existing adapter boundaries;
   do not leak provider payloads into the domain or invent support for an unmapped vendor field.
2. Explicit global do_not_contact blocks both channels. Preserve its provenance and existing
   durable suppression guarantees. Two channel restrictions or missing contact details are not a
   newly received global instruction. Conflicting historical provenance requires review, not clearing.
3. UNKNOWN/absent permission status is allowed when a usable destination and all other safety facts
   are available. Do not rewrite it as positive evidence, add a confirmed-permission requirement,
   or create a workspace A2P gate. Unavailable CRM/history/configuration is a different kind of unknown.
4. Remove the strict/default policy split. Keep one authoritative decision shared by planning,
   enrollment/resume/read consumers, send_outbound_message and the later durable dispatch check.
   Earlier checks are advisory about current eligibility; they cannot replace final revalidation.
   Do not broaden enrollment or resume permissions while making their contactability answers agree.
5. Distinguish channel consent, destination availability, channel enablement and temporary safety
   deferral. Fallback is triggered by an explicit channel no, not merely an invalid/missing primary
   destination, a disabled channel, quiet hours, a frequency limit or an arbitrary provider error.

| Current facts for an otherwise authorized outbound intent | Required policy outcome |
| --- | --- |
| Requested channel usable, consent UNKNOWN or CONFIRMED | Use that channel, subject to final safety checks; no unnecessary switch |
| Requested channel explicitly denied; other channel usable and permitted | Re-render the same logical message on the other channel, then revalidate before sending |
| Requested channel explicitly denied; no usable permitted alternative | Visible PAUSED / no_usable_channel for ordinary nurture; do not consume the touch |
| Alternative is otherwise usable but not yet time/frequency eligible | Apply the existing deferral for the actual alternate channel; no send yet, no completed touch |
| Explicit global do-not-contact | Zero lead-provider calls; existing global suppression/end behavior, never fallback |
| Human control, unresolved reply, stale data/version, missing configuration or another independent block | Preserve that restriction and its accurate outcome; fallback is not an override |

The no-channel row is the current Issue 13/pre-send target. G2 requires aligning the stale consensus
template, not reopening whether a usable alternate may carry the message. When independent holds
coexist, preserve their evidence and recovery restrictions rather than overwriting them with a
weaker no_usable_channel reason.

### 3.3 Select and render the same logical message safely

1. Resolve the applicable enabled-channel configuration for the actual run/message purpose (R1).
   A step authored as SMS does not, by itself, forbid the approved email fallback; equally, having
   an email address is not permission to enable email for a campaign that disallows it. Do not use
   a synthetic one-channel context or an unconditional two-channel allowlist as the policy source.
2. Planning must be able to choose an allowed alternative when the authored channel is already
   denied. If denial arrives after planning/queueing, send-time orchestration must safely adapt or
   hold/replan before dispatch. An early contactability rejection cannot silently skip the touch
   and prevent the shared fallback rule from being reached.
3. Keep the same business intent, approved facts, workflow/enrollment and logical cadence step,
   recurring occurrence or AI turn. Render channel-specific content through supported existing
   drafting/template boundaries: appropriate email subject/sender/thread handling and SMS content
   limits. Do not just put an SMS body in an email payload or truncate an email into different meaning.
4. Agree the exact cross-channel template/profile and operator-approval contract under R2. A
   missing renderer, invalid result or unavailable LLM is a visible content/review failure, not a
   completed fallback, a made-up email subject or permission to send unreviewed substantive copy.
5. Preserve original and selected channel, source/reason for switching, logical identity and
   content/version lineage in the supported persisted message/attempt/audit model. Reconcile
   durable step/channel and payload validation with a legitimate fallback; retain checks against
   arbitrary destination, content, channel or version substitution. Never just delete mismatch checks.
6. Use the same authoritative decision again with current facts immediately before either direct
   or queued provider dispatch. Recheck the alternate's consent/destination, current campaign/run,
   message, human/reply controls, timing, global/campaign/actual-channel frequency and concurrency
   protection. Reload state changed by live refresh; a context captured before it is not authoritative.
7. Coordinate final decisions using existing locking/transaction conventions. Do CRM/LLM rendering
   outside long-held database locks, then revalidate the selected payload against current locked
   state. Test the commit/dispatch boundary; no lock can recall a message already released externally.

### 3.4 Apply D1 to lifecycle as well as to the provider call

- Honor deterministic hard-word opt-outs without AI and persist their evidence through the
  integrated 9-A contract, rather than reimplementing its ordering repair. Persist accepted
  classifier-detected opt-outs when that result is available; classifier failure never authorizes
  sending. A channel opt-out alone must no longer terminalize ordinary nurture or leave a consent-only
  pause requiring manual resume when an allowed alternative remains. Keep genuine manual/review /
  handoff restrictions intact.
- Apply that same channel-scoped outcome for a hard word, accepted classifier opt-out, CRM/provider
  unsubscribe notification and refreshed explicit denial. Inbound and suppression handlers record
  restrictions and coordinate lifecycle; they do not fire a new provider message merely on receipt.
- A receipt awaiting processing still holds every pending automated message, on both channels.
  Only the normal explicit handling of the relevant reply can release its hold. Another unresolved
  reply, exhausted processing or a human request still prevents continuation. Do not add a timer,
  treat elapsed time as resolution, or send stale pre-reply content by moving it to another channel.
- With no usable permitted channel, hold ordinary nurture as PAUSED / no_usable_channel with
  evidence for both channels, no executable next send and an unconsumed logical touch. Keep workflow,
  enrollment, message and occurrence state coherent; do not mark the enrollment successfully ended.
  Make the hold actionable in existing status/Attention and send the assigned-agent notification
  through the approved durable path (R3), including retry/failure evidence rather than false success.
- Global DNC remains a global send prohibition and terminal suppression for ordinary nurture.
  Existing human-handoff/owned state and accountability are not replaced merely to display the
  consent result. Terminal runs are not revived by a channel update or a late processing result.
- Persist the required lifecycle/transition and execution instructions with existing transaction /
  outbox conventions. Trace Temporal timers, inbound/suppression signals and their consumers: a
  channel-only signal must not still cancel the run after Postgres says continuation is allowed.
  Duplicate/delayed instructions must not resume an independently held lead or target a successor.

**Handoff acknowledgment boundary:** existing configured lead-facing acknowledgments must honor
the same explicit-denial/global-DNC rule. They are not a route to resume nurture from HUMAN_HANDOFF.
Any alternate acknowledgment must be independently enabled for that purpose and use the approved
template/rendering contract (R1/R2); retain its existing permissions and timing exceptions only.
If none is permitted, record the unsent acknowledgment without undoing the handoff. Staff notifications
are separate and are not suppressed merely because a lead cannot receive outreach.

### 3.5 Account once and do not turn uncertainty into another send

- A consent-blocked primary makes zero provider attempts and consumes no delivered/logical touch.
  A queued alternate is pending, not delivered. On successful alternate send, advance the one
  original step/occurrence/AI turn once, retaining its normal next schedule and existing caps.
  Here “completed touch” means the existing successful-send milestone, not guaranteed inbox delivery.
- Preserve recurring paused-search slot/occurrence identity, fallback evidence and logical-touch
  limits. Do not create an extra occurrence, consume the cap on a pre-send rejection, advance both
  channel variants, or change Issue 8's campaign-completion/late-reply behavior.
- A channel is part of today's idempotency key. Merely generating a second key can create a second
  message, not a safe substitution. Coordinate the original intent and its alternate so retries,
  concurrent dispatch and repeated opt-out observations cannot send both or repeat the fallback.
  Prove the specific supported race guarantees; do not advertise Issue 17's unbuilt global protection.
- A previously sent, accepted or uncertain original cannot be retried on the other channel to evade
  its claim/status. A failed/uncertain alternate follows the integrated release's existing failure /
  reconciliation behavior; do not label it successful, ping-pong channels or add uncertain-as-sent
  policy here. Callbacks remain scoped to the original message/run, never a successor enrollment.
- Standard non-opt-out permanent failures remain provider_failure_exhausted, not consent fallback.
  No generic invalid-number/error is written as opt-out. Resolve the configured paused-search
  exception under G3. Once Issue 12 separately normalizes a real carrier opt-out, it uses this shared
  consent rule; a seeded canonical opt-out test here is not proof that carrier recognition works.

### 3.6 User-visible explanation and authorized recovery

Channel panels, message history, next-action displays and permitted operator actions must agree
with the backend result. Show the actual channel/content/status, why the original channel was
blocked and whether the touch is pending, deferred, sent or held. Do not turn one channel's no into
a generic “all outreach blocked,” or show UNKNOWN as confirmed permission.

For no_usable_channel, show both blockers, when the hold began, accountable agent and permitted next
action. A corrected destination or newly usable alternate is not an automatic resume. R3 must name
the real permission-checked review/resume route and verify that it can continue the correct pending
intent with current safety facts. This never lifts the original channel's durable opt-out, clears
another review/reply hold, or grants a normal Resume action for terminal global suppression.

No new browser-push guarantee is required: a fresh authorized API/UI fetch after commit must show
the correct state. Preserve loading, empty and error states, workspace isolation, assigned-agent
visibility and existing operator permissions. Do not create an invisible backend-only hold.

### 3.7 Remaining gates — not new votes on the settled consent policy

These are implementation/release conditions, not behaviors claimed to exist today.
**G2 is not a new choice between pause and suppression:** the no-channel hold is the current target.
Its gate verifies state/provenance mapping and corrects stale guidance. D1 needs no further policy
vote; individual Class B release authorization is still required.

| Gate | Required clarification / proposed boundary | Who closes it |
| --- | --- | --- |
| G2 — No usable channel and global provenance | Align the stale consensus “no channel left → SUPPRESSED” template to the issue/pre-send PAUSED / no_usable_channel target; keep explicit global DNC terminal for ordinary nurture. Verify canonical derivations cannot turn absent destinations or two channel blocks into a newly asserted global stop. Verify exact state/reason tests implement that target and approve treatment of ambiguous legacy evidence; do not clear real DNC. | Product owner + engineering reviewer; mapping/test verification before code, aligned governing guidance before release |
| G3 — Configured provider-failure fallback | CLAUDE.md forbids non-opt-out rerouting, while Issue 13/pre-send text retains configured paused-search fallback. Inventory affected tracks; owner must explicitly preserve a bounded exception or remove it with configuration/cutover treatment. Align documents and tests. Do not silently choose either, and do not reopen D1 consent fallback. | Product/release owner + track administrator, before implementing the affected interaction |
| R1 — Which alternate is enabled? | Proposed: use the bound campaign/track configuration and purpose-specific controls, not the authored step-only tuple or a global allow-all. Specify the authoritative allowlist on every journey, including paused-search and non-campaign/handoff acknowledgments. Known disallowance leaves no usable alternate; missing/ambiguous configuration is its own visible failure, not guessed permission. | Product owner + engineering reviewer, before implementation |
| R2 — Same message, rendering and approval | Define supported cross-channel template/profile mapping, email subject/thread/sender rules, SMS limits and what an operator approves when the final channel changes. Preserve approved intent/facts; substantive new copy must not inherit an old approval silently. Specify a visible held/review outcome when safe conversion is unavailable. For a disabled/missing acknowledgment template, record the unsent message without undoing the handoff. | Product owner + content/review owner + engineering reviewer, before implementation |
| R3 — Review, notification and recovery | Name existing Attention/notification integrations, deduplication/retry ownership and authorized resume/end action for no_usable_channel; keep independent holds intact. Prove an authorized recovery can use a newly usable alternate without consuming the old touch twice. Separately approve legacy paused/terminal cohorts; no automatic historical restart and no new consent-lift promise. | Product owner + operations + engineering reviewer; live contract before code, cohort/runbook approval before activation |

The draft records these gates without editing the earlier drafts or source decision documents.
Closing them is not a license to reopen D1 or bundle neighboring A/B work into the implementation.

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Use synthetic leads, controlled clocks and recording
transports. Map each ID/variant to the real entry point and persisted outcome. AC-01–03 must cover
standard cadence **through dispatch**, paused-search variants, AI continuation, operator send-now
and draft approval, not only the shared helper. Verify the settled G2 state/provenance mapping and
close the G3/R1–R3 implementation contracts before claiming affected cases implementation-ready;
G2's governing-guidance alignment remains a merge/release gate, not a new policy vote.
For operator cases, “otherwise valid” includes any R2-required alternate-channel approval; until
then an unapproved conversion stays visibly held, not sent.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | SMS permission is DENIED; email is permitted/usable; request an otherwise valid SMS touch on each named journey. | Zero SMS provider calls; after any R2-required alternate approval, one correctly rendered email at its eligible time, explicit fallback evidence and one logical outcome. Until approval, remain visibly held without sending. | Direct-path SMS, standard-only protection, channel_mismatch rejection of a valid alternate, unapproved conversion or nothing sending after all prerequisites offered as success. |
| AC-02 | Reverse the channels: email DENIED/unsubscribed, usable permitted SMS; include SMS-opt-out/email-usable variants too. | The denied channel never sends; supported reverse rendering and actual selected channel follow the same rule. | An SMS-only fix, email denial ignored, or reusing email-only payload/thread data in SMS. |
| AC-03 | Both permission fields are UNKNOWN or absent/normalized unknown with valid required data; then use UNKNOWN on an alternate after primary denial. | Ordinary original-channel and alternate sends work when otherwise eligible. Stored evidence remains unknown; no A2P setting is required. | Requiring CONFIRMED, strict unknown-email rejection, fabricating positive consent or disabling all sends. |
| AC-04 | Observe hard-word STOP, accepted classifier opt-out, mapped CRM flag/DENIED refresh, and supported unsubscribe events; duplicate/reorder observations with the same channel restriction. | Equivalent consent-only lifecycle: restriction persists, other usable channel may carry a due permitted intent, no spurious terminalization/manual resume. Source evidence is retained/deduplicated. | Human-word versus unsubscribe-click outcome split, an old suppression pause/cancel defeating D1, or a new message sent solely because the event arrived. |
| AC-05 | Receive STOP with the classifier unavailable; separately leave another reply unresolved or exhausted while an alternate is contactable. After explicit valid processing, test an otherwise permitted due continuation. | 9-A evidence/ordering remain effective. Zero automated calls on either channel while processing is unresolved; valid handled continuation can proceed under D1 without replaying stale pre-reply content. | Fallback bypassing reply hold, opt-out persistence depending on AI, a new 30-minute timer or “email STOP acknowledgment” invented by this ticket. |
| AC-06 | Primary explicitly denied; alternate destination missing, denied or unsubscribed; no independent global DNC. | PAUSED / no_usable_channel, both reasons visible, coherent enrollment and unconsumed touch, no executable next send; one logical agent notification with durable retry evidence. | SUPPRESSED because an address is missing, silent skip, false successful enrollment completion, lost occurrence or a UI-only hold. |
| AC-07 | Apply supported explicit global DNC with one/both otherwise usable destinations; include active and already human-owned/handoff cases. | Zero lead-provider calls on all paths; ordinary nurture follows global suppression/end behavior. Global evidence and human accountability remain; no normal terminal Resume. | Fallback, downgrading DNC to missing-channel review, or erasing handoff ownership to display a consent result. |
| AC-08 | Exercise canonical conversion with absent destinations/DNC field, two channel-specific blocks, and an independently explicit global DNC control. | Missing-channel/data evidence is distinguished from an explicit global stop under G2. No sending without required data and no fabricated global consent event. | Terminalizing solely because a convenience helper derives DNC, or clearing an actual recorded global no to get a hold test passing. |
| AC-09 | Both channels enabled versus alternate explicitly disabled; include bound published campaign/track versions, purpose-specific acknowledgment settings and missing configuration. | R1 source is honored. Valid consent fallback is not stopped by the authored-channel tuple; disabled alternate is not used; unknown config gets an accurate non-sendable failure. | Blanket enabling of SMS/email, borrowing another campaign's configuration, or treating provider-fallback opt-in as D1's only authorization. |
| AC-10 | Primary denied; alternate is within/outside quiet hours and has global, campaign or actual-channel frequency restrictions; exercise existing send-now exceptions separately. | Evaluate the actual alternate against every applicable existing limit. Temporary restriction defers without consuming the touch; a permitted later attempt succeeds. | Switching to evade frequency/mixed-channel limits, new timing overrides, or labeling a temporary limit no_usable_channel. |
| AC-11 | Render both fallback directions through real drafting/template orchestration, including supported paused-search profiles; reject an invalid or unavailable conversion. | Same intent/approved facts and logical identity; valid subject/body/sender/thread behavior under R2. Invalid conversion remains visible/non-sendable with no completed touch. | Copying payloads blindly, inventing facts/subject, truncating meaning, new content counted as already approved, or swallowing render failure. |
| AC-12 | Use operator send-now and approve-and-send; deny the requested channel before planning and again after preview/approval. Test allowed and unauthorized actors. | R2-approved alternate/review behavior is explicit to the user; current consent and approval/version checks remain decisive. Authorized valid flow still works. | “Force send” bypass, unreviewed substantive rewrite, stale approval reused after replacement, or disabling the operator feature to avoid the problem. |
| AC-13 | Generate an existing handoff acknowledgment with its original channel denied; alternate acknowledgment enabled/disabled; also test DNC. | Consent rule enforced on the actual provider boundary; only approved purpose-enabled rendering can switch. Handoff persists; unsent acknowledgment is recorded and staff notification still follows its own rules. | Nurture resume, turning on a disabled acknowledgment, using nurture content as acknowledgment or suppressing staff notification as if it were lead outreach. |
| AC-14 | Change consent in live CRM refresh; separately fail required CRM/history/config reads and omit a production-required refresh dependency. | Current canonical/locked state is used on both direct and durable paths; incomplete safety data gives honest non-sendable evidence. Unknown permission alone is still allowed. | Stale scheduled permission accepted as final, optional-wiring fail-open, or data-fetch failure interpreted as unknown consent permission. |
| AC-15 | Primary is already denied at initial planning/admission/resume assessment; other configured channel is usable. | Shared contactability answers agree; eligible planning reaches the valid alternate rather than an early skip. Existing admission/resume restrictions and positive controls remain. | Only fixing the final checker while planning rejects every fallback, or broadening terminal enrollment/resume permissions. |
| AC-16 | Combine channel denial with manual pause, handoff/ownership, unresolved review, preflight veto, inactive campaign/workspace or the integrated release's tag/CRM block. | No alternate call; independent state/reason and permission-checked recovery requirements survive. Removing only the consent blocker cannot auto-resume the lead. | Overwriting a human/review hold with weaker no_usable_channel or quietly implementing/removing Issue 14 controls. |
| AC-17 | Block the primary before any attempt, then queue/defer the alternate and finally complete a successful send. | No primary provider attempt/touch; DISPATCH_PENDING or deferral is not completion; the one original step advances only at the applicable successful-send milestone. | Counting two steps, advancing on queue acknowledgment, silently skipping the denied step or claiming confirmed recipient delivery. |
| AC-18 | Fall back for standard and recurring paused-search touches and an AI continuation turn; retry their completion bookkeeping. | One correct step/occurrence/AI-turn outcome, preserved logical identity/caps and normal next schedule. Rejection without a send does not consume an occurrence cap. | Extra occurrence, double logical-touch/AI count, exhausted loop from skipped steps or a new completion/late-reply policy. |
| AC-19 | After rendering/queueing, commit alternate-channel denial, global DNC or a reply before final dispatch. Separately race after the provider call was already released. | First case makes zero new prohibited calls with an accurate latest-state outcome. Second case is documented as the tested external-call limit, without duplicate retry or false recall claims. | Trusting a pre-render snapshot, bypassing locked checks, claiming atomicity with the provider or emailing a copy of an already released message. |
| AC-20 | Race original/alternate requests and duplicate operator/worker attempts for the same intent in independent database sessions; include retry after a claim. | Persisted logical coordination prevents both variants or duplicate fallback within the specified tested boundary; current consent and message version remain valid. Record residual Issue 17 gaps explicitly. | Treating two channel-specific keys as sufficient deduplication, fake-only race proof or an unconditional exactly-once external-delivery claim. |
| AC-21 | Delay/duplicate inbound/suppression engine signals and old provider callbacks; create a protected hold or successor run before delivery. | Postgres and execution converge for the correct run. Channel-only observations cannot terminalize/cancel permitted continuation; old instructions cannot resume a held lead or act on a successor. | Database-only D1 while Temporal remains cancelled, stale callback resurrection or changing Issue 17-B reconciliation policy. |
| AC-22 | Standard provider returns a permanent non-opt-out rejection; compare a configured paused-search provider fallback and a canonical carrier opt-out input. | Standard holds provider_failure_exhausted without rerouting; configured-track behavior matches the signed G3 decision. Canonical opt-out uses D1. Transient failure keeps its applicable retry policy. | General error-to-email fallback, writing arbitrary errors as consent, silently keeping/removing the configured exception or claiming Issue 12 recognition was implemented. |
| AC-23 | Alternate provider fails or has an uncertain outcome; try original/alternate again and deliver a reconciliation callback. | No channel ping-pong or resend around an existing sent/uncertain claim. Persist/report the real outcome using the integrated failure/uncertainty contract and correct run identity. | Falsifying successful fallback, automatically treating uncertain as sent here, or using a fresh channel key to resend an ambiguous attempt. |
| AC-24 | Add a usable alternate while no_usable_channel review is open; attempt unauthorized, then approved authorized recovery with fresh facts and no other blocker. | No automatic resume from the field change; real R3 action can continue the correct pending intent once. Original opt-out and independent restrictions remain. | Clearing consent to recover, an unusable Resume route, duplicate old touch, global-DNC resume or granting new role capability. |
| AC-25 | Persist platform opt-out, run the integrated 16-A refresh paths with weaker/contradictory CRM fields, then plan/dispatch and read the lead. | Suppression/evidence remain durable and shared consent still blocks that channel; assignments and surviving activity fields remain correct. | Refresh undoing opt-out, unknown/confirmed overwriting durable evidence, or repackaging 16-A implementation in this B PR. |
| AC-26 | Read real APIs then refetch UI for one-channel denial with successful/pending alternate, temporary deferral, no usable channel and global DNC; fail the hold notification transport. | Channel panels, actual message and next action agree; actionable review includes both reasons/age/owner. Notification failure has durable visible/retry evidence, not “notified” success. Loading/empty/error views remain. | Healthy-looking stuck lead, one denied channel shown as global unreachable, incorrect sent copy/channel, raw reason-only dead end or invisible failed notification. |
| AC-27 | Use assigned agent, authorized operator, unrelated agent and another workspace across reads, send-now, approval and recovery. | Existing role/ownership/tenant boundaries hold; authorized permitted controls still work. Provider calls and stored evidence belong to the correct lead/workspace. | Cross-tenant fallback destination, privilege escalation, consent override by a privileged actor or leaked lead content in broad diagnostics. |
| AC-28 | Inject persistence failure between restriction/lifecycle/message/required-outbox writes and retry after rollback; also fail after the external dispatch boundary. | Atomic local outcome and recoverable unfinished work via existing conventions; no committed “processed” marker hiding missing required state. External outcome remains honest/non-duplicated under the actual dispatch contract. | Partial consent-only lifecycle, lost notification/execution obligation, assumed rollback of a provider call or broad Issue 17-A work hidden in the fix. |
| AC-29 | Rehearse cutover with legacy channel-only PAUSED/SUPPRESSED, ambiguous DNC provenance, missing destinations, manual/handoff/reply holds and sent/uncertain pending variants. | Dry-run inventory separates cohorts; only explicitly authorized recovery proceeds through supported controls after fresh checks. Unreviewed cases stay safely contained with named follow-up. | Blanket revival/resend, inferring no global stop from incomplete history, new automatic terminal re-entry or mixed workers restoring old channel-only terminalization. |
| AC-30 | Run a synthetic integrated standard-cadence and direct/paused-search journey through permitted send → channel opt-out → next due alternate touch; then no-channel hold and authorized recovery. | Actual persisted channel/content, transition/execution, counters, notification and fresh UI observations support the contract; positive and prohibited-send controls both pass. | Helper-only green claimed as end-to-end proof, live customer outreach, tests never executing final queued dispatch or unverified vendor delivery claims. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — approve before implementation:**
- **Contactability policy:** public pure decision with independently specified two-channel facts;
  UNKNOWN, explicit denials, destinations and explicit global DNC are separate inputs/assertions.
- **Journey → final provider boundary:** real planning/cadence/AI/operator use cases, final direct
  send and actual durable dispatcher, recording transports, saved message/step/occurrence results.
  Also test the lead acknowledgment purpose, not just the five advertised nurture entry points.
- **Consent event → execution/read model:** actual inbound/suppression/refresh application paths,
  normal transitions and required outbox work; verify provider counts, current workflow, next action,
  persisted evidence and fresh authorized API results. Do not mock the policy or lifecycle outcome.
- **Real persistence/execution:** local/disposable Postgres for atomic writes, rollback, idempotency
  and independent-session races; existing Temporal test boundaries for cancellation/signals/timers
  and paused-search occurrence continuation. Fakes cannot prove locking or execution convergence.
- **User/operator experience:** focused API permission tests and existing UI route/helper tests
  using real contract shapes; an approved synthetic integrated demonstration with sink messaging.
  Any vendor sandbox/write verification needs separate approval; no real-lead acceptance outreach.

External CRM/LLM/messaging/notification transports and clocks may be hand-written fakes. Repository
fakes are useful for fast application tests but do not replace SQL evidence. Exercise real decision,
normalization, rendering validation, transitions, permissions and accounting within the agreed seam.

1. Choose one scenario/boundary, write one behavioral test, and run it against unchanged behavior.
   A useful first red is DENIED SMS on a direct journey with usable email: assert zero SMS calls and
   one correctly rendered email for the same logical touch. Capture the actual failing assertion.
2. Make the smallest implementation for that slice, rerun it green, then take the next scenario.
   Minimal no-op/interface scaffolding may make a new case runnable; record it separately. Missing
   imports, invalid fixtures, absent database, no collected tests and skips are not meaningful red.
3. Existing UNKNOWN and global-DNC protections may already be green. Preserve them as controls;
   prove sensitivity against baseline or an isolated mutation instead of fabricating failures.
   Replace old path-specific or terminal-STOP expectations deliberately with independent review.
4. Sensitivity checks must catch: ignoring DENIED on a direct path; requiring known email consent;
   checking only the primary channel; retaining terminal channel-only signals; failing early before
   fallback; overriding enabled channels/reply holds; consuming a touch before send; and using a
   second channel key to bypass a claimed intent. Restore mutations and rerun the affected tests.
5. Assert literal business outcomes and actual recording-provider channel/body/call count, not
   expected values calculated by the production evaluator under test or “helper was called.” Keep
   valid original sends, both fallback directions and authorized recovery as positive controls.

| AC / journey / variant | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Remaining integration gap |
| --- | --- | --- | --- | --- | --- |
| Implementer fills each row | Exact invocation | Business assertion, not setup failure | Revision, exit code, pass/fail/skip counts | Observed protected behavior | Explicit unverified claim |

## 6. Engineering starting points — navigation, not a prescribed implementation

References are grouped by repository and use repository-relative paths for portability. Retrace
current callers/signatures; these are existing locations, not proof the proposed behavior exists.

| Repository / responsibility | Existing reference |
| --- | --- |
| API — consent and canonical derivation | app/domain/compliance/contactability.py; app/application/services/canonical_lead_inputs.py; app/domain/leads/canonical.py; app/infrastructure/crm/follow_up_boss/lead_mapper.py |
| API — planning, rendering and final direct send | app/application/use_cases/plan_outbound_message.py; plan_next_outbound_message.py; send_outbound_message.py in that directory; app/application/services/llm/outbound_message_drafting.py; app/domain/campaigns/pre_send.py |
| API — cadence and durable boundary | app/application/use_cases/campaign_cadence_execution.py; refresh_outbound_send_request.py; revalidate_outbound_send_request.py; dispatch_outbound_send_requests.py in that directory; app/application/services/pre_send_crm_refresh.py |
| API — inbound, suppression and operator journeys | app/application/use_cases/process_inbound_message_event.py; process_contact_suppression_event.py; send_deferred_outbound_message_now.py; lead_resume.py in that directory; app/interfaces/api/v1/leads.py |
| API — persisted purpose/configuration/lifecycle | app/domain/campaigns/execution.py; app/domain/workflows/models.py; app/infrastructure/workflows/temporal/; app/infrastructure/persistence/postgres/ |
| Web — consent, message status and controls | src/lib/helpers/leadPresentation.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/workflowReasons.ts; src/pages/LeadDetailPage.tsx; src/app/LeadsRoutes.test.tsx |

**Design review before code:** compare (a) extending the shared pre-send orchestration to coordinate
channel resolution/re-rendering for direct and durable paths, with (b) a pure shared channel decision
used by existing planners plus explicit alternate-intent preparation before final dispatch. The
first centralizes retry/lifecycle handling but risks a large I/O-heavy send helper and extra latency;
the second keeps rendering outside final locks but needs careful stale-plan and identity coordination.
Recommend the smallest extension of existing seams that centralizes the rule, supports late denial,
and preserves current validation/transactions. Record latency, locking, maintenance and D6 boundaries;
obtain design approval. Neither option is a generic router or permission to migrate every dispatcher.

**Existing test starting points, not claimed coverage:**
- API domain/services: tests/domain/compliance/test_contactability.py;
  tests/domain/campaigns/test_pre_send.py; tests/application/services/test_canonical_lead_inputs.py;
  tests/application/services/llm/test_outbound_message_drafting.py.
- API application: tests/application/use_cases/test_plan_outbound_message.py;
  test_plan_next_outbound_message.py; test_send_outbound_message.py;
  test_revalidate_outbound_send_request.py; test_dispatch_outbound_send_requests.py;
  test_campaign_cadence_execution.py; test_process_inbound_message_event.py;
  test_process_contact_suppression_event.py; test_send_deferred_outbound_message_now.py;
  test_lead_resume.py; test_process_provider_delivery_callback.py;
  test_uncertain_paused_search_occurrence.py; test_business_flow_harness.py in the same directory.
- Real persistence/execution: tests/infrastructure/persistence/postgres/test_business_flow_harness.py;
  test_temporal_paused_search_workflow_postgres_e2e.py in that directory, plus affected repository tests.
- Web: src/app/LeadsRoutes.test.tsx and affected message-presentation/Attention tests.

Use Python 3.12/uv: one exact pytest node, its file, related suites, then make lint, make typecheck and
make test. For changed frontend behavior run focused Vitest tests, then pnpm test, pnpm typecheck and
pnpm lint. Confirm integration targets are local/disposable. Record commands, exit codes and actual
counts; skipped integration tests are evidence gaps. No behavioral tests ran to draft this ticket.

## 7. Existing records, activation and safe recovery

1. **Inventory without mutation.** Bound by workspace/run: channel-only pauses/terminal suppression,
   genuine global DNC, unknown/contradictory provenance, missing/disabled alternates, manual/review /
   handoff holds, unresolved replies, pending/sent/uncertain messages, recurring occurrences and old
   execution signals. Include configured provider-fallback tracks and unsupported cross-channel copy.
2. **Approve cohort treatment.** Do not reinterpret every SUPPRESSED record as a reversible channel
   hold or assume an absent global marker proves permission. Legacy terminal state is not resumable
   by assigning ACTIVE_NURTURE. Use a supported separately authorized recovery/re-entry path only;
   preserve 16-A protections and 9-A unresolved-reply evidence before considering any contact.
3. **Name the actual operation.** R3's runbook must identify environment, bounded cohort, authorized
   operator, dry-run/approval, supported commands/UI action, audit/idempotency guarantees and verification.
   If a recovery tool is missing, review/test that scope first. This draft authorizes no data repair,
   resubscribe, webhook replay, CRM write, bulk resume/re-enrollment or deployment.
4. **Coordinate all executors.** Roll out compatible API/worker/Temporal behavior; old workers,
   queued channel payloads and channel-only terminal/pause instructions must not restore divergent
   policy. Do not discard real manual/handoff/global instructions as legacy cleanup. No old sent or
   uncertain intent is made resendable simply because the alternate channel is now supported.
5. **Verify narrowly.** Use synthetic contacts and sink providers to demonstrate permitted original
   send, denial → due alternate, no-channel review/notification and authorized recovery on both direct
   and durable paths. Inventory and safely contain unresolved cohorts with accountable follow-up;
   do not turn unresolved configuration/rendering into an invisible stall or a dispatch bypass.

## 8. Class B release, communication and rollback

**Required agent/brokerage explanation:**
> A no on SMS stops SMS everywhere; email may continue if permitted and usable. An email unsubscribe
> similarly blocks email, not automatically SMS. A global do-not-contact stops both. Missing consent
> status alone does not prevent V1 outreach, but it is not displayed as confirmed consent. When no
> permitted channel is usable, the lead is held for review rather than silently skipped. Manual
> pauses, human handoffs and unresolved replies still protect the lead; operator send controls do
> not override consent. An opt-out cannot recall a message already released to a provider.

Show the actual fallback/review experience and approved recovery route. Explain applicable channel
configuration and the signed G3 outcome; do not advertise an unbuilt opt-out lift or promise every
message will arrive. D5/G7 communication applies to the behavior actually being activated, not all
adjacent recorded policies at once.

Before activation, record:
- Named owner's **explicit yes for this B release**, including email-after-STOP and reverse fallback,
  G2/G3 and R1–R3 closure, independent acceptance evidence and delivered brokerage/agent briefing.
- Compatible dependency revisions, complete journey/purpose coverage, meaningful test-first evidence,
  actual persistence/execution/UI results, remaining provider-boundary limits and no mixed-class PR.
- Approved cohort/recovery runbook and a staged activation/containment procedure using verified
  existing controls; no invented feature switch, recovery command or safe-deployment guarantee.
- Minimal operational evidence: blocked-channel reasons, selected channel, logical identity/count,
  deferred/held/sent outcomes, notification failures and suspicious duplicates/restarts. Avoid raw
  message bodies, destinations, credentials or unrestricted CRM payloads in logs/review artifacts.

**Rollback:** contain affected enrollment/outbound execution first using verified controls and a
release-owner-approved scope. Reverting code may restore denied-consent sends on direct paths and
channel-only terminalization; it is not a safe return to a neutral old behavior. Preserve durable
consent, global/human/reply holds, alternate-message claims, content/history and notification evidence.
Do not clear suppression, repeat old touches or revive terminal runs to undo the policy. Approve
compatible workers/DB behavior and tell operators which controls/outcomes remain in effect.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Stakeholder approves §1–4, verifies the settled G2 mapping and records G3/R1–R3 outcomes;
      D1 and the no-channel hold are not reopened as policy votes.
- [ ] Separate prerequisites/revisions and owners are recorded; earlier draft approval is not
      implementation evidence. Any broader dispatch dependency is sized and kept in its A PR.
- [ ] Test seams, first meaningful red and smallest complete rendering/identity/lifecycle design
      approved. No unresolved channel configuration, copy approval or recovery outcome is guessed.

### Ready to merge
- [ ] Every AC/variant maps to actual red/green or justified existing-control evidence and relevant
      sensitivity checks. Tests exercise real final dispatch, not only enqueue/helper success.
- [ ] All named journeys and lead acknowledgment purpose enforce one rule; both fallback directions
      render correctly, preserve permissions/safety and account for one logical message.
- [ ] Inbound/suppression lifecycle and Temporal agree; no-channel review/notification/recovery is
      durable and visible, global DNC remains distinct, and real SQL tests prove claimed races.
- [ ] API/UI communicate actual channel, content, reason and next action without tenant leakage or
      false consent/delivery claims. Positive sends and authorized recovery work, not just blocks.
- [ ] Governing consent/pre-send/help guidance reconciled, including stale G2 wording, signed G3
      scope and superseded A2P requirements. Historical reviews/drafts are not runtime success claims.
- [ ] Cohort runbook, staged release/rollback steps, compatibility and limitations recorded; no
      neighboring A repair or unrelated B policy, no unbuilt recovery promise or fake vendor proof.

### Production acceptance complete — not merely merged
- [ ] Individual owner release sign-off and applicable agent/brokerage briefing recorded.
- [ ] Compatible direct/durable/Temporal paths active; synthetic integrated evidence supports actual
      blocked-channel protection, alternate send, single accounting, visible hold and recovery.
- [ ] Existing affected cohorts are reviewed/reconciled or contained with named follow-up; no bulk
      restart/resend or consent lifting was performed without separate authorization.
- [ ] Operations can identify failed rendering, missing channel/configuration and failed notification,
      and use the tested permitted recovery path without bypassing human/reply/global restrictions.

**Evidence status at drafting:** source/code trace and document review only. No application changes,
new behavioral tests, runtime pass, Jira publication, commit, deployment or production data operation.

## 10. References and decision precedence

- [Issue 16-A — durable suppression/recovery prerequisite](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [Issue 9-A — STOP ordering, unresolved-reply hold and visibility](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [Issue 11-A — ownership projection](issue-11-a-project-crm-reassignment-immediately.md)
- [Issue 14-B — separate CRM-control release](issue-14-b-use-enrollment-tag-as-crm-control.md)
- [Source Issue 13 and business/readiness appendix, including G2/G3/G7](../production-state-consistency-issues.md)
- [Closed D1 decision and D7 ship-class gate](../production-state-consistency-review-consensus.md)
- [Pre-send rule target — includes separately released policies](../../business-rules/04-pre-send-safety-checks.md)
- [Contactability rule target](../../business-rules/01-lead-contactability.md)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product, layering and design review.

The dated approved consent rule and D1 closure supersede older terminal-hard-word, unknown-email
permission and workspace-A2P requirements. The business-rule-change summary spans several tickets;
it is not permission to ship them together. G2 is a named wording alignment; G3 requires an explicit
owner ruling. Escalate new material conflicts rather than quietly choosing a different product rule.