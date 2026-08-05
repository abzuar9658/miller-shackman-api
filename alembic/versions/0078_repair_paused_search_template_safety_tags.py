"""repair seeded paused-search template safety tags

Revision ID: 0078_repair_paused_search_template_safety_tags
Revises: 0077_durable_paused_search_track_assignments
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0078_repair_paused_search_template_safety_tags"
down_revision: str | None = "0077_durable_paused_search_track_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_required_tag(
        template_prefixes=(
            "paused-search-waiting-for-rates-",
            "paused-search-financial-prep-",
        ),
        tag="no_financial_advice",
    )
    _add_required_tag(
        template_prefixes=("paused-search-waiting-for-inventory-",),
        tag="listing_context_allowed",
    )


def downgrade() -> None:
    # These tags may have been added or approved independently after this repair;
    # removing them would make the downgrade destructive to template policy data.
    pass


def _add_required_tag(*, template_prefixes: tuple[str, ...], tag: str) -> None:
    prefix_parameters = {
        f"prefix_{index}": f"{prefix}%"
        for index, prefix in enumerate(template_prefixes)
    }
    prefix_predicate = " OR ".join(
        f"template_key LIKE :{name}" for name in prefix_parameters
    )
    statement = sa.text(
        f"""
        UPDATE template_versions
        SET permitted_use_tags = (
            SELECT jsonb_agg(value ORDER BY value)
            FROM (
                SELECT DISTINCT value
                FROM jsonb_array_elements_text(permitted_use_tags::jsonb)
                UNION ALL
                SELECT :tag
            ) AS tags
        )
        WHERE purpose = 'paused_search'
          AND ({prefix_predicate})
          AND NOT (permitted_use_tags::jsonb ? CAST(:tag AS text))
        """
    ).bindparams(tag=tag, **prefix_parameters)
    op.execute(statement)