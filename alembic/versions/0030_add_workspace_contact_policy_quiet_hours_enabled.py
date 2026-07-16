"""add quiet hours enabled flag to workspace contact policies

Revision ID: 0030_add_workspace_contact_policy_quiet_hours_enabled
Revises: 0029_create_workspace_operational_controls_table
Create Date: 2026-07-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_add_workspace_contact_policy_quiet_hours_enabled"
down_revision: str | None = "0029_create_workspace_operational_controls_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_contact_policies",
        sa.Column(
            "quiet_hours_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "workspace_contact_policies",
        "quiet_hours_enabled",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("workspace_contact_policies", "quiet_hours_enabled")