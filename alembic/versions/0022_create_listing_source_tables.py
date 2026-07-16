"""create listing source tables

Revision ID: 0022_create_listing_source_tables
Revises: 0021
Create Date: 2026-07-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_create_listing_source_tables"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
                CREATE EXTENSION IF NOT EXISTS vector;
            END IF;
        END $$;
        """
    )

    op.create_table(
        "listing_sources",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("allowed_url_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("disallowed_url_patterns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("crawl_frequency_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("requires_auth", sa.Boolean(), nullable=False),
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data_use_policy", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["terms_reviewed_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_listing_sources_workspace_name"),
    )
    op.create_index(
        "ix_listing_sources_workspace_enabled",
        "listing_sources",
        ["workspace_id", "enabled"],
        unique=False,
    )

    op.create_table(
        "listing_crawl_runs",
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("parsed_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["listing_sources.source_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("crawl_run_id"),
    )
    op.create_index(
        "ix_listing_crawl_runs_workspace_source_started",
        "listing_crawl_runs",
        ["workspace_id", "source_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_listing_crawl_runs_workspace_status_started",
        "listing_crawl_runs",
        ["workspace_id", "status", "started_at"],
        unique=False,
    )

    op.create_table(
        "listing_snapshots",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_listing_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("address_text", sa.String(length=500), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=50), nullable=True),
        sa.Column("neighborhood", sa.String(length=255), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("beds", sa.Numeric(6, 2), nullable=True),
        sa.Column("baths", sa.Numeric(6, 2), nullable=True),
        sa.Column("property_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_payload_hash", sa.String(length=128), nullable=False),
        sa.Column("source_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["listing_crawl_runs.crawl_run_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["listing_sources.source_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_id",
            "external_listing_id",
            "source_payload_hash",
            name="uq_listing_snapshots_workspace_source_external_payload",
        ),
    )
    op.create_index(
        "ix_listing_snapshots_workspace_source_external_current",
        "listing_snapshots",
        ["workspace_id", "source_id", "external_listing_id", "is_current"],
        unique=False,
    )
    op.create_index(
        "ix_listing_snapshots_workspace_source_status_current",
        "listing_snapshots",
        ["workspace_id", "source_id", "status", "is_current"],
        unique=False,
    )
    op.create_index(
        "ix_listing_snapshots_workspace_source_scraped",
        "listing_snapshots",
        ["workspace_id", "source_id", "scraped_at"],
        unique=False,
    )

    for table_name in ("listing_sources", "listing_crawl_runs", "listing_snapshots"):
        _enable_workspace_rls(table_name)


def downgrade() -> None:
    for table_name in reversed(("listing_sources", "listing_crawl_runs", "listing_snapshots")):
        _disable_workspace_rls(table_name)

    op.drop_index("ix_listing_snapshots_workspace_source_scraped", table_name="listing_snapshots")
    op.drop_index(
        "ix_listing_snapshots_workspace_source_status_current",
        table_name="listing_snapshots",
    )
    op.drop_index(
        "ix_listing_snapshots_workspace_source_external_current",
        table_name="listing_snapshots",
    )
    op.drop_table("listing_snapshots")
    op.drop_index(
        "ix_listing_crawl_runs_workspace_status_started",
        table_name="listing_crawl_runs",
    )
    op.drop_index(
        "ix_listing_crawl_runs_workspace_source_started",
        table_name="listing_crawl_runs",
    )
    op.drop_table("listing_crawl_runs")
    op.drop_index("ix_listing_sources_workspace_enabled", table_name="listing_sources")
    op.drop_table("listing_sources")


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