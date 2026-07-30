"""add CRM sync window state and lead cap

Revision ID: 0055_add_crm_sync_window_state_and_lead_cap
Revises: 0054_add_rich_fields_to_crm_conversation_events
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0055_add_crm_sync_window_state_and_lead_cap"
down_revision: str | None = "0054_add_rich_fields_to_crm_conversation_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_crm_sync_configs",
        sa.Column("max_leads_per_sync_cycle", sa.Integer(), nullable=True),
    )

    op.create_table(
        "crm_sync_window_states",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("crm_provider", sa.String(length=50), nullable=False),
        sa.Column("sync_type", sa.String(length=50), nullable=False),
        sa.Column("updated_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_cursor", sa.Text(), nullable=False),
        sa.Column("sort_by", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "crm_provider"),
    )
    op.create_index(
        "ix_crm_sync_window_states_workspace_provider_updated",
        "crm_sync_window_states",
        ["workspace_id", "crm_provider", "updated_at"],
    )
    _enable_workspace_rls("crm_sync_window_states")


def downgrade() -> None:
    _disable_workspace_rls("crm_sync_window_states")
    op.drop_index(
        "ix_crm_sync_window_states_workspace_provider_updated",
        table_name="crm_sync_window_states",
    )
    op.drop_table("crm_sync_window_states")
    op.drop_column("workspace_crm_sync_configs", "max_leads_per_sync_cycle")


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
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def _policy_name(table_name: str) -> str:
    return f"{table_name}_workspace_isolation"