"""lead_workflows ai_interaction_count

Revision ID: 0094_lead_workflows_ai_interaction_count
Revises: 0093_add_outbound_message_status_detail
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0094_lead_workflows_ai_interaction_count"
down_revision: str | None = "0093_add_outbound_message_status_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_workflows",
        sa.Column(
            "ai_interaction_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_workflows", "ai_interaction_count")
