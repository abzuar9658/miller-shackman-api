"""create crm agent mapping tables

Revision ID: 0040_create_crm_agent_mapping_tables
Revises: 0039_create_attention_acknowledgements
Create Date: 2026-07-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0040_create_crm_agent_mapping_tables"
down_revision: str | None = "0039_create_attention_acknowledgements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = ("crm_agents", "workspace_agent_crm_mappings", "workspace_agent_mapping_configs")


def upgrade() -> None:
    op.create_table(
        "crm_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crm_provider", sa.String(length=50), nullable=False),
        sa.Column("crm_agent_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_crm_agents_workspace_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "crm_provider",
            "crm_agent_id",
            name="uq_crm_agents_workspace_provider_agent",
        ),
    )
    op.create_index("ix_crm_agents_workspace_active", "crm_agents", ["workspace_id", "is_active"])
    op.create_index(
        "ix_crm_agents_workspace_email",
        "crm_agents",
        ["workspace_id", "email_normalized"],
    )
    op.create_table(
        "workspace_agent_crm_mappings",
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crm_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("app_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mapping_status", sa.String(length=50), nullable=False),
        sa.Column("resolution_source", sa.String(length=100), nullable=False),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(
            ["workspace_id", "crm_agent_id"],
            ["crm_agents.workspace_id", "crm_agents.id"],
        ),
        sa.ForeignKeyConstraint(["app_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("mapping_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "crm_agent_id",
            name="uq_workspace_agent_crm_mappings_workspace_crm_agent",
        ),
    )
    op.create_index(
        "ix_workspace_agent_crm_mappings_workspace_status",
        "workspace_agent_crm_mappings",
        ["workspace_id", "mapping_status"],
    )
    op.create_index(
        "uq_workspace_agent_crm_mappings_active_app_user",
        "workspace_agent_crm_mappings",
        ["workspace_id", "app_user_id"],
        unique=True,
        postgresql_where=sa.text(
            "app_user_id IS NOT NULL AND mapping_status IN ('verified', 'overridden')"
        ),
    )
    op.create_table(
        "workspace_agent_mapping_configs",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "unmapped_assignment_fallback_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["unmapped_assignment_fallback_user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    for table_name in _TABLES:
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(_TABLES):
        _disable_workspace_rls(table_name)
    op.drop_table("workspace_agent_mapping_configs")
    op.drop_index(
        "uq_workspace_agent_crm_mappings_active_app_user",
        table_name="workspace_agent_crm_mappings",
    )
    op.drop_index(
        "ix_workspace_agent_crm_mappings_workspace_status",
        table_name="workspace_agent_crm_mappings",
    )
    op.drop_table("workspace_agent_crm_mappings")
    op.drop_index("ix_crm_agents_workspace_email", table_name="crm_agents")
    op.drop_index("ix_crm_agents_workspace_active", table_name="crm_agents")
    op.drop_table("crm_agents")


def _enable_workspace_rls(table_name: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" USING ('
        "app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id()"
        ") WITH CHECK ("
        "app_rls_service_access_enabled() OR workspace_id = app_current_workspace_id())"
    )


def _disable_workspace_rls(table_name: str) -> None:
    policy_name = _policy_name(table_name)
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')


def _policy_name(table_name: str) -> str:
    return f"rls_{table_name}_workspace_isolation"
