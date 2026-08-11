import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.campaigns.paused_search_timing import (
    PausedSearchOccurrencePlan,
    PausedSearchTimingReasonCode,
    paused_search_duration_end,
    paused_search_step_occurrence_cap,
    plan_next_paused_search_occurrence,
)
from app.domain.campaigns.paused_search_tracks import (
    PausedSearchTrack,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.paused_search_validation import (
    PausedSearchTrackValidationReport,
    validate_paused_search_track,
    validation_report_evidence,
)
from app.domain.campaigns.template_registry import TemplateVersion
from app.domain.identity import AuthenticatedActor, PermissionCapability, evaluate_permission
from app.domain.leads import LeadPausedSearchProfile
from app.domain.workflows import LeadWorkflow


class PausedSearchTrackPreviewStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PausedSearchTrackPreviewOccurrence:
    plan: PausedSearchOccurrencePlan
    local_next_action_at: datetime | None
    channel: str
    review_required: bool


@dataclass(frozen=True)
class PausedSearchTrackPreviewResult:
    status: PausedSearchTrackPreviewStatus
    validation: PausedSearchTrackValidationReport
    preview_reference: str | None = None
    occurrences: tuple[PausedSearchTrackPreviewOccurrence, ...] = ()
    maximum_logical_touches: int = 0
    expires_at: datetime | None = None
    local_expires_at: datetime | None = None


async def preview_paused_search_track_version(
    *,
    actor: AuthenticatedActor,
    track: PausedSearchTrack,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    profile: LeadPausedSearchProfile,
    workflow: LeadWorkflow,
    timezone: str,
    now: datetime,
    templates: Mapping[UUID, TemplateVersion] | None = None,
    quiet_hours_enabled: bool = True,
    quiet_hours_start: time | None = time(10, 0),
    quiet_hours_end: time | None = time(17, 0),
) -> PausedSearchTrackPreviewResult:
    empty_report = PausedSearchTrackValidationReport(findings=())
    if not evaluate_permission(
        actor,
        PermissionCapability.LAUNCH_OR_PUBLISH_CAMPAIGN,
    ).allowed:
        return PausedSearchTrackPreviewResult(
            status=PausedSearchTrackPreviewStatus.REJECTED,
            validation=empty_report,
        )

    validation = validate_paused_search_track(
        track=track,
        version=version,
        steps=steps,
        for_publish=True,
        templates=templates,
    )
    reference = paused_search_preview_reference(track, version, steps, validation, templates)
    if not validation.publishable:
        return PausedSearchTrackPreviewResult(
            status=PausedSearchTrackPreviewStatus.BLOCKED,
            validation=validation,
            preview_reference=reference,
        )

    occurrences = _plan_occurrences(
        version=version,
        steps=steps,
        profile=profile,
        workflow=workflow,
        timezone=timezone,
        now=now,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )
    expires_at = paused_search_duration_end(
        workflow=workflow,
        track_version=version,
        timezone=timezone,
    )
    return PausedSearchTrackPreviewResult(
        status=PausedSearchTrackPreviewStatus.READY,
        validation=validation,
        preview_reference=reference,
        occurrences=occurrences,
        maximum_logical_touches=min(
            version.max_total_touches,
            sum(paused_search_step_occurrence_cap(step, version) for step in steps),
        ),
        expires_at=expires_at,
        local_expires_at=expires_at.astimezone(ZoneInfo(timezone)),
    )


def paused_search_preview_evidence(
    track: PausedSearchTrack,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    validation: PausedSearchTrackValidationReport,
    templates: Mapping[UUID, TemplateVersion] | None = None,
) -> dict[str, object]:
    return {
        "track_id": str(track.track_id),
        "track_version_id": str(version.track_version_id),
        "version_number": version.version_number,
        "selection_guidance": version.selection_guidance,
        "maximum_logical_touches": min(
            version.max_total_touches,
            sum(paused_search_step_occurrence_cap(step, version) for step in steps),
        ),
        "max_duration_days": version.max_duration_days,
        "terminal_behavior": version.terminal_behavior.value,
        "steps": [
            {
                "step_id": str(step.step_id),
                "step_order": step.step_order,
                "phase": step.phase.value,
                "channel": step.channel.value,
                "delay_hours": step.delay_hours,
                "interval_days": step.interval_days,
                "max_occurrences": step.max_occurrences,
                "review_required": step.review_required,
                "template_key": step.template_key,
                "template_version_id": (
                    str(step.template_version_id) if step.template_version_id is not None else None
                ),
                "template": _template_evidence(step.template_version_id, templates),
            }
            for step in sorted(steps, key=lambda item: item.step_order)
        ],
        "validation": validation_report_evidence(validation),
    }


def paused_search_preview_reference(
    track: PausedSearchTrack,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    validation: PausedSearchTrackValidationReport,
    templates: Mapping[UUID, TemplateVersion] | None = None,
) -> str:
    evidence = paused_search_preview_evidence(track, version, steps, validation, templates)
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _template_evidence(
    template_version_id: UUID | None,
    templates: Mapping[UUID, TemplateVersion] | None,
) -> dict[str, object] | None:
    if template_version_id is None or templates is None:
        return None
    template = templates.get(template_version_id)
    if template is None:
        return None
    return {
        "template_version_id": str(template.template_version_id),
        "template_key": template.template_key,
        "version": template.version,
        "channel": template.channel.value,
        "purpose": template.purpose,
        "status": template.status.value,
        "allowed_variables": list(template.allowed_variables),
        "permitted_use_tags": list(template.permitted_use_tags),
    }


def _plan_occurrences(
    *,
    version: PausedSearchTrackVersion,
    steps: tuple[PausedSearchTrackStep, ...],
    profile: LeadPausedSearchProfile,
    workflow: LeadWorkflow,
    timezone: str,
    now: datetime,
    quiet_hours_enabled: bool,
    quiet_hours_start: time | None,
    quiet_hours_end: time | None,
) -> tuple[PausedSearchTrackPreviewOccurrence, ...]:
    items: list[PausedSearchTrackPreviewOccurrence] = []
    scheduled_touches = 0
    for step in sorted(steps, key=lambda item: item.step_order):
        targeted_workflow = replace(workflow, paused_search_track_step_id=step.step_id)
        previous_due_at: datetime | None = None
        occurrence_cap = paused_search_step_occurrence_cap(step, version)
        for occurrence_number in range(1, occurrence_cap + 1):
            planning_now = _planning_now_for_step(
                step=step,
                profile=profile,
                version=version,
                now=now,
            )
            plan = plan_next_paused_search_occurrence(
                profile=profile,
                track_version=version,
                step=step,
                steps=steps,
                workflow=targeted_workflow,
                timezone=timezone,
                now=planning_now,
                occurrence_number=occurrence_number,
                previous_due_at=previous_due_at,
                quiet_hours_enabled=quiet_hours_enabled,
                quiet_hours_start=quiet_hours_start,
                quiet_hours_end=quiet_hours_end,
            )
            if plan.reason_code is PausedSearchTimingReasonCode.MAINTENANCE_WINDOW_ENDED:
                break
            items.append(
                PausedSearchTrackPreviewOccurrence(
                    plan=plan,
                    local_next_action_at=(
                        plan.next_action_at.astimezone(ZoneInfo(timezone))
                        if plan.next_action_at is not None
                        else None
                    ),
                    channel=step.channel.value,
                    review_required=step.review_required,
                )
            )
            if plan.reason_code is not PausedSearchTimingReasonCode.SCHEDULED:
                break
            scheduled_touches += 1
            if scheduled_touches >= version.max_total_touches:
                return tuple(items)
            previous_due_at = plan.due_at
    return tuple(items)


def _planning_now_for_step(
    *,
    step: PausedSearchTrackStep,
    profile: LeadPausedSearchProfile,
    version: PausedSearchTrackVersion,
    now: datetime,
) -> datetime:
    if step.phase is not PausedSearchTrackStepPhase.REACTIVATION:
        return now
    if profile.reengagement_not_before is None:
        return now
    boundary = profile.reengagement_not_before - timedelta(
        days=version.reactivation_window_days
    )
    return max(now, boundary)
