"""add lead classification LLM trace

Revision ID: 0057_add_lead_classification_llm_trace
Revises: 0056_add_crm_sync_job_heartbeat
Create Date: 2026-07-28 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0057_add_lead_classification_llm_trace"
down_revision: str | None = "0056_add_crm_sync_job_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "lead_classification_artifacts",
        sa.Column("prompt_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "lead_classification_artifacts",
        sa.Column(
            "input_context",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "lead_classification_artifacts",
        sa.Column("raw_llm_response_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "lead_classification_artifacts",
        sa.Column(
            "parsed_llm_response",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("lead_classification_artifacts", "parsed_llm_response")
    op.drop_column("lead_classification_artifacts", "raw_llm_response_text")
    op.drop_column("lead_classification_artifacts", "input_context")
    op.drop_column("lead_classification_artifacts", "prompt_text")