from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.domain.campaigns.paused_search_tracks import (
    PausedSearchChannelSequence,
    PausedSearchStepAction,
    PausedSearchTrack,
    PausedSearchTrackMode,
    PausedSearchTrackStep,
    PausedSearchTrackVersion,
    effective_paused_search_step_action,
    paused_search_interim_contact_is_configured,
)
from app.domain.campaigns.template_registry import (
    ALLOWED_TEMPLATE_VARIABLES,
    TemplateStatus,
    TemplateVersion,
)

MAX_AI_TOUCHES_PER_TRACK = 5
MAX_PAUSED_SEARCH_CYCLES = 12
UNIVERSAL_PAUSED_SEARCH_SAFETY_TAGS = frozenset(
    {
        "no_prohibited_advice",
        "no_financial_advice",
        "no_legal_advice",
        "no_tax_advice",
        "no_investment_advice",
        "no_market_predictions",
        "no_unverified_listing_claims",
    }
)


class PausedSearchValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class PausedSearchValidationCode(StrEnum):
    EMPTY_TRACK_KEY = "empty_track_key"
    EMPTY_DISPLAY_NAME = "empty_display_name"
    NO_ALLOWED_CHANNELS = "no_allowed_channels"
    INVALID_SELECTION_GUIDANCE = "invalid_selection_guidance"
    INVALID_MAINTENANCE_INTERVAL = "invalid_maintenance_interval"
    INVALID_REACTIVATION_WINDOW = "invalid_reactivation_window"
    INVALID_TOUCH_LIMIT = "invalid_touch_limit"
    INVALID_DURATION = "invalid_duration"
    INVALID_CYCLE_LIMIT = "invalid_cycle_limit"
    INVALID_AI_INTERACTION_LIMIT = "invalid_ai_interaction_limit"
    INTERIM_PERMISSION_REQUIRED = "interim_permission_required"
    INVALID_STEP_ACTION = "invalid_step_action"
    INCOMPATIBLE_STEP_ACTION = "incompatible_step_action"
    UNSUPPORTED_CHANNEL_SEQUENCE = "unsupported_channel_sequence"
    NO_STEPS = "no_steps"
    INVALID_STEP_ORDER = "invalid_step_order"
    STEP_CHANNEL_NOT_ALLOWED = "step_channel_not_allowed"
    INVALID_STEP_DELAY = "invalid_step_delay"
    EMPTY_MESSAGE_GOAL = "empty_message_goal"
    EMPTY_TEMPLATE_KEY = "empty_template_key"
    INVALID_MAX_ATTEMPTS = "invalid_max_attempts"
    INVALID_MAX_OCCURRENCES = "invalid_max_occurrences"
    INVALID_RECURRING_INTERVAL = "invalid_recurring_interval"
    VERSION_DISABLED = "version_disabled"
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
    if templates is not None:
        _validate_templates(version, steps, templates, findings)
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
    if not 30 <= len(version.selection_guidance.strip()) <= 1000:
        _error(
            findings,
            PausedSearchValidationCode.INVALID_SELECTION_GUIDANCE,
            "selection_guidance",
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
    if not 0 < version.max_cycles <= MAX_PAUSED_SEARCH_CYCLES:
        _error(findings, PausedSearchValidationCode.INVALID_CYCLE_LIMIT, "max_cycles")
    if not 0 < version.max_ai_interactions <= MAX_AI_TOUCHES_PER_TRACK:
        _error(
            findings,
            PausedSearchValidationCode.INVALID_AI_INTERACTION_LIMIT,
            "max_ai_interactions",
        )
    if (
        version.track_mode is PausedSearchTrackMode.PERMISSION_BASED_INTERIM_CONTACT
        and not paused_search_interim_contact_is_configured(version.interim_contact_policy)
    ):
        _error(
            findings,
            PausedSearchValidationCode.INTERIM_PERMISSION_REQUIRED,
            "interim_contact_policy",
        )
    if version.channel_sequence is PausedSearchChannelSequence.SIMULTANEOUS:
        _error(
            findings,
            PausedSearchValidationCode.UNSUPPORTED_CHANNEL_SEQUENCE,
            "channel_sequence",
        )
    if not steps:
        _error(findings, PausedSearchValidationCode.NO_STEPS, "steps")
    if for_publish and not version.enabled:
        _error(findings, PausedSearchValidationCode.VERSION_DISABLED, "enabled")


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
        action = effective_paused_search_step_action(step)
        if step.action is not None and not isinstance(step.action, PausedSearchStepAction):
            _error(findings, PausedSearchValidationCode.INVALID_STEP_ACTION, f"{field}.action")
        if action is PausedSearchStepAction.SEND and step.review_required:
            _error(
                findings,
                PausedSearchValidationCode.INCOMPATIBLE_STEP_ACTION,
                f"{field}.action",
            )
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
        if (
            step.phase.value == "maintenance"
            and step.interval_days is not None
            and step.max_occurrences > 1
            and not paused_search_interim_contact_is_configured(version.interim_contact_policy)
        ):
            _error(
                findings,
                PausedSearchValidationCode.INTERIM_PERMISSION_REQUIRED,
                f"{field}.interval_days",
            )


def _validate_templates(
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    templates: Mapping[UUID, TemplateVersion],
    findings: list[PausedSearchValidationFinding],
) -> None:
    for index, step in enumerate(steps):
        field = f"steps[{index}].template_version_id"
        severity = PausedSearchValidationSeverity.ERROR
        if step.template_profile is not None:
            continue
        template = (
            templates.get(step.template_version_id)
            if step.template_version_id is not None
            else None
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
        required_tags = UNIVERSAL_PAUSED_SEARCH_SAFETY_TAGS
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
