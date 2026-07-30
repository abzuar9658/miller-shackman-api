"""add paused search track pin to workflows

Revision ID: 0050_add_paused_search_track_pin_to_workflows
Revises: 0049_create_paused_search_track_tables
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0050_add_paused_search_track_pin_to_workflows"
down_revision: str | None = "0049_create_paused_search_track_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_workflows",
        sa.Column(
            "paused_search_track_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("paused_search_track_versions.track_version_id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_workflows", "paused_search_track_version_id")