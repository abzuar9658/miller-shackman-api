"""add outbound crm conversation publish timestamp

Revision ID: 0046_add_outbound_crm_conversation_publish_timestamp
Revises: 0045_add_handoff_acknowledgment_prompt_text
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046_add_outbound_crm_conversation_publish_timestamp"
down_revision: str | None = "0045_add_handoff_acknowledgment_prompt_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_message_crm_completions",
        sa.Column("crm_conversation_published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbound_message_crm_completions", "crm_conversation_published_at")