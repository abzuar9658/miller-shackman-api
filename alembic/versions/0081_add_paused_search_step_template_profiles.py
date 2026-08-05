"""add paused search step template profiles

Revision ID: 0081_add_paused_search_step_template_profiles
Revises: 0080_add_dormant_step_template_profiles
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0081_add_paused_search_step_template_profiles"
down_revision: str | None = "0080_add_dormant_step_template_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_track_steps",
        sa.Column("template_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paused_search_track_steps", "template_profile")