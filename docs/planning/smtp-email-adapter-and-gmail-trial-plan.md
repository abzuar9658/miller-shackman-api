# SMTP Email Adapter and Gmail Trial Plan

## Status

Status: **proposed, not implemented**.

This document defines the recommended approach for adding a reusable SMTP email
adapter that can use Gmail for a short trial now and keep the system switchable
to SendGrid later.

## Purpose

The immediate goal is to let the team exercise more of the real outbound flow
without requiring a registered domain for SendGrid.

The longer-term goal is to preserve the current provider boundary so the email
adapter can later switch cleanly to `sendgrid` when the client is ready.

## Current baseline

Already implemented:

- outbound email sending via `EmailProvider`
- provider selection in `app/infrastructure/providers.py`
- `sendgrid`, `mailpit`, and `sink` email providers
- outbound send orchestration in `send_outbound_message`
- inbound email webhook handling for `sendgrid`
- outbound SMS, inbound SMS, and delivery callbacks for `twilio`

Important current constraint:

- `mailpit` already proves the codebase has an SMTP-shaped seam
- Gmail SMTP can support **real outbound email sending**
- Gmail SMTP does **not** provide the same provider webhooks the app already has
  for SendGrid inbound email and delivery events

## Problem statement

The team wants a real trial path now, but does not yet have a registered domain
for SendGrid sender authentication.

The system therefore needs a temporary but architecture-safe email sending path
that:

- works with Gmail SMTP for outbound delivery
- keeps provider choice explicit in configuration
- does not leak Gmail-specific behavior into application logic
- does not misrepresent Gmail as full email webhook support

## Alternatives considered

### Option 1 — add a reusable generic SMTP adapter

Add a new `EMAIL_PROVIDER="smtp"` adapter implemented with Python SMTP client
logic and environment-driven configuration.

Use Gmail by setting:

- `SMTP_HOST="smtp.gmail.com"`
- `SMTP_PORT="587"`
- `SMTP_USERNAME="..."`
- `SMTP_PASSWORD="..."`
- `SMTP_FROM_EMAIL="..."`
- `SMTP_STARTTLS="true"`

Pros:

- best fit for the existing provider architecture
- reusable for Gmail now and other SMTP providers later
- minimal duplication because `mailpit` already follows the same transport shape
- keeps future switch to `sendgrid` as a config change

Cons:

- slightly broader config surface than a Gmail-only adapter
- still outbound-only for real email E2E; inbound email webhooks remain a
  separate capability

### Option 2 — add a Gmail-specific adapter

Add `EMAIL_PROVIDER="gmail_smtp"` with Gmail-specific configuration and
behavior.

Pros:

- quickest narrow path for the immediate trial
- simpler mental model for one account

Cons:

- duplicates SMTP logic in a provider-specific adapter
- less reusable than the existing architecture expects
- encourages Gmail-specific thinking where the app should stay provider-neutral

## Recommended approach

Choose **Option 1: reusable generic SMTP adapter**.

This is the smallest change that matches the codebase rules:

- business logic stays unchanged
- provider-specific code remains in infrastructure
- the adapter is easy to replace later
- Gmail is treated as configuration, not as a domain concept inside core code

## Scope

### In scope

- add one new email provider: `smtp`
- add SMTP settings to `Settings` and `.env.example`
- wire `build_email_provider()` to construct the SMTP adapter
- support authenticated SMTP sending with plaintext and optional HTML content
- document a Gmail-compatible trial setup using an App Password
- add provider-builder tests and focused adapter tests

### Out of scope

- inbound Gmail email parsing or webhook handling
- Gmail IMAP polling
- production-grade Gmail deliverability work
- replacing or changing the existing SendGrid webhook flow
- adding a new dynamic rules engine for provider routing

## E2E behavior expectations

With Gmail SMTP, the realistic test envelope is:

### Fully real

- outbound SMS via Twilio
- Twilio delivery callbacks
- Twilio inbound SMS replies
- outbound email delivery via Gmail SMTP

### Not fully real with Gmail alone

- email delivery-status webhooks
- provider-driven inbound email reply webhooks

For the Gmail trial, email success should therefore mean:

- the app sends outbound email through Gmail SMTP
- the email lands in a real inbox
- the content, sender, and basic flow are verified manually

If later full email inbound/delivery automation is needed, `sendgrid` remains the
correct provider path already supported by the application.

## Proposed implementation shape

### Infrastructure adapter

Add `app/infrastructure/messaging/smtp/client.py` with a provider such as
`SMTPEmailProvider`.

Responsibilities:

- build an SMTP message from `EmailMessage`
- support plain text and optional HTML alternative
- authenticate with configured username/password when provided
- support STARTTLS when configured
- return a stable provider message identifier such as the generated `Message-ID`

### Configuration

Add to `app/core/config.py`:

- allow `email_provider = "smtp"`
- `smtp_host: str = ""`
- `smtp_port: int = 587`
- `smtp_username: str = ""`
- `smtp_password: SecretStr | None = None`
- `smtp_from_email: str = ""`
- `smtp_starttls: bool = True`

Do not reuse `SENDGRID_FROM_EMAIL` for SMTP. The SMTP adapter should own its own
config surface.

### Provider factory

Update `build_email_provider()` in `app/infrastructure/providers.py` to:

- validate required SMTP settings when `EMAIL_PROVIDER="smtp"`
- construct `SMTPEmailProvider`

### Tests

Add or update tests for:

- `build_email_provider()` rejects incomplete SMTP config
- `build_email_provider()` returns the SMTP adapter for valid config
- SMTP adapter sends plain text email
- SMTP adapter includes HTML alternative when provided

The application-layer send use case should not need behavior changes because it
already depends only on `EmailProvider`.

## Delivery plan

### Slice 1 — adapter and config

- add `SMTPEmailProvider`
- add `Settings` fields
- add `.env.example` entries
- wire provider factory
- add infrastructure tests

### Slice 2 — local validation

- run targeted provider tests
- run typecheck, lint, and relevant backend test scope
- verify the SMTP adapter works against a local SMTP target if needed

### Slice 3 — Gmail trial runbook

- document Gmail App Password setup
- document `.env` values for Gmail
- document how to send a safe test email
- document the known trial limitation: no inbound email webhook automation

## Validation plan

Minimum validation after implementation:

- targeted provider tests pass
- `ruff`, `mypy`, and relevant pytest scope pass
- a safe manual send reaches a real inbox using Gmail SMTP

Recommended manual verification sequence:

1. Send one outbound SMS through Twilio.
2. Verify Twilio status callback handling.
3. Reply by SMS and verify inbound processing.
4. Send one outbound email through Gmail SMTP.
5. Verify receipt in a real inbox.
6. Do not claim full email inbound E2E unless a real email webhook-capable
   provider is configured.

## Risks and mitigations

### Risk: Gmail is mistaken for a production provider

Mitigation:

- document Gmail as a **trial-only outbound SMTP path**
- keep `sendgrid` as the recommended production provider

### Risk: config confusion between SendGrid and SMTP

Mitigation:

- use separate `SMTP_*` settings
- avoid sharing `SENDGRID_*` variables with the SMTP adapter

### Risk: user expects real inbound email replies to flow automatically

Mitigation:

- document explicitly that Gmail SMTP does not replace the existing SendGrid
  inbound webhook path
- define the Gmail trial as outbound email verification only

## Approval checkpoint

If this plan is approved, the next implementation step should be:

1. add the generic SMTP provider and config
2. add tests
3. validate locally
4. provide the Gmail-specific `.env` runbook