# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.core.database import enable_postgres_service_access
from app.domain.identity import Workspace, WorkspaceStatus
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresWorkspaceRepository,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create one workspace.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--timezone", default="UTC")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    name = args.name.strip()
    timezone = args.timezone.strip()
    if not name:
        raise SystemExit("--name must not be empty")
    if not timezone:
        raise SystemExit("--timezone must not be empty")

    now = datetime.now(UTC)
    workspace = Workspace(
        workspace_id=uuid4(),
        name=name,
        status=WorkspaceStatus.ACTIVE,
        default_timezone=timezone,
        created_at=now,
        updated_at=now,
    )
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            await PostgresWorkspaceRepository(session).save(workspace)
            await session.commit()
    finally:
        await engine.dispose()
    print(f"workspace_id={workspace.workspace_id}")
    print(f"name={workspace.name}")
    print(f"default_timezone={workspace.default_timezone}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
