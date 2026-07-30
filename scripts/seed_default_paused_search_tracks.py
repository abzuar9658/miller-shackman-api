"""Seed one default paused-search dashboard track per canonical pause reason."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from app.application.use_cases.seed_default_paused_search_tracks import (
        SeedDefaultPausedSearchTracksResult,
    )
    from app.domain.identity import AuthenticatedActor


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the seven default paused-search dashboard tracks for a workspace."
    )
    parser.add_argument("--workspace-id", required=True, type=UUID, help="Target workspace UUID.")
    parser.add_argument(
        "--actor-user-id",
        required=True,
        type=UUID,
        help="Active admin or manager user UUID used for audit attribution.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the seed plan without committing.",
    )
    parser.add_argument("--format", choices=("table", "json"), default="table")
    return parser.parse_args(argv)


async def _main() -> int:
    args = parse_args()

    # ruff: noqa: E402
    from app.application.use_cases.seed_default_paused_search_tracks import (
        seed_default_paused_search_tracks,
    )
    from app.core.config import get_settings
    from app.core.database import enable_postgres_service_access
    from app.infrastructure.persistence.postgres.outbox_event_repository import (
        PostgresOutboxEventRepository,
        PostgresTransactionalEventBus,
    )
    from app.infrastructure.persistence.postgres.paused_search_track_repository import (
        PostgresPausedSearchTrackAdminAuditLogRepository,
        PostgresPausedSearchTrackAdminRepository,
    )

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            actor = await _load_actor(
                workspace_id=args.workspace_id,
                user_id=args.actor_user_id,
                session=session,
            )
            result = await seed_default_paused_search_tracks(
                actor=actor,
                workspace_id=args.workspace_id,
                repository=PostgresPausedSearchTrackAdminRepository(session),
                audit_log_repository=PostgresPausedSearchTrackAdminAuditLogRepository(session),
                event_bus=(
                    None
                    if args.dry_run
                    else PostgresTransactionalEventBus(PostgresOutboxEventRepository(session))
                ),
                now=datetime.now(UTC),
            )

            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()

        _print_result(result, output_format=args.format, dry_run=args.dry_run)
        return 0
    finally:
        await engine.dispose()


async def _load_actor(
    *,
    workspace_id: UUID,
    user_id: UUID,
    session: AsyncSession,
) -> AuthenticatedActor:
    from app.domain.identity import AuthenticatedActor
    from app.infrastructure.persistence.postgres.identity_repository import (
        PostgresUserRepository,
        PostgresWorkspaceMembershipRepository,
        PostgresWorkspaceRepository,
    )

    user_repository = PostgresUserRepository(session)
    workspace_repository = PostgresWorkspaceRepository(session)
    membership_repository = PostgresWorkspaceMembershipRepository(session)

    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise SystemExit(f"User {user_id} not found.")
    membership = await membership_repository.get_by_user_and_workspace(user_id, workspace_id)
    if membership is None:
        raise SystemExit(f"User {user_id} is not a member of workspace {workspace_id}.")
    workspace = await workspace_repository.get_by_id(workspace_id)
    if workspace is None:
        raise SystemExit(f"Workspace {workspace_id} not found.")

    return AuthenticatedActor(
        user_id=user.user_id,
        user_status=user.status,
        active_role=membership.role,
        active_workspace_id=workspace.workspace_id,
        active_workspace_status=workspace.status,
        active_membership_id=membership.membership_id,
        active_membership_status=membership.status,
    )


def _print_result(
    result: SeedDefaultPausedSearchTracksResult,
    *,
    output_format: str,
    dry_run: bool,
) -> None:
    rows = [
        {
            "reason_code": item.reason_code.value,
            "display_name": item.display_name,
            "track_key": item.track_key,
            "status": item.status.value,
            "track_id": str(item.track_id) if item.track_id is not None else None,
            "track_version_id": (
                str(item.track_version_id) if item.track_version_id is not None else None
            ),
            "reasons": list(item.reasons),
            "detail": item.detail,
        }
        for item in result.items
    ]
    if output_format == "json":
        print(json.dumps({"dry_run": dry_run, "items": rows}, indent=2))
        return

    print(
        "Default paused-search track seed results"
        + (" (dry run):" if dry_run else ":")
    )
    for row in rows:
        print(
            f"- {row['reason_code']} | {row['status']} | {row['display_name']} | {row['track_key']}"
        )
        if row["detail"]:
            print(f"    detail: {row['detail']}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))