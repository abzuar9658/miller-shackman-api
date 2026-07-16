"""create inbound message crm completions table

Revision ID: 0023_create_inbound_message_crm_completions
Revises: 0022
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_create_inbound_message_crm_completions"
down_revision: str | None = "0022_create_listing_source_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbound_message_crm_completions",
        sa.Column(
            "inbound_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inbound_messages.inbound_message_id"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("crm_note_idempotency_key", sa.String(length=500), nullable=False),
        sa.Column("crm_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_lead_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crm_latest_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "crm_updates_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("crm_note_written_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("inbound_message_id"),
    )
    op.create_index(
        "ix_inbound_message_crm_completions_workspace_completed",
        "inbound_message_crm_completions",
        ["workspace_id", "completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_message_crm_completions_workspace_completed",
        table_name="inbound_message_crm_completions",
    )
    op.drop_table("inbound_message_crm_completions")
