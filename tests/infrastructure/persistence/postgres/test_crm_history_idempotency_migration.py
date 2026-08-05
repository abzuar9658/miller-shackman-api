from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from tests.infrastructure.persistence.postgres._harness import (
    postgres_connect_kwargs,
    run_migrations,
    temporary_postgres_database,
)


def test_migration_merges_existing_extension_and_pulled_duplicates() -> None:
    try:
        with temporary_postgres_database(prefix="ms_history_identity_") as database:
            run_migrations(database.migration_url, "0074_create_extension_device_tables")
            workspace_id, lead_id = uuid4(), uuid4()
            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.service_access', 'on', false)")
                    _insert_workspace_and_lead(cursor, workspace_id, lead_id)
                    _insert_duplicate_events(cursor, workspace_id, lead_id)

            run_migrations(database.migration_url)

            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.service_access', 'on', false)")
                    cursor.execute(
                        "SELECT crm_activity_id, canonical_identity, source_payload_version "
                        "FROM crm_conversation_events WHERE workspace_id = %s AND lead_id = %s",
                        (workspace_id, lead_id),
                    )
                    rows = cursor.fetchall()

            assert len(rows) == 1
            assert rows[0][0] == "text_message:42"
            assert len(rows[0][1]) == 64
            assert rows[0][2] == "follow_up_boss/v1"
    except psycopg.OperationalError as error:
        pytest.skip(f"Local Postgres is unavailable for migration test: {error}")


def _insert_workspace_and_lead(
    cursor: psycopg.Cursor[tuple[object, ...]], workspace_id: object, lead_id: object
) -> None:
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    cursor.execute(
        "INSERT INTO workspaces "
        "(workspace_id, name, status, default_timezone, created_at, updated_at) "
        "VALUES (%s, 'Migration test', 'active', 'UTC', %s, %s)",
        (workspace_id, now, now),
    )
    cursor.execute(
        """
        INSERT INTO leads (
            lead_id, workspace_id, crm_provider, crm_lead_id, source_payload_version,
            facts_derived_at, assigned_agent_name_present, has_accountable_owner,
            lead_type, classification_reason, lead_source, lead_stage, created_via,
            tags, mapped_custom_fields, has_email, has_phone, has_sms_capable_phone,
            email_count, phone_count, sms_permission_status, email_permission_status,
            sms_opted_out, email_unsubscribed, suppression_types, permission_evidence,
            activity_reliability, latest_property_context_present, created_at, updated_at
        ) VALUES (
            %s, %s, 'follow_up_boss', 'fub-1', 'follow_up_boss/v1',
            %s, false, false, 'unknown', 'migration_test', 'unknown', 'unknown', 'sync',
            '[]'::jsonb, '{}'::jsonb, false, false, false, 0, 0, 'unknown', 'unknown',
            false, false, '[]'::jsonb, '{}'::jsonb, 'reliable', false, %s, %s
        )
        """,
        (lead_id, workspace_id, now, now, now),
    )


def _insert_duplicate_events(
    cursor: psycopg.Cursor[tuple[object, ...]], workspace_id: object, lead_id: object
) -> None:
    occurred_at = datetime(2026, 8, 1, 18, 30, tzinfo=UTC)
    for activity_id, activity_type, content, source in (
        ("extension-fingerprint:abc", "text", "Hello there", "extension/v1"),
        ("text_message:42", "Text message", "<span>Hello there</span>", "follow_up_boss/v1"),
    ):
        cursor.execute(
            """
            INSERT INTO crm_conversation_events (
                crm_conversation_event_id, workspace_id, lead_id, crm_provider,
                crm_activity_id, activity_type, direction, occurred_at, content,
                details, transcript_segments, source_payload_version, created_at, updated_at
            ) VALUES (
                %s, %s, %s, 'follow_up_boss', %s, %s, 'inbound', %s, %s,
                '{}'::jsonb, '[]'::jsonb, %s, %s, %s
            )
            """,
            (
                uuid4(), workspace_id, lead_id, activity_id, activity_type, occurred_at,
                content, source, occurred_at, occurred_at,
            ),
        )