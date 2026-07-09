# Business Use-Case Readiness

## Purpose

This is the living readiness checklist for the business-flow backend. It tracks what
is already true, what is still missing, and what must be completed before we can
honestly say the system is ready for real business-use-case testing.

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

Current baseline: **Slice 7 complete**.

This means the backend can now:

- sync lead snapshots from Follow Up Boss into Postgres
- map provider payloads into `CanonicalLeadRecord`
- evaluate contactability, enrollment eligibility, queueing, pre-flight veto, and
  pre-send safety as explicit business rules
- plan outbound messages and persist them safely
- send outbound messages through sink or provider adapters
- ingest inbound replies with idempotency and conversation persistence
- persist workflow state and workflow transition history
- start a Temporal `LeadNurtureWorkflow` for an enrolled lead
- load persisted campaign execution config by `campaign_version_id`
- execute the first persisted cadence step and move the workflow to
  `waiting_for_response`

The backend cannot yet run the full intended V1 business loop end-to-end.

## Done Now

### Business rules and flow foundations

- canonical lead facts are persisted and usable by downstream rules
- lead contactability rules exist with fail-safe behavior
- campaign enrollment eligibility rules exist
- campaign start queue and pre-flight veto rules exist
- pre-send safety checks exist and run immediately before send
- inbound replies can pause automation and trigger handoff behavior
- workflow state transitions are explicit and auditable

### Technical foundations

- Postgres persistence exists for leads, campaigns, enrollments, workflows,
  transitions, conversations, inbound messages, outbound messages, handoffs,
  CRM sync jobs, and external events
- repository ports and Postgres adapters exist for the major business-flow seams
- Temporal worker, starter, workflow, and activities exist for enrollment and the
  first cadence-step path
- sink providers exist for safe local end-to-end outbound testing
- validation baseline is green at the current slice boundary

## Still Missing Before Real Business-Use-Case Testing

### Highest-priority business gaps

- workspace-level contact policy is not yet persisted as the source of truth for
  SMS compliance state, quiet hours, timezone, and channel policy
- only the first cadence step runs; the workflow does not yet execute a full
  multi-step wait/send/wait campaign loop
- there is no thin end-to-end business-flow harness for:
  `sync -> enrollment -> first cadence send -> inbound reply -> pause/handoff`
- handoff is not yet complete from the business side because agent notification
  and CRM writeback are still missing
- human agent activity from the CRM does not yet pause AI outreach automatically
- daily dormant-lead selection and the full pre-flight digest workflow are not yet
  wired into a repeatable operational flow
- opt-out and unsubscribe handling still needs the full provider/CRM event path

### Important technical gaps

- workspace contact-policy persistence seam and repository are not implemented
- provider delivery callbacks are not yet wired into outbound status updates
- CRM activity webhooks are not yet consumed into pause/resume business logic
- transactional outbox and RabbitMQ fan-out are not yet production-real
- reporting, audit views, and operational dashboards are not yet implemented
- PostgreSQL row-level security is not yet enforced as deployed policy
- campaign admin and publishing APIs are not yet implemented

## Recommended Next Order

1. persist workspace contact policy and SMS compliance state
2. add the narrow business-flow harness for the first end-to-end loop
3. extend `LeadNurtureWorkflow` into a full multi-step cadence loop
4. complete handoff with agent notification and CRM writeback
5. add CRM human-activity pause detection
6. wire dormant-lead selection and full pre-flight digest flow
7. add provider callback handling, reporting, and operational readiness pieces

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
