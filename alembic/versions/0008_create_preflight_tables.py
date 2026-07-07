"""create preflight tables

Revision ID: 0008_preflight_tables
Revises: 0007_workflow_decision_tables
Create Date: 2026-07-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_preflight_tables"
down_revision: str | None = "0007_workflow_decision_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preflight_digests",
        sa.Column("digest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", sa.String(length=255), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("veto_window_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("digest_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "batch_id",
            "recipient_user_id",
            name="uq_preflight_digests_workspace_campaign_batch_recipient",
        ),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_preflight_digests_workspace_idempotency"
        ),
    )
    op.create_index(
        "ix_preflight_digests_workspace_status", "preflight_digests", ["workspace_id", "status"]
    )

    op.create_table(
        "preflight_vetoes",
        sa.Column("veto_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_id", sa.String(length=255), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.campaign_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("veto_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "campaign_id",
            "batch_id",
            "lead_id",
            "actor_user_id",
            name="uq_preflight_vetoes_workspace_campaign_batch_lead_actor",
        ),
        sa.UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_preflight_vetoes_workspace_idempotency"
        ),
    )
    op.create_index(
        "ix_preflight_vetoes_workspace_lead", "preflight_vetoes", ["workspace_id", "lead_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_preflight_vetoes_workspace_lead", table_name="preflight_vetoes")
    op.drop_table("preflight_vetoes")
    op.drop_index("ix_preflight_digests_workspace_status", table_name="preflight_digests")
    op.drop_table("preflight_digests")
