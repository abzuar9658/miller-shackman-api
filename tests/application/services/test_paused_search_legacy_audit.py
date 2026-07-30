from uuid import UUID

from app.application.services.paused_search_legacy_audit import (
    LegacyAuditFindingCode,
    LegacyPausedSearchStepRecord,
    LegacyPausedSearchVersionRecord,
    LegacyPausedSearchWorkflowRecord,
    audit_legacy_paused_search_data,
)
from app.domain.campaigns import PausedSearchFallbackTimingPolicy

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