# Issue 12-B — Honor carrier-reported SMS opt-outs and use email safely

**Status: DRAFT — stakeholder, design and test-contract review required.**
This is the seventeenth proposed Jira description, not a published issue or permission to implement.
The carrier-opt-out policy is recorded; G2/G3, R1–R4 and individual Class B release gates remain.
Continuing the drafts does not authorize deployment, provider sends or historical data changes.

## 1. Business impact — read this first

**The promise:** When the SMS provider explicitly reports that a recipient has unsubscribed, the
platform remembers the SMS restriction instead of treating it as an ordinary delivery problem.
If this is a definite rejection of the current, still-unconsumed touch, the same intended message
can go by usable email after the normal checks and any required approval. That is one touch, not
two. If no channel is usable, the agent sees an actionable review hold rather than a silent stop.

| Business question | What this ticket means |
| --- | --- |
| What goes wrong today? | Twilio's unsubscribe code is discarded in favor of the HTTP status. It becomes a generic permanent failure without correcting the lead's SMS consent. A later resume, operator send or new journey can attempt the unsubscribed number again. |
| What changes? | A verified carrier unsubscribe becomes the existing durable SMS opt-out. The current definitely rejected touch uses 13-B's safe email fallback when permitted; later checks block SMS without having to rediscover the opt-out at the provider. |
| Does every blocked or failed SMS mean unsubscribe? | No. Twilio 21610 explicitly reports an unsubscribed recipient. An invalid mobile number, filtering, throttling, timeout or arbitrary error text is not that consent evidence. |
| Is the failed SMS counted as sent? | No. The definitely rejected primary consumes no logical touch. A successful email completes the original step, occurrence or AI turn once. Queueing or rendering an email is not sending it; provider acceptance is not proof of inbox delivery. |
| Will the email always go immediately? | No. Only an already-authorized, due intent may continue. Email-specific rendering/approval, channel enablement, current consent, quiet hours, spacing and all other safeguards still apply. A temporary timing restriction defers; a missing safe rendering or approval stays visibly held. |
| What if email is unavailable? | For ordinary nurture, use 13-B's PAUSED / no_usable_channel review with both channel reasons, an unconsumed touch and its approved agent-notification/recovery path. Do not invent global do-not-contact from missing destinations. |
| Can fallback bypass a pause, STOP or human handoff? | No. The SMS restriction is recorded, but independent human, reply, review, global-DNC and campaign controls remain decisive. A handoff acknowledgment keeps its special purpose; it never restarts nurture. |
| What if the unsubscribe evidence arrives later? | Preserve valid consent evidence for future work. Do not replace an already accepted, sent, consumed or uncertain old touch with an email, refund its count or rewind the track. Delivery reconciliation and consent enforcement are separate operations. |
| What happens to other permanent errors? | Standard cadence still holds for provider_failure_exhausted, without consent fallback. The existing configured paused-search exception is the inherited G3 decision, not permission to reroute every error or silently remove an opted-in track feature. |
| What will agents see? | “SMS opted out,” the actual email and its pending/deferred/accepted/uncertain result, or a specific actionable hold. The unsubscribe itself is not an unresolved generic provider-failure item; original attempt and consent evidence remain inspectable. |
| Can a CRM edit or Resume clear the opt-out? | No. Preserve 16-A's platform-owned restriction and evidence through CRM refresh. This ticket adds no START/resubscribe or human consent-clear capability and does not promise that an approved target lift route already works. |
| Will old failed leads restart on release? | No. Historical consent restoration and any permitted journey recovery require separate bounded approval and evidence. A generic failed row is neither proof of unsubscribe nor permission to resend. |

**This is Class B because it changes contact behavior.** Email after carrier-reported SMS opt-out
must be included in the owner's release approval and operator briefing. The vendor report is a
channel restriction, not proof of a global instruction or legal-compliance assurance for a brokerage.
No provider test here may contact real leads or rotate senders to bypass a carrier block.

## 2. Ticket identity, scope and dependencies

| Field | Value |
| --- | --- |
| Proposed issue type / priority | Story / High — durable carrier opt-out and safe same-intent continuation; confirm at publication |
| Source / delivery class | Production-state consistency Issue 12 / **Class B: recorded carrier-opt-out and fallback policy** |
| Repositories / components | miller-schackman-api: Twilio normalization, durable send outcome, suppression, consent fallback, callbacks, lifecycle and reads; miller-schackman-web: lead/action/message/Attention explanation |
| Sequence | Seventeenth draft after 16-A, 9-A, 11-A, 14-B, 13-B, 17-A, 17-B, 1-A, 2-A, 3-A, 4-A, 5-A, 6-A, 7-A, 8-A and 10-A. Draft order does not establish integration or release. |
| Required consent integration | Separately integrated 16-A preservation and 13-B shared consent, rendering, lifecycle and recovery contracts, including G2/G3 and its R1–R3. A canonical opt-out unit test is not proof these journeys are built. |
| Required dispatch integration | 17-A durable original intent/claim, attempt evidence, purpose/occurrence linkage and recoverable completion on every affected producer. Record integrated revisions and D6/G6-sized coverage; no surviving direct-send bypass. |
| Protected integrations | 9-A deterministic STOP and unresolved-reply safety; current ownership/CRM controls; 1-A/5-A/6-A holds, 2-A instructions, 3-A accounting, 4-A history and 7-A/10-A recovery where used. Reuse rather than rebuild them. |
| Separate uncertainty policy | 17-B owns uncertain-as-sent and audit-only delivery reconciliation. Record the actual released baseline: preserve it where active, and disclose remaining pre-17-B holds rather than introducing or removing that policy inside 12-B. |
| Decision ownership | Name product/release owner, Twilio integration owner, implementer, independent reviewer, API/web owner, track administrator and recovery operator. G2/G3 and R1–R4 remain open at their stated boundaries. |
| Reviewed baseline | API a761c1b and web 04d4361; source/vendor reference rechecked 2026-09-08. No live provider account, production cohort or runtime behavior was inspected. Retrace the integrated implementation branch. |
| Closure boundary | Trusted unsubscribe evidence → retained SMS restriction → one safe original-intent fallback or accurate hold → truthful authorized reads/recovery, without duplicate sending or weakened controls. |

**Included:** definite Twilio SMS unsubscribe rejection on standard cadence, paused-search single-fire
and recurring outreach, AI continuation, deferred Send now, rejected-draft approval and existing
configured lead-facing handoff acknowledgments. Include authenticated, exactly correlated Twilio
status evidence as a separate consent-projection path, never as permission to replace the old touch.
Cover retries, evidence persistence, execution, accounting, API/UI, tests and scoped cutover.

**Excluded:**
- SendGrid, Mailgun or other vendors' new unsubscribe/bounce mappings. A bounce is not automatically
  an unsubscribe. Existing supported email-suppression flows remain; this draft does not certify
  every email callback as already implementing suppression.
- New consent sources, global suppression from a channel event, sender/number rotation, WhatsApp
  policy, contact-identity merging, or a cross-workspace phone-number suppression service.
- Reimplementing 13-B's shared policy or 17-A's dispatch migration; building 17-B's uncertainty
  lifecycle; changing completion/late-reply/re-entry rules, retry budgets or frequency policy.
- New consent-lifting routes, courtesy CRM writes, customer notifications, staff-message fallback,
  broad dashboard redesign, generic routing infrastructure or automatic historical restart.
