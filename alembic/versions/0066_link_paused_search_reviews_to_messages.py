"""link paused-search reviews to immutable outbound message versions

Revision ID: 0066_link_paused_search_reviews_to_messages
Revises: 0065_bind_paused_search_steps_to_templates
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0066_link_paused_search_reviews_to_messages"
down_revision: str | None = "0065_bind_paused_search_steps_to_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paused_search_reviews",
        sa.Column("outbound_message_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "paused_search_reviews",
        sa.Column("outbound_message_version", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_paused_search_reviews_outbound_message",
        "paused_search_reviews",
        "outbound_messages",
        ["outbound_message_id"],
        ["message_id"],
    )
    op.create_unique_constraint(
        "uq_paused_search_reviews_workspace_occurrence_kind",
        "paused_search_reviews",
        ["workspace_id", "occurrence_id", "kind"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_paused_search_reviews_workspace_occurrence_kind",
        "paused_search_reviews",
        type_="unique",
    )
    op.drop_constraint(
        "fk_paused_search_reviews_outbound_message",
        "paused_search_reviews",
        type_="foreignkey",
    )
    op.drop_column("paused_search_reviews", "outbound_message_version")
    op.drop_column("paused_search_reviews", "outbound_message_id")