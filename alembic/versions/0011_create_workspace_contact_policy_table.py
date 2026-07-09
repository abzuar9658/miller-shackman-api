"""create workspace contact policy table

Revision ID: 0011_workspace_contact_policy_table
Revises: 0010_provider_outbox_tables
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_workspace_contact_policy_table"
down_revision: str | None = "0010_provider_outbox_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_contact_policies",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("sms_compliance_state", sa.String(length=50), nullable=False),
        sa.Column("quiet_hours_start", sa.Time(), nullable=False),
        sa.Column("quiet_hours_end", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_contact_policies")
