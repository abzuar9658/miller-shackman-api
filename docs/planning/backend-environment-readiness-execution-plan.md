# Backend Environment Readiness Execution Plan

## Purpose

This document turns the approved dependency and readiness assessment into an
execution plan. The goal is to make the backend fully dev-ready first and then
prod-ready without mixing unrelated work.

## Planning Principles

- make local development repeatable before production hardening
- close architectural gaps in dependency order, not in convenience order
- prefer explicit runtime decisions over optional or implicit setup
- keep provider behavior testable through ports and fakes
- do not treat a package declaration as a finished infrastructure integration

## Target Outcomes

### Dev-ready outcome

The backend can be started locally as a complete V1 system with:

- Postgres
- RabbitMQ
- Temporal
- Redis if retained as an intentional runtime dependency
- API process
- Temporal worker process
- documented fake-versus-real strategy for CRM, LLM, SMS, email, and storage
- reproducible commands for boot, migrate, test, lint, and typecheck

### Prod-ready outcome

The backend can be deployed with:

- explicit runtime topology for API and worker processes
- managed stateful dependencies
- provider credential strategy
- observability, health checks, backups, and recovery
- validated workflow, broker, and database integrations

## Phase 0 Decisions for the Initial Local-Readiness Slice

These decisions are locked for the first implementation slice and may be revisited
only with an explicit planning update.

1. **Redis is part of the full local stack now.** The default `CACHE_PROVIDER` is
   `redis`, the Redis adapter exists, and keeping Redis out of local orchestration
   creates unnecessary environment drift.
2. **Temporal uses a local Docker Compose stack now.** The official local endpoint
   is `localhost:7233`, with a Temporal UI exposed for debugging.
3. **SendGrid remains the implemented outbound email provider.** Google email/SMTP
   references in user-management planning remain unresolved auth/operational-email
   planning debt until a separate provider decision is made.
4. **Twilio and SendGrid credentials are not required for routine local boot.** They
   are required only for live integration testing and must use non-production
   accounts, senders, and recipients.
5. **Production deployment target remains undecided.** Production topology stays in
   Phase 6 and should not be guessed during local-readiness work.

## Work Sequence Overview

### Phase 0: Lock the remaining dependency decisions

This phase prevents rework later.

Decisions to make explicitly:

1. Is Redis mandatory in V1 runtime, or merely a prepared adapter?
2. What is the official local Temporal stack?
3. What is the official local Redis strategy?
4. What is the production email provider strategy?
   - SendGrid for all outbound email
   - Google for auth/operational email and SendGrid for campaign email
   - another split, but explicit and documented
5. Are Twilio and SendGrid required only for integration testers in dev?
6. What is the production deployment target?

Deliverables:

- approved decision log in planning docs
- updated dependency/readiness doc if any decision changes the baseline

Exit criteria:

- no unresolved question remains about Redis, email provider ownership, or deploy target

### Phase 1: Build the official local infrastructure stack

This phase makes local infrastructure complete and repeatable.

Implementation slices:

1. Expand local orchestration so it can start all required services.
   - keep Postgres and RabbitMQ
   - add Temporal
   - add Redis if Redis remains required
2. Add local service defaults and connection guidance.
3. Add local startup instructions and failure troubleshooting.
4. Add service health verification steps.

Recommended outputs:

- expanded `compose.yaml` or equivalent local stack definition
- documented startup order for API and worker
- `.env.example` aligned with the chosen local stack
- clear notes on which provider secrets may remain empty for routine development

Exit criteria:

- a new developer can start the required local services without guessing
- all declared local service endpoints are reachable from the backend

### Phase 2: Make runtime process boundaries real

This phase turns the architecture from a scaffold into an executable system.

Implementation slices:

1. Implement a real Temporal worker bootstrap.
2. Define workflow and activity registration boundaries.
3. Separate API startup from worker startup clearly.
4. Define task queue naming and worker process conventions.
5. Add health/readiness behavior for both API and worker entrypoints.

Recommended outputs:

- working worker entrypoint instead of `NotImplementedError`
- documented command(s) for running API and worker locally
- smoke verification that worker can connect to Temporal

Exit criteria:

- API process can start independently
- worker process can start independently
- worker connects successfully to the local Temporal server

### Phase 3: Resolve provider strategy for development and production

This phase removes ambiguity around real integrations.

Implementation slices:

1. Resolve the email inconsistency between planning docs and current implementation.
2. Define which providers are:
   - required in unit tests
   - faked in local development
   - sandboxed in integration testing
   - required in production
3. Add provider-specific environment guidance.
4. Add validation rules for missing secrets when a provider is enabled.

Recommended outputs:

- explicit provider matrix for CRM, LLM, SMS, email, and storage
- updated docs for Twilio and SendGrid dev usage
- startup validation policy for provider-dependent modes

Exit criteria:

- no provider dependency is ambiguous
- developers know when they need real credentials and when they should use fakes

### Phase 4: Turn declared infrastructure into actual integrations

This phase closes the gap between config and implementation.

Implementation slices:

1. Implement the transactional outbox and RabbitMQ publishing path.
2. Add broker-facing integration tests or smoke checks.
3. Confirm whether Redis is actually used in the runtime path.
   - if yes, wire the intended cache-backed behavior
   - if no, remove it from the required readiness baseline until needed
4. Add clear failure behavior for unavailable broker, cache, or workflow runtime.

Recommended outputs:

- concrete RabbitMQ integration code
- explicit Redis decision: adopt now or defer cleanly
- tests or smoke checks proving the chosen integrations work

Exit criteria:

- RabbitMQ is no longer just a declared dependency
- Redis is either intentionally implemented or intentionally removed from the critical path

### Phase 5: Developer ergonomics and verification

This phase turns the stack into something the team can use every day.

Implementation slices:

1. Add a documented local bootstrap flow.
2. Add `make` targets or equivalent convenience commands for:
   - infrastructure startup
   - migration
   - API run
   - worker run
   - full verification
3. Add smoke checks for:
   - database connectivity
   - broker connectivity
   - Temporal connectivity
   - cache connectivity if retained
4. Add lightweight integration tests for the local stack where practical.

Exit criteria:

- local setup is scripted and documented
- the team has a fast, deterministic way to verify environment readiness

### Phase 6: Production runtime design

This phase chooses the actual deployment model.

Decisions and slices:

1. Choose the deploy target.
   - container platform
   - VM-based deployment
   - managed service mix
2. Choose the serving model for the API.
   - `uvicorn` directly
   - `gunicorn` with Uvicorn workers
   - another explicit ASGI strategy
3. Define separate deployables for:
   - API
   - Temporal workers
   - optional broker/outbox consumer processes
4. Define managed dependencies for:
   - Postgres
   - RabbitMQ
   - Temporal
   - Redis if retained
5. Define secret management strategy.

Recommended outputs:

- production topology document
- deployment manifests or infrastructure-as-code target list
- secret and configuration management approach

Exit criteria:

- there is one approved production topology, not multiple competing assumptions

### Phase 7: Production hardening and operations

This phase makes the chosen production design safe to operate.

Implementation slices:

1. Add logging, error monitoring, and metrics integration.
2. Add health endpoints and readiness checks for runtime components.
3. Add backup and recovery documentation for stateful services.
4. Add operational runbooks for provider and infrastructure failures.
5. Add staging validation for worker, broker, cache, and database behavior.

Recommended outputs:

- active Sentry and metrics wiring if those packages remain part of the stack
- deployment health checks
- runbooks for common incidents

Exit criteria:

- production dependencies are monitored and recoverable
- on-call and operational behavior is documented

## Recommended Order of Implementation

The safest implementation order is:

1. Phase 0 decision lock
2. Phase 1 local infrastructure completion
3. Phase 2 runtime process boundaries
4. Phase 3 provider strategy resolution
5. Phase 4 real infrastructure integrations
6. Phase 5 developer ergonomics and verification
7. Phase 6 production runtime design
8. Phase 7 production hardening and operations

This order is intentional:

- local orchestration must exist before worker and service verification are meaningful
- worker startup must exist before Temporal can be treated as real
- provider rules must be clear before developer setup can be called complete
- production design should not be finalized while the runtime dependency picture is still moving

## Milestones

### Milestone A: Full local infrastructure readiness

Includes:

- Phases 0 and 1 complete

Success signal:

- all required local infrastructure services can start with one documented flow

### Milestone B: Full local runtime readiness

Includes:

- Phase 2 complete

Success signal:

- API and worker both run locally against the official local stack

### Milestone C: Full dev readiness

Includes:

- Phases 3 through 5 complete

Success signal:

- developers can build, run, test, and integration-verify the intended backend system

### Milestone D: Production design approved

Includes:

- Phase 6 complete

Success signal:

- the team has one approved deployment and secret-management model

### Milestone E: Production readiness

Includes:

- Phase 7 complete

Success signal:

- runtime dependencies are provisioned, observable, and operationally supported

## Risks and Watchouts

### 1. Provider inconsistency

If email provider decisions stay split across docs and code, implementation will drift.

### 2. False readiness

Starting only Postgres and the API is not enough to call the system dev-ready because
the intended architecture includes broker and workflow runtime dependencies.

### 3. Redis ambiguity

Keeping Redis configured without deciding whether it is mandatory creates repeated
environment confusion in both dev and prod.

### 4. Premature production work

Infrastructure-as-code or deployment work should not start until the local runtime
shape is stable enough to know what actually needs to be deployed.

## Recommended Immediate Next Slice

Start with **Phase 0 and Phase 1 together** as the next implementation slice.

That slice should:

1. lock the Redis and email-provider decisions
2. expand the official local stack to include every required service
3. align `.env.example` and local docs with that stack

This is the highest-leverage next step because every later worker, integration, and
deployment task depends on a stable local dependency baseline.