- Editing any prior draft or resolving G3 by implication. Its affected behavior must match an
  explicit owner decision recorded with 13-B, not an assumption in an adapter patch.

**D7: A and B must not share a PR.** Recognition plus consent continuation is explicitly a B slice.
Any newly discovered independent mechanical defect needs a separately scoped A dependency. B-only
staging is possible, but a partial channel/producer implementation is not an all-journey release.

## 3. Current behavior and contract to approve

### 3.1 What the traced code does today

TwilioSMSProvider.send catches TwilioRestException and creates ProviderSendFailure using only
classify_http_status(exc.status) and the exception string. Its port currently has PERMANENT,
TEMPORARY and UNCERTAIN, not RECIPIENT_OPTED_OUT. The adapter's provider-specific error code is
therefore not a canonical consent outcome. It also contains a WhatsApp-address branch; that is
not proof that an SMS suppression policy applies to every channel routed through this class.

send_outbound_message has both queue and direct branches. Standard cadence uses the durable queue;
paused-search withholds that wiring, and other producers can send directly. The separate dispatcher
also handles provider failures. Changing the direct helper alone misses actual standard-cadence I/O;
adding the enum alone does not record consent, render email, complete the touch or explain the result.
17-A supplies the migrated foundation; these baseline bypasses are not an implementation prescription.

provider_fallback_allowed permits one differently configured channel after PERMANENT. It is the
legacy paused-search provider-failure exception, not 13-B's consent-based alternative selection.
A missing per-step fallback_channel must not disable D1's consent fallback; an address alone must
not enable a disallowed channel. G3 preserves the unresolved exception boundary explicitly.

The suppression use case already writes sms_opted_out, SMS_OPT_OUT and permission evidence. It also
selects the latest workflow, pauses if either channel is sendable, otherwise suppresses, and can
queue PAUSE_REQUESTED. Reusing it unchanged would stop the continuation this ticket promises and
can target the wrong run. Use 16-A's durable fact and integrated 13-B's lifecycle/identity contract.

The Twilio status endpoint validates signatures only when configured, derives an event identity
from message SID/status/error code, and places the error code/message into callback metadata. It
uses service-level database access and correlates via provider message ID; it does not supply the
application idempotency key. The inspected send call does not set a per-message callback URL, so
actual callback delivery/configuration is not established by this route's existence. Missing IDs
cannot be recovered by guessing from the recipient, body or timing.

The delivery use case reconciles message/reconciliation/occurrence data and has existing counter /
BLOCKED_REVIEW_COMPLETED effects; it does not project Twilio unsubscribe into canonical lead consent.
Those generic reconciliation effects belong to 17-A/17-B, not a second completion owner in 12-B.
Free-form failure_reason and fields labelled payload_redacted are not automatically safe metadata.

Lead-detail/contactability reads, send exceptions, Resume and Send now have existing permissions and
rechecks, but do not provide a complete automatic channel substitution/recovery journey. Their
post-13-B/17-A contracts must be used; no new endpoint or unconditional Resume success is presumed.

### 3.2 Recognize evidence, not an HTTP status or an English sentence

**Verified vendor meaning:** Twilio's current error reference describes 21610 as “Attempt to send
to unsubscribed recipient” for the sender/Channels sender/Messaging Service. It can also arise after
number reassignment. It is evidence of the provider's SMS restriction, not a reconstructed STOP
body, its original time, a particular person's intent or global do-not-contact. Twilio 21614 means
an invalid mobile number; 30007 means message filtering, including carrier/provider policy filtering.
Neither is unsubscribe proof. R1 records the supported SMS route and exact current code allowlist;
21610 is the verified initial member, not a claim that all future/vendor-specific codes are known.

| Evidence / original-intent state | Required classification and response |
| --- | --- |
| Trusted Twilio SMS send rejects with verified 21610 before acceptance; original attempt remains authoritative and unconsumed | Normalize to the proposed port kind RECIPIENT_OPTED_OUT, retain safe evidence and durably project SMS_OPT_OUT. Continue the same intent through 13-B if permitted. |
| 21614, 30007, another non-opt-out code, or an absent/malformed code | No opt-out inference from HTTP 400, “blocked” text or provider name. Preserve the integrated non-opt-out classification/retry/review rules, including signed G3 where applicable. |
| Timeout, dropped response, stale in-flight claim or conflicting evidence of possible acceptance | Preserve 17-A's uncertainty/claim protection. No email replacement or SMS retry to find out what happened. Separately valid consent evidence can still be recorded. |
| Authenticated, exactly correlated status evidence explicitly reports unsubscribe after acceptance, consumption or uncertainty | Reconcile delivery under the integrated 17 contract and independently project valid SMS restriction. Future eligible work uses current consent; the old touch is not replaced. |
| Untrusted, unmatched, wrong-channel or contradictory evidence lacking a safe interpretation | Do not guess a lead, opt-out, acceptance or fallback. Retain/report the supported unresolved evidence and contain affected unsafe work under R1; no guessed or cross-tenant mutation. |

1. Inspect the vendor code at the Twilio adapter boundary before the HTTP fallback. Define supported
   SDK/code normalization, allowlisted evidence and unsupported shapes at R1. A public canonical
   kind carries business meaning inward; vendor exceptions/raw payloads stay in adapters/interfaces.
   Keep other providers' same numeric value from acquiring Twilio meaning.
2. Carry the known provider, normalized reason/code, original durable attempt identity and observation
   time through the existing outcome/evidence seam. A synchronous rejection need not have a message
   SID: use the application's stable attempt/source identity, never a fabricated provider event ID
   presented as vendor-issued. Keep an actual provider event/message ID when available.
3. Distinguish provider occurrence time when actually supplied, application observation/receipt time
   and projection time. Do not label callback receipt as when the lead originally opted out. Replays
   retain original evidence times/identities rather than stamping a new opt-out each time.
4. Bind workspace, provider/account/sender context where available, original message/attempt,
   destination/channel and canonical lead. The existing lead-level SMS restriction is the product
   scope; it is not a universal block on every lead sharing a phone. Resolve missing/mismatched
   linkage at R1. Neither changing sender nor refreshing a destination is a consent-lift operation.
5. Do not parse str(exc), error_message or failure_reason for “STOP,” “blocked” or “unsubscribed.”
   Store/display bounded safe categories and support references, not raw exception text, contact
   bodies/destinations, tokens, signatures or headers. Keep required sensitive evidence in its
   existing access-controlled boundary; extending diagnostic access needs explicit review.

### 3.3 Record suppression durably before allowing an alternate

1. Record the existing SMS_OPT_OUT representation and provider-origin evidence using the integrated
   16-A path. It blocks future SMS via ordinary sms_opted_out contactability. Do not add a second
   contactability reason, mark email unsubscribed, or create global DNC from this channel event.
2. The confirmed rejection, consent projection and original-intent continuation/hold obligation must
   commit coherently, or leave an explicit durable recoverable obligation that prevents unsafe
   dispatch. R2 approves the actual transaction/locking/outbox boundary. Email cannot dispatch before
   the restriction and its required durable continuation evidence are committed.
3. If rendering, notification, CRM work or completion fails, the recorded SMS restriction survives.
   Retry owed local projection/continuation from durable evidence, not by sending another SMS. A
   processed/deduplicated delivery event must not conceal an unperformed consent projection.
4. If the process loses the only 21610 observation before any durable record, do not claim it was
   recovered. 17-A's existing uncertain claim prevents replay; a fallback may be missed. If evidence
   was saved, retry its projection without provider I/O. R1/R2 must expose this distinction honestly.
