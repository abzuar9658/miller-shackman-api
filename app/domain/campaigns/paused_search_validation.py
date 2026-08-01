from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.capability_profiles import capability_profile_for_reason
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrack,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.template_registry import (
    ALLOWED_TEMPLATE_VARIABLES,
    TemplateStatus,
    TemplateVersion,
)

MAX_AI_TOUCHES_PER_TRACK = 5


class PausedSearchValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class PausedSearchValidationCode(StrEnum):
    EMPTY_TRACK_KEY = "empty_track_key"
    EMPTY_DISPLAY_NAME = "empty_display_name"
    NO_ALLOWED_CHANNELS = "no_allowed_channels"
    NO_REASON_MAPPING = "no_reason_mapping"
    DUPLICATE_REASON_MAPPING = "duplicate_reason_mapping"
    INVALID_MAINTENANCE_INTERVAL = "invalid_maintenance_interval"
    INVALID_REACTIVATION_WINDOW = "invalid_reactivation_window"
    INVALID_TOUCH_LIMIT = "invalid_touch_limit"
    INVALID_DURATION = "invalid_duration"
    NO_STEPS = "no_steps"
    INVALID_STEP_ORDER = "invalid_step_order"
    STEP_CHANNEL_NOT_ALLOWED = "step_channel_not_allowed"
    INVALID_STEP_DELAY = "invalid_step_delay"
    EMPTY_MESSAGE_GOAL = "empty_message_goal"
    EMPTY_TEMPLATE_KEY = "empty_template_key"
    INVALID_MAX_ATTEMPTS = "invalid_max_attempts"
    INVALID_MAX_OCCURRENCES = "invalid_max_occurrences"
    INVALID_RECURRING_INTERVAL = "invalid_recurring_interval"
    PROFILE_TOUCH_LIMIT_EXCEEDED = "profile_touch_limit_exceeded"
    PROFILE_DURATION_EXCEEDED = "profile_duration_exceeded"
    PROFILE_INTERVAL_OUT_OF_RANGE = "profile_interval_out_of_range"
    VERSION_DISABLED = "version_disabled"
    LEGACY_PUBLISH_REVIEW_REQUIRED = "legacy_publish_review_required"
    EXPECTED_TOUCHES_CAPPED = "expected_touches_capped"
    WORKSPACE_MISMATCH = "workspace_mismatch"
    VERSION_NOT_IN_TRACK = "version_not_in_track"
    STEP_NOT_IN_VERSION = "step_not_in_version"
    TEMPLATE_VERSION_MISSING = "template_version_missing"
    TEMPLATE_VERSION_NOT_FOUND = "template_version_not_found"
    TEMPLATE_KEY_MISMATCH = "template_key_mismatch"
    TEMPLATE_CHANNEL_MISMATCH = "template_channel_mismatch"
    TEMPLATE_PURPOSE_MISMATCH = "template_purpose_mismatch"
    TEMPLATE_NOT_APPROVED = "template_not_approved"
    TEMPLATE_SAFETY_TAG_MISSING = "template_safety_tag_missing"
    TEMPLATE_VARIABLES_INVALID = "template_variables_invalid"


@dataclass(frozen=True)
class PausedSearchValidationFinding:
    code: PausedSearchValidationCode
    severity: PausedSearchValidationSeverity
    field: str
    detail: str


