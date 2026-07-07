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

Local infrastructure includes:

- PostgreSQL on `localhost:55432`
- RabbitMQ on `localhost:55672`
- RabbitMQ management UI on `http://localhost:15673`
- Redis on `localhost:56379`
- Temporal on `localhost:57233`
- Temporal UI on `http://localhost:58080`

These host ports intentionally avoid the default ports commonly used by locally
installed PostgreSQL, Redis, and RabbitMQ services.

Provider credentials for Follow Up Boss, OpenRouter, Twilio, SendGrid, and S3 may
remain empty for routine local development. They are required only when exercising
the corresponding live integration paths.

The local infrastructure services can start before `.env` exists because Compose
marks the API env file as optional. The API itself should still be run with a local
`.env` copied from `.env.example`.

`make worker` now starts a real Temporal worker connected to the configured
`TEMPORAL_ADDRESS` and polling the configured `TEMPORAL_TASK_QUEUE`. The current
worker registers a minimal smoke workflow/activity so the workflow runtime can be
started and verified locally before business workflows are implemented.

## Local infrastructure commands

- `make infra-up`
- `make infra-down`
- `make infra-logs`
- `make infra-ps`

## Checks

- make lint
- make typecheck
- make test
- make check

## Architecture

Business rules belong in app/domain and app/application.
Provider-specific code belongs in app/infrastructure.
FastAPI routes and workers belong in app/interfaces.
