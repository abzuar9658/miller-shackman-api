"""add listing search scopes and crawl guard

Revision ID: 0031_add_listing_search_scopes_and_crawl_guard
Revises: 0030_add_workspace_contact_policy_quiet_hours_enabled
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031_add_listing_search_scopes_and_crawl_guard"
down_revision: str | None = "0030_add_workspace_contact_policy_quiet_hours_enabled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_source_search_scopes",
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("search_type", sa.String(length=20), nullable=False),
        sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_beds", sa.Numeric(6, 2), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["listing_sources.source_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("scope_id"),
    )
    op.create_index(
        "ix_listing_source_search_scopes_workspace_source_enabled",
        "listing_source_search_scopes",
        ["workspace_id", "source_id", "enabled"],
        unique=False,
    )
    op.create_index(
        "uq_listing_crawl_runs_one_active_source",
        "listing_crawl_runs",
        ["workspace_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    _enable_workspace_rls("listing_source_search_scopes")


def downgrade() -> None:
    _disable_workspace_rls("listing_source_search_scopes")
    op.drop_index("uq_listing_crawl_runs_one_active_source", table_name="listing_crawl_runs")
    op.drop_index(
        "ix_listing_source_search_scopes_workspace_source_enabled",
        table_name="listing_source_search_scopes",
    )
    op.drop_table("listing_source_search_scopes")


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