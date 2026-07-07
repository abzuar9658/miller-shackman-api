# User Management Planning

## Purpose

This document defines the V1 user-management plan for the Miller Schackman API.
User management is required before the outbound nurture system can become a fully
testable product because every important action depends on workspace isolation,
actor identity, role-based permissions, and auditability.

The system must support:

- signup
- signin
- forgot-password / password reset
- token-based authentication
- refresh-token rotation and session revocation
- workspace membership
- role-based permissions
- current-user API context
- testable domain and application rules

## Current State

There is currently no user-management implementation in the backend.

Existing code already assumes the future presence of identity and tenancy:

- tenant-owned records use `workspace_id`
- business rules require assigned-agent, manager, and brokerage-admin decisions
- campaign changes, lead enrollment, veto, pause, resume, and handoff actions
  need an authenticated actor
- audit logs need to record who performed sensitive actions

## Technical Approaches

### Option A: Internal JWT auth with password credentials

Build first-party authentication inside the modular monolith.

The API owns users, password credentials, refresh sessions, reset tokens,
workspace membership, and RBAC. Access tokens are signed JWTs. Refresh tokens and
password-reset tokens are opaque random tokens stored only as hashes.

#### Pros

- fully testable locally with fake repositories and token services
- no external identity-provider dependency for V1
- fits the current monolith and PostgreSQL setup
- straightforward to enforce workspace-specific roles
- supports signup/signin/forgot-password directly

#### Cons

- we own password security, token rotation, lockout, and reset flows
- future SSO/OAuth support will need an additional identity adapter
- requires careful implementation to avoid security mistakes

### Option B: External identity provider first

Use Auth0, Clerk, Cognito, or another IdP for signup, signin, password reset, and
token issuance. The backend stores only local user profiles and workspace
memberships mapped to external subject IDs.

#### Pros

- fastest path to mature password and MFA features
- fewer auth-security details owned by the application
- easier later support for SSO depending on provider

#### Cons

- less locally deterministic for unit tests
- adds vendor dependency before core product behavior is complete
- workspace and role authorization still must be built internally
- provider-specific details risk leaking into application code if not isolated

## Recommendation

Use **Option A for V1**.

Build internal token-based auth now, but keep boundaries clean so an external IdP
can be added later. Core business code should depend on internal identity models
and authorization services, not FastAPI, JWT libraries, password hash libraries,
or any future IdP SDK.

## V1 Scope

### Included

- admin-created workspaces
- admin-created user invitations
- invited-user signup for brokerage admins, managers, and assigned agents
- signin with email and password
- short-lived JWT access tokens
- opaque refresh tokens with rotation
- logout for current session
- logout from all sessions
- forgot-password request
- password reset with one-time opaque token
- current-user endpoint
- workspace membership and role checks
- disabled / suspended user handling
- audit records for sensitive auth and permission events

### Deferred

- public self-service workspace signup
- OAuth social login
- SAML / enterprise SSO
- MFA / passkeys
- multiple passwordless magic-link modes
- user impersonation
- platform-admin UI
- billing ownership and plan management

## Core Domain Concepts

### User

A user is a human account that can authenticate.

Fields:

- `id`
- `email`
- `email_normalized`
- `full_name`
- `status`
- `email_verified_at`
- `created_at`
- `updated_at`

Statuses:

- `pending_verification`
- `active`
- `disabled`
- `locked`

### Workspace

A workspace represents one brokerage tenant.

V1 starts with one workspace for the brokerage, but authorized admins may create
additional workspaces later, for example to separate groups of agents or separate
operating units. A user may belong to multiple workspaces through separate
memberships.

Fields:

- `id`
- `name`
- `status`
- `default_timezone`
- `created_at`
- `updated_at`

Statuses:

- `active`
- `suspended`
- `closed`

### Workspace Membership

A membership connects a user to a workspace and assigns a role.

Fields:

- `id`
- `workspace_id`
- `user_id`
- `role`
- `status`
- `created_at`
- `updated_at`

Roles:

- `brokerage_admin`
- `manager`
- `assigned_agent`
- `platform_super_admin`

Membership statuses:

- `invited`
- `active`
- `disabled`

### Password Credential

