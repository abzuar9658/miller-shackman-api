"""create crm sync tables

Revision ID: 0005_crm_sync_tables
Revises: 0004_user_management_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_crm_sync_tables"
down_revision: str | None = "0004_user_management_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_sync_jobs",
        sa.Column("sync_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crm_provider", sa.String(length=50), nullable=False),
        sa.Column("sync_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_seen", sa.Integer(), nullable=False),
        sa.Column("total_upserted", sa.Integer(), nullable=False),
        sa.Column("total_failed", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("sync_job_id"),
    )
    op.create_index(
        "ix_crm_sync_jobs_workspace_provider_created",
        "crm_sync_jobs",
        ["workspace_id", "crm_provider", "created_at"],
    )
    op.create_index(
        "ix_crm_sync_jobs_workspace_status_created",
        "crm_sync_jobs",
        ["workspace_id", "status", "created_at"],
    )

    op.create_table(
        "external_events",
        sa.Column("external_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("crm_lead_id", sa.String(length=255), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("payload_redacted", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("external_event_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "provider_event_id",
            name="uq_external_events_workspace_provider_event",
        ),
    )
    op.create_index(
        "ix_external_events_workspace_provider_received",
        "external_events",
        ["workspace_id", "provider", "received_at"],
    )
    op.create_index(
        "ix_external_events_workspace_status_received",
        "external_events",
        ["workspace_id", "status", "received_at"],
    )
    op.create_index(
        "ix_external_events_workspace_lead_received",
        "external_events",
        ["workspace_id", "lead_id", "received_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_external_events_workspace_lead_received", table_name="external_events")
    op.drop_index("ix_external_events_workspace_status_received", table_name="external_events")
    op.drop_index("ix_external_events_workspace_provider_received", table_name="external_events")
    op.drop_table("external_events")

    op.drop_index("ix_crm_sync_jobs_workspace_status_created", table_name="crm_sync_jobs")
    op.drop_index("ix_crm_sync_jobs_workspace_provider_created", table_name="crm_sync_jobs")
    op.drop_table("crm_sync_jobs")
