"""create campaign admin audit logs

Revision ID: 0015_campaign_admin_audit_logs
Revises: 0014_add_outbound_delivery_tracking_fields
Create Date: 2026-07-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_campaign_admin_audit_logs"
down_revision: str | None = "0014_add_outbound_delivery_tracking_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaign_admin_audit_logs",
        sa.Column("audit_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["campaign_version_id"], ["campaign_versions.campaign_version_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("audit_log_id"),
    )
    op.create_index(
        "ix_campaign_admin_audit_workspace_campaign",
        "campaign_admin_audit_logs",
        ["workspace_id", "campaign_id", "created_at"],
    )
    op.create_index(
        "ix_campaign_admin_audit_actor_created",
        "campaign_admin_audit_logs",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_campaign_admin_audit_workspace_action",
        "campaign_admin_audit_logs",
        ["workspace_id", "action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_admin_audit_workspace_action", table_name="campaign_admin_audit_logs"
    )
    op.drop_index("ix_campaign_admin_audit_actor_created", table_name="campaign_admin_audit_logs")
    op.drop_index(
        "ix_campaign_admin_audit_workspace_campaign", table_name="campaign_admin_audit_logs"
    )
    op.drop_table("campaign_admin_audit_logs")