Password hashes are stored separately from the user profile.

Fields:

- `user_id`
- `password_hash`
- `password_changed_at`
- `failed_attempt_count`
- `locked_until`
- `created_at`
- `updated_at`

Use Argon2id if available. If not, use bcrypt with a strong cost factor. Never
store or log raw passwords.

### Refresh Session

Refresh sessions represent long-lived authenticated sessions.

Fields:

- `id`
- `user_id`
- `workspace_id`
- `refresh_token_hash`
- `family_id`
- `rotated_from_session_id`
- `expires_at`
- `revoked_at`
- `revoked_reason`
- `created_at`
- `last_used_at`

Refresh tokens must be opaque random values, not JWTs. Store only the hash.

### Password Reset Token

Password-reset tokens must be one-time opaque random values stored only as hashes.

Fields:

- `id`
- `user_id`
- `token_hash`
- `expires_at`
- `used_at`
- `created_at`

## Token Security Design

### Access Token

Access tokens are signed JWTs.

Claims:

- `sub`: user ID
- `workspace_id`: active workspace ID
- `membership_id`: active membership ID
- `role`: role for active workspace
- `iat`: issued at
- `exp`: expiration
- `jti`: token ID

Defaults:

- expiration: 15 minutes
- signing: asymmetric key preferred; symmetric secret acceptable for local V1
- algorithm configured centrally

Access tokens are bearer tokens. They are not stored in the database.

### Refresh Token

Refresh tokens are opaque random strings.

Defaults:

- expiration: 30 days
- stored only as a hash
- rotated on every refresh
- old token is invalid immediately after rotation
- refresh-token reuse revokes the entire token family

### Password Reset Token

Password reset tokens are opaque random strings.

Defaults:

- expiration: 30 minutes
- stored only as a hash
- one-time use
- reset invalidates existing refresh sessions

### Token Storage

Bearer tokens are acceptable for V1 API authorization when they are short-lived,
sent only over HTTPS, never logged, and stored carefully by the frontend. A bearer
token gives access to whoever possesses it, so storage matters.

V1 decision:

- use bearer access tokens in the `Authorization` header
- keep access tokens short-lived, defaulting to 15 minutes
- use opaque refresh tokens with rotation and reuse detection
- treat refresh tokens as high-risk credentials

Recommended browser handling:

- keep access tokens in memory when practical
- avoid storing refresh tokens in `localStorage` for production because XSS can
  expose them
- consider secure HTTP-only cookies for refresh tokens before production launch

If the initial frontend implementation uses bearer refresh tokens, that is a V1
tradeoff and must be paired with short expiry, rotation, reuse detection, logout,
logout-all, and strong XSS prevention.

## API Flows

### Admin creates workspace

Endpoint:

- `POST /api/v1/workspaces`

Inputs:

- workspace name
- default timezone

Rules:

1. Require an authenticated admin allowed to create workspaces.
2. Create workspace.
3. Record audit event.
4. Optionally create or invite the first `brokerage_admin` membership for that
   workspace.

V1 bootstrap: a platform super admin (or seeded bootstrap account) creates the
first workspace and the first brokerage admin. After that, authorized brokerage
admins may create additional workspaces.

There is no public self-service workspace signup in V1.

### Admin invites user

Endpoint:

- `POST /api/v1/workspaces/{workspace_id}/users/invitations`

Inputs:

- email
- role
- optional full name

Rules:

1. Require `brokerage_admin` permission for the workspace.
2. Normalize and validate email.
3. Validate requested role.
4. Create or reuse user profile.
5. Create invited workspace membership.
6. Create one-time invitation token.
7. Send invitation email through the workspace Google email/SMTP integration.
8. Record audit event.

Admins create users by invitation. The invitee receives an email, lands on the
app, sets a password, and then signs in.

### Signup: invited user

Endpoint:

- `POST /api/v1/auth/invitations/accept`

Inputs:

- invitation token
- full name
- password

Rules:

1. Validate invitation token.
2. Create or activate user.
3. Activate workspace membership with invited role.
4. Store password hash.
5. Mark invitation used.
6. Issue access and refresh tokens scoped to the invited workspace.

No separate email-verification requirement is needed in V1 because possession of
the invitation email is sufficient for the simple account-completion flow.

### Switch workspace

Endpoint:

- `POST /api/v1/auth/switch-workspace`

Inputs:

- `workspace_id`

Rules:

1. Verify the user belongs to the requested workspace.
2. Issue a new access token with the requested `workspace_id` as the active
   workspace.
3. Keep the existing refresh session unchanged.

This allows multi-workspace users to change active context without signing out.

### Signin

Endpoint:

- `POST /api/v1/auth/signin`

Inputs:

- email
- password
- optional workspace ID when user belongs to multiple workspaces

Rules:

1. Normalize email.
2. Find active user and credential.
3. Enforce lockout rules.
4. Verify password hash.
5. Resolve active workspace membership.
6. Issue access token and refresh token.
7. Record auth audit event.

### Refresh

Endpoint:

- `POST /api/v1/auth/refresh`

Inputs:

- refresh token

Rules:

1. Hash incoming token.
2. Find active refresh session.
3. Reject expired or revoked sessions.
4. If token reuse is detected, revoke token family.
5. Rotate refresh token.
6. Issue new access token.

### Logout current session

Endpoint:

- `POST /api/v1/auth/logout`

Rules:

1. Require authenticated user.
2. Revoke current refresh session.
3. Return success idempotently.

### Logout all sessions

Endpoint:

- `POST /api/v1/auth/logout-all`

Rules:

1. Require authenticated user.
2. Revoke all active refresh sessions for that user.
3. Return success idempotently.

### Forgot password

Endpoint:

- `POST /api/v1/auth/forgot-password`

Inputs:

- email

Rules:

1. Always return a generic success response.
2. If the user exists, create a one-time password-reset token.
3. Store only token hash.
4. Send reset email through Google email integration.
5. Rate-limit by email and IP.

Never reveal whether an email exists.

### Reset password

Endpoint:

- `POST /api/v1/auth/reset-password`

Inputs:

- reset token
- new password

Rules:

1. Hash token and find unused valid token.
2. Validate password policy.
3. Update password hash.
4. Mark reset token used.
5. Revoke all refresh sessions for the user.
6. Issue no tokens by default; require signin after reset.

V1 password policy: at least 8 characters. Do not add complicated composition
rules unless needed later.

### Current user

Endpoint:

- `GET /api/v1/users/me`

Returns:

- user profile
- active workspace
- active membership
- role
- permissions

## Authorization Model

Permissions should be explicit application rules, not route-only checks.

| Capability                           | Assigned Agent   | Manager | Brokerage Admin | Platform Super Admin |
| ------------------------------------ | ---------------- | ------- | --------------- | -------------------- |
| View own assigned leads              | Yes              | Yes     | Yes             | Support only         |
| Enroll own lead when campaign allows | Yes              | Yes     | Yes             | No by default        |
| Enroll any eligible lead             | No               | Yes     | Yes             | No by default        |
| Veto own pre-flight lead             | Yes              | Yes     | Yes             | No by default        |
| Pause campaign                       | No               | Yes     | Yes             | No by default        |
| Launch/publish campaign              | No               | No      | Yes             | No by default        |
| Resume AI after handoff for own lead | Yes, with reason | Yes     | Yes             | No by default        |
| Resume/reassign any lead             | No               | Yes     | Yes             | No by default        |
| Change consent/suppression policy    | No               | No      | Yes             | No by default        |
| Manage workspace users               | No               | Limited | Yes             | Support only         |

Platform super admins are for technical support and tenant administration. They
should not normally make business outreach decisions for a brokerage.

## Application Ports

Add internal ports before infrastructure implementations:

- `UserRepository`
- `WorkspaceRepository`
- `WorkspaceMembershipRepository`
- `PasswordCredentialRepository`
- `RefreshSessionRepository`
- `PasswordResetTokenRepository`
- `InvitationRepository`
- `AuthAuditLogRepository`
- `PasswordHasher`
- `AccessTokenService`
- `OpaqueTokenService`
- `EmailNotificationProvider` backed by Google email integration for V1

Application and domain code must not import JWT libraries, SQLAlchemy, FastAPI,
or provider SDKs directly.

## Database Plan

Tables:

- `users`
- `workspaces`
- `workspace_memberships`
- `password_credentials`
- `refresh_sessions`
- `password_reset_tokens`
- `user_invitations`
- `auth_audit_logs`

Important constraints:

- unique `users.email_normalized`
- unique `(workspace_id, user_id)` membership
- unique active invitation token hash
- all workspace-owned tables include `workspace_id`
- indexes for token hashes, email lookup, membership lookup, and session family

## Implementation Slices

### Slice 1: Domain and application auth models

- user, workspace, membership, and role enums
- password policy decision logic
- permission decision service
- unit tests for role and permission rules

### Slice 2: Persistence schema and repositories

- Alembic migrations
- SQLAlchemy models
- repository implementations
- repository tests where useful

### Slice 3: Password and token services

- password hashing adapter
- JWT access-token adapter
- opaque-token generation and hashing
- refresh-token rotation logic
- unit tests with fake token services

### Slice 4: Auth use cases

- signup
- signin
- refresh
- logout
- logout all sessions
- forgot password
- reset password
- current user context

### Slice 5: API routes and dependency injection

- FastAPI schemas
- auth routes
- `require_current_user`
- `require_workspace_membership`
- role/permission dependencies kept thin

### Slice 6: Integrate permissions into product use cases

- lead enrollment
- campaign launch/pause
- pre-flight veto
- handoff resume
- user-management admin actions

## Testing Strategy

Unit tests should use fakes, not live auth providers.

At minimum test:

- email normalization
- password policy acceptance and rejection
- signup creates workspace admin membership
- invited signup activates invited membership
- signin rejects wrong password
- signin rejects disabled or locked users
- signin selects correct workspace membership
- access token contains required claims
- refresh rotates tokens
- refresh-token reuse revokes token family
- logout revokes current session idempotently
- logout-all revokes every session
- forgot-password response does not reveal whether email exists
- reset-password consumes token once
- reset-password revokes existing sessions
- role permissions for agent, manager, brokerage admin, and platform super admin
- workspace isolation for user-management queries
- audit records for sensitive auth actions

## Security Requirements

- Never log raw passwords, access tokens, refresh tokens, reset tokens, or hashes.
- Store only hashes for refresh tokens and reset tokens.
- Use constant-time token hash comparison where applicable.
- Rate-limit signin and forgot-password attempts.
- Lock accounts after repeated failed signin attempts.
- Revoke refresh sessions after password reset.
- Revoke token family on refresh-token reuse.
- Keep access tokens short-lived.
- Keep permission checks in application services and use cases.
- Do not trust client-provided `workspace_id` without checking membership.
- Add audit records for signin, failed signin, logout, password reset, invitation
  accepted, invitation resent, role changed, user disabled, user enabled, membership
  disabled, and membership enabled.

## Resolved V1 Decisions

1. **Workspace creation**: workspace creation is admin-controlled, not public
   self-service signup. A platform super admin bootstraps the first workspace
   and the first brokerage admin. The brokerage will normally start with one
   workspace, but authorized brokerage admins may create additional workspaces
   later for different groups of agents or operating units.
2. **User creation**: admins create users through invitations. The invited user
   receives an email, lands on the app, sets a password, and completes signup.
3. **Email verification**: no separate email-verification flow is required in V1.
   Possession of the invitation email is enough for the account-completion flow.
4. **Forgot password**: users can request a password-reset email and set a new
   password through a one-time reset token.
5. **Email provider**: use the workspace Google email/SMTP integration for
   invitation and password-reset emails in V1.
6. **Password policy**: keep it simple: at least 8 characters.
7. **Multi-workspace users**: users may belong to multiple workspaces through
   separate workspace memberships. Access tokens are scoped to one active
   workspace at a time; a workspace-switch endpoint refreshes the access token
   without changing the refresh session.
8. **Tokens**: use bearer access tokens in the `Authorization` header. Access
   tokens are short-lived, defaulting to 15 minutes. Refresh tokens are opaque,
   rotated, revocable, and treated as high-risk credentials.

## Recommended Next Step

Implement Slice 1 first: domain/application identity models, role enums,
permission rules, and unit tests. Do not start API routes or JWT infrastructure
until the business authorization rules are explicit and tested.
