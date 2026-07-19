.PHONY: infra-up infra-down infra-logs infra-ps run worker outbox-publisher crm-sync-worker crm-sync-scheduler crm-sync-publisher listing-crawl-worker listing-crawl-scheduler test lint format typecheck check migrate revision

infra-up:
	docker compose up -d postgres rabbitmq redis temporal temporal-ui mailpit

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f postgres rabbitmq redis temporal temporal-ui mailpit

infra-ps:
	docker compose ps

run:
	uv run uvicorn app.main:app --reload

worker:
	uv run python -c "import asyncio; from app.interfaces.workers.temporal_worker import main; asyncio.run(main())"

outbox-publisher:
	uv run python -c "import asyncio; from app.interfaces.workers.outbox_publisher_worker import main; asyncio.run(main())"

crm-sync-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_sync_worker import main; asyncio.run(main())"

crm-sync-scheduler:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_sync_scheduler_worker import main; asyncio.run(main())"

crm-sync-publisher: outbox-publisher

listing-crawl-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.listing_source_crawl_worker import main; asyncio.run(main())"

listing-crawl-scheduler:
	uv run python -c "import asyncio; from app.interfaces.workers.listing_source_crawl_scheduler_worker import main; asyncio.run(main())"

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app tests

check: lint typecheck test

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(message)"
