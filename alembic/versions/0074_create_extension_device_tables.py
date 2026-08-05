"""create extension pairing code and device tables

Revision ID: 0074_create_extension_device_tables
Revises: 0073_create_crm_history_import_tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0074_create_extension_device_tables"
down_revision: str | None = "0073_create_crm_history_import_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("extension_pairing_codes", "extension_devices")


def upgrade() -> None:
    op.create_table(
        "extension_pairing_codes",
        sa.Column("pairing_code_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "pairing_code_id",
            name="uq_extension_pairing_codes_workspace_code",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "token_hash",
            name="uq_extension_pairing_codes_workspace_token",
        ),
    )
    op.create_index(
        "ix_extension_pairing_codes_workspace_user_created",
        "extension_pairing_codes",
        ["workspace_id", "user_id", "created_at"],
    )

    op.create_table(
        "extension_devices",
        sa.Column("device_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("device_name", sa.String(100), nullable=False),
        sa.Column("extension_version", sa.String(32)),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "revoked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
        ),
        sa.Column("revocation_reason", sa.String(500)),
        sa.UniqueConstraint(
            "workspace_id", "device_id", name="uq_extension_devices_workspace_device"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "credential_hash",
            name="uq_extension_devices_workspace_credential",
        ),
    )
    op.create_index(
        "ix_extension_devices_workspace_user_revoked",
        "extension_devices",
        ["workspace_id", "user_id", "revoked_at"],
    )
    for table_name in _TABLES:
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        _disable_workspace_rls(table_name)
    op.drop_table("extension_devices")
    op.drop_table("extension_pairing_codes")


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'''
        CREATE POLICY "{policy_name}" ON "{table_name}"
        USING (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )
        WITH CHECK (
            app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()
        )
        '''
    )


def _disable_workspace_rls(table_name: str) -> None:
    policy_name = f"rls_{table_name}_workspace_isolation"
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')