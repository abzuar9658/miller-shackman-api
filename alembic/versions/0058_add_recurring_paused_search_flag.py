"""add recurring paused-search rollout flag

Revision ID: 0058_add_recurring_paused_search_flag
Revises: 0057_add_lead_classification_llm_trace
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0058_add_recurring_paused_search_flag"
down_revision: str | None = "0057_add_lead_classification_llm_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_operational_controls",
        sa.Column(
            "recurring_paused_search_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("workspace_operational_controls", "recurring_paused_search_enabled")