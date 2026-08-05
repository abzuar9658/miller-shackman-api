from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest

from tests.infrastructure.persistence.postgres._harness import (
    postgres_connect_kwargs,
    run_migrations,
    temporary_postgres_database,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_ID = UUID("10000000-0000-0000-0000-000000000002")
TRACK_A_ID = UUID("20000000-0000-0000-0000-000000000001")
TRACK_B_ID = UUID("20000000-0000-0000-0000-000000000002")
TRACK_A_V1_ID = UUID("30000000-0000-0000-0000-000000000001")
TRACK_A_V2_ID = UUID("30000000-0000-0000-0000-000000000002")
TRACK_B_V1_ID = UUID("30000000-0000-0000-0000-000000000003")
UNIQUE_REASON_LEAD_ID = UUID("40000000-0000-0000-0000-000000000001")
AMBIGUOUS_REASON_LEAD_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKFLOW_LEAD_ID = UUID("40000000-0000-0000-0000-000000000003")


def test_migration_backfills_workflow_then_only_unambiguous_reason_history() -> None:
    try:
        with temporary_postgres_database(prefix="ms_paused_assignment_") as database:
            run_migrations(database.migration_url, "0076_preserve_paused_track_delete_audit")
            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.service_access', 'on', false)")
                    _seed_pre_assignment_state(cursor)

            run_migrations(database.migration_url)

            with psycopg.connect(
                autocommit=True,
                **postgres_connect_kwargs(database.database_name),
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.service_access', 'on', false)")
                    cursor.execute(
                        "SELECT lead_id, track_id, track_version_id, track_key_snapshot, "
                        "track_name_snapshot, track_version_snapshot, source "
                        "FROM paused_search_track_assignments ORDER BY lead_id"
                    )
                    rows = cursor.fetchall()
                    cursor.execute(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE oid = 'paused_search_track_assignments'::regclass"
                    )
                    rls = cursor.fetchone()

            assert rows == [
                (
                    UNIQUE_REASON_LEAD_ID,
                    TRACK_A_ID,
                    TRACK_A_V2_ID,
                    "track-a",
                    "Track A",
                    2,
                    "legacy_reason_backfill",
                ),
                (
                    WORKFLOW_LEAD_ID,
                    TRACK_B_ID,
                    TRACK_B_V1_ID,
                    "track-b",
                    "Track B",
                    1,
                    "workflow_backfill",
                ),
            ]
            assert AMBIGUOUS_REASON_LEAD_ID not in {row[0] for row in rows}
            assert rls == (True, True)
    except psycopg.OperationalError as error:
        pytest.skip(f"Local Postgres is unavailable for migration test: {error}")


def _seed_pre_assignment_state(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    cursor.execute(
        "INSERT INTO workspaces "
        "(workspace_id, name, status, default_timezone, created_at, updated_at) "
        "VALUES (%s, 'Migration test', 'active', 'UTC', %s, %s)",
        (WORKSPACE_ID, NOW, NOW),
    )
    cursor.execute(
        "INSERT INTO users "
        "(user_id, email, email_normalized, full_name, status, created_at, updated_at) "
        "VALUES (%s, 'admin@example.com', 'admin@example.com', 'Admin', 'active', %s, %s)",
        (USER_ID, NOW, NOW),
    )
    _insert_track(cursor, TRACK_A_ID, "track-a", "Track A")
    _insert_track(cursor, TRACK_B_ID, "track-b", "Track B")
    _insert_version(
        cursor,
        TRACK_A_V1_ID,
        TRACK_A_ID,
        1,
        '["rented_temporarily", "waiting_for_rates"]',
    )
    _insert_version(
        cursor,
        TRACK_A_V2_ID,
        TRACK_A_ID,
        2,
        '["rented_temporarily", "waiting_for_rates"]',
    )
    _insert_version(cursor, TRACK_B_V1_ID, TRACK_B_ID, 1, '["waiting_for_rates"]')
    _insert_lead(cursor, UNIQUE_REASON_LEAD_ID, "rented_temporarily")
    _insert_lead(cursor, AMBIGUOUS_REASON_LEAD_ID, "waiting_for_rates")
    _insert_lead(cursor, WORKFLOW_LEAD_ID, "waiting_for_rates")
    _insert_workflow_pin(cursor)


def _insert_track(
    cursor: psycopg.Cursor[tuple[object, ...]], track_id: UUID, key: str, name: str
) -> None:
    cursor.execute(
        "INSERT INTO paused_search_tracks "
        "(track_id, workspace_id, track_key, display_name, status, created_by_user_id, "
        "created_at, updated_at) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s)",
        (track_id, WORKSPACE_ID, key, name, USER_ID, NOW, NOW),
    )


def _insert_version(
    cursor: psycopg.Cursor[tuple[object, ...]],
    version_id: UUID,
    track_id: UUID,
    version_number: int,
    reasons_json: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO paused_search_track_versions (
            track_version_id, workspace_id, track_id, version_number, status, track_family,
            enabled, allowed_channels, default_for_reason_codes, fallback_timing_policy,
            maintenance_interval_days, reactivation_window_days, max_total_touches,
            requires_review_before_publish, max_duration_days, default_pause_duration_days,
            terminal_behavior, created_by_user_id, created_at
        ) VALUES (
            %s, %s, %s, %s, 'published', 'maintenance', true, '["email"]'::jsonb,
            %s::jsonb, 'use_maintenance_interval', 30, 30, 5, false, 365, 60,
            'complete_keep_paused', %s, %s
        )
        """,
        (version_id, WORKSPACE_ID, track_id, version_number, reasons_json, USER_ID, NOW),
    )


def _insert_lead(
    cursor: psycopg.Cursor[tuple[object, ...]], lead_id: UUID, reason_code: str
) -> None:
    cursor.execute(
        """
        INSERT INTO leads (
            lead_id, workspace_id, crm_provider, crm_lead_id, source_payload_version,
            facts_derived_at, assigned_agent_name_present, has_accountable_owner,
            lead_type, classification_reason, lead_source, lead_stage, created_via,
            tags, mapped_custom_fields, has_email, has_phone, has_sms_capable_phone,
            email_count, phone_count, sms_permission_status, email_permission_status,
            sms_opted_out, email_unsubscribed, suppression_types, permission_evidence,
            activity_reliability, latest_property_context_present, paused_search_active,
            pause_reason_code, paused_search_recorded_at, created_at, updated_at
        ) VALUES (
            %s, %s, 'follow_up_boss', %s, 'follow_up_boss/v1', %s, false, false,
            'buyer', 'migration_test', 'unknown', 'paused', 'sync', '[]'::jsonb, '{}'::jsonb,
            false, false, false, 0, 0, 'unknown', 'unknown', false, false, '[]'::jsonb,
            '{}'::jsonb, 'reliable', false, true, %s, %s, %s, %s
        )
        """,
        (lead_id, WORKSPACE_ID, f"fub-{lead_id}", NOW, reason_code, NOW, NOW, NOW),
    )


def _insert_workflow_pin(cursor: psycopg.Cursor[tuple[object, ...]]) -> None:
    campaign_id = UUID("50000000-0000-0000-0000-000000000001")
    campaign_version_id = UUID("50000000-0000-0000-0000-000000000002")
    enrollment_id = UUID("50000000-0000-0000-0000-000000000003")
    cursor.execute(
        "INSERT INTO campaigns (campaign_id, workspace_id, name, status, created_by_user_id, "
        "created_at, updated_at) VALUES (%s, %s, 'Paused migration', 'active', %s, %s, %s)",
        (campaign_id, WORKSPACE_ID, USER_ID, NOW, NOW),
    )
    cursor.execute(
        """
        INSERT INTO campaign_versions (
            campaign_version_id, workspace_id, campaign_id, version_number, status,
            enabled_channels, daily_start_cap, dormant_threshold_days, quiet_hours_start,
            quiet_hours_end, timezone, sms_compliance_required, preflight_digest_enabled,
            prompt_version, approved_model, created_by_user_id, created_at
        ) VALUES (
            %s, %s, %s, 1, 'published', '["email"]'::jsonb, 10, 60, '10:00', '17:00',
            'UTC', true, false, 'v1', 'test-model', %s, %s
        )
        """,
        (campaign_version_id, WORKSPACE_ID, campaign_id, USER_ID, NOW),
    )
    cursor.execute(
        """
        INSERT INTO campaign_enrollments (
            campaign_enrollment_id, workspace_id, campaign_id, campaign_version_id, lead_id,
            source, status, reason_codes, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, 'manual', 'completed', '[]'::jsonb, %s, %s)
        """,
        (
            enrollment_id,
            WORKSPACE_ID,
            campaign_id,
            campaign_version_id,
            WORKFLOW_LEAD_ID,
            NOW,
            NOW,
        ),
    )
    cursor.execute(
        """
        INSERT INTO lead_workflows (
            workflow_id, temporal_workflow_id, workspace_id, campaign_enrollment_id,
            campaign_id, lead_id, state, last_transition_at, state_version,
            logical_touch_count, paused_search_track_version_id, created_at, updated_at
        ) VALUES (
            %s, 'paused-migration-workflow', %s, %s, %s, %s, 'completed', %s, 1, 0, %s, %s, %s
        )
        """,
        (
            UUID("50000000-0000-0000-0000-000000000004"),
            WORKSPACE_ID,
            enrollment_id,
            campaign_id,
            WORKFLOW_LEAD_ID,
            NOW,
            TRACK_B_V1_ID,
            NOW,
            NOW,
        ),
    )