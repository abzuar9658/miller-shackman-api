"""create temporal signal outbox

Revision ID: 0036_create_temporal_signal_outbox
Revises: 0035_add_inbound_review_tag_fields
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036_create_temporal_signal_outbox"
down_revision: str | None = "0035_add_inbound_review_tag_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "temporal_signal_outbox",
        sa.Column("temporal_signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=False),
        sa.Column("signal_name", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["lead_workflows.workflow_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("temporal_signal_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_temporal_signal_outbox_workspace_idempotency",
        ),
    )
    op.create_index(
        "ix_temporal_signal_outbox_status_available",
        "temporal_signal_outbox",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_temporal_signal_outbox_workspace_status_created",
        "temporal_signal_outbox",
        ["workspace_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_temporal_signal_outbox_workspace_status_created",
        table_name="temporal_signal_outbox",
    )
    op.drop_index(
        "ix_temporal_signal_outbox_status_available",
        table_name="temporal_signal_outbox",
    )
    op.drop_table("temporal_signal_outbox")