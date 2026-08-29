"""widen cadence step message_goal to 1000 chars

Revision ID: 0095_widen_cadence_step_message_goal
Revises: 0094_lead_workflows_ai_interaction_count
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0095_widen_cadence_step_message_goal"
down_revision: str | None = "0094_lead_workflows_ai_interaction_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "campaign_cadence_steps",
        "message_goal",
        existing_type=sa.String(length=500),
        type_=sa.String(length=1000),
        existing_nullable=False,
    )
    op.alter_column(
        "paused_search_track_steps",
        "message_goal",
        existing_type=sa.String(length=500),
        type_=sa.String(length=1000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "paused_search_track_steps",
        "message_goal",
        existing_type=sa.String(length=1000),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
    op.alter_column(
        "campaign_cadence_steps",
        "message_goal",
        existing_type=sa.String(length=1000),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
