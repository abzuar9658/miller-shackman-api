# Canonical Lead Record

## Purpose

This document defines the foundational lead data layer that runs before Phase One
business rules.

**Raw CRM payloads are translated into a persisted canonical lead record. Business
rules consume that record; they do not parse Follow Up Boss payloads directly.**

This is the canonical input model that allows business rules and later
message-planning steps to stay stable as CRM integrations evolve.

## Runtime position

The intended runtime flow is:

1. Receive or fetch CRM lead data.
2. Translate provider-specific payloads into canonical lead facts.
3. Store the canonical lead record in PostgreSQL under the workspace.
4. Run business rules against the stored canonical record.
5. Persist decisions, workflow state, audit records, and outbound actions separately.

Business rules may re-read the canonical record at decision time, especially before
sending messages. Scheduled workflow state must never be trusted without current facts.

## What this layer includes

This layer extracts and stores facts such as:

- workspace and CRM identity
- assigned agent/accountable owner facts
- lead type classification
- CRM source, stage, created-via, tags, and mapped custom fields
- email and phone availability
- channel permission and consent facts when known
- opt-out, do-not-contact, and suppression facts when known
- activity and timing facts
- latest safe property/event context
- extraction timestamps, source timestamps, and reason codes

## What this layer does not decide

This layer does **not** decide:

- whether a lead is contactable
- whether a lead can be enrolled
- whether a candidate starts outreach today
- whether a message may send now
- which message template to use
- whether AI should hand off to a human

Those remain explicit business rules and workflow/application decisions.

## Canonical lead record fields

### Identity and tenancy

| Field                    | Meaning                                         |
| ------------------------ | ----------------------------------------------- |
| `workspace_id`           | Required tenant/workspace ID                    |
| `lead_id`                | Internal lead ID                                |
| `crm_provider`           | Source CRM provider, initially `follow_up_boss` |
| `crm_lead_id`            | Provider lead/person ID                         |
| `source_payload_version` | Version of the provider mapping used            |
| `source_updated_at`      | Provider's latest known updated timestamp       |
| `facts_derived_at`       | Timestamp when canonical facts were produced    |

Every persisted lead-owned row must include `workspace_id`.

### Ownership and routing facts

| Field                         | Meaning                                             |
| ----------------------------- | --------------------------------------------------- |
| `assigned_agent_crm_id`       | Provider ID of assigned agent when known            |
| `assigned_agent_name_present` | Whether a non-sensitive assigned-agent label exists |
| `has_accountable_owner`       | True when outreach can be routed to a known owner   |
| `ownership_last_changed_at`   | Known ownership-change timestamp, if available      |

These facts support campaign start, pre-flight digest routing, pre-send checks, and
handoff routing. They do not decide eligibility by themselves.

### Classification and CRM context facts

| Field                   | Meaning                                              |
| ----------------------- | ---------------------------------------------------- |
| `lead_type`             | `buyer`, `seller`, `buyer_seller`, or `unknown`      |
| `classification_reason` | Reason code explaining the lead type result          |
| `crm_type_raw`          | Raw CRM type string, normalized but provider-neutral |
| `lead_source`           | CRM source string or `unknown`                       |
| `lead_stage`            | CRM stage string or `unknown`                        |
| `created_via`           | CRM created-via string or `unknown`                  |
| `tags`                  | Sorted, deduplicated CRM tags                        |
| `mapped_custom_fields`  | Explicitly mapped custom fields only                 |

In V1, lead type is derived only from the CRM type field. Source, stage, tags, and
custom fields are stored as facts and do not override lead type.

### Channel presence facts

| Field                   | Meaning                                        |
| ----------------------- | ---------------------------------------------- |
| `has_email`             | At least one usable email value exists         |
| `has_phone`             | At least one phone value exists                |
| `has_sms_capable_phone` | At least one phone is not known to be landline |
| `email_count`           | Count of email records, not raw email values   |
| `phone_count`           | Count of phone records, not raw phone values   |

Sensitive contact values should be stored only where needed for operations and should
not be duplicated in broad fact snapshots unnecessarily.

### Consent, opt-out, and suppression facts

| Field                     | Meaning                                                 |
| ------------------------- | ------------------------------------------------------- |
| `sms_permission_status`   | `known_allowed`, `known_denied`, or `unknown`           |
| `email_permission_status` | `known_allowed`, `known_denied`, or `unknown`           |
| `sms_opted_out`           | True when SMS opt-out is known                          |
| `email_unsubscribed`      | True when email unsubscribe is known                    |
| `do_not_contact`          | True when all automated outreach must be blocked        |
| `suppression_types`       | Channel/global suppression categories                   |
| `permission_evidence`     | Non-sensitive source/timestamp metadata where available |

These are facts. `01-lead-contactability.md` still decides whether a channel is
contactable. Stored permission facts remain explicit, but the contactability rule may
still treat a usable email address or SMS-capable phone as sufficient permission in V1
when no explicit denial or suppression exists. When the canonical record has no explicit
`do_not_contact` value, the contactability mapping derives `False` if any email or phone
destination is present and `True` otherwise.

### Activity and timing facts

| Field                              | Meaning                                             |
| ---------------------------------- | --------------------------------------------------- |
| `crm_created_at`                   | CRM lead creation timestamp                         |
| `crm_updated_at`                   | CRM lead update timestamp                           |
| `last_activity_at`                 | Latest CRM-visible activity timestamp when reliable |
| `last_meaningful_communication_at` | Latest communication timestamp when reliable        |
| `last_agent_activity_at`           | Latest known human/agent activity timestamp         |
| `contacted_count`                  | CRM-visible contacted count when reliable           |
| `activity_reliability`             | `reliable`, `partial`, or `unknown`                 |

Dormancy and recent-human-activity decisions consume these fields. If activity data is
partial or unknown, downstream rules must fail safe.

### Safe property/event context facts

| Field                             | Meaning                                                         |
| --------------------------------- | --------------------------------------------------------------- |
| `latest_property_event_type`      | Safe event type such as `property_inquiry` or `viewed_property` |
| `latest_property_event_at`        | Event timestamp                                                 |
| `latest_property_price_band`      | Rounded/category price signal, not exact price                  |
| `latest_property_context_present` | Whether safe context exists                                     |

Do not store raw property URLs, exact addresses, or exact prices in this canonical
fact layer unless a later operational requirement explicitly justifies it.

## Business-rule compatibility map

| Business rule                                            | Canonical facts it consumes                                                                    |
| -------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `01-lead-contactability.md`                              | channel presence, permission, opt-out, suppression, do-not-contact, workspace SMS compliance   |
| `02-campaign-enrollment-eligibility.md`                  | lead type, source, stage, tags, ownership, activity, contacted count, contactability decisions |
| `03-campaign-start-queue-and-preflight-veto.md`          | enrollment source, owner, dormant age, campaign caps, veto facts, FIFO timestamps              |
| `04-pre-send-safety-checks.md`                           | current contactability, ownership, activity, reply, suppression, workflow state                |
| `05-preflight-digest-notification-and-veto-recording.md` | owner routing, eligible dormant candidates, notification recipient facts                       |

The goal is for existing business rules to keep their decision logic while receiving
their inputs from this canonical record instead of raw CRM payloads.

## Persistence expectations

Use PostgreSQL as the source of truth for canonical lead facts. Canonical lead facts
are stored in a `leads` table with explicit columns for high-value queried fields and
JSON only for low-volume mapped metadata.

Required persistence properties:

- include `workspace_id` on every tenant-owned row
- enforce uniqueness on `(workspace_id, crm_provider, crm_lead_id)`
- keep provider-specific payloads out of domain/application models
- record fact extraction version and timestamps
- support idempotent upsert from CRM sync/webhook events
- avoid storing unnecessary raw PII in broad fact snapshots
- preserve auditability of why a fact was unknown or unsupported

## Follow Up Boss V1 mapping rules

| FUB field                                         | Canonical usage                                      |
| ------------------------------------------------- | ---------------------------------------------------- |
| `id`                                              | `crm_lead_id`                                        |
| `assignedUserId` / `assignedTo`                   | ownership and routing facts                          |
| `type`                                            | `lead_type`, `crm_type_raw`, `classification_reason` |
| `source`                                          | `lead_source`                                        |
| `stage`                                           | `lead_stage`                                         |
| `createdVia`                                      | `created_via`                                        |
| `tags`                                            | `tags`                                               |
| `emails`                                          | email presence/count facts                           |
| `phones`                                          | phone and SMS-capable presence/count facts           |
| `created`, `updated`, `lastActivity`, `contacted` | activity/timing facts                                |
| property events                                   | safe property/event context facts                    |

## Hard safety rules

- AI does not extract or override hard eligibility facts.
- Missing consent remains unknown.
- Unknown SMS permission must not become allowed.
- Unknown email permission must not become allowed without approved policy mapping.
- Suppression and do-not-contact facts must be preserved for downstream hard blocks.
- Lead type is not inferred from source, tags, property events, or AI in V1.
- Provider-specific objects must not leak beyond the adapter/mapping boundary.
