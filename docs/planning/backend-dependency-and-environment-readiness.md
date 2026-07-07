# Backend Dependency and Environment Readiness

## Purpose

This document defines the complete backend dependency picture for local development
and production for the Miller Schackman API. It is the source of truth for what
must exist before the backend can be called dev-ready or prod-ready.

It covers:

- local developer tooling
- Python runtime and package dependencies
- local and managed infrastructure services
- external provider accounts and credentials
- observability and operational dependencies
- current gaps between the intended architecture and the present repository state

## Scope

This document is about backend dependencies and environment readiness only. It does
not define the implementation plan to close the gaps. Planning and sequencing come
after this document is approved.

## Current Backend State

The repository currently provides:

- FastAPI application scaffold
- PostgreSQL models and Alembic migrations
- provider adapters for Follow Up Boss, OpenRouter, Twilio, SendGrid, S3, and Redis
- `compose.yaml` with Postgres and RabbitMQ only
- environment examples for Postgres, RabbitMQ, Temporal, Redis, CRM, LLM, SMS,
  email, and S3

The repository does not yet provide a complete runnable system for the full V1
architecture because:

- Temporal worker startup is still a stub
- Redis is configured but not provisioned in local compose
- Temporal is configured but not provisioned in local compose
- RabbitMQ is declared in config and compose, but no concrete event-bus or outbox
  integration is implemented in the application code yet
- production deployment manifests and runtime infrastructure definitions are absent
- auth and operational email planning currently reference Google email integration,
  while the implemented general email adapter is SendGrid

## Dependency Categories

### 1. Local developer tooling

These are tools needed on a developer machine to build, run, debug, and verify the
backend.

| Dependency                            | Purpose                                   | Dev Required         | Prod Required       |
| ------------------------------------- | ----------------------------------------- | -------------------- | ------------------- |
| Python 3.12                           | Backend runtime                           | Yes                  | Yes                 |
| `uv`                                  | Dependency and command runner             | Yes                  | Build-time only     |
| Docker                                | Local infrastructure and container builds | Strongly recommended | No                  |
| Docker Compose                        | Local multi-service startup               | Strongly recommended | No                  |
| `make`                                | Convenience commands                      | Recommended          | No                  |
| `psql`                                | DB inspection and migration debugging     | Recommended          | Recommended for ops |
| `redis-cli`                           | Cache inspection and debugging            | Recommended          | Recommended for ops |
| `rabbitmqctl` or management UI access | Broker inspection                         | Recommended          | Recommended for ops |
| `temporal` CLI                        | Workflow inspection and debugging         | Recommended          | Recommended for ops |

### 2. Python runtime and package dependencies

These are declared in `pyproject.toml` and are part of the backend runtime or dev
toolchain.

#### Runtime packages currently declared

- FastAPI
- SQLAlchemy async ORM
- Alembic
- asyncpg
- psycopg
- aio-pika
- redis
- temporalio
- httpx
- openai SDK for OpenRouter access
- twilio
- sendgrid
- boto3
- structlog
- sentry-sdk
- prometheus-client
- email-validator
- phonenumbers
- python-jose
- passlib with bcrypt
- python-multipart
- gunicorn
- uvicorn
- tenacity

#### Dev-only packages currently declared

- pytest
- pytest-asyncio
- pytest-cov
- mypy
- ruff
- faker
- respx
- time-machine

### 3. Local and managed infrastructure services

These are external processes or managed services the backend depends on beyond the
Python process itself.

| Service                           | Purpose                                                        | Dev Required                                                                                       | Prod Required                             | Current Repo State                                               |
| --------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------- |
| PostgreSQL                        | Source of truth for app data, audit data, migrations           | Yes                                                                                                | Yes                                       | Implemented and provisioned in compose                           |
| RabbitMQ                          | Async fan-out and outbox consumer target                       | Required for full system; optional only for limited scaffold work                                  | Yes                                       | Provisioned in compose, not yet wired in app code                |
| Temporal server                   | Durable workflows, timers, pause/resume, handoff orchestration | Required for full system; optional only for limited scaffold work                                  | Yes                                       | Configured only, not provisioned locally, worker not implemented |
| Redis                             | Cache and future coordination support                          | Required for full target readiness; optional for limited scaffold work if unused paths are avoided | Yes if retained as default cache provider | Configured and adapter exists, not provisioned in compose        |
| Object storage compatible with S3 | Attachments, exports, or durable file storage                  | Not required for every dev task, but required when storage features are exercised                  | Yes if storage remains S3-backed          | Adapter exists, no local provisioning                            |

### 4. External provider dependencies

These are vendor accounts, credentials, or remote APIs the backend expects for full
V1 behavior.

| Provider       | Purpose                                             | Dev Requirement                                                                                         | Prod Requirement                                      | Current State                                              |
| -------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------- |
| Follow Up Boss | CRM read/write, tags, notes, ownership, activity    | Required for live integration testing; otherwise use fakes or a dedicated non-prod CRM account          | Yes                                                   | Adapter implemented; webhook subscription not implemented  |
| OpenRouter     | LLM drafting, classification, extraction, summaries | Required for live AI testing; otherwise use fake LLMs in unit tests                                     | Yes                                                   | Adapter implemented                                        |
| Twilio         | SMS delivery                                        | Required only when exercising real SMS send paths; use Twilio test credentials or a non-prod sender     | Yes for production SMS                                | Adapter implemented; broader compliance flow not yet wired |
| SendGrid       | Email delivery                                      | Required only when exercising real email send paths; use dedicated non-prod API key and sender identity | Yes for production email if SendGrid remains provider | Adapter implemented                                        |
| AWS S3         | File/object storage                                 | Required only when exercising file storage behavior                                                     | Yes if S3 remains provider                            | Adapter implemented                                        |

## Environment Variables and Secrets

The backend currently expects these environment categories.

### Core runtime configuration

- `APP_NAME`
- `APP_VERSION`
- `ENVIRONMENT`
- `DEBUG`
- `LOG_LEVEL`
- `API_V1_PREFIX`
- `ALLOWED_ORIGINS`

### Database

- `DATABASE_URL`
- `DATABASE_MIGRATION_URL`

### Message broker and workflows

- `RABBITMQ_URL`
- `TEMPORAL_ADDRESS`

### CRM

- `CRM_PROVIDER`
- `FUB_API_KEY`
- `FUB_BASE_URL`

### LLM

- `LLM_PROVIDER`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`

### SMS

- `SMS_PROVIDER`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_PHONE`

### Email

- `EMAIL_PROVIDER`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`

### Storage

- `STORAGE_PROVIDER`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `S3_BUCKET`
- `S3_REGION`

### Cache

- `CACHE_PROVIDER`
- `REDIS_URL`

### Authentication and authorization

Authentication is implemented with bearer JWT access tokens and opaque refresh tokens.
The following environment variables and runtime settings are required for auth flows.

#### Required secrets

- `AUTH_JWT_SECRET` — secret used to sign and verify access tokens. Must be strong,
  random, and unique per environment. Required for any API that validates access tokens.

#### Required configuration

- `AUTH_JWT_ALGORITHM` — algorithm used for JWT signing. Defaults to `HS256`.
- `AUTH_ACCESS_TOKEN_TTL_MINUTES` — access token lifetime. Defaults to `15`.
- `AUTH_REFRESH_TOKEN_TTL_DAYS` — refresh token lifetime. Defaults to `30`.
- `AUTH_INVITATION_TOKEN_TTL_DAYS` — invitation token lifetime. Defaults to `7`.
- `AUTH_PASSWORD_RESET_TOKEN_TTL_MINUTES` — password reset token lifetime. Defaults to `30`.
- `AUTH_SIGNIN_LOCKOUT_MAX_ATTEMPTS` — failed sign-in attempts before lockout. Defaults to `5`.
- `AUTH_SIGNIN_LOCKOUT_WINDOW_MINUTES` — lockout duration after max failed attempts. Defaults to `15`.

#### Password hashing

- Passwords are hashed using `passlib`.
- Primary scheme is Argon2 when available.
- Fallback scheme is bcrypt for environments where Argon2 is not available.
- Both are declared as part of the `passlib[bcrypt]` dependency.

#### Auth email delivery

- User invitations and password reset emails require a working email provider.
- The default provider is SendGrid, configured via `EMAIL_PROVIDER`, `SENDGRID_API_KEY`, and `SENDGRID_FROM_EMAIL`.
- In development, a fake or test email provider is acceptable; real customer email addresses must not be used in local development.

#### Auth package dependencies

- `python-jose` — JWT signing and verification.
- `passlib[bcrypt]` — password hashing with Argon2 and bcrypt fallback.
- `email-validator` — email normalization and validation for invitations and sign-in.
- `python-multipart` — parsing form data if used by auth routes.

## Development Dependency Requirements

### Minimum dev-ready baseline

The backend is minimally dev-ready only when all of the following exist:

1. Python 3.12 and `uv` are installed.
2. A local `.env` is created from `.env.example` with valid local values.
3. PostgreSQL is reachable and migrations can run successfully.
4. The API boots locally.
5. Unit tests, lint, and typecheck run locally.

This minimum baseline supports scaffold development, domain/application work, and
limited API work. It does not represent a full-system environment.

### Full-system dev-ready baseline

The backend is fully dev-ready only when all of the following exist:

1. PostgreSQL is available.
2. RabbitMQ is available.
3. Temporal server is available.
4. Redis is available.
5. A working Temporal worker process exists and can start.
6. Local startup orchestration exists for all required services.
7. A local `.env` or equivalent secret mechanism exists for all enabled providers.
8. Developers have a clear fake-or-real strategy for CRM, LLM, SMS, email, and S3.

### Dev expectations by dependency

#### PostgreSQL

- required in all realistic dev setups
- must support both async app access and Alembic migration access
- a local Docker container is acceptable

#### RabbitMQ

- required for full event-driven development
- not enough to list it in config; a local broker must be runnable and reachable
- management UI access is highly desirable for debugging

#### Temporal

- required for any workflow development beyond pure domain logic
- local Temporal server or dev stack must be runnable
- worker registration and startup must exist before calling the system workflow-ready

#### Redis

- required if cache-backed code paths are enabled in local development
- optional only if the backend deliberately avoids using cache-dependent paths
- for full-system readiness, Redis should be part of local startup

#### Follow Up Boss for dev

- unit tests should use fakes
- integration testing needs a dedicated non-production Follow Up Boss account,
  workspace, or sandbox-like environment
- never use live customer data in local development

#### OpenRouter for dev

- unit tests should use fake LLM clients
- integration testing needs a non-production API key with usage controls
- prompt-version and model configuration should be explicit in dev as in prod

#### Twilio for dev

- not every developer needs live SMS sending for routine work
- any real send-path testing needs dedicated dev credentials and a safe sender
- use Twilio test credentials or a tightly controlled non-production messaging setup
- dev must never risk sending real unsolicited customer SMS

#### SendGrid for dev

- not every developer needs live email delivery for routine work
- any real send-path testing needs a dedicated dev API key and verified sender
- use non-production recipient lists and safe sandbox/test practices where possible

#### S3 for dev

- only required when exercising storage features
- acceptable options include a dedicated non-production bucket or an S3-compatible
  local substitute if later adopted

## Production Dependency Requirements

The backend is prod-ready only when all required runtime, operational, and provider
dependencies are present and validated.

### Core production services

#### PostgreSQL

- required
- must be managed, backed up, monitored, and migration-safe
- must support tenant isolation, audit data, and production retention policies

#### RabbitMQ

- required for the intended V1 architecture
- must be durable, monitored, and configured for retry and dead-letter handling as
  the implementation matures

#### Temporal

- required for the intended V1 architecture
- must be deployed as a real workflow backend, not only referenced by config
- production workers must be separately runnable and observable

#### Redis

- required if retained as the default cache provider in production configuration
- must be deployed intentionally rather than implied by package presence

#### Container runtime and process model

- a production container image exists, but deployment definitions do not
- the repository currently runs `uvicorn` directly in Docker while also declaring
  `gunicorn` as a dependency
- prod readiness requires an explicit, chosen ASGI serving strategy and deployment
  topology for API and workers

### Production provider requirements

#### Follow Up Boss

- production API credentials
- webhook and integration strategy aligned with the final CRM event model
- operational playbook for CRM outages, throttling, and retries

#### OpenRouter

- production API credentials
- approved production model configuration
- cost controls, rate-limit handling, and metadata capture

#### Twilio

- production account and sender configuration
- approved A2P 10DLC state for any production SMS sending
- webhook and delivery callback handling once implemented

#### SendGrid

- production API credentials
- verified sender/domain setup
- unsubscribe and deliverability strategy once full outbound email behavior matures

#### S3

- production bucket
- IAM policy and credential strategy
- retention, access control, and object lifecycle policies

### Observability and operations

For production readiness, the backend also needs explicit operational dependencies.

- centralized logs
- error monitoring
- metrics collection
- health checks for API, workers, database, broker, and workflow runtime
- backup and recovery procedures for stateful services

The codebase currently declares `sentry-sdk` and `prometheus-client`, but no active
backend integration or configuration was found. Those dependencies should therefore
be treated as planned or partial rather than production-ready.

## Current Dependency Gaps

### Gaps that block full dev readiness

1. No complete local startup stack for Postgres, RabbitMQ, Redis, and Temporal.
2. No implemented Temporal worker startup.
3. No documented fake-versus-real strategy for CRM, LLM, SMS, email, and storage.
4. No committed local setup that proves the full stack can be started together.

### Gaps that block prod readiness

1. No production deployment manifests or infrastructure-as-code.
2. No implemented Temporal workflow worker.
3. No implemented RabbitMQ event bus or transactional outbox integration.
4. Redis is configured but not proven as an intentional production dependency.
5. Observability packages are present but not wired into runtime configuration.
6. API serving strategy is unresolved because `gunicorn` is declared but unused.
7. Provider strategy is inconsistent for email: current auth planning references
   Google email integration, while implemented general outbound email uses SendGrid.

## Dependency Decisions That Must Be Explicit Before Calling the System Ready

The following cannot remain implicit:

1. Redis is included in the full local stack while `CACHE_PROVIDER=redis` remains
   the default.
2. The official local Temporal stack is Docker Compose with Temporal exposed at
   `localhost:7233`.
3. The official local Redis strategy is Docker Compose with Redis exposed at
   `localhost:6379`.
4. Twilio and SendGrid are required only for developers exercising live integration
   paths, and must use non-production credentials.
5. What is the final provider for auth and operational email: SendGrid, Google, or
   separate providers by use case?
6. What is the production deployment target and process model for API and workers?

## Definition of Done for Environment Readiness

### Dev-ready means

- every required local service can be started repeatably
- every required env var has a documented source and purpose
- API boot, migrations, lint, typecheck, and tests are documented and runnable
- developers know which providers are mocked, which are sandboxed, and which are
  optional for routine work
- the local stack supports the full intended backend architecture, not only the API
  scaffold

### Prod-ready means

- every required managed service exists and is monitored
- every required provider credential has an approved secret-management path
- API and worker processes can be deployed separately and safely
- workflow, broker, cache, database, and provider failure handling are operationally
  understood
- observability, backups, and recovery exist for stateful dependencies
- no critical dependency exists only in docs or package declarations; each one is
  implemented, provisioned, configured, and exercised

## Recommended Next Step

After this document is approved, create a gap-closure plan that sequences the work
to make the backend fully dev-ready first and then prod-ready, with explicit slices
for local infrastructure, worker/runtime implementation, provider strategy, and
deployment/operations.
