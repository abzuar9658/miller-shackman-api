"""enforce one active paused-search workflow per lead

Revision ID: 0067_enforce_active_paused_search_workflow_overlap
Revises: 0066_link_paused_search_reviews_to_messages
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0067_enforce_active_paused_search_workflow_overlap"
down_revision: str | None = "0066_link_paused_search_reviews_to_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_lead_workflows_active_paused_search_lead"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "lead_workflows",
        ["workspace_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text(
            "paused_search_track_version_id IS NOT NULL "
            "AND state IN "
            "('queued', 'active_nurture', 'waiting_for_response', 'response_processing')"
        ),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="lead_workflows")