"""enforce one non-terminal workflow per lead

Revision ID: 0085_enforce_single_active_workflow_per_lead
Revises: 0084_add_paused_search_restart_delay
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0085_enforce_single_active_workflow_per_lead"
down_revision: str | None = "0084_add_paused_search_restart_delay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_lead_workflows_non_terminal_lead"
_NON_TERMINAL_PREDICATE = "state NOT IN ('completed', 'suppressed', 'closed')"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "lead_workflows",
        ["workspace_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text(_NON_TERMINAL_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="lead_workflows")
