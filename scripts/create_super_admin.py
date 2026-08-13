# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.services.authentication import normalize_email_address
from app.core.config import get_settings
from app.core.database import enable_postgres_service_access
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    PasswordCredential,
    User,
    UserStatus,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.infrastructure.auth.passwords import PasslibPasswordHasher
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresPasswordCredentialRepository,
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create one platform super-admin account.")
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    email = normalize_email_address(args.email)
    full_name = args.full_name.strip()
    if not full_name:
        raise SystemExit("--full-name must not be empty")
    password = getpass.getpass("Super-admin password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    now = datetime.now(UTC)
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await enable_postgres_service_access(session)
            workspace_repository = PostgresWorkspaceRepository(session)
            user_repository = PostgresUserRepository(session)
            membership_repository = PostgresWorkspaceMembershipRepository(session)
            credential_repository = PostgresPasswordCredentialRepository(session)
            audit_repository = PostgresAuthAuditLogRepository(session)

            if await workspace_repository.get_by_id(args.workspace_id) is None:
                raise SystemExit(f"Workspace not found: {args.workspace_id}")

            user = await user_repository.get_by_email_normalized(email)
            if user is None:
                user = User(
                    user_id=uuid4(),
                    email=email,
                    email_normalized=email,
                    full_name=full_name,
                    status=UserStatus.ACTIVE,
                    email_verified_at=now,
                    created_at=now,
                    updated_at=now,
                )
            else:
                user = User(
                    user_id=user.user_id,
                    email=user.email,
                    email_normalized=user.email_normalized,
                    full_name=full_name,
                    status=UserStatus.ACTIVE,
                    email_verified_at=user.email_verified_at or now,
                    created_at=user.created_at,
                    updated_at=now,
                )
            saved_user = await user_repository.save(user)

            membership = await membership_repository.get_by_user_and_workspace(
                saved_user.user_id,
                args.workspace_id,
            )
            await membership_repository.save(
                WorkspaceMembership(
                    membership_id=membership.membership_id if membership else uuid4(),
                    workspace_id=args.workspace_id,
                    user_id=saved_user.user_id,
                    role=WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN,
                    status=WorkspaceMembershipStatus.ACTIVE,
                    created_at=membership.created_at if membership else now,
                    updated_at=now,
                ),
            )

            existing_credential = await credential_repository.get_by_user_id(saved_user.user_id)
            await credential_repository.save(
                PasswordCredential(
                    user_id=saved_user.user_id,
                    password_hash=await PasslibPasswordHasher().hash_password(password),
                    password_changed_at=now,
                    failed_attempt_count=0,
                    locked_until=None,
                    created_at=existing_credential.created_at if existing_credential else now,
                    updated_at=now,
                ),
            )
            await audit_repository.append(
                AuthAuditLog(
                    audit_log_id=uuid4(),
                    event_type=AuthAuditEventType.USER_ENABLED,
                    created_at=now,
                    workspace_id=args.workspace_id,
                    subject_user_id=saved_user.user_id,
                    event_details={
                        "source": "create_super_admin.py",
                        "role": WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN.value,
                    },
                ),
            )
            await session.commit()
    finally:
        await engine.dispose()
    print(f"super_admin_user_id={saved_user.user_id}")
    print(f"workspace_id={args.workspace_id}")
    print(f"email={saved_user.email}")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
