"""add reply routing token to outbound messages

Revision ID: 0043_add_reply_routing_token_to_outbound_messages
Revises: 0042_allow_multiple_crm_agents_per_app_user
Create Date: 2026-07-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043_add_reply_routing_token_to_outbound_messages"
down_revision: str | None = "0042_allow_multiple_crm_agents_per_app_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column("reply_routing_token", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_outbound_messages_workspace_reply_token",
        "outbound_messages",
        ["workspace_id", "reply_routing_token"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_outbound_messages_workspace_reply_routing_token",
        "outbound_messages",
        ["workspace_id", "reply_routing_token"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_outbound_messages_workspace_reply_routing_token",
        "outbound_messages",
        type_="unique",
    )
    op.drop_index("ix_outbound_messages_workspace_reply_token", table_name="outbound_messages")
    op.drop_column("outbound_messages", "reply_routing_token")
