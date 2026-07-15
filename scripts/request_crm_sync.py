"""Enqueue a one-time CRM sync for a workspace.

Usage:
    uv run python scripts/request_crm_sync.py \
        --workspace-id 7f36d30d-2383-5312-9790-4efff9d74bc1

Use --full to force a full repull instead of the default incremental sync.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.use_cases.crm_sync import RequestCRMSyncStatus, request_crm_sync
from app.core.config import get_settings
from app.core.database import enable_postgres_service_access
from app.domain.crm_sync import CRMSyncLeadSort, CRMSyncType
from app.infrastructure.persistence.postgres.crm_sync_repository import (
    PostgresCRMSyncJobRepository,
)
from app.infrastructure.persistence.postgres.outbox_event_repository import (
    PostgresOutboxEventRepository,
    PostgresTransactionalEventBus,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enqueue a one-time CRM sync for a workspace.")
    parser.add_argument(
        "--workspace-id",
        required=True,
        type=UUID,
        help="UUID of the workspace whose CRM leads should be synced.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run a full sync instead of an incremental sync.",
    )
    parser.add_argument(
        "--max-leads",
        type=_positive_int,
        help="Limit a full sync to the most recent N leads.",
    )
    parser.add_argument(
        "--latest-by",
        choices=[sort.value for sort in CRMSyncLeadSort],
        help="Which field defines recency when using --max-leads.",
    )
    args = parser.parse_args()
    if args.max_leads is not None and not args.full:
        parser.error("--max-leads requires --full.")
    if args.latest_by is not None and args.max_leads is None:
        parser.error("--latest-by requires --max-leads.")
    return args


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        await enable_postgres_service_access(session)
        result = await request_crm_sync(
            workspace_id=args.workspace_id,
            sync_type=CRMSyncType.FULL if args.full else CRMSyncType.INCREMENTAL,
            max_leads=args.max_leads,
            latest_by=CRMSyncLeadSort(args.latest_by) if args.latest_by is not None else None,
            crm_sync_job_repository=PostgresCRMSyncJobRepository(session),
            event_bus=PostgresTransactionalEventBus(PostgresOutboxEventRepository(session)),
            now=datetime.now(UTC),
        )
        await session.commit()

    if result.status == RequestCRMSyncStatus.REQUESTED:
        print(f"Requested {result.job.sync_type.value} sync job {result.job.sync_job_id}")
        return 0

    print(f"Sync not requested: {result.status.value}")
    print(f"Existing/latest job: {result.job.sync_job_id}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
