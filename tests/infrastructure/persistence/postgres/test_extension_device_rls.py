from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import (
    clear_postgres_rls_context,
    enable_postgres_service_access,
    set_postgres_workspace_context,
)
from app.infrastructure.persistence.postgres.models import (
    ExtensionDeviceModel,
    UserModel,
    WorkspaceModel,
)

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
USER_ID = UUID("30000000-0000-0000-0000-000000000003")
DEVICE_ID = UUID("40000000-0000-0000-0000-000000000004")


@pytest.mark.asyncio
async def test_extension_device_rls_isolates_workspace_and_allows_service_access(
    postgres_session: AsyncSession,
) -> None:
    await _seed_device(postgres_session)
    await _enable_rls_role(postgres_session)

    await clear_postgres_rls_context(postgres_session)
    hidden = await _device_count(postgres_session)

    await set_postgres_workspace_context(postgres_session, str(WORKSPACE_ID))
    visible = await _device_count(postgres_session)

    await set_postgres_workspace_context(postgres_session, str(OTHER_WORKSPACE_ID))
    cross_workspace = await _device_count(postgres_session)

    await enable_postgres_service_access(postgres_session)
    service_visible = await _device_count(postgres_session)

    assert (hidden, visible, cross_workspace, service_visible) == (0, 1, 0, 1)


async def _device_count(session: AsyncSession) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(ExtensionDeviceModel)
        .where(ExtensionDeviceModel.workspace_id == WORKSPACE_ID)
    )
    return int(value or 0)


async def _enable_rls_role(session: AsyncSession) -> None:
    await session.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls_tester') THEN
                    CREATE ROLE app_rls_tester;
                END IF;
            END
            $$;
            """
        )
    )
    await session.execute(text("GRANT USAGE ON SCHEMA public TO app_rls_tester"))
    await session.execute(text("GRANT SELECT ON extension_devices TO app_rls_tester"))
    await session.execute(text("SET LOCAL ROLE app_rls_tester"))


async def _seed_device(session: AsyncSession) -> None:
    session.add_all(
        [
            WorkspaceModel(
                workspace_id=WORKSPACE_ID,
                name="Extension RLS Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            WorkspaceModel(
                workspace_id=OTHER_WORKSPACE_ID,
                name="Other Extension Workspace",
                status="active",
                default_timezone="UTC",
                created_at=NOW,
                updated_at=NOW,
            ),
            UserModel(
                user_id=USER_ID,
                email="extension-rls@example.com",
                email_normalized="extension-rls@example.com",
                full_name="Extension User",
                status="active",
                email_verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            ),
        ]
    )
    await session.flush()
    session.add(
        ExtensionDeviceModel(
            device_id=DEVICE_ID,
            workspace_id=WORKSPACE_ID,
            user_id=USER_ID,
            device_name="RLS test browser",
            extension_version="0.2.0",
            credential_hash="a" * 64,
            created_at=NOW,
            last_seen_at=None,
            revoked_at=None,
            revoked_by_user_id=None,
            revocation_reason=None,
        )
    )
    await session.flush()