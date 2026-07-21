"""create outbound message crm completions table

Revision ID: 0037_create_outbound_message_crm_completions
Revises: 0036
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0037_create_outbound_message_crm_completions"
down_revision: str | None = "0036_create_temporal_signal_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbound_message_crm_completions",
        sa.Column(
            "outbound_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("outbound_messages.message_id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("crm_note_idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("crm_note_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("outbound_message_id"),
    )
    op.create_index(
        "ix_outbound_message_crm_completions_workspace_completed",
        "outbound_message_crm_completions",
        ["workspace_id", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbound_message_crm_completions_workspace_completed",
        table_name="outbound_message_crm_completions",
    )
    op.drop_table("outbound_message_crm_completions")