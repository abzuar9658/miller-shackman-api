# Miller Schackman API

Production-ready FastAPI backend scaffold for the AI-assisted real estate lead nurturing platform.

## Stack

- FastAPI
- Pydantic v2 settings
- SQLAlchemy 2 async ORM
- Alembic migrations
- PostgreSQL
- RabbitMQ via aio-pika
- Redis cache provider
- Temporal Python SDK
- Ruff, mypy, pytest

## Local setup

1. Copy `.env.example` to `.env` before running the API locally.
2. Run `uv sync`.
3. Start local infrastructure with `make infra-up`.
4. If you already had a local `.env`, update its infrastructure URLs to match the current `.env.example` values.
5. Run migrations with `make migrate`.
6. Start the API with `make run`.
7. Start the Temporal worker in a separate terminal with `make worker`.

For outbox-driven features, start the shared outbox publisher in a separate terminal:

- `make outbox-publisher`

For listing-source crawls:

- `make listing-crawl-worker` for manual **Run now** requests and retry execution
- `make listing-crawl-scheduler` if you also want automatic scheduled due crawls

Manual listing-source crawls are not processed by the Temporal worker. They flow through the shared outbox publisher and RabbitMQ-backed listing crawl worker, so `make worker` alone is not enough.

For the CRM sync loop, start these in separate terminals as needed:

- `make crm-sync-scheduler`
- `make outbox-publisher` (or the backward-compatible alias `make crm-sync-publisher`)
- `make crm-sync-worker`

For local frontend development, the default API CORS configuration now allows these dev origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`
- `http://localhost:4173`
- `http://127.0.0.1:4173`

If you change the frontend dev origin, update `ALLOWED_ORIGINS` in `.env` accordingly.

Local infrastructure includes:

- PostgreSQL on `localhost:55432`
- CloudBeaver DB explorer on `http://localhost:58978`
- RabbitMQ on `localhost:55672`
- RabbitMQ management UI on `http://localhost:15673`
- Redis on `localhost:56379`
- Temporal on `localhost:57233`
- Temporal UI on `http://localhost:58080`
- Mailpit SMTP on `localhost:51025`
- Mailpit UI on `http://localhost:58025`

These host ports intentionally avoid the default ports commonly used by locally
installed PostgreSQL, Redis, and RabbitMQ services.

CloudBeaver is preconfigured on first boot with a shared connection to the app's
PostgreSQL database. It reads the DB host, name, user, and password from the
Compose environment, so you do not need to create the connection manually.

Use these `.env` values for CloudBeaver access and bootstrapping:

- `CLOUDBEAVER_SERVER_URL`
- `CLOUDBEAVER_ADMIN_NAME`
- `CLOUDBEAVER_ADMIN_PASSWORD`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

If you expose CloudBeaver anywhere beyond local development, change the default
admin password, keep anonymous access disabled, and place it behind private
networking, VPN, or SSO/reverse-proxy protection rather than a public open port.

Provider credentials for Follow Up Boss, OpenRouter, Twilio, SendGrid, and S3 may
remain empty for routine local development. They are required only when exercising
the corresponding live integration paths.

For local outbound email testing, the default `.env.example` uses `EMAIL_PROVIDER=mailpit`.
Mailpit accepts SMTP mail locally and exposes a browser inbox at `http://localhost:58025`.
If you prefer the old in-memory capture behavior, set `EMAIL_PROVIDER=sink` instead.

The default `.env.example` also enables `LISTING_CONTEXT_ENRICHMENT_ENABLED=true`.
When a lead has usable preferences and an approved StreetEasy source is available,
outbound drafting can reference a safe listing-relevance brief so follow-ups feel
more specific without naming exact properties or prices.

The local infrastructure services can start before `.env` exists because Compose
marks the API env file as optional. The API itself should still be run with a local
`.env` copied from `.env.example`.

`make worker` starts a real Temporal worker connected to the configured
`TEMPORAL_ADDRESS` and polling the configured `TEMPORAL_TASK_QUEUE`.

The worker currently registers:

- the smoke workflow/activity used for local Temporal verification
- the lead nurture workflow and its cadence/signal activities

That includes pause/resume signal handling used by the admin-facing lead resume flow.

## Current admin-facing API additions

The current backend includes admin-oriented workflow/reporting endpoints beyond the base read surfaces, including:

- campaign publish/pause/dormant-selector actions
- campaign reporting
- campaign audit logs
- lead resume eligibility
- lead resume action

Key routes:

- `GET /api/v1/workspaces/{workspace_id}/reporting/campaigns/{campaign_id}`
- `GET /api/v1/workspaces/{workspace_id}/reporting/campaigns/{campaign_id}/audit-logs`
- `GET /api/v1/workspaces/{workspace_id}/leads/{lead_id}/resume-eligibility`
- `POST /api/v1/workspaces/{workspace_id}/leads/{lead_id}/resume`

## Local infrastructure commands

- `make infra-up`
- `make infra-down`
- `make infra-logs`
- `make infra-ps`
- `make db-ui-up`
- `make db-ui-down`
- `make db-ui-logs`

## Checks

- make lint
- make typecheck
- make test
- make check

## Architecture

Business rules belong in app/domain and app/application.
Provider-specific code belongs in app/infrastructure.
FastAPI routes and workers belong in app/interfaces.
