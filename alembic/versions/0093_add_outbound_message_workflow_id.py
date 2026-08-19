"""add workflow_id to outbound messages

Revision ID: 0093_add_outbound_message_workflow_id
Revises: 0092_remove_sms_compliance_fields
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0093_add_outbound_message_workflow_id"
down_revision: str | None = "0092_remove_sms_compliance_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbound_messages",
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbound_messages", "workflow_id")
