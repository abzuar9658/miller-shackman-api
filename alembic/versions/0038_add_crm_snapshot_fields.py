"""add crm snapshot fields

Revision ID: 0038_add_crm_snapshot_fields
Revises: 0037_create_outbound_message_crm_completions
Create Date: 2026-07-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038_add_crm_snapshot_fields"
down_revision: str | None = "0037_create_outbound_message_crm_completions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_snapshot_summary_field", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_snapshot_status_field", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_snapshot_latest_inbound_field", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_snapshot_latest_outbound_field", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_snapshot_last_activity_at_field", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "handoff_completions",
        sa.Column("crm_snapshot_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inbound_message_crm_completions",
        sa.Column("crm_snapshot_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbound_message_crm_completions",
        sa.Column("crm_snapshot_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbound_message_crm_completions", "crm_snapshot_updated_at")
    op.drop_column("inbound_message_crm_completions", "crm_snapshot_updated_at")
    op.drop_column("handoff_completions", "crm_snapshot_updated_at")
    op.drop_column("workspace_handoff_configs", "crm_snapshot_last_activity_at_field")
    op.drop_column("workspace_handoff_configs", "crm_snapshot_latest_outbound_field")
    op.drop_column("workspace_handoff_configs", "crm_snapshot_latest_inbound_field")
    op.drop_column("workspace_handoff_configs", "crm_snapshot_status_field")
    op.drop_column("workspace_handoff_configs", "crm_snapshot_summary_field")