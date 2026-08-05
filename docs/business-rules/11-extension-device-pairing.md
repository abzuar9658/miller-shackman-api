# Extension device pairing

## Purpose

Agents can use the authorized Follow Up Boss history extension without signing in to the Miller Schackman dashboard. A brokerage admin pairs each browser installation to one active workspace user.

## Rules

- Only a brokerage admin may generate setup codes, list devices, or revoke devices.
- A setup code is assigned to one active user and workspace, expires after 15 minutes, and is single-use.
- Creating a new code revokes that user's previous unclaimed codes.
- Setup codes and device credentials use high-entropy opaque tokens; PostgreSQL stores only SHA-256 hashes.
- A user may have at most five active extension devices. An admin must revoke one before pairing another.
- A device credential is accepted only by the extension history-export endpoint. It is not a dashboard access or refresh token.
- Every device request rechecks the device, workspace, user, membership, role, and lead workspace/provider boundaries. An active paired brokerage agent may export any Follow Up Boss lead in that workspace; dashboard imports retain their ordinary ownership rules.
- Disabling the user, membership, or workspace blocks the next request without waiting for device revocation.
- Admin revocation takes effect on the next request. Authentication uses a pessimistic row lock to serialize revocation and export.
- Pairing, successful claim, and revocation are audited. Failed device authentication emits a structured warning without the credential.
- Secret-bearing responses use `Cache-Control: no-store`. Secrets must never be logged, synchronized, or included in support messages.

## Tenant isolation

Both extension tables contain `workspace_id`, use application workspace filters, and have forced PostgreSQL RLS. Public claim codes include the workspace UUID only to establish the RLS context; the random secret remains necessary to retrieve and claim the row.

## Operations

- Production ingress must rate-limit `/api/v1/extension-auth/pair` by trusted client IP and apply a conservative request-body limit. The application code intentionally does not trust forwarded IP headers or use a per-process limiter.
- Expired setup rows contain hashes only. They may be retained with authentication audit data, then purged according to the platform retention policy.
- The admin device list shows creation, last use, version, revocation time, and reason.
- Removing browser storage requires a new setup code. Admins should revoke the abandoned device record.

## Failure behavior

- Invalid, expired, revoked, and reused setup codes return the same generic authentication error.
- The active-device limit returns an actionable conflict without disclosing user information to invalid codes.
- Invalid or revoked device credentials return a generic authentication error.
- Cross-workspace leads, unsupported CRM providers, inactive principals, revoked devices, and disabled history import remain hard failures.

## Idempotency

- The server calculates event identity from normalized activity type, direction, occurrence time, and content; it never trusts a client fingerprint as the canonical identity.
- Follow Up Boss activity IDs remain provenance, while canonical identity prevents the same timeline event from being duplicated when CRM pull and extension push use different IDs.
- Database uniqueness enforces canonical event identity per workspace, provider, and lead. When both sources exist, the provider-backed record wins over extension-rendered data.
- An extension batch fingerprint is derived from its canonical event identities. Repeating the same event set returns the existing job; a batch containing new events may create a new job.