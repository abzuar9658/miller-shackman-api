# Miller Schackman API

Production-ready FastAPI backend scaffold for the AI-assisted real estate lead nurturing platform.

## Stack

- FastAPI
- Pydantic v2 settings
- SQLAlchemy 2 async ORM
- Alembic migrations
- PostgreSQL
- RabbitMQ via aio-pika
- Temporal Python SDK
- Ruff, mypy, pytest

## Local setup

1. Copy .env.example to .env.
2. Run uv sync.
3. Run uv run uvicorn app.main:app --reload.

## Checks

- make lint
- make typecheck
- make test
- make check

## Architecture

Business rules belong in app/domain and app/application.
Provider-specific code belongs in app/infrastructure.
FastAPI routes and workers belong in app/interfaces.
