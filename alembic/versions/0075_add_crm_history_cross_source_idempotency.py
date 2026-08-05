"""add CRM history cross-source idempotency

Revision ID: 0075_add_crm_history_cross_source_idempotency
Revises: 0074_create_extension_device_tables
"""

import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0075_add_crm_history_cross_source_idempotency"
down_revision: str | None = "0074_create_extension_device_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HTML_TAG = re.compile(r"<[^>]+>")
_ACTIVITY_TYPE_ALIASES = {
    "sms": "text",
    "text": "text",
    "text message": "text",
    "text_message": "text",
}


def upgrade() -> None:
    op.add_column(
        "crm_conversation_events",
        sa.Column("canonical_identity", sa.String(64), nullable=True),
    )
    _backfill_and_merge_conversation_event_identities()
    op.alter_column("crm_conversation_events", "canonical_identity", nullable=False)
    op.create_unique_constraint(
        "uq_crm_conversation_events_workspace_provider_lead_identity",
        "crm_conversation_events",
        ["workspace_id", "crm_provider", "lead_id", "canonical_identity"],
    )

    op.add_column(
        "crm_history_import_jobs",
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
    )
    op.add_column(
        "crm_history_import_jobs",
        sa.Column("batch_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "crm_history_import_jobs",
        sa.Column("source_device_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "uq_crm_history_import_jobs_workspace_lead_batch",
        "crm_history_import_jobs",
        ["workspace_id", "lead_id", "batch_fingerprint"],
        unique=True,
        postgresql_where=sa.text(
            "batch_fingerprint IS NOT NULL AND status NOT IN ('failed', 'cancelled')"
        ),
    )
    op.create_foreign_key(
        "fk_crm_history_import_jobs_workspace_device",
        "crm_history_import_jobs",
        "extension_devices",
        ["workspace_id", "source_device_id"],
        ["workspace_id", "device_id"],
    )
    op.alter_column("crm_history_import_jobs", "source", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "fk_crm_history_import_jobs_workspace_device",
        "crm_history_import_jobs",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_crm_history_import_jobs_workspace_lead_batch",
        table_name="crm_history_import_jobs",
    )
    op.drop_column("crm_history_import_jobs", "source_device_id")
    op.drop_column("crm_history_import_jobs", "batch_fingerprint")
    op.drop_column("crm_history_import_jobs", "source")
    op.drop_constraint(
        "uq_crm_conversation_events_workspace_provider_lead_identity",
        "crm_conversation_events",
        type_="unique",
    )
    op.drop_column("crm_conversation_events", "canonical_identity")


def _backfill_and_merge_conversation_event_identities() -> None:
    connection = op.get_bind()
    last_event_id: object | None = None
    while True:
        rows = connection.execute(
            sa.text(
                """
                SELECT crm_conversation_event_id, activity_type, occurred_at, content, direction
                FROM crm_conversation_events
                WHERE (
                    CAST(:last_event_id AS uuid) IS NULL
                    OR crm_conversation_event_id > CAST(:last_event_id AS uuid)
                )
                ORDER BY crm_conversation_event_id
                LIMIT 1000
                """
            ),
            {"last_event_id": last_event_id},
        ).mappings().all()
        if not rows:
            break
        updates = [
            {
                "event_id": row["crm_conversation_event_id"],
                "identity": _canonical_identity_v1(
                    activity_type=row["activity_type"],
                    occurred_at=row["occurred_at"],
                    content=row["content"],
                    direction=row["direction"],
                ),
            }
            for row in rows
        ]
        _write_identity_batch(connection, updates)
        last_event_id = rows[-1]["crm_conversation_event_id"]

    # Prefer provider-backed rows over rendered extension rows for pre-existing duplicates.
    connection.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT crm_conversation_event_id,
                       row_number() OVER (
                           PARTITION BY workspace_id, crm_provider, lead_id, canonical_identity
                           ORDER BY (source_payload_version LIKE 'extension/%') ASC,
                                    created_at ASC,
                                    crm_conversation_event_id ASC
                       ) AS duplicate_rank
                FROM crm_conversation_events
            )
            DELETE FROM crm_conversation_events AS event
            USING ranked
            WHERE event.crm_conversation_event_id = ranked.crm_conversation_event_id
              AND ranked.duplicate_rank > 1
            """
        )
    )


def _write_identity_batch(
    connection: sa.Connection, updates: list[dict[str, object]]
) -> None:
    if not updates:
        return
    connection.execute(
        sa.text(
            "UPDATE crm_conversation_events SET canonical_identity = :identity "
            "WHERE crm_conversation_event_id = :event_id"
        ),
        updates,
    )


def _canonical_identity_v1(
    *, activity_type: str, occurred_at: datetime, content: str | None, direction: str | None
) -> str:
    """Frozen copy of the v1 identity used for this irreversible backfill."""
    normalized_type = " ".join(activity_type.strip().lower().replace("-", " ").split())
    normalized_content = "" if content is None else " ".join(
        unicodedata.normalize("NFKC", _HTML_TAG.sub(" ", html.unescape(content))).split()
    )
    source = json.dumps(
        {
            "activity_type": _ACTIVITY_TYPE_ALIASES.get(normalized_type, normalized_type),
            "content": normalized_content,
            "direction": (direction or "").strip().lower(),
            "occurred_at": occurred_at.astimezone(UTC).replace(microsecond=0).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()