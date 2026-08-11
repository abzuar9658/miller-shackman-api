"""Mint a fresh access token for an existing super-admin membership (dev-only diagnostic).

Does not touch passwords or credentials. Reads user/membership from Postgres and
signs a new JWT using the configured AUTH_JWT_SECRET, exactly like the real signin
flow would produce.

Usage:
    arch -arm64 uv run python scripts/_mint_token.py --email abuzar@gmail.com
"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.ports.auth import AccessTokenSubject
from app.core.config import get_settings
from app.core.database import enable_postgres_service_access
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
)
from app.infrastructure.providers import build_access_token_service


async def _run(email: str) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            user_repo = PostgresUserRepository(session)
            membership_repo = PostgresWorkspaceMembershipRepository(session)
            user = await user_repo.get_by_email_normalized(email)
            if user is None:
                raise SystemExit(f"user not found: {email}")
            memberships = await membership_repo.list_by_user_id(user.user_id)
            if not memberships:
                raise SystemExit(f"no memberships for user: {email}")
            membership = memberships[0]

            token_service = build_access_token_service(settings)
            now = datetime.now(UTC)
            issued = token_service.issue_token(
                AccessTokenSubject(
                    user_id=user.user_id,
                    workspace_id=membership.workspace_id,
                    membership_id=membership.membership_id,
                    role=membership.role,
                ),
                issued_at=now,
                expires_at=now + timedelta(minutes=60),
            )
            print(issued.token)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.email))


if __name__ == "__main__":
    main()
