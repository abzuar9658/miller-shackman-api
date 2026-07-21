"""add inbound review tag fields

Revision ID: 0035_add_inbound_review_tag_fields
Revises: 0034_add_channel_prompt_texts_to_outbound_drafting
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0035_add_inbound_review_tag_fields"
down_revision: str | None = "0034_add_channel_prompt_texts_to_outbound_drafting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_handoff_configs",
        sa.Column("crm_review_tag", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "inbound_message_crm_completions",
        sa.Column("crm_review_tag_applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("inbound_message_crm_completions", "crm_review_tag_applied_at")
    op.drop_column("workspace_handoff_configs", "crm_review_tag")