"""add primary contact destinations to leads

Revision ID: 0003_primary_contact_fields
Revises: 0002_create_outbound_messages
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_primary_contact_fields"
down_revision: str | None = "0002_create_outbound_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("primary_email", sa.String(length=320), nullable=True))
    op.add_column("leads", sa.Column("primary_phone", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "primary_phone")
    op.drop_column("leads", "primary_email")
