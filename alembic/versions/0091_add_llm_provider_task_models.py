"""add llm provider and task-split model columns to workspace llm configs

Revision ID: 0091_add_llm_provider_task_models
Revises: 0090_add_paused_search_writing_purposes
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0091_add_llm_provider_task_models"
down_revision: str | None = "0090_add_paused_search_writing_purposes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_LLM_PROVIDER = "openrouter"
DEFAULT_BEDROCK_DRAFTING_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_BEDROCK_CLASSIFICATION_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def upgrade() -> None:
    op.add_column(
        "workspace_llm_configs",
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "workspace_llm_configs",
        sa.Column("openrouter_drafting_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_llm_configs",
        sa.Column("openrouter_classification_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_llm_configs",
        sa.Column("bedrock_drafting_model", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "workspace_llm_configs",
        sa.Column("bedrock_classification_model", sa.String(length=255), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE workspace_llm_configs
            SET llm_provider = :provider,
                openrouter_drafting_model = openrouter_model,
                openrouter_classification_model = openrouter_model,
                bedrock_drafting_model = :bedrock_drafting,
                bedrock_classification_model = :bedrock_classification
            """
        ).bindparams(
            provider=DEFAULT_LLM_PROVIDER,
            bedrock_drafting=DEFAULT_BEDROCK_DRAFTING_MODEL,
            bedrock_classification=DEFAULT_BEDROCK_CLASSIFICATION_MODEL,
        )
    )
    op.alter_column("workspace_llm_configs", "llm_provider", nullable=False)
    op.alter_column("workspace_llm_configs", "openrouter_drafting_model", nullable=False)
    op.alter_column(
        "workspace_llm_configs", "openrouter_classification_model", nullable=False
    )
    op.alter_column("workspace_llm_configs", "bedrock_drafting_model", nullable=False)
    op.alter_column("workspace_llm_configs", "bedrock_classification_model", nullable=False)


def downgrade() -> None:
    op.drop_column("workspace_llm_configs", "bedrock_classification_model")
    op.drop_column("workspace_llm_configs", "bedrock_drafting_model")
    op.drop_column("workspace_llm_configs", "openrouter_classification_model")
    op.drop_column("workspace_llm_configs", "openrouter_drafting_model")
    op.drop_column("workspace_llm_configs", "llm_provider")
