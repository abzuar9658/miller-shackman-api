# Business Use-Case Readiness

## Purpose

This is the living readiness checklist for the business-flow backend. It tracks what
is already true, what is still missing, and what must be completed before we can
honestly say the system is V1-complete for the intended pilot business flow.

Update this document after every completed slice.

## Readiness Target

The target V1 business scenario is:

1. sync leads from Follow Up Boss
2. normalize them into canonical lead facts
3. select or enroll eligible leads into a published campaign
4. execute campaign cadence steps through Temporal
5. send only when contactability, consent, suppression, quiet hours, ownership,
   frequency, and compliance rules all pass
6. react safely to inbound replies, human activity, and opt-outs
7. stop AI when a human should take over
8. notify the assigned agent and write the correct CRM handoff context

## Current Baseline

Current baseline: **Slice 12 complete**.

This means the backend can now:

- sync lead snapshots from Follow Up Boss into Postgres
- map provider payloads into `CanonicalLeadRecord`
- evaluate contactability, enrollment eligibility, queueing, pre-flight veto, and
  pre-send safety as explicit business rules
- plan outbound messages and persist them safely
- send outbound messages through sink or provider adapters, using persisted
  workspace contact policy for SMS compliance and timezone-aware quiet hours
- ingest inbound replies with idempotency and conversation persistence
- persist workflow state and workflow transition history
- start a Temporal `LeadNurtureWorkflow` for an enrolled lead
- load persisted campaign execution config by `campaign_version_id`
- execute all persisted cadence steps in a multi-step wait/send/wait loop,
  keeping the workflow alive after the final send for inbound replies and handoff
- complete handoff delivery by notifying the assigned agent, writing CRM note/tag/
  custom-field updates, and persisting handoff completion status for retries
- consume CRM human-activity events that pause active nurture and signal Temporal to
  stop pending AI sends

The backend now has the core V1 business-flow spine, but it is not yet V1-complete
because dormant-selector operations, opt-out event completion, delivery callbacks,
and the remaining operational readiness slices are still missing.

## V1 Status Summary

### What is done

- the core sync -> enroll -> cadence -> inbound -> pause/handoff path exists
- the main business rules are explicit in code rather than hidden in prompts or CRM
  adapters
- Temporal orchestration, workflow persistence, campaign execution config, and
  workspace contact policy are implemented
- both fake-based and real Postgres-backed harnesses prove the first critical
  business loop end-to-end

### What is left before V1 can be called complete

- wire the daily dormant-lead selector and full pre-flight digest/veto flow
- complete opt-out and unsubscribe handling across real provider/CRM event paths
- wire provider delivery callbacks into outbound status updates
- complete the operational slices for outbox/RabbitMQ, campaign admin/publishing,
  reporting, and deployed tenant-isolation hardening

### Current honest status

- the backend is past the foundation stage and into completion work
- the project is **not yet V1-complete**
- the next most important milestone is **opt-out and unsubscribe completion**

## Done Now

### Business rules and flow foundations

- canonical lead facts are persisted and usable by downstream rules
- lead contactability rules exist with fail-safe behavior
- campaign enrollment eligibility rules exist
- campaign start queue and pre-flight veto rules exist
- pre-send safety checks exist and run immediately before send
- pre-send quiet-hour checks now respect the workspace timezone
- inbound replies can pause automation and trigger handoff behavior
- handoff completion now notifies the assigned agent and writes the configured CRM
  handoff context back to Follow Up Boss
- CRM human activity can now pause active nurture and signal Temporal with an
  explicit pause reason
- workflow state transitions are explicit and auditable
- workspace-level contact policy is persisted and used by cadence execution
  (SMS compliance state, quiet hours, timezone)

### Technical foundations

- Postgres persistence exists for leads, campaigns, enrollments, workflows,
  transitions, conversations, inbound messages, outbound messages, handoffs,
  CRM sync jobs, external events, and workspace contact policies
- repository ports and Postgres adapters exist for the major business-flow seams
- Temporal worker, starter, workflow, and activities exist for enrollment and the
  multi-step cadence execution path
- dedicated persistence exists for workspace handoff config and handoff completion
  tracking
- sink providers exist for safe local end-to-end outbound testing
- both application-level and real Postgres-backed business-flow harnesses now cover:
  `sync -> enrollment -> first cadence send -> inbound reply -> human_handoff`
- validation baseline is green at the current slice boundary

## Still Missing Before V1 Completion

### Highest-priority business gaps

- daily dormant-lead selection and the full pre-flight digest workflow are not yet
  wired into a repeatable operational flow
- opt-out and unsubscribe handling still needs the full provider/CRM event path

### Important technical gaps

- provider delivery callbacks are not yet wired into outbound status updates
- transactional outbox and RabbitMQ fan-out are not yet production-real
- reporting, audit views, and operational dashboards are not yet implemented
- PostgreSQL row-level security is not yet enforced as deployed policy
- campaign admin and publishing APIs are not yet implemented

## Recommended Next Order

1. complete opt-out and unsubscribe handling across real provider/CRM events
2. wire dormant-lead selection and full pre-flight digest flow
3. add provider callback handling and outbound status reconciliation
4. add outbox/RabbitMQ, reporting, admin APIs, and operational readiness pieces

## Ready-to-Test Definitions

### Ready for narrow business-use-case testing

We can claim this when the backend can reliably demonstrate:

- sync
- enrollment
- first cadence send
- inbound reply
- pause or handoff

with persisted state transitions and no unsafe sends.

### Ready for broader V1 business-use-case testing

We can claim this when the backend additionally has:

- persisted workspace contact policy
- full multi-step cadence execution
- handoff notification and CRM writeback
- human-activity pause behavior
- opt-out and unsubscribe enforcement across real inbound events

### Ready for V1 completion

We can claim this when the backend additionally has:

- handoff completion through notification plus CRM writeback
- human-activity pause behavior from real CRM activity/update signals
- dormant-lead selection and the full pre-flight digest/veto workflow
- provider delivery callbacks and safe outbound status reconciliation
- transactional outbox plus RabbitMQ fan-out for important asynchronous events
- campaign admin/publishing controls, reporting visibility, and deployed RLS policy

## Maintenance Rule

Whenever a slice is completed, update this document in the same change set to:

- move completed items from "Still Missing" into "Done Now"
- adjust the recommended next order if priorities change
- keep the baseline honest about what can and cannot be tested

## Related Documents

- `docs/planning/business-flow-implementation-plan.md`
- `docs/planning/business-flow-persistence-and-workflow-design.md`
- `docs/foundational-data/canonical-lead-record.md`
- `docs/business-rules/01-lead-contactability.md`
- `docs/business-rules/02-campaign-enrollment-eligibility.md`
- `docs/business-rules/03-campaign-start-queue-and-preflight-veto.md`
- `docs/business-rules/04-pre-send-safety-checks.md`
- `docs/business-rules/05-preflight-digest-notification-and-veto-recording.md`
