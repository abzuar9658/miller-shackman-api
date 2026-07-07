# User Management Implementation Plan

## Purpose

This document turns the approved V1 user-management design into an execution plan.
It defines the implementation order, boundaries, deliverables, and validation
requirements so work can proceed slice by slice without leaking infrastructure
details into domain or application code.

## Approved Approach

Use **Option A** from `docs/planning/user-management.md`:

- internal auth and authorization in the modular monolith
- bearer JWT access tokens
- opaque rotated refresh tokens
- invited-user onboarding
- explicit workspace membership and role rules

The first implementation target is **Slice 1 only**. Later slices should begin
only after the previous slice is implemented, tested, and reviewed.

## Slice Sequence

### Slice 1 — Domain and application rules

Goal: define pure identity and permission rules before touching persistence,
JWT libraries, FastAPI routes, or provider adapters.

Deliverables:

- domain models for user, workspace, and workspace membership
- enums for membership role and membership status
- password policy decision logic
- permission decision service for V1 actions
- application-facing auth context models if needed by permission checks
- fake-based unit tests for all core rules

Out of scope:

- SQLAlchemy models
- Alembic migrations
- JWT issuance
- password hashing adapter
- API routes

Validation:

- targeted unit tests for Slice 1
- `ruff`
- `mypy`

### Slice 2 — Persistence schema and repositories

Goal: persist the identity model without changing the Slice 1 rule boundaries.

Deliverables:

- Alembic migration for users, workspaces, memberships, credentials, sessions,
  invitations, password reset tokens, and auth audit logs
- SQLAlchemy models in `infrastructure/persistence/postgres/models.py`
- repository ports in `application/ports`
- Postgres repository implementations
- repository tests where they provide meaningful safety

Validation:

- repository tests
- migration sanity checks
- `ruff`, `mypy`, targeted `pytest`

### Slice 3 — Password and token services

Goal: add infrastructure adapters for secrets and token mechanics while keeping
application logic library-agnostic.

Deliverables:

- `PasswordHasher` port and adapter
- `AccessTokenService` port and adapter
- `OpaqueTokenService` port and adapter
- refresh token family rotation / reuse handling helpers
- unit tests with fakes plus adapter-focused tests

Dependency note:

- if new packages are required, use the package manager and ask before adding

### Slice 4 — Auth use cases

Goal: implement business workflows over the ports and domain rules.

Deliverables:

- admin create workspace
- admin invite user
- accept invitation / complete signup
- signin
- refresh
- logout current session
- logout all sessions
- forgot password
- reset password
- current user context
- switch workspace

Validation:

- fake-based use-case tests
- negative-path tests for disabled users, lockout, bad tokens, and workspace
  isolation

### Slice 5 — API routes and request dependencies

Goal: expose the use cases through thin FastAPI handlers.

Deliverables:

- request and response schemas
- auth and user-management routes
- current-user dependency
- workspace-membership dependency
- thin permission wrappers only at the interface layer

Validation:

- route tests
- auth dependency tests

### Slice 6 — Product authorization integration

Goal: apply the new auth context to real product actions.

Deliverables:

- permission checks for lead enrollment
- permission checks for campaign launch / pause
- permission checks for pre-flight veto
- permission checks for resume / reassign / handoff-related actions
- permission checks for future admin-only configuration changes

Validation:

- targeted use-case tests proving business authorization is enforced

## Execution Rules

- Do not skip ahead to API routes before the underlying use-case and rule tests exist.
- Keep permission decisions explicit in code, not embedded in route decorators only.
- Keep JWT, password hashing, SMTP, and SQLAlchemy details out of `domain/` and
  `application/`.
- Prefer fakes in tests for business rules and use cases.
- Each slice should end in green tests before the next slice starts.

## Immediate Next Step

Start **Slice 1**:

1. inspect existing domain patterns and ID/value-object usage
2. add auth domain models and enums
3. add password policy rule
4. add permission decision service
5. add targeted unit tests
6. run validation