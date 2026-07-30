"""add rich fields to crm conversation events

Revision ID: 0054_add_rich_fields_to_crm_conversation_events
Revises: 0053_create_lead_routing_reviews
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0054_add_rich_fields_to_crm_conversation_events"
down_revision: str | None = "0053_create_lead_routing_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "crm_conversation_events",
        sa.Column(
            "details",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "crm_conversation_events",
        sa.Column(
            "transcript_segments",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("crm_conversation_events", "details", server_default=None)
    op.alter_column("crm_conversation_events", "transcript_segments", server_default=None)


def downgrade() -> None:
    op.drop_column("crm_conversation_events", "transcript_segments")
    op.drop_column("crm_conversation_events", "details")