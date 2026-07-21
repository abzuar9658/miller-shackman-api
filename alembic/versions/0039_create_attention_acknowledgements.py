"""create attention acknowledgements

Revision ID: 0039_create_attention_acknowledgements
Revises: 0038_add_crm_snapshot_fields
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0039_create_attention_acknowledgements"
down_revision: str | None = "0038_add_crm_snapshot_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attention_acknowledgements",
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
        sa.Column("attention_item_id", sa.String(length=255), nullable=False),
        sa.Column("attention_item_version", sa.String(length=500), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "user_id",
            "attention_item_id",
            name="pk_attention_acknowledgements",
        ),
    )
    op.create_index(
        "ix_attention_acknowledgements_workspace_user_acknowledged",
        "attention_acknowledgements",
        ["workspace_id", "user_id", "acknowledged_at"],
    )
    _enable_workspace_rls("attention_acknowledgements")


def downgrade() -> None:
    _disable_workspace_rls("attention_acknowledgements")
    op.drop_index(
        "ix_attention_acknowledgements_workspace_user_acknowledged",
        table_name="attention_acknowledgements",
    )
    op.drop_table("attention_acknowledgements")


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
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
    policy_name = _policy_name(table_name)
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def _policy_name(table_name: str) -> str:
    return f"rls_{table_name}_workspace_isolation"