"""add paused-search restart delay

Revision ID: 0084_add_paused_search_restart_delay
Revises: 0083_add_paused_search_agent_reminders
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0084_add_paused_search_restart_delay"
down_revision: str | None = "0083_add_paused_search_agent_reminders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_track_versions",
        sa.Column("restart_delay_days", sa.Integer(), nullable=False, server_default=sa.text("30")),
    )
    op.alter_column(
        "paused_search_track_versions",
        "restart_delay_days",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("paused_search_track_versions", "restart_delay_days")