"""add campaign version manual enrollment flag

Revision ID: 0020_add_campaign_version_manual_enrollment_flag
Revises: 0019_create_crm_conversation_events
Create Date: 2026-07-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_add_campaign_version_manual_enrollment_flag"
down_revision: str | None = "0019_create_crm_conversation_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaign_versions",
        sa.Column(
            "allow_assigned_agent_manual_enrollment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("campaign_versions", "allow_assigned_agent_manual_enrollment")