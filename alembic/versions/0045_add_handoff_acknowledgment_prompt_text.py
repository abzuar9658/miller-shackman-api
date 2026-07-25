"""add handoff acknowledgment prompt text

Revision ID: 0045_add_handoff_acknowledgment_prompt_text
Revises: 0044_add_handoff_lead_acknowledgment_config
Create Date: 2026-07-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0045_add_handoff_acknowledgment_prompt_text"
down_revision: str | None = "0044_add_handoff_lead_acknowledgment_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("lead_acknowledgment_prompt_text", sa.String(length=12000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_handoff_configs", "lead_acknowledgment_prompt_text")
