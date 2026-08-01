"""add canonical customer timing candidates

Revision ID: 0061_add_customer_timing_candidates
Revises: 0060_add_occurrence_execution_state
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0061_add_customer_timing_candidates"
down_revision: str | None = "0060_add_occurrence_execution_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_timing_candidates",
        sa.Column("timing_id", sa.UUID(), primary_key=True),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("reason_code", sa.String(100)),
        sa.Column("customer_date", sa.DateTime(timezone=True)),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("evidence_type", sa.String(100), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by_user_id", sa.UUID()),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspace_id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.lead_id"]),
    )
    op.create_index(
        "ix_customer_timing_workspace_lead_created",
        "customer_timing_candidates",
        ["workspace_id", "lead_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_timing_workspace_lead_created",
        table_name="customer_timing_candidates",
    )
    op.drop_table("customer_timing_candidates")