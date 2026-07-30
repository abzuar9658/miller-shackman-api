"""add paused search track step to workflows

Revision ID: 0051_add_paused_search_track_step_to_workflows
Revises: 0050_add_paused_search_track_pin_to_workflows
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0051_add_paused_search_track_step_to_workflows"
down_revision: str | None = "0050_add_paused_search_track_pin_to_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_workflows",
        sa.Column(
            "paused_search_track_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_steps.step_id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_workflows", "paused_search_track_step_id")
