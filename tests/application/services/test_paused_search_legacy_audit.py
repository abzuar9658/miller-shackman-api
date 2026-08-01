from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.services.paused_search_legacy_audit import (
    LegacyAuditFindingCode,
    LegacyPausedSearchStepRecord,
    LegacyPausedSearchVersionRecord,
    LegacyPausedSearchWorkflowRecord,
    audit_legacy_paused_search_data,
)
from app.application.services.paused_search_legacy_migration import (
    LegacyMigrationOutcome,
    LegacyMigrationReason,
    LegacyPausedSearchMigrationInput,
    plan_legacy_paused_search_migration,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrackStepPhase,
)
from app.domain.compliance.contactability import ContactChannel

VERSION_ID = UUID("00000000-0000-0000-0000-000000000701")
STEP_ID = UUID("00000000-0000-0000-0000-000000000702")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000703")


def test_legacy_audit_reports_mapping_warning_and_unknown_template_block() -> None:
    report = audit_legacy_paused_search_data(
        versions=(
            LegacyPausedSearchVersionRecord(
                track_version_id=VERSION_ID,
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
                requires_review_before_publish=True,
                steps=(LegacyPausedSearchStepRecord(STEP_ID, "unknown-template"),),
            ),
        ),
        workflows=(),
        approved_template_keys=frozenset(),
    )

    assert report.ready_for_recurring_execution is False
    assert {finding.code for finding in report.findings} == {
        LegacyAuditFindingCode.LEGACY_FALLBACK_POLICY,
        LegacyAuditFindingCode.LEGACY_PUBLISH_REVIEW_FIELD,
        LegacyAuditFindingCode.UNKNOWN_TEMPLATE,
    }
    assert len(report.blocking_findings) == 1


def test_legacy_audit_accepts_complete_compatible_records() -> None:
    report = audit_legacy_paused_search_data(
        versions=(
            LegacyPausedSearchVersionRecord(
                track_version_id=VERSION_ID,
                fallback_timing_policy=PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW,
                requires_review_before_publish=False,
                steps=(LegacyPausedSearchStepRecord(STEP_ID, "approved-template"),),
            ),
        ),
        workflows=(
            LegacyPausedSearchWorkflowRecord(
                workflow_id=WORKFLOW_ID,
                track_version_id=VERSION_ID,
                step_id=STEP_ID,
                has_next_action_at=True,
            ),
        ),
        approved_template_keys=frozenset({"approved-template"}),
    )

    assert report.ready_for_recurring_execution is True
    assert report.findings == ()


def test_legacy_audit_blocks_workflow_without_pinned_version() -> None:
    report = audit_legacy_paused_search_data(
        versions=(),
        workflows=(
            LegacyPausedSearchWorkflowRecord(
                workflow_id=WORKFLOW_ID,
                track_version_id=None,
                step_id=None,
                has_next_action_at=False,
            ),
        ),
        approved_template_keys=frozenset(),
    )

    assert report.ready_for_recurring_execution is False
    assert report.blocking_findings[0].code is LegacyAuditFindingCode.INCOMPLETE_WORKFLOW_CURSOR


def test_legacy_migration_creates_idempotent_non_touching_baseline() -> None:
    migration_input = LegacyPausedSearchMigrationInput(
        workspace_id=UUID("00000000-0000-0000-0000-000000000704"),
        lead_id=UUID("00000000-0000-0000-0000-000000000705"),
        workflow_id=WORKFLOW_ID,
        track_version_id=VERSION_ID,
        step_id=STEP_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        next_action_at=datetime(2026, 8, 1, 15, tzinfo=UTC),
        logical_touch_count=1,
        max_total_touches=5,
        timezone="America/Chicago",
    )

    first = plan_legacy_paused_search_migration(input_=migration_input, now=datetime.now(UTC))
    second = plan_legacy_paused_search_migration(input_=migration_input, now=datetime.now(UTC))

    assert first.outcome is LegacyMigrationOutcome.MIGRATED
    assert first.reason is LegacyMigrationReason.MIGRATED_BASELINE
    assert first.terminalize_workflow is False
    assert first.occurrence is not None
    assert first.occurrence.status.value == "migrated_legacy"
    assert first.occurrence.occurrence_number == 0
    assert first.occurrence.logical_touch_count == 0
    assert second.occurrence is not None
    assert first.occurrence.occurrence_id == second.occurrence.occurrence_id
    assert first.occurrence.idempotency_key == second.occurrence.idempotency_key


def test_legacy_migration_holds_incomplete_cursor_and_terminalizes_touch_limit() -> None:
    incomplete = LegacyPausedSearchMigrationInput(
        workspace_id=UUID("00000000-0000-0000-0000-000000000704"),
        lead_id=UUID("00000000-0000-0000-0000-000000000705"),
        workflow_id=WORKFLOW_ID,
        track_version_id=None,
        step_id=None,
        phase=None,
        channel=None,
        next_action_at=None,
        logical_touch_count=0,
        max_total_touches=5,
        timezone="UTC",
    )
    at_limit = replace(
        incomplete,
        track_version_id=VERSION_ID,
        step_id=STEP_ID,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=ContactChannel.EMAIL,
        next_action_at=datetime(2026, 8, 1, 15, tzinfo=UTC),
        logical_touch_count=5,
    )

    held = plan_legacy_paused_search_migration(input_=incomplete, now=datetime.now(UTC))
    migrated = plan_legacy_paused_search_migration(input_=at_limit, now=datetime.now(UTC))

    assert held.outcome is LegacyMigrationOutcome.HOLD_FOR_REVIEW
    assert held.reason is LegacyMigrationReason.INCOMPLETE_CURSOR
    assert held.occurrence is None
    assert migrated.reason is LegacyMigrationReason.TOUCH_LIMIT_AT_MIGRATION
    assert migrated.terminalize_workflow is True
