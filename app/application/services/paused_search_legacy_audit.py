from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns import PausedSearchFallbackTimingPolicy


class LegacyAuditSeverity(StrEnum):
    WARNING = "warning"
    BLOCKING = "blocking"


class LegacyAuditFindingCode(StrEnum):
    UNKNOWN_TEMPLATE = "unknown_template"
    EMPTY_TRACK_VERSION = "empty_track_version"
    LEGACY_FALLBACK_POLICY = "legacy_fallback_policy"
    LEGACY_PUBLISH_REVIEW_FIELD = "legacy_publish_review_field"
    INCOMPLETE_WORKFLOW_CURSOR = "incomplete_workflow_cursor"


@dataclass(frozen=True)
class LegacyPausedSearchStepRecord:
    step_id: UUID
    template_key: str


@dataclass(frozen=True)
class LegacyPausedSearchVersionRecord:
    track_version_id: UUID
    fallback_timing_policy: PausedSearchFallbackTimingPolicy
    requires_review_before_publish: bool
    steps: tuple[LegacyPausedSearchStepRecord, ...]


@dataclass(frozen=True)
class LegacyPausedSearchWorkflowRecord:
    workflow_id: UUID
    track_version_id: UUID | None
    step_id: UUID | None
    has_next_action_at: bool


@dataclass(frozen=True)
class LegacyAuditFinding:
    code: LegacyAuditFindingCode
    severity: LegacyAuditSeverity
    entity_id: UUID
    message: str


@dataclass(frozen=True)
class LegacyPausedSearchAuditReport:
    version_count: int
    workflow_count: int
    findings: tuple[LegacyAuditFinding, ...]

    @property
    def blocking_findings(self) -> tuple[LegacyAuditFinding, ...]:
        return tuple(
            finding for finding in self.findings if finding.severity is LegacyAuditSeverity.BLOCKING
        )

    @property
    def ready_for_recurring_execution(self) -> bool:
        return not self.blocking_findings


def audit_legacy_paused_search_data(
    *,
    versions: tuple[LegacyPausedSearchVersionRecord, ...],
    workflows: tuple[LegacyPausedSearchWorkflowRecord, ...],
    approved_template_keys: frozenset[str],
) -> LegacyPausedSearchAuditReport:
    findings: list[LegacyAuditFinding] = []
    version_ids = {version.track_version_id for version in versions}

    for version in versions:
        if not version.steps:
            findings.append(
                LegacyAuditFinding(
                    LegacyAuditFindingCode.EMPTY_TRACK_VERSION,
                    LegacyAuditSeverity.BLOCKING,
                    version.track_version_id,
                    "Published legacy track version has no steps.",
                )
            )
        if version.fallback_timing_policy is not PausedSearchFallbackTimingPolicy.HOLD_FOR_REVIEW:
            findings.append(
                LegacyAuditFinding(
                    LegacyAuditFindingCode.LEGACY_FALLBACK_POLICY,
                    LegacyAuditSeverity.WARNING,
                    version.track_version_id,
                    "Legacy fallback timing requires compatibility mapping.",
                )
            )
        if version.requires_review_before_publish:
            findings.append(
                LegacyAuditFinding(
                    LegacyAuditFindingCode.LEGACY_PUBLISH_REVIEW_FIELD,
                    LegacyAuditSeverity.WARNING,
                    version.track_version_id,
                    "Admin must reconfirm the replacement publish contract.",
                )
            )
        for step in version.steps:
            if step.template_key not in approved_template_keys:
                findings.append(
                    LegacyAuditFinding(
                        LegacyAuditFindingCode.UNKNOWN_TEMPLATE,
                        LegacyAuditSeverity.BLOCKING,
                        step.step_id,
                        f"Template key is not in the approved registry: {step.template_key}",
                    )
                )

    for workflow in workflows:
        if workflow.track_version_id is None or workflow.track_version_id not in version_ids:
            message = "Active legacy workflow has no auditable pinned track version."
        elif workflow.step_id is None or not workflow.has_next_action_at:
            message = "Active legacy workflow cannot be safely imported without a cursor."
        else:
            continue
        if message:
            findings.append(
                LegacyAuditFinding(
                    LegacyAuditFindingCode.INCOMPLETE_WORKFLOW_CURSOR,
                    LegacyAuditSeverity.BLOCKING,
                    workflow.workflow_id,
                    message,
                )
            )

    return LegacyPausedSearchAuditReport(len(versions), len(workflows), tuple(findings))
