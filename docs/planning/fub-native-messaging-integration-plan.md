# FUB-Native Messaging Integration Plan

## Status

**Proposed, not implemented.**

This document describes how to make SMS, WhatsApp, and email outreach look native inside Follow Up Boss without using FUB as the actual delivery provider.

## Core principle

FUB's public API cannot send SMS, WhatsApp, or email directly. We mirror the partner-app pattern instead:

- Our backend sends messages through external providers
- We surface those messages back into FUB through a **FUB Embedded App** and a **FUB Inbox App**
- Leads and agents see normal FUB conversations

## FUB integration layers

### 1. Embedded App

A sidebar panel inside FUB for AI controls:

- AI status per lead
- Pause/resume outreach
- Handoff reason and summary
- Override next message

### 2. Inbox App

A partner-only FUB feature that displays third-party conversations inside the FUB inbox:

- Outbound messages appear as messages in the FUB thread
- Inbound replies arrive via FUB webhook to our backend
- Conversation looks native to the agent

**Requirement:** FUB integration partner status and a `publishedInboxAppId` from FUB.

## Architecture overview

```text
+-------------+     +----------------+     +------------------+
|   FUB UI    | <-->|  Embedded App  | <-->|  Our backend     |
|  (sidebar)  |     |  (iframe panel)|     |  (AI, workflows) |
+-------------+     +----------------+     +------------------+
       ^                                            |
       | Inbox App                                  | Twilio / Gmail / WhatsApp
       | message threads                            v
+-------------+     +----------------+     +------------------+
| FUB Inbox / |     |  FUB Inbox App |     |  External providers|
| Lead thread | <-->|  webhook/API   | <-->|  (real delivery)   |
+-------------+     +----------------+     +------------------+
```

## Channel-by-channel design

### SMS

1. Backend decides to send SMS
2. Twilio sends the message from a registered number
3. Backend calls FUB Inbox App to display the message in the lead thread
4. Lead reply hits Twilio webhook and FUB Inbox App webhook
5. AI processes the reply and decides next step

**Lead sees:** normal text from a phone number.
**Agent sees:** normal SMS thread inside FUB.

### WhatsApp

Same flow as SMS, but Twilio sends through WhatsApp Business API.

**Open question:** confirm FUB Inbox App supports WhatsApp threads. If not, fall back to SMS.

### Email

1. Backend decides to send email
2. Send through the **same connected mailbox** FUB already syncs (Gmail / Microsoft 365)
3. FUB sees the sent email in the synced mailbox and displays it as a real email thread
4. Replies arrive in the mailbox and FUB syncs them

**Lead sees:** normal email from the agent's address.
**Agent sees:** normal email thread inside FUB.
**Alternative:** keep SendGrid delivery and use Inbox App for display, but mailbox sync looks more native.

## Outbound message flow

1. Workflow decides to send
2. Pre-send checks: consent, suppression, quiet hours, frequency, ownership
3. LLM drafts the message
4. External provider delivers it
5. Outbound message is logged in our database
6. Message is surfaced in FUB:
   - SMS / WhatsApp → Inbox App API
   - Email → mailbox sync
7. Audit event is emitted

## Inbound reply flow

1. Provider receives the reply
2. Provider webhook sends it to our backend
3. FUB Inbox App also displays it in the thread
4. We deduplicate by `(workspace_id, external_event_id)`
5. AI classifies intent and extracts preferences
6. System pauses, continues, or hands off to human
7. FUB tags, notes, and custom fields are updated

## Required FUB access

- Integration partner status
- `publishedInboxAppId`
- Registered system with `X-System` and `X-System-Key` headers
- Installation redirect URL
- Subscription URL for inbound Inbox App webhooks

**Fallback if no Inbox App access:** use FUB notes plus a lightweight Embedded App panel. Less native but still functional.

## Implementation phases

| Phase | Goal |
|-------|------|
| 1 | Confirm FUB Inbox App access; lock provider choices |
| 2 | Build FUB Embedded App panel for AI controls |
| 3 | Implement Inbox App install handshake, outbound display, and inbound webhook |
| 4 | Make email appear native via connected mailbox sync |
| 5 | Harden safety, audit, and idempotency |

## Key risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| FUB Inbox App access delayed or denied | High | Contact FUB immediately; keep note-based fallback |
| WhatsApp not supported by Inbox App | Medium | Verify before building; fall back to SMS |
| Mailbox sync unreliable | Medium | Test with real mailbox; keep SendGrid fallback |
| Duplicate FUB entries | High | Use idempotency keys and external event deduplication |
| Email deliverability | Medium | Use SPF/DKIM/DMARC; send from established mailbox |

## Next steps

1. Email `api@followupboss.com` to request Inbox App partner access
2. Confirm WhatsApp support with FUB or Twilio
3. Identify the email mailbox identity the client will use
4. Build a small SMS proof of concept first

## Summary

A fully FUB-native experience is achievable. We send through external providers and use FUB's partner integration model (Embedded App + Inbox App) to make the result look native. Email is the special case: the best native look comes from sending through the same connected mailbox FUB already syncs.