5. Repeated/reordered send results, callbacks and inbound STOP can support the same restriction.
   Preserve 16-A's valid provenance and other restrictions; deduplicate each owed effect. An already
   set flag is not proof that a newly owed fallback/hold obligation completed, and extra evidence
   is not permission to create a second outbound intent.
6. Apply integrated 13-B lifecycle, not the old unconditional PAUSE_REQUESTED/terminal path. A lone
   SMS no with a usable alternative must not create a consent-only pause needing manual resume.
   No usable permitted channel means its ordinary-nurture review; explicit global DNC keeps its
   global end behavior. Protected human/terminal states and independent holds keep their authority.
7. Consent facts belong to the verified lead; delivery and completion belong to the original run /
   purpose. An old run's valid restriction can affect that same lead's future send checks, but must
   not transplant its cursor, failure hold or signals onto a successor. No latest-workflow lookup
   alone is sufficient authority. Apply consent lifecycle to current work only under 13-B's checked
   contract; never revive a terminal/human-owned journey.

### 3.4 Complete the same intent, not a second message journey

1. A verified, definitely rejected primary is an attempted-but-unaccepted SMS, not SENT. Retain its
   attempt evidence and original claim; authorize at most one alternate channel variant for the
   same logical intent through the integrated 13-B/17-A contract. Two channel-specific keys alone
   do not prevent duplicates. Do not replay the SMS after the opt-out has been recorded.
2. Reuse 13-B's authoritative purpose/campaign/track channel enablement, template/rendering and
   operator-approval contract. Do not require legacy provider-fallback opt-in for consent fallback,
   blindly copy the SMS payload into email, invent a subject, silently approve new substantive copy
   or remove step/channel/version mismatch checks to make dispatch pass.
3. After rendering and before email release, refresh/reload and revalidate current email consent,
   destination, enabled purpose, original intent/version, human/reply/review controls, workflow /
   campaign/workspace eligibility and the actual email's timing/frequency/mixed-channel limits.
   Unknown consent alone is allowed under 13-B; missing required safety data is not. Use existing
   lock order and conditional claims; no lock is an atomic transaction with the external provider.
4. A due permitted email can be prepared without a manual consent-only Resume, but “immediate
   fallback” is not an inline-send mandate or a latency guarantee. Render/queue/deferral/required
   approval remain pending. Use existing durable continuation; do not skip to the next step while
   the old intent has no send/hold outcome, or make the next step race an outstanding alternate.
5. Successful email acceptance completes the original step/occurrence/AI turn once using 17-A's
   recoverable purpose-specific completion. Retain original pinned run, occurrence number/phase,
   caps, content lineage and configured next action. No extra start/enrollment/touch, invented
   sent-at time for the rejected SMS or claim of recipient delivery. Completion retries never send.
6. If email is not yet time-eligible, retain the same pending intent and existing deferral; no
   no_usable_channel mislabel. If no permitted email is usable, ordinary nurture follows 13-B's
   PAUSED / no_usable_channel with both reasons, unconsumed touch and no executable next send.
   A missing renderer, configuration or approval has its own honest non-sendable/review outcome.
7. A definitely unaccepted temporary email failure may use the existing bounded retries on that
   same alternate, with final checks. One alternate is not a new one-call retry budget. Permanent
   non-opt-out email failure follows the applicable failure review contract; never ping-pong back
   to opted-out SMS or overwrite the SMS restriction with the email failure.
8. If either attempt is already accepted/possibly accepted, uncertain or consumed, no new channel,
   content version, operator approval or recovery key may replace it. An uncertain alternate retains
   17-A protection and the actual released 17-B accounting policy; it is not confirmed email success.
   A late worker's 21610 cannot reopen a claim already settled as uncertain to create fallback.
9. Existing lead-facing handoff acknowledgments use purpose-enabled, approved alternative copy only.
   If none is permitted, record the unsent acknowledgment while retaining handoff and staff duties.
   Do not add cadence/AI charges, enable a disabled acknowledgment, or duplicate an independently
   configured email acknowledgment already owned by the same handoff flow. R2 pins that identity.

### 3.5 Late callbacks: retain consent without re-sending the old touch

The endpoint's existence and synthetic callback fixture do not establish real webhook delivery.
R1 must verify the deployed sender/route configuration, SDK capability, authenticating trust boundary
and exact original-message attribution before relying on callback evidence. No valid signature /
approved trust context means no production consent mutation; the baseline optional-signature helper
is not proof of that guarantee. A separately needed general security repair remains an A dependency.

For supported callbacks, normalize the explicit provider code and keep **two distinct obligations**:
- **Delivery evidence:** attribute to the original message/attempt. Follow the integrated 17-A/17-B
  precedence and deduplication contract. Where 17-B is active this is strictly audit-only: no state,
  cursor/count/schedule changes, unblock/advance signal, refund or replacement. 12-B does not rebuild
  that generic reconciliation policy or remove legitimate initial completion instructions.
- **Consent evidence:** idempotently record the verified SMS restriction and apply 13-B to future
  work under current authority. This is not “delivery failed, therefore pause/resume.” Email-usable
  ordinary nurture has no new consent-only hold; no usable channel can have the independent consent
  review. Its reason/instruction must be attributed to consent, never used to replace the old touch.

Delivery ordering/deduplication must not discard an independently valid unprojected opt-out. Preserve
accepted/uncertain consumption and original clocks even when a later event corrects delivery to
FAILED. Contradictory or incomplete evidence stays explicitly unresolved under R1, not a guessed
fallback. Missing provider IDs, early unmatched callbacks and projection failures need a supported
capture/retry/owned limitation, not a false “processed” response that loses the only evidence.

An opt-out observation does not generate an email by itself. Only the current due, still-unconsumed
intent can use fallback; a later scheduled intent goes through its own checks. 9-A's separate inbound
receipt hold remains decisive on both channels until explicitly handled, even if a callback arrives
first. Do not claim the system can block on an event it has not yet received or recall a released send.

### 3.6 Make the result actionable without erasing history

Fresh authorized API/UI reads must show the SMS block/source, original rejection, alternate channel /
content lineage and actual pending/deferred/accepted/uncertain/held result. Keep message delivery,
logical-touch completion and lead contactability distinct. A carrier consent outcome alone must not
appear as unresolved provider_failure_exhausted in send-exception/Attention counts or offer “retry
SMS.” Filtering/rerouting that operational item must retain its historical attempt and provenance;
an actual failure of email dispatch or consent projection remains independently visible and owned.

No_usable_channel uses 13-B's existing reviewed Attention/agent-notification contract. Record both
blockers, age, responsible actor and permitted next action. Notification failure cannot undo the
restriction, falsely say “notified,” or become the only record of the hold. Protected human ownership
and generic technical failures retain their accurate, separately actionable meaning.

Correcting email/configuration does not auto-resume a held lead. The real permission-checked review /
Resume/Send now or approval journey must revalidate the original pending intent, safely render/use
the alternate and keep SMS blocked. A permitted ordinary Resume request is not proof that execution
applied it. No terminal/global-DNC resume, stale approval, new role entitlement or resend of consumed
work is introduced. Maintain assigned-agent/tenant scope and loading/empty/error presentation; no
browser-push guarantee is required, only correct fresh reads after commit.

### 3.7 Remaining implementation and release gates

These gates are artifacts to complete, not a new vote on D1 or on whether 21610 is an SMS restriction.
They remain open in this draft. Required behavior is not a claim that a new enum, route or runner
has been implemented. Close each dependent expected outcome before writing its implementation test.

| Gate | Required artifact / boundary | Who closes it |
| --- | --- | --- |
| 16-A / 13-B / 17-A integration | Exact accepted revisions and all in-scope purposes: durable suppression; shared fallback/render/approval/lifecycle; committed intent/claim, per-attempt linkage and recoverable completion. Identify missing A-only work/contained routes. Record actual 17-B and CRM-control baseline rather than silently including them. | Engineering owner + independent reviewer, before integration/activation claims and scope approval |
| G2 — No usable channel | Consume 13-B's PAUSED / no_usable_channel versus explicit global-DNC target. Verify canonical provenance/state mapping before affected code and align stale governing guidance before release. Missing email/two channel restrictions are not a global instruction. | Product + engineering reviewer; this is mapping/alignment, not reopening D1 |
| G3 — Configured paused-search exception | CLAUDE.md's blanket non-opt-out no-fallback rule conflicts with Issue 13/pre-send preservation of the configured exception. Use its signed owner decision to retain a bounded exception or remove it with track/config/cutover treatment. Do not silently change either side. Affected expectations/implementation remain blocked until recorded. | Product/release owner + track administrator with 13-B owner, before affected interaction; documents/tests aligned before release |
| R1 — Vendor, identity and evidence | Confirm supported SMS sender/route and current codes/SDK normalization; definite rejection versus ambiguity/late-result precedence; canonical safe metadata; stable attempt/event/time identity; real callback authentication/configuration/correlation; missing SID, unmatched/duplicate/mismatched destination or old-run cases; existing-provenance/later-lift conflicts and bounded retry/owned limitations. No reliance on unverified WhatsApp or provider key echo. | Integration/security + application reviewer; evidence/contract before code, deployed trust/configuration proof before activation |
| R2 — Durable same-intent continuation | Choose §6 design with explicit commit/locking/claim/projection/continuation ownership and crash/replay rules. Reuse 13-B enabled-channel/render/approval and current-run lifecycle gates; specify per-purpose accounting/deferral, recurring/handoff identities and compatible Temporal signals. Include lost rejection observation and independently failed completion without provider retry. | Engineering/workflow + content/review owners and independent reviewer, before affected code |
| R3 — Operator and public outcomes | Exact canonical/API/exception/history/count/Attention/UI outputs for consent, alternate dispatch and separate technical failures; approved no-channel notification/recovery; role/tenant authorization and stale-client behavior; useful correction → revalidation → execution evidence. No assumed automatic channel substitution in today's Resume or Send now. | Product + API/web + operations, before affected code; demonstrated end-to-end before release |
| R4 — History, rollout and rollback | Inventory proven/ambiguous opt-outs, generic failures, accepted/uncertain claims, configured exceptions, old workers/events/Temporal histories and legacy consent-only holds. Name existing bounded inventory/repair/recovery operations, exact containment controls, compatible rollout, monitored projection/continuation failures, thresholds/owners and per-cohort no-send treatment. Approve historical writes separately. | Release/recovery owner + reviewer; compatibility/design before code, scope/runbook/monitoring proof before activation |
| D7 — Individual B release approval | Explicit owner authorization of carrier-opt-out email continuation, G2/G3 and R1–R4 release closure, prerequisite evidence, operator briefing and accepted provider/correlation limits. Acknowledging this draft is not a deployment or bulk-recovery authorization. | Product/release owner, before activation |

## 4. Business acceptance scenarios — for approval

These are requirements, not passing tests. Use synthetic leads, literal expected identities/counts /
times, controlled clocks and recording transports. AC-04/05/12/15–20 apply across standard dispatch,
paused-search single-fire/recurring, AI continuation, Send now and draft approval where relevant;
include purpose-specific handoff controls under AC-17. Execute actual queued dispatch, not enqueue
alone. Close relevant gates before declaring their expected variants implementation-ready.
“Otherwise permitted” includes any 13-B-required rendering/alternate-channel approval and current
safety facts. A blocked pre-send primary makes zero SMS calls; discovery by rejection necessarily
has one initial SMS call, which must not be confused with a successful SMS or a duplicate attempt.

| ID | Given / action | Required observable result | Forbidden result |
| --- | --- | --- | --- |
| AC-01 | Real Twilio adapter normalization receives an SDK rejection with 21610 on the supported SMS route; exercise approved code representations and contrast another code at the same HTTP status. | Verified unsubscribe becomes RECIPIENT_OPTED_OUT with safe stable evidence, independently of generic HTTP classification. The other code retains its non-opt-out meaning. | HTTP-400-only mapping, string matching, raw exception leakage or passing only a hand-seeded canonical opt-out to bypass the adapter. |
| AC-02 | Return 21614, 30007, unknown/missing/malformed codes, definitely unaccepted temporary rejection and genuine transport ambiguity. | No invented SMS opt-out. Standard permanent failure holds for provider_failure_exhausted without rerouting; bounded temporary handling and 17-A uncertainty remain distinct. Signed G3 is tested separately. | Every blocked/error code becomes unsubscribe, all errors become uncertain, or generic provider-failure email fallback. |
| AC-03 | Present a different provider/channel with a similar code, a wrong sender context, and free-form “unsubscribed” text without trusted code evidence. | No Twilio-derived consent mutation/fallback outside R1's verified mapping; honest supported failure/unresolved outcome. Valid SMS control still works. | Reusing the Twilio number globally, accidentally applying SMS policy to WhatsApp, or text parsing as evidence. |
| AC-04 | An otherwise permitted SMS intent reaches actual dispatch and is definitively rejected as 21610; email is usable. | One initial rejected SMS call; durable SMS restriction before one properly rendered email acceptance; same intent completes once, no consent-only pause or generic provider-failure review. Future SMS is blocked locally. | Only changing the port enum, durable path missed, suppressed/cancelled engine defeating email, two logical touches or acceptance invented for SMS. |
| AC-05 | Repeat with email missing, denied/unsubscribed or explicitly disabled; no independent global DNC. | SMS restriction remains; zero email calls; ordinary nurture PAUSED / no_usable_channel with both reasons, unconsumed touch, coherent occurrence/enrollment, approved notification and real recovery action. | Global SUPPRESSED from unavailable email, silent skip/completion, provider_failure_exhausted for the opt-out or a healthy-looking stalled engine. |
| AC-06 | Start with explicit global DNC; separately commit DNC after the rejected primary but before alternate release. Include handoff/human-owned controls. | Pre-existing DNC prevents both provider calls; later DNC prevents email without claiming recall of the prior call. Global evidence and protected human accountability survive. | Using email to bypass DNC, removing handoff ownership or claiming the rejected SMS never happened in the race case. |
| AC-07 | The carrier restriction is already recorded before planning/admission/resume assessment; an otherwise authorized due intent has usable email. | Shared 13-B rule reaches email without another SMS probe. No message is generated solely by recording the opt-out; no new enrollment/resume entitlement. | Rediscovering opt-out at Twilio each time, early channel rejection silently skipping the touch, or automatic outreach on event receipt. |
| AC-08 | SMS becomes opted out; email consent is UNKNOWN versus DENIED; alternate is enabled versus disallowed or its configuration unavailable. | UNKNOWN alone permits an otherwise valid email without fabricated confirmation or A2P gate. Denial/disallowance blocks; unknown required config has its own honest non-sendable result under 13-B. | Require confirmed email, globally enable both channels, use a missing per-step provider-fallback setting as the D1 gate or guess configuration. |
| AC-09 | Email fallback is due inside/outside quiet hours and global/campaign/actual-channel/mixed-channel spacing limits; retry after the permitted time. | Existing actual-alternate timing rules and allowed Send now exceptions apply; deferral retains one pending intent, no touch consumption, and a later permitted send succeeds once. | Timing evasion by switching keys/channels, new frequency policy, no_usable_channel for temporary timing, or a next step racing unresolved fallback. |
| AC-10 | Run valid channel-specific rendering, missing template/subject contract, invalid output and renderer/LLM failure after 21610. | Valid email keeps original intent/approved facts and supported sender/subject/thread treatment. Invalid/unavailable conversion is visibly non-sendable; committed opt-out survives. | Raw SMS payload sent as email, invented facts/subject, swallowed content failure or rendered/queued counted as sent. |
| AC-11 | Channel changes after preview/approval; repeat Send now/approve, race edit/dismiss and use unauthorized/stale actors. | Actual content/version and R2-required alternate approval remain authoritative; truthful queued/held/result responses, current permissions and one original dispatch obligation. | Substantive rewrite inheriting old approval, “force SMS,” repeated action creating another message or disabling valid operator flows to pass. |
| AC-12 | While fallback renders/queues, commit manual/review/handoff control, unresolved reply, campaign/workspace stop, integrated tag restriction or alternate denial; separately fail a required safety read. | Latest final checks prevent inappropriate email; correct independent reasons/protected states persist. Valid no-new-block control sends. Post-release races retain honest external-call limits. | Stale context permission, clearing another hold, treating unavailable safety data as unknown consent, or claiming a DB lock recalls an external send. |
| AC-13 | Project carrier SMS opt-out then run all four 16-A refresh paths with omitted/false/permissive CRM fields; race refresh and projection in independent SQL sessions. | Fresh lead read retains suppression type/flag and valid provenance in both commit orders; legitimate unrelated CRM updates still apply. Later SMS stays blocked. | Refresh erases the carrier restriction/evidence, fake-only race proof or freezing all CRM-owned fields. |
| AC-14 | Repeat/reorder synchronous rejection evidence, a supported callback and a separate inbound STOP for the same lead; leave another inbound unresolved. | Evidence/effects deduplicate without losing owed continuation. 9-A receipt/processing hold blocks both channels until its own valid handling; event arrival alone sends nothing. | Duplicate email or notifications, new opt-out timestamps on every retry, old terminal-STOP behavior restored, or carrier evidence used to clear all reply holds. |
| AC-15 | Fail before/after rejection-evidence commit, during consent/continuation writes, then during rendering/required notification or completion. Kill/restart across the approved boundary. | Saved evidence can finish owed projection/continuation without SMS I/O; missing durable observation remains an honestly protected 17-A uncertainty/limitation, not invented recovery. Committed SMS restriction survives secondary failure. | Email before required consent commit, processed marker hiding missing state, provider retry to reconstruct lost evidence or claiming transaction rollback undid contact. |
| AC-16 | Concurrent original/alternate dispatchers and duplicate operator/worker requests compete in independent DB sessions; race stale-claim recovery with a late 21610 return. | One original logical owner and bounded permitted alternate; no duplicate dispatch/accounting. A claim already classified uncertain/consumed cannot be reopened for fallback; late valid consent can still project. | Two channel keys treated as sufficient identity, fallback worker multiplying emails, stale save reopening the claim or in-memory fake offered as SQL proof. |
| AC-17 | Complete successful fallback for standard, recurring and AI purposes; repeat completion; test configured handoff acknowledgment with alternate disabled/enabled/already separately planned. | Exactly one original step/occurrence/AI charge and correct configured next action/cap. Handoff acknowledgment keeps human ownership and its own identity, no cadence/AI charge or duplicate configured email; unsent acknowledgment retains staff duties. | Extra occurrence/start, double count, reset phase/schedule, lost approval, forced nurture resume or staff notification treated as lead outreach. |
| AC-18 | Alternate email has a definite temporary rejection then succeeds; separately has permanent non-opt-out failure or exhausts its existing retries. | Existing bounded same-alternate retry with fresh checks or accurate independent provider-failure review; no primary SMS retry and SMS suppression survives. No consumed touch for definitely unsent work. | Channel ping-pong, a new unbounded retry loop, changing budgets under “one fallback,” labeling email failure as SMS opt-out alone or false successful fallback. |
| AC-19 | Primary attempt is uncertain/possibly accepted, including stale claim; later trusted 21610 arrives before or after its existing consumption bookkeeping. | No same-touch email or SMS replacement. Valid SMS restriction projects; original claim, consumption and clocks follow the separately integrated 17 contract. Under 17-B, delivery correction is audit-only and uncertainty counts once. On a pre-17-B baseline, pin its existing allowed reconciliation effects without adding 17-B policy here. | Converting old uncertainty into definitely-unattempted work, refund/resend, callback-owned 17-B progression or secretly implementing/removing 17-B. |
| AC-20 | The authorized alternate becomes uncertain; repeat source/action and deliver late success/failure evidence. | Neither channel sends another copy. Honest alternate uncertainty and once-only applicable released accounting; later email evidence does not clear SMS suppression or authorize a new content/key variant. | “Fallback succeeded/delivered” on ambiguity, SMS ping-pong, new approval as retry or double logical charge. |
| AC-21 | Supported authenticated 21610 callback arrives for an accepted/sent/consumed old touch, including after reconciliation reporting timeout or a successor enrollment. | Delivery evidence stays on the original attempt; valid same-lead SMS consent affects future current checks under 13-B. No replacement or old cursor/count/schedule/hold transplanted onto successor; under 17-B reconciliation has no workflow effects. | A late failed event used to email that old step, resurrect terminal nurture, change callback clocks into cadence clocks or discard consent because delivery is audit-only. |
| AC-22 | Duplicate/reorder delivery events around stronger delivery evidence, a prior processed marker and an independently failed consent projection; retry projection. | Delivery precedence remains intact; independently valid owed consent projection completes idempotently from evidence without another send. Conflicting unsupported evidence has the signed R1 unresolved treatment. | Delivery dedup hiding unrecorded SMS restriction, opt-out silently cleared by a delivered callback or treating any contradictory body as a new consent fact. |
| AC-23 | Invalid/missing callback authentication, unconfigured production trust, wrong tenant/provider/message, missing SID and early unmatched callbacks. | No untrusted/misattributed consent mutation or fallback. Verified matched control projects once; supported capture/retry or explicit owned correlation limitation is observable without leaking sensitive payloads. | Public callback can suppress arbitrary leads, recipient/body/time guessing, fake key echo claimed as real provider support or false processed acknowledgment losing evidence. |
| AC-24 | Original/current destination or sender changes; two leads/workspaces share a number/CRM identifier; old-run evidence arrives for a lead with newer protected state or conflicting lift evidence. | R1's exact identity/provenance decision is enforced; existing proven restriction is not lifted by refresh/sender change. No guessed identity propagation, override of a proven authorized later lift, cross-lead mutation or old-run recovery authority. Ambiguity stays explicitly owned/contained. | Universal phone blacklist, newest-workflow targeting, automatic opt-in from a different number or erasing valid history to make linkage simple. |
| AC-25 | Delay/duplicate old PAUSE_REQUESTED, new consent/continuation instructions and completion signals while another hold or successor appears; fail instruction delivery. | Integrated 2-A/13-B/17-A ownership preserves correct current state and original continuation; no channel-only cancel defeating valid email or stale instruction clearing a stronger control. Owed failed execution remains visible, not “delivered” on enqueue. | Database-only fallback while Temporal stays cancelled, signal-driven resurrection, duplicate progression or hidden missing engine. |
| AC-26 | Fetch actual APIs then fresh UI for restriction-only, pending/deferred/successful/uncertain email, no-channel review and distinct technical failure; use permitted/unrelated roles and read failures. | Channel/history/next action/Attention and exception counts agree. Consent alone is not generic provider_failure_exhausted or retry-SMS; history retained, actual separate failures visible, loading/empty/error and scope correct. | Delete evidence to hide an exception, show queued as delivered, contact data leakage, unrelated-agent access or API failure displayed as an empty healthy queue. |
| AC-27 | Correct email/configuration while no-channel review is open; attempt unauthorized, then authorized recovery; repeat it and race a new block. | No field-change auto-resume. Real approved action can continue the same still-unconsumed intent once after current checks and any required approval; SMS opt-out and independent holds remain. Request/engine acceptance/application are truthful distinct facts. | Clearing consent to recover, terminal-DNC Resume, unusable backend-only recovery, repeated old touch or success toast offered as engine proof. |
| AC-28 | Exercise configured paused-search permanent-failure fallback, no configured exception and canonical carrier fallback before/after the intended cutover. | Behavior matches G3's explicit signed retained-exception or removal contract, including track configuration/read/UI treatment; 21610 uses shared consent fallback independent of that opt-in. Unresolved G3 blocks the affected implementation/release. | Silently retaining/removing the exception, blanket fallback, treating its setting as consent approval or claiming G3 closed by this draft. |
| AC-29 | Dry-run historical proven 21610, unrelated/missing-code failures, erased flags, duplicate evidence, conflicting later lift, lost IDs and accepted/uncertain/terminal/protected cohorts. | Bounded inventory separates consent-restoration evidence from permission to continue. Reuse approved 16-A recovery/provenance; dry-run writes nothing, repeated approved application is safe, unresolved records have owners and no automatic send/resume. | Infer opt-out from generic failure text/status, overwrite later valid consent evidence, bulk replay webhook/business actions or restart all provider-failure holds. |
| AC-30 | Rehearse compatible API, callback, dispatch/inbound worker and Temporal rollout with queued old payloads, in-flight rejection/uncertainty, old signals and configured exceptions. | No supported activated path loses carrier evidence, restores old consent-only pause/terminal behavior or bypasses durable approved alternate dispatch. Required safety/config/trust gates and G3 cohort treatment are verified. | New adapter with incompatible consumers, missing production wiring, old direct worker sending, unsafe history replay or all-journey claim on partial coverage. |
| AC-31 | Rehearse rollback after restriction and fallback intent/acceptance/uncertainty were committed. | Verified containment precedes incompatible rollback; preserve opt-outs/evidence, original/alternate claims, approvals, consumption and schedules. Compatible consumers or explicit containment prevent repeat contact; limits explained to operators. | Delete suppression/claims, reset primary to retryable, revert to unsafe inline send, refund a consumed touch or pretend contact was undone. |
| AC-32 | Run synthetic standard and migrated recurring/inbound/operator flows from raw 21610 → committed restriction → actual alternate dispatch or hold → execution → supported late evidence → fresh API/UI; include normal SMS/email positive controls. | Surviving provider-call ledger, real SQL/execution evidence, purpose-correct counts/times, truthful views and authorized recovery substantiate each claim. Normal permitted sending still works; blocked controls make no forbidden call. | Helper-only green, skipped integration labeled acceptance, tests never dispatching queued work, real-customer traffic or provider-wide exactly-once/delivery guarantee. |

## 5. Testing boundaries and mandatory test-first workflow

**Proposed boundaries — agree before implementation:**
- **Vendor → canonical failure:** actual Twilio adapter with a recording SDK/HTTP transport and
  realistic synthetic exceptions. Assert normalized kind/evidence through the public send boundary,
  not a private code-list constant. Exercise non-opt-out and normal accepted-send controls.
- **Journey → actual dispatch → completion:** real producers and integrated 13-B/17-A dispatch /
  rendering/approval orchestration; record provider channel/payload/call count and public result.
  Observe original intent, suppression, workflow/occurrence/count/time through agreed persistence
  and read seams. Queue acknowledgment alone is not the tested business outcome.
- **Callback → delivery and consent projections:** real payload validation, authenticated matching,
  deduplication, application mapping and persistence. Separate evidence ordering from consent effect
  completion and original-purpose advancement. Fake webhook key echo is not a vendor capability.
- **Persistence/execution:** local/disposable Postgres, independent sessions, deterministic barriers
  and actual transaction rollback/claim recovery; real Temporal test boundaries for continuation,
  late signal protection and compatible old histories. Repository fakes cannot prove those claims.
- **Operator/API/UI/recovery:** existing role-scoped routes and focused presentation tests plus an
  approved synthetic integrated demonstration. Validate allowed sending and usable authorized
  recovery as well as prohibited sends; no real lead, provider account mutation or production fault.

CRM/LLM/provider/notification transports and clocks may be hand-written fakes. Keep normalization,
consent, rendering validation, authorization, original identity, transitions and accounting real
inside the approved seam. Crash-test transport evidence must survive the process being killed.

1. Start on the integrated prerequisite baseline with one meaningful red: a real SMS dispatch receives
   synthetic Twilio 21610 and, with otherwise usable approved email, must retain SMS suppression and
   complete the one intended touch by email. Capture the actual failed business assertion before
   implementation. Pair the next slice with no-usable-email and then a non-opt-out control.
2. Write one test → observe meaningful red → smallest complete implementation → green, then repeat.
   Minimal enum/interface scaffolding may make a new case runnable; record it separately. Import /
   collection errors, invalid fixtures, missing infrastructure, empty selections and skips are not red.
3. A kind-value assertion can use the literal agreed recipient_opted_out outcome without needing a
   missing enum member to fail collection. Expected provider counts, consent evidence and logical
   outcomes must come from this contract, not the production classifier/evaluator under test.
4. Keep already-green normal sends, DNC, consent persistence and no-redispatch as baseline controls;
   prove sensitivity with isolated mutations rather than fabricating failures. Independently review
   changed old generic-failure/pause/exception assertions and G3-dependent expectations.
5. Critical sensitivity checks must catch HTTP-only recognition, arbitrary code/text suppression,
   forgotten durable-dispatch handling, email before consent commit, stale CRM overwrite, old
   consent-only pause signals, lost owed projection after dedup, two channel keys escaping identity,
   fallback on an uncertain primary, 17-B delivery callbacks changing consumed progress, and hiding
   all failures by removing exception rows. Pin the actual released reconciliation baseline and
   distinguish initial completion and independent consent effects. Restore mutations and rerun checks.
6. Independently review literal expected outcomes and meaningful red/green at each relevant purpose /
   race. Passing an adapter unit test alone is not consent durability, safe fallback or UI proof.

| AC / purpose / evidence variant | Actual test + command | Baseline + meaningful red | Fix + green | Sensitivity / existing control | Remaining integration limit |
| --- | --- | --- | --- | --- | --- |
| Implementer fills every relevant variant | Exact invocation | Business assertion and revision | Revision, exit code, pass/fail/skip counts | Observed protection, not helper-call proof | Named unverified claim |

## 6. Engineering starting points and design review

Navigation only, grouped by repository with repository-relative paths for portability. Retrace
the implementation branch and all consumers; these are existing locations, not claimed new coverage.

| Repository / responsibility | Existing references |
| --- | --- |
| API — vendor classification and port | app/infrastructure/messaging/twilio/client.py; app/infrastructure/messaging/provider_errors.py; app/application/ports/messaging.py; app/application/services/provider_fallback.py |
| API — consent, suppression and refresh | app/domain/compliance/contactability.py; app/domain/leads/canonical.py; app/application/services/canonical_lead_inputs.py; app/application/services/pre_send_crm_refresh.py; app/application/use_cases/process_contact_suppression_event.py |
| API — actual send and cadence | app/application/use_cases/send_outbound_message.py; app/application/use_cases/dispatch_outbound_send_requests.py; app/application/use_cases/revalidate_outbound_send_request.py; app/application/use_cases/campaign_cadence_execution.py |
| API — original purpose and operator controls | app/application/use_cases/continue_ai_conversation_after_inbound.py; app/application/use_cases/process_inbound_message_event.py; app/application/use_cases/send_deferred_outbound_message_now.py; app/application/use_cases/lead_draft_review.py; app/application/use_cases/lead_resume.py |
| API — callback normalization and evidence | app/interfaces/api/v1/webhooks.py; app/interfaces/api/schemas/provider_delivery.py; app/application/use_cases/process_provider_delivery_callback.py; app/infrastructure/persistence/postgres/provider_message_event_repository.py |
| API — claims, persistence, execution and reads | app/infrastructure/persistence/postgres/outbound_send_request_repository.py; app/infrastructure/persistence/postgres/outbound_send_reconciliation_repository.py; app/infrastructure/persistence/postgres/lead_repository.py; app/infrastructure/workflows/temporal/lead_nurture.py; app/application/use_cases/outbound_send_exception_read.py; app/interfaces/api/v1/leads.py |
| Web — lead/action/exception/Attention consumers | src/pages/LeadDetailPage.tsx; src/lib/helpers/leadPresentation.ts; src/lib/helpers/agentAttentionItems.ts; src/lib/helpers/adminAttentionItems.ts; src/lib/helpers/attentionVersions.ts; src/lib/api/outboundSendExceptions.ts; src/lib/presentation/operations.ts |

**Compare at least two technical approaches before code:**
1. Extend the integrated durable outcome boundary: normalize the rejection, persist its consent /
   continuation obligation, then reuse 13-B's shared original-intent alternative preparation.
   This centralizes identity and failure recovery and can continue without a separate callback,
   but transaction ownership, rendering latency and per-purpose completion must stay explicit.
2. Record the normalized rejection with an explicit durable consent-processing/continuation task
   in the existing outbox/job mechanisms; the existing application boundary projects consent and
   prepares the alternate independently. This separates provider I/O from rendering/projection
   recovery, but adds delivery latency and another owed effect that must be monitored/deduplicated.

Recommend the smallest extension of the actual 17-A/13-B seams that commits consent before email
and proves one original-intent owner. Neither option permits calling the old suppression handler
unchanged, building a second suppression authority, or a generic provider router. Compare maintainability,
latency, lock/transaction behavior, compatible workflow histories and implementation scope; get
design approval. Policy-dependent schema changes can be B work; unrelated A repairs stay separate.

**Existing test starting points, not evidence that the proposed behavior passes:**
- API policy/adapters: tests/infrastructure/messaging/test_twilio.py;
  tests/application/services/test_provider_fallback.py;
  tests/domain/compliance/test_contactability.py; tests/domain/campaigns/test_pre_send.py.
- API journeys: tests/application/use_cases/test_send_outbound_message.py;
  tests/application/use_cases/test_dispatch_outbound_send_requests.py;
  tests/application/use_cases/test_revalidate_outbound_send_request.py;
  tests/application/use_cases/test_campaign_cadence_execution.py;
  tests/application/use_cases/test_process_contact_suppression_event.py;
  tests/application/use_cases/test_process_provider_delivery_callback.py;
  tests/application/use_cases/test_send_deferred_outbound_message_now.py;
  tests/application/use_cases/test_lead_resume.py;
  tests/application/use_cases/test_outbound_send_exception_read.py;
  tests/application/use_cases/test_business_flow_harness.py.
- Real persistence/execution: tests/infrastructure/persistence/postgres/test_lead_repository.py;
  tests/infrastructure/persistence/postgres/test_business_flow_harness.py;
  tests/infrastructure/persistence/postgres/test_reporting_and_rls.py;
  tests/infrastructure/persistence/postgres/test_temporal_paused_search_workflow_postgres_e2e.py;
  tests/infrastructure/test_temporal_lead_nurture_workflow.py.
- API/UI: tests/interfaces/api/v1/test_webhooks.py; tests/interfaces/api/v1/test_leads.py;
  web src/app/LeadsRoutes.test.tsx; src/lib/api/outboundSendExceptions.test.ts.

Use Python 3.12/uv: exact pytest node, its file, related suites, then make lint, make typecheck and
make test. For affected web behavior: focused Vitest targets, then pnpm test, pnpm typecheck and
pnpm lint. Confirm local/disposable SQL/Temporal targets and safe sink transports; record actual
commands/exit codes/counts. Skipped required integration tests remain gaps, not green acceptance.
This drafting task runs document checks only; no behavioral tests or implementation have run.

## 7. Existing records and bounded recovery

1. **Inventory without mutation:** by workspace/provider/original run, distinguish explicitly proven
   retained 21610 evidence, generic permanent failures, recorded/lost consent, pending/accepted /
   uncertain/consumed attempts, paused-search exceptions, old signals and independent human/reply /
   DNC holds. Include callbacks previously processed for delivery without consent projection, and
   unmatched evidence. Current failure status or pause reason alone cannot identify safe treatment.
2. **Separate restoration from permission to send:** reuse 16-A's proven-evidence/provenance and
   idempotent recovery contract. Do not infer unsubscribe from generic error text, fabricate original
   opt-out time, rerun an LLM over history or overwrite a proven later authorized lift. Preserve
   all supporting evidence; incomplete/contradictory history is an owned unresolved case.
3. **No blanket restart:** consent restoration sends nothing. A proven old rejection is not itself
   authorization for an overdue email or new campaign. Only a separately reviewed permitted recovery
   can continue a still-owed intent after current controls/render/approval/timing checks. Accepted /
   uncertain/consumed work stays non-replaceable; legacy terminal runs are not ordinary Resume cases.
4. **Name the exact operation:** R4 must identify environment, bounded IDs/cohort, operator, existing
   supported inventory/dry-run/apply/revalidation action, safe evidence access and post-check counts.
   If tooling is absent, scope/review/test the required work before use. Do not blindly replay whole
   inbound/delivery/suppression workflows; dedup may skip the repair and side effects may run again.
5. **Reconcile and retain exclusions:** count candidate, already-correct, changed, deferred/unresolved
   and failed records; repetition/interruption must be safe. Unverified consent or send history
   remains explicitly contained with an owner, not declared recovered because a batch command exited.

This draft authorizes no production inspection/write, provider query/send, CRM courtesy update,
consent lift, bulk resume, re-enrollment or Jira publication. Approval of a code PR is not approval
of a historical recovery run; the exact cohort and operation require separate authorization.

## 8. Release, operator explanation and rollback

**Required operator explanation:**
> A carrier-reported SMS unsubscribe is now remembered as an SMS opt-out. When the current SMS was
> definitely rejected, the same intended touch can continue by usable email after its normal checks
> and any required approval. No usable alternate means a visible review hold, not permission to force
> SMS. Email may be pending, deferred or uncertain; “fallback” does not mean confirmed delivery.
> A later unsubscribe report changes future consent, not permission to send the old touch again.
> CRM refresh, sender changes and Resume do not clear the SMS restriction. Human control and unresolved
> replies still apply. Use the supported review/recovery route; do not create a fresh key or campaign
> to retry a possibly sent message.

Before activation, record the owner's individual D7 yes, prerequisite revisions and R1–R4 release
closure, G2 guidance alignment and G3's signed exception decision. Brief the affected brokerage /
operators on email-after-carrier-opt-out and any agreed configured-track change. Do not imply a
generic delivery-filter bypass, legal guarantee or new opt-in/notification capability.

Coordinate compatible adapter/API/UI, callback/inbound/dispatch workers, persisted schema/contracts
and Temporal builds/histories. No mixed-version caller may drop the canonical kind, apply old
consent-only pause/terminal signals, skip durable alternate work or redispatch a stale primary.
Verify callback trust/configuration if relied upon, and the exact controls that stop real dispatch.
Observe owned projection/continuation failures, unsafe/duplicate attempts prevented, no-channel
holds, rejected versus accepted alternates and unresolved evidence with approved bounded thresholds.
Use safe scoped references rather than message/contact exports; no invented monitoring runner/flag.

**Rollback:** contain affected dispatch and incompatible writers before reverting. Preserve opt-outs,
provenance, original and alternate intent/claim evidence, approvals, counts and schedules. Retain
compatible consumers or explicit safe containment; old code that forgets consent or treats claims
as resendable is not a safe fallback. Never delete suppression, reset primary/alternate status to
retryable, refund a consumed touch, replay old unblock/pause instructions indiscriminately or bulk
resume. External contact cannot be undone. Rehearse rollback with pending, accepted and uncertain
alternates, and explain any operational hold and its real recovery owner.

## 9. Definition of done and review gates

### Ready for implementation
- [ ] Business outcomes and scenario variants accepted; D1 not reopened and B-only scope explicit.
- [ ] Required integrated 16-A/13-B/17-A coverage and actual 17-B/CRM-control baseline identified.
- [ ] G2 mapping verified, G3 affected interaction decided, and R1–R3 implementation artifacts concrete.
- [ ] Two approaches compared, approved test seams/first meaningful red selected, and R4 compatible
      rollout/recovery design recorded. No nonexistent route, callback field or provider guarantee assumed.

### Ready to merge
- [ ] All supported SMS producers normalize real rejection evidence and durably preserve SMS opt-out
      before any permitted alternate dispatch; no generic exception-only dead end or SMS-only stop
      when an otherwise permitted alternate is usable. Preserve the required no-channel review.
- [ ] One original-intent alternate/hold and purpose-correct completion work through actual dispatch,
      recurring/AI/operator/handoff boundaries; rendering/approval, controls, counts and timing agree.
- [ ] Trusted late evidence projects consent without replacing accepted/uncertain/consumed work;
      dedup/order/authentication/correlation/projection failures have verified safe outcomes.
- [ ] Each AC/variant maps to meaningful red/green or justified baseline-control evidence; sensitivity,
      real SQL rollback/races and actual execution/compatible-history checks pass with skips disclosed.
- [ ] APIs/UI, exception/Attention counts, required notification and authorized correction/recovery
      are truthful and scoped; no raw sensitive evidence or misleading SMS retry/sent-now action.
- [ ] G2/G3 governing guidance aligned, independent review complete, required dependencies verified;
      no separate A defect or neighboring unapproved B policy hidden in the PR.
- [ ] Exact cutover/rollback controls, evidence-based historical cohorts, supported runbook and
      monitoring owners/thresholds reviewed. Unresolvable provider evidence is explicitly disclosed.

### Production acceptance complete — not merely merged
- [ ] Individual B activation and any exact historical recovery operation separately authorized;
      operator briefing delivered with actual supported behavior and limitations.
- [ ] Compatible producers/workers/executors and callback trust where used verified in the approved
      environment; synthetic end-to-end evidence demonstrates correct channel, retained consent,
      no prohibited/duplicate send, one logical outcome and usable permitted recovery.
- [ ] Historical proven restrictions restored only as authorized; ambiguous/protected cohorts remain
      visibly excluded with named follow-up, never automatically emailed/resumed.
- [ ] Projection/continuation/read/notification failures have accountable monitoring and response;
      no claim of universal carrier coverage, all lost history recovered or exactly-once delivery.

**Evidence status at drafting:** source/vendor trace and document review only. No application code,
new behavioral tests, runtime pass, commit, Jira publication, deployment or production data operation.

## 10. References and decision precedence

- [Source Issue 12 and business/readiness appendix](../production-state-consistency-issues.md)
- [D1 closure and D7 ship-class gate](../production-state-consistency-review-consensus.md)
- [Business-rule changes summary](../production-state-business-rule-changes.md)
- [Pre-send target — carrier Rule 3a, consent, timing and separate uncertainty policy](../../business-rules/04-pre-send-safety-checks.md)
- [Contactability target](../../business-rules/01-lead-contactability.md)
- [16-A — opt-out preservation and evidence-backed recovery](issue-16-a-preserve-opt-outs-during-crm-refresh.md)
- [9-A — deterministic STOP and unresolved replies](issue-9-a-honor-opt-outs-and-hold-unprocessed-replies.md)
- [13-B — shared consent, rendering, lifecycle, G2/G3 and recovery gates](issue-13-b-consistent-consent-and-channel-fallback.md)
- [17-A — durable original intent, dispatch and completion prerequisite](issue-17-a-durable-outbound-dispatch.md)
- [17-B — separate uncertainty accounting and audit-only delivery reconciliation](issue-17-b-continue-cadence-after-uncertain-send.md)
- [2-A — durable instruction identity and truthful delivery](issue-2-a-reliable-instruction-delivery.md)
- [3-A — accurate enrollment and start accounting](issue-3-a-accurate-enrollment-progress-and-daily-cap.md)
- [4-A — retained operational evidence](issue-4-a-retained-operational-evidence.md)
- [5-A — same-journey send-time holds](issue-5-a-durable-send-time-holds.md)
- [6-A — visible cannot-proceed outcomes](issue-6-a-visible-cannot-proceed-outcomes.md)
- [7-A — independent missing-engine recovery](issue-7-a-missing-engine-recovery.md)
- [10-A — exhausted-engine visibility and recovery](issue-10-a-exhausted-engine-failure-visibility.md)
- [Twilio 21610 — attempt to send to unsubscribed recipient](https://www.twilio.com/docs/api/errors/21610)
- [Twilio 21614 — not a valid mobile number](https://www.twilio.com/docs/api/errors/21614)
- [Twilio 30007 — message filtered](https://www.twilio.com/docs/api/errors/30007)
- Parent workspace AGENTS.md / CLAUDE.md and .augment/rules/rules.md: product, layering and design-review rules.

Code establishes current behavior; dated owner decisions establish the target; D7 governs delivery
class. Vendor references establish code meaning, not live configuration, trustworthy correlation or
permission to resend. G3 remains explicitly unresolved here. Escalate any material new policy or
evidence conflict to the owner rather than choosing the behavior that makes implementation easiest.
