# Inbound Conversation Completion Plan

## Purpose

This document defines the remaining work needed to finish the Phase One inbound
conversation flow so the system can safely decide whether AI should continue,
pause for review, suppress outreach, or hand the lead to a human agent.

It builds on the existing outbound delivery, inbound capture, reply
classification, workflow persistence, and handoff foundations already present in
the backend.

## Current baseline

Already implemented:

- outbound message drafting, planning, sending, and provider delivery updates
- inbound reply receipt for Follow Up Boss, Twilio SMS, and SendGrid email
- inbound message persistence, duplicate-event handling, and conversation linkage
- reply classification, summary generation, preference extraction, and opt-out
  override handling
- persisted workflow transitions for pause and handoff states
- handoff record creation, CRM note/tag updates, and agent notification

Still missing or incomplete:

- a true “AI continues the conversation” branch after a safe inbound reply
- deterministic application-owned handoff decisions instead of relying on raw LLM
  `handoff_required`
- a single clear owner for inbound orchestration between webhook intake and
  Temporal workflow execution
- explicit inbound reply signaling into Temporal like the existing human-activity
  and suppression pause flows
- stricter outbound policy enforcement for SMS compliance and unknown consent
- an operational review path for low-confidence or ambiguous inbound replies
- turn-cap enforcement and richer decision audit trails for multi-turn AI chats

## Target business outcome

The finished flow should support this sequence safely:

1. AI sends an outbound message.
2. The lead replies by SMS or email.
3. The system stores the inbound event idempotently.
4. The system evaluates the reply.
5. The application decides one of four outcomes:
   - continue AI conversation
   - hand off to agent
   - pause for human review
   - suppress future outreach
6. The durable workflow and Postgres state stay consistent and auditable.

## Recommended implementation approach

Use Temporal as the owner of post-intake inbound orchestration.

- Webhooks should validate payloads, resolve the lead, persist the inbound event,
  and commit.
- After commit, the running lead nurture workflow should be signaled.
- Workflow-owned activities should classify the reply, apply deterministic
  decision rules, transition workflow state, and trigger the next safe action.

This keeps long-running conversation state inside the durable workflow while
preserving Postgres as the queryable source of truth.

## Delivery phases

### Phase 1 — deterministic inbound decision policy

Goal: move final inbound action selection into explicit application rules.

Deliverables:

- an application-level decision module that accepts inbound classification and
  workflow context
- four explicit outcomes: `continue_ai`, `human_handoff`, `pause_for_review`,
  and `suppress`
- rules that force handoff for human requests, meaningful buyer/seller intent,
  and questions about specific properties, pricing, financing, legal, tax, or
  investment topics
- rules that force review for low-confidence, invalid, or ambiguous replies
- tests proving the final decision comes from app logic, not raw model output

### Phase 2 — inbound orchestration ownership cleanup

Goal: remove split ownership between webhook code and Temporal for inbound state
changes.

Deliverables:

- one documented owner for post-intake inbound orchestration
- removal of duplicate transition paths for the same inbound reply
- updated tests proving one inbound reply results in one authoritative decision
  path

### Phase 3 — inbound reply signaling into Temporal

Goal: make the durable workflow aware of inbound replies immediately after
intake.

Deliverables:

- post-commit inbound reply signal from webhook path to Temporal
- workflow activity handling for the signal
- error handling and audit behavior for signal failures
- tests for webhook intake → commit → signal → workflow reaction

### Phase 4 — real AI continuation branch

Goal: allow safe non-handoff inbound replies to continue the conversation.

Deliverables:

- a dedicated conversational reply drafting path for inbound continuations
- reuse of existing safe send orchestration only after a new reply is drafted
- state transitions that reflect response processing and return to waiting for
  response after successful send
- tests for outbound → inbound → AI continue → waiting for next reply

### Phase 5 — outbound policy hardening

Goal: enforce the product rules required before enabling a more autonomous loop.

Deliverables:

- SMS blocked unless workspace A2P 10DLC status is approved
- unknown SMS consent blocks SMS
- unknown email permission blocks automated email unless explicitly allowed by a
  workspace policy we intentionally support
- updated contactability and cadence tests for these blocked cases

### Phase 6 — human review path for unclear inbound

Goal: turn ambiguous replies into an explicit operational state instead of a
silent pause.

Deliverables:

- a persisted review-needed path for rejected or unclear classifications
- optional notification hook for assigned agent or operator review
- explicit resume/review completion behavior
- tests proving unclear inbound is visible and actionable

### Phase 7 — resume and recovery alignment

Goal: make resume behavior match the new inbound decision model.

Deliverables:

- resume rules that distinguish unresolved review, active handoff, suppression,
  and safe continuation states
- prevention of automatic resume after handoff
- recovery behavior when signal delivery fails after state changes were already
  committed

### Phase 8 — turn-cap enforcement

Goal: keep V1 bounded and prevent open-ended AI conversations.

Deliverables:

- tracked AI/lead turn counts per workflow or conversation
- configurable maximum back-and-forth count
- automatic pause or handoff when the cap is reached

### Phase 9 — audit and reporting hardening

Goal: make each inbound decision explainable after the fact.

Deliverables:

- stored classifier intent, confidence, prompt version, model, and extracted
  preferences
- stored final application decision and why it was chosen
- stored send-block reasons when continuation was allowed in principle but not
  sendable at the moment of reply

### Phase 10 — end-to-end test expansion

Goal: prove the complete conversation loop under realistic conditions.

Deliverables:

- webhook tests for inbound SMS and email continuation outcomes
- workflow tests for signal-driven pause/handoff/continue behavior
- business-flow harness coverage for continue, handoff, suppress, and review
  scenarios
- race-condition tests where inbound arrives before a scheduled outbound send

## Delivery order

Implement the phases in this order:

1. Phase 1 — deterministic inbound decision policy
2. Phase 2 — inbound orchestration ownership cleanup
3. Phase 3 — inbound reply signaling into Temporal
4. Phase 5 — outbound policy hardening
5. Phase 4 — real AI continuation branch
6. Phase 6 — human review path for unclear inbound
7. Phase 7 — resume and recovery alignment
8. Phase 8 — turn-cap enforcement
9. Phase 9 — audit and reporting hardening
10. Phase 10 — end-to-end test expansion

Phase 5 is intentionally moved ahead of Phase 4 so automated continuation is not
built on top of permissive send-policy gaps.

## Definition of done

This plan is complete when:

- safe inbound replies can continue the conversation automatically
- risky inbound replies hand off deterministically
- unclear inbound replies become explicit review work
- opt-outs suppress outreach immediately
- Temporal is the durable owner of the live inbound conversation flow
- Postgres remains the auditable source of truth for decisions and transitions
- SMS compliance and unknown-consent policy rules are enforced
- tests cover continue, handoff, review, suppression, and race conditions

## First execution slice

Start with Phase 1.

The first code slice should introduce the deterministic inbound decision module
without yet changing every downstream behavior at once. The initial target is to
replace direct trust in `classification.handoff_required` with explicit app rules
while preserving the current pause and handoff outcomes until Temporal ownership
and signaling are cleaned up in Phases 2 and 3.