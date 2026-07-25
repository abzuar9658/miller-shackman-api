# Mailgun Sandbox Email Provider with SendGrid Switch Control

## Status

Status: **approved for implementation**.

## Purpose

Enable a real end-to-end email demo (outbound send + inbound reply webhook + delivery callbacks) using a Mailgun sandbox domain, with no custom domain. Keep the email provider boundary clean so switching to SendGrid later is a configuration and dashboard change, not a rewrite.

## Current baseline

- `EmailProvider` port already supports multiple outbound providers (`sendgrid`, `mailpit`, `sink`).
- Inbound email is currently handled only by `POST /sendgrid/inbound-messages/{workspace_id}` with SendGrid-specific payload parsing and signature verification.
- Delivery callbacks are handled for `twilio` and `sendgrid`.
- `WorkspaceContactPolicy.inbound_email_address` is already used to validate the inbound destination address.
- `sendgrid_from_email` is currently the only sender-address setting and is used for both SendGrid and Mailpit.

## Problem statement

We need:

1. A real email provider that can send without a verified custom domain.
2. Real inbound reply webhooks so the app can process lead replies automatically.
3. A provider switch path back to SendGrid that is controlled and low-risk.

Mailgun sandbox satisfies (1) and (2) for a small set of authorized recipients. It requires a new provider adapter and a new inbound webhook handler because its payload and signatures differ from SendGrid's.

## Alternatives considered

### Outbound transport: Mailgun API vs Mailgun SMTP

- **Mailgun API**: simpler async integration, returns a proper Mailgun message ID, easier to set `Reply-To`, and handles delivery webhooks natively.
- **Mailgun SMTP**: reuses the existing `mailpit` SMTP pattern, but needs `smtplib` + `Message-ID` handling and does not naturally surface the Mailgun message ID for webhook correlation.

**Decision:** use the **Mailgun HTTP API** for outbound.

### Inbound reply handling: Mailgun routes vs domain-level webhooks

- **Routes (`forward()` action)**: easiest in sandbox; forwards received emails as form-encoded POST to any URL.
- **Domain-level inbound webhook**: requires a receiving domain with MX records, which is not available in a sandbox.

**Decision:** use **Mailgun Routes** for inbound reply forwarding.

### Delivery callbacks

Mailgun delivery events can be received via domain-level webhooks. The code will implement the webhook path so the same route works once a domain is used later. For the sandbox, we can additionally verify delivery through the Mailgun dashboard if webhooks are limited.

## Recommended approach

Add a first-class `mailgun` email provider alongside `sendgrid`. Keep provider-specific logic at the infrastructure and interface edges, and normalize both providers into the existing `InboundMessageEvent` and `ProviderDeliveryCallback` models.

### Design principles

- **Provider-specific parsing/verification at the edge.** Mailgun and SendGrid each have their own route, payload schema, and signature verification.
- **Provider-neutral business handling after normalization.** Both hand off to the same `process_inbound_message_event(...)` and `process_provider_delivery_callback(...)` use cases.
- **Generic sender address config.** Introduce `EMAIL_FROM_EMAIL` as the default outbound sender. Keep `SENDGRID_FROM_EMAIL` as a SendGrid-specific override for backward compatibility. Mailgun uses `EMAIL_FROM_EMAIL` and validates it ends with the configured `MAILGUN_DOMAIN`.

## Scope

### In scope

1. `Settings` additions: `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_WEBHOOK_SIGNING_KEY`, `EMAIL_FROM_EMAIL`.
2. `MailgunEmailProvider` in `app/infrastructure/messaging/mailgun/client.py`.
3. Wire `EMAIL_PROVIDER=mailgun` in `app/infrastructure/providers.py`.
4. New `POST /mailgun/inbound-messages/{workspace_id}` route, signature verification, and payload parser.
5. New `POST /mailgun/message-events/{workspace_id}` route for delivery callbacks (delivered, failed, bounced, etc.).
6. Shared helper for email inbound normalization so SendGrid and Mailgun reuse lookup-by-inbound-address logic.
7. `.env.example` updates.
8. Tests: provider factory, outbound send, inbound webhook, delivery callback, signature verification.
9. Demo runbook: Mailgun sandbox setup, ngrok, route configuration, send a reply, inspect result.
10. Switch-back runbook: moving from Mailgun to SendGrid.

### Out of scope

- Generic plugin registry for email providers.
- Dynamic webhook engine.
- Custom MIME parsing beyond what Mailgun already normalizes.
- Production-grade domain/DNS setup for Mailgun (this is the sandbox path).
- Mailgun list-management or template features.

## Configuration

```env
# Active provider
EMAIL_PROVIDER=mailgun

# Generic sender address used by all providers
EMAIL_FROM_EMAIL=reply@sandbox-xxxxxxxxxxxxxxxx.mailgun.org

# Mailgun-specific
MAILGUN_API_KEY=key-xxxxxxxxxxxxxxxx
MAILGUN_DOMAIN=sandbox-xxxxxxxxxxxxxxxx.mailgun.org
MAILGUN_WEBHOOK_SIGNING_KEY=xxxxxxxxxxxxxxxx

# SendGrid kept ready for later switch
# EMAIL_PROVIDER=sendgrid
# SENDGRID_API_KEY=SG.xxxxxxxxxxxxxxxx
# SENDGRID_EVENT_WEBHOOK_PUBLIC_KEY=MFkw...
# SENDGRID_FROM_EMAIL=noreply@yourdemo.domain
```

## Code changes

| File | Change |
|------|--------|
| `app/core/config.py` | Add `mailgun_*` settings, `email_from_email`. Keep `sendgrid_from_email` as optional override. |
| `app/infrastructure/messaging/mailgun/client.py` | New `MailgunEmailProvider` using `httpx` to `POST /v3/{domain}/messages`. |
| `app/infrastructure/providers.py` | Add `mailgun` branch in `build_email_provider()`. |
| `app/interfaces/api/schemas/inbound.py` | Add `MailgunInboundParsePayload` schema. |
| `app/interfaces/api/schemas/provider_delivery.py` | Add `MailgunEventWebhookPayload` schema. |
| `app/interfaces/api/v1/webhooks.py` | Add `receive_mailgun_inbound_message` and `receive_mailgun_message_events` routes. Extract shared email inbound lookup/response helper. |
| `.env.example` | Add Mailgun vars and `EMAIL_FROM_EMAIL`. |
| `tests/infrastructure/test_providers.py` | Add Mailgun wiring tests. |
| `tests/infrastructure/messaging/test_mailgun.py` | New file for outbound send unit tests. |
| `tests/interfaces/api/v1/test_webhooks_mailgun.py` | New file for inbound and delivery webhook tests. |

## Tests

- `test_build_email_provider_returns_mailgun_adapter`
- `test_mailgun_send_returns_message_id` (monkeypatch `httpx` POST)
- `test_receive_mailgun_inbound_message_verifies_signature`
- `test_receive_mailgun_inbound_message_processes_reply`
- `test_receive_mailgun_inbound_message_rejects_bad_destination`
- `test_receive_mailgun_message_events_maps_delivered_and_failed`
- `test_duplicate_mailgun_event_is_ignored`

## Demo runbook

1. Sign up for Mailgun and get a sandbox domain.
2. Add an authorized recipient email address (e.g., your Gmail) in the Mailgun dashboard.
3. Set `EMAIL_PROVIDER=mailgun`, `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_WEBHOOK_SIGNING_KEY`, and `EMAIL_FROM_EMAIL=<reply@sandbox-...>` in `.env`.
4. Update the workspace's `inbound_email_address` to `reply@sandbox-...mailgun.org`.
5. Start the API: `make run`.
6. Start ngrok: `ngrok http 8000` and copy the HTTPS URL.
7. In Mailgun, create a route: `match_recipient("reply@sandbox-...mailgun.org")`, action `forward("https://<ngrok>/api/v1/mailgun/inbound-messages/{workspace_id}")`.
8. Optional: configure domain-level webhook for delivery events to `https://<ngrok>/api/v1/mailgun/message-events/{workspace_id}`.
9. Trigger an outbound email from the app.
10. Reply from the authorized recipient inbox.
11. Verify the webhook is received and the reply appears in the lead conversation.

## Switch back to SendGrid later

1. Get a domain and complete SendGrid domain authentication.
2. Set `EMAIL_PROVIDER=sendgrid` and fill in `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, and `SENDGRID_EVENT_WEBHOOK_PUBLIC_KEY`.
3. Update the workspace's `inbound_email_address` to the new SendGrid receiving address.
4. Configure SendGrid Inbound Parse and event webhook to the existing `/sendgrid/*` routes.
5. No application code changes are needed because the core send path, inbound event, and delivery callback are provider-neutral.

## Risks and notes

- Mailgun sandbox restricts recipients to addresses manually authorized in the dashboard. The demo must use an authorized address.
- Sandbox domains are not branded, so the client will see a `mailgun.org` sender. This is acceptable for a technical demo but not for production.
- Mailgun inbound routes are account-level; the route expression filters by recipient.
- Webhook signature verification uses the `MAILGUN_WEBHOOK_SIGNING_KEY`; disabling it (empty value) is allowed for local dev only.
- Mailgun delivery webhooks may be limited in sandbox depending on account configuration; the code will still support them and the dashboard can be used for demo verification.
