"""add dormant step template profiles

Revision ID: 0080_add_dormant_step_template_profiles
Revises: 0079_add_campaign_version_drafting_config
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0080_add_dormant_step_template_profiles"
down_revision: str | None = "0079_add_campaign_version_drafting_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_cadence_steps",
        sa.Column(
            "template_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("campaign_cadence_steps", "template_profile")