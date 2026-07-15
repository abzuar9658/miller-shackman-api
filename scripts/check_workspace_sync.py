"""Check latest CRM sync job status for a workspace."""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.infrastructure.persistence.postgres.models import CRMSyncJobModel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check latest CRM sync job for a workspace.")
    parser.add_argument("--workspace-id", required=True, type=UUID, help="Workspace UUID.")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        jobs = await session.execute(
            select(CRMSyncJobModel)
            .where(CRMSyncJobModel.workspace_id == args.workspace_id)
            .order_by(CRMSyncJobModel.created_at.desc())
            .limit(5)
        )
        jobs = jobs.scalars().all()
        print(f"Latest CRM sync jobs for workspace {args.workspace_id}: {len(jobs)}")
        for job in jobs:
            print(
                f"  - {job.sync_job_id} | type={job.sync_type} | status={job.status} | "
                f"seen={job.total_seen} | upserted={job.total_upserted} | "
                f"failed={job.total_failed} | created={job.created_at} | "
                f"finished={job.finished_at} | reason={job.failure_reason}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
