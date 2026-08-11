"""create durable outbound send reconciliation records

Revision ID: 0086_create_outbound_send_reconciliations
Revises: 0085_enforce_single_active_workflow_per_lead
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0086_create_outbound_send_reconciliations"
down_revision: str | None = "0085_enforce_single_active_workflow_per_lead"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_send_reconciliations",
        sa.Column("reconciliation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=255), nullable=False),
        sa.Column("outbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("provider_delivery_status", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbound_messages.message_id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.PrimaryKeyConstraint("reconciliation_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_outbound_reconciliations_workspace_idempotency",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "outbound_message_id",
            name="uq_outbound_reconciliations_workspace_message",
        ),
    )
    op.create_index(
        "ix_outbound_reconciliations_workspace_status",
        "outbound_send_reconciliations",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_reconciliations_workspace_status",
        table_name="outbound_send_reconciliations",
    )
    op.drop_table("outbound_send_reconciliations")