"""create campaign tables

Revision ID: 0006_campaign_tables
Revises: 0005_crm_sync_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_campaign_tables"
down_revision: str | None = "0005_crm_sync_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("campaign_id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_campaigns_workspace_name"),
    )
    op.create_index("ix_campaigns_workspace_status", "campaigns", ["workspace_id", "status"])

    op.create_table(
        "campaign_versions",
        sa.Column("campaign_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("enabled_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("daily_start_cap", sa.Integer(), nullable=False),
        sa.Column("dormant_threshold_days", sa.Integer(), nullable=False),
        sa.Column("quiet_hours_start", sa.Time(), nullable=False),
        sa.Column("quiet_hours_end", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("sms_compliance_required", sa.Boolean(), nullable=False),
        sa.Column("preflight_digest_enabled", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("approved_model", sa.String(length=100), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("campaign_version_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "version_number",
            name="uq_campaign_versions_workspace_campaign_version",
        ),
    )
    op.create_index(
        "ix_campaign_versions_workspace_campaign_status",
        "campaign_versions",
        ["workspace_id", "campaign_id", "status"],
    )
    op.create_foreign_key(
        "fk_campaigns_active_version",
        "campaigns",
        "campaign_versions",
        ["active_version_id"],
        ["campaign_version_id"],
    )

    op.create_table(
        "campaign_cadence_steps",
        sa.Column("cadence_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("delay_hours", sa.Integer(), nullable=False),
        sa.Column("message_goal", sa.String(length=500), nullable=False),
        sa.Column("template_key", sa.String(length=255), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_version_id"], ["campaign_versions.campaign_version_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("cadence_step_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "campaign_version_id",
            "step_order",
            name="uq_cadence_steps_workspace_version_order",
        ),
    )


def downgrade() -> None:
    op.drop_table("campaign_cadence_steps")
    op.drop_constraint("fk_campaigns_active_version", "campaigns", type_="foreignkey")
    op.drop_index(
        "ix_campaign_versions_workspace_campaign_status",
        table_name="campaign_versions",
    )
    op.drop_table("campaign_versions")
    op.drop_index("ix_campaigns_workspace_status", table_name="campaigns")
    op.drop_table("campaigns")