@dataclass(frozen=True)
class PausedSearchTrackValidationReport:
    findings: tuple[PausedSearchValidationFinding, ...]

    @property
    def errors(self) -> tuple[PausedSearchValidationFinding, ...]:
        return tuple(
            item for item in self.findings if item.severity is PausedSearchValidationSeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[PausedSearchValidationFinding, ...]:
        return tuple(
            item
            for item in self.findings
            if item.severity is PausedSearchValidationSeverity.WARNING
        )

    @property
    def publishable(self) -> bool:
        return not self.errors


def validate_paused_search_track(
    *,
    track: PausedSearchTrack,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    for_publish: bool,
    templates: Mapping[UUID, TemplateVersion] | None = None,
) -> PausedSearchTrackValidationReport:
    findings: list[PausedSearchValidationFinding] = []
    _validate_identity(track, version, steps, findings)
    _validate_track_metadata(track, findings)
    _validate_version(version, steps, findings, for_publish=for_publish)
    _validate_steps(version, steps, findings)
    _validate_profiles(version, steps, findings)
    if templates is not None:
        _validate_templates(version, steps, templates, findings, for_publish=for_publish)
    configured_touches = sum(step.max_occurrences for step in steps)
    if configured_touches > version.max_total_touches:
        _add(
            findings,
            PausedSearchValidationCode.EXPECTED_TOUCHES_CAPPED,
            PausedSearchValidationSeverity.WARNING,
            "steps",
            "configured occurrences exceed the track touch cap and will be bounded at runtime",
        )
    return PausedSearchTrackValidationReport(findings=tuple(findings))


def validation_report_evidence(report: PausedSearchTrackValidationReport) -> dict[str, object]:
    return {
        "publishable": report.publishable,
        "errors": [_finding_evidence(item) for item in report.errors],
        "warnings": [_finding_evidence(item) for item in report.warnings],
    }


def _validate_identity(
    track: PausedSearchTrack,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    findings: list[PausedSearchValidationFinding],
) -> None:
    if version.workspace_id != track.workspace_id or any(
        step.workspace_id != track.workspace_id for step in steps
    ):
        _error(findings, PausedSearchValidationCode.WORKSPACE_MISMATCH, "workspace_id")
    if version.track_id != track.track_id:
        _error(findings, PausedSearchValidationCode.VERSION_NOT_IN_TRACK, "track_id")
    if any(step.track_version_id != version.track_version_id for step in steps):
        _error(findings, PausedSearchValidationCode.STEP_NOT_IN_VERSION, "steps")


def _validate_track_metadata(
    track: PausedSearchTrack,
    findings: list[PausedSearchValidationFinding],
) -> None:
    if not track.track_key.strip():
        _error(findings, PausedSearchValidationCode.EMPTY_TRACK_KEY, "track_key")
    if not track.display_name.strip():
        _error(findings, PausedSearchValidationCode.EMPTY_DISPLAY_NAME, "display_name")


def _validate_version(
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    findings: list[PausedSearchValidationFinding],
    *,
    for_publish: bool,
) -> None:
    if not version.allowed_channels:
        _error(findings, PausedSearchValidationCode.NO_ALLOWED_CHANNELS, "allowed_channels")
    if not version.default_for_reason_codes:
        _error(findings, PausedSearchValidationCode.NO_REASON_MAPPING, "default_for_reason_codes")
    elif len(version.default_for_reason_codes) != len(set(version.default_for_reason_codes)):
        _error(
            findings,
            PausedSearchValidationCode.DUPLICATE_REASON_MAPPING,
            "default_for_reason_codes",
        )
    if version.maintenance_interval_days <= 0:
        _error(
            findings,
            PausedSearchValidationCode.INVALID_MAINTENANCE_INTERVAL,
            "maintenance_interval_days",
        )
    if version.reactivation_window_days <= 0:
        _error(
            findings,
            PausedSearchValidationCode.INVALID_REACTIVATION_WINDOW,
            "reactivation_window_days",
        )
    if not 0 < version.max_total_touches <= MAX_AI_TOUCHES_PER_TRACK:
        _error(findings, PausedSearchValidationCode.INVALID_TOUCH_LIMIT, "max_total_touches")
    if not 30 <= version.max_duration_days <= 730:
        _error(findings, PausedSearchValidationCode.INVALID_DURATION, "max_duration_days")
    if not steps:
        _error(findings, PausedSearchValidationCode.NO_STEPS, "steps")
    if for_publish and not version.enabled:
        _error(findings, PausedSearchValidationCode.VERSION_DISABLED, "enabled")
    if version.requires_review_before_publish:
        severity = (
            PausedSearchValidationSeverity.ERROR
            if for_publish
            else PausedSearchValidationSeverity.WARNING
        )
        _add(
            findings,
            PausedSearchValidationCode.LEGACY_PUBLISH_REVIEW_REQUIRED,
            severity,
            "requires_review_before_publish",
            "legacy draft must be resaved under the current publish contract",
        )


def _validate_steps(
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    findings: list[PausedSearchValidationFinding],
) -> None:
    expected_orders = list(range(1, len(steps) + 1))
    if sorted(step.step_order for step in steps) != expected_orders:
        _error(findings, PausedSearchValidationCode.INVALID_STEP_ORDER, "steps")
    allowed_channels = set(version.allowed_channels)
    for index, step in enumerate(steps):
        field = f"steps[{index}]"
        if step.channel not in allowed_channels:
            _error(
                findings, PausedSearchValidationCode.STEP_CHANNEL_NOT_ALLOWED, f"{field}.channel"
            )
        if step.delay_hours < 0:
            _error(findings, PausedSearchValidationCode.INVALID_STEP_DELAY, f"{field}.delay_hours")
        if not step.message_goal.strip():
            _error(findings, PausedSearchValidationCode.EMPTY_MESSAGE_GOAL, f"{field}.message_goal")
        if not step.template_key.strip():
            _error(findings, PausedSearchValidationCode.EMPTY_TEMPLATE_KEY, f"{field}.template_key")
        if step.max_attempts <= 0:
            _error(
                findings, PausedSearchValidationCode.INVALID_MAX_ATTEMPTS, f"{field}.max_attempts"
            )
        if step.max_occurrences <= 0:
            _error(
                findings,
                PausedSearchValidationCode.INVALID_MAX_OCCURRENCES,
                f"{field}.max_occurrences",
            )
        if step.interval_days is not None and not 14 <= step.interval_days <= 365:
            _error(
                findings,
                PausedSearchValidationCode.INVALID_RECURRING_INTERVAL,
                f"{field}.interval_days",
            )


def _validate_profiles(
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    findings: list[PausedSearchValidationFinding],
) -> None:
    for reason_code in dict.fromkeys(version.default_for_reason_codes):
        profile = capability_profile_for_reason(reason_code)
        if profile is None:
            continue
        if version.max_total_touches > profile.max_total_touches:
            _error(
                findings,
                PausedSearchValidationCode.PROFILE_TOUCH_LIMIT_EXCEEDED,
                "max_total_touches",
            )
        if version.max_duration_days > profile.max_duration_days:
            _error(
                findings,
                PausedSearchValidationCode.PROFILE_DURATION_EXCEEDED,
                "max_duration_days",
            )
        for index, step in enumerate(steps):
            interval = step.interval_days
            if interval is not None and not (
                profile.min_recurring_interval_days
                <= interval
                <= profile.max_recurring_interval_days
            ):
                _error(
                    findings,
                    PausedSearchValidationCode.PROFILE_INTERVAL_OUT_OF_RANGE,
                    f"steps[{index}].interval_days",
                )


def _validate_templates(
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    templates: Mapping[UUID, TemplateVersion],
    findings: list[PausedSearchValidationFinding],
    *,
    for_publish: bool,
) -> None:
    for index, step in enumerate(steps):
        field = f"steps[{index}].template_version_id"
        template = (
            templates.get(step.template_version_id)
            if step.template_version_id is not None
            else None
        )
        severity = (
            PausedSearchValidationSeverity.ERROR
            if for_publish
            else PausedSearchValidationSeverity.WARNING
        )
        if step.template_version_id is None:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_VERSION_MISSING,
                severity,
                field,
                "step must bind to an approved template version",
            )
            continue
        if template is None:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_VERSION_NOT_FOUND,
                severity,
                field,
                "bound template version was not found in this workspace",
            )
            continue
        if template.workspace_id != version.workspace_id:
            _error(
                findings,
                PausedSearchValidationCode.WORKSPACE_MISMATCH,
                field,
            )
        if template.template_key != step.template_key:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_KEY_MISMATCH,
                severity,
                field,
                "bound template key does not match the authored step key",
            )
        if template.channel.value != step.channel.value:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_CHANNEL_MISMATCH,
                severity,
                field,
                "bound template channel does not match the step channel",
            )
        if template.purpose != "paused_search":
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_PURPOSE_MISMATCH,
                severity,
                field,
                "template purpose must be paused_search",
            )
        if template.status is not TemplateStatus.APPROVED:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_NOT_APPROVED,
                severity,
                field,
                "template version must be approved before publication",
            )
        if any(
            variable not in ALLOWED_TEMPLATE_VARIABLES for variable in template.allowed_variables
        ):
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_VARIABLES_INVALID,
                severity,
                field,
                "template contains variables outside the approved renderer schema",
            )
        required_tags: set[str] = set()
        for reason_code in version.default_for_reason_codes:
            profile = capability_profile_for_reason(reason_code)
            if profile is not None:
                required_tags.update(profile.required_safety_tags)
        missing_tags = required_tags.difference(template.permitted_use_tags)
        if missing_tags:
            _add(
                findings,
                PausedSearchValidationCode.TEMPLATE_SAFETY_TAG_MISSING,
                severity,
                field,
                f"template is missing required safety tags: {', '.join(sorted(missing_tags))}",
            )


def _error(
    findings: list[PausedSearchValidationFinding],
    code: PausedSearchValidationCode,
    field: str,
) -> None:
    _add(findings, code, PausedSearchValidationSeverity.ERROR, field, code.value.replace("_", " "))


def _add(
    findings: list[PausedSearchValidationFinding],
    code: PausedSearchValidationCode,
    severity: PausedSearchValidationSeverity,
    field: str,
    detail: str,
) -> None:
    findings.append(PausedSearchValidationFinding(code, severity, field, detail))


def _finding_evidence(finding: PausedSearchValidationFinding) -> dict[str, str]:
    return {
        "code": finding.code.value,
        "severity": finding.severity.value,
        "field": finding.field,
        "detail": finding.detail,
    }
