.PHONY: infra-up infra-down infra-logs infra-ps db-ui-up db-ui-down db-ui-logs run worker outbox-publisher temporal-signal-dispatcher outbound-send-dispatcher crm-sync-worker crm-sync-scheduler crm-webhook-retry-worker crm-sync-publisher crm-history-import-worker listing-crawl-worker listing-crawl-scheduler report-paused-search-messages start-all start-temporal start-workers stop-all tail-logs test lint format typecheck check migrate revision

infra-up:
	docker compose up -d --build

infra-down:
	docker compose down

infra-logs:
	docker compose logs -f api outbound-send-dispatcher prometheus grafana

infra-ps:
	docker compose ps

db-ui-up:
	docker compose up -d postgres cloudbeaver

db-ui-down:
	docker compose stop cloudbeaver

db-ui-logs:
	docker compose logs -f cloudbeaver

run:
	uv run uvicorn app.main:app --reload

worker:
	uv run python -c "import asyncio; from app.interfaces.workers.temporal_worker import main; asyncio.run(main())"

outbox-publisher:
	uv run python -c "import asyncio; from app.interfaces.workers.outbox_publisher_worker import main; asyncio.run(main())"

temporal-signal-dispatcher:
	uv run python -c "import asyncio; from app.interfaces.workers.temporal_signal_dispatcher_worker import main; asyncio.run(main())"

outbound-send-dispatcher:
	uv run python -c "import asyncio; from app.interfaces.workers.outbound_send_dispatch_worker import main; asyncio.run(main())"

crm-sync-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_sync_worker import main; asyncio.run(main())"

crm-sync-scheduler:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_sync_scheduler_worker import main; asyncio.run(main())"

crm-webhook-retry-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_webhook_retry_worker import main; asyncio.run(main())"

crm-sync-publisher: outbox-publisher

crm-history-import-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.crm_history_import_worker import main; asyncio.run(main())"

listing-crawl-worker:
	uv run python -c "import asyncio; from app.interfaces.workers.listing_source_crawl_worker import main; asyncio.run(main())"

listing-crawl-scheduler:
	uv run python -c "import asyncio; from app.interfaces.workers.listing_source_crawl_scheduler_worker import main; asyncio.run(main())"

test:
	uv run pytest

report-paused-search-messages:
	uv run python scripts/report_paused_search_messages.py $(ARGS)

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

start-all:
	uv run python scripts/start_workers.py --group all

start-temporal:
	uv run python scripts/start_workers.py --group temporal

start-workers:
	uv run python scripts/start_workers.py --group workers

stop-all:
	uv run python scripts/stop_workers.py

tail-logs:
	@mkdir -p logs
	@tail -f logs/*.log
