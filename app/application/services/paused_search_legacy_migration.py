from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from app.domain.campaigns import (
    PausedSearchTrackStepPhase,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.common.ids import PausedSearchTrackVersionId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel


class LegacyMigrationOutcome(StrEnum):
    MIGRATED = "migrated"
    HOLD_FOR_REVIEW = "hold_for_review"


class LegacyMigrationReason(StrEnum):
    MIGRATED_BASELINE = "migrated_baseline"
    INCOMPLETE_CURSOR = "incomplete_cursor"
    TOUCH_LIMIT_AT_MIGRATION = "touch_limit_at_migration"


@dataclass(frozen=True)
class LegacyPausedSearchMigrationInput:
    workspace_id: WorkspaceId
    lead_id: UUID
    workflow_id: UUID
    track_version_id: PausedSearchTrackVersionId | None
    step_id: UUID | None
    phase: PausedSearchTrackStepPhase | None
    channel: ContactChannel | None
    next_action_at: datetime | None
    logical_touch_count: int
    max_total_touches: int
    timezone: str


@dataclass(frozen=True)
class LegacyPausedSearchMigrationPlan:
    outcome: LegacyMigrationOutcome
    reason: LegacyMigrationReason
    occurrence: RecurringOccurrence | None
    terminalize_workflow: bool = False


def plan_legacy_paused_search_migration(
    *,
    input_: LegacyPausedSearchMigrationInput,
    now: datetime,
) -> LegacyPausedSearchMigrationPlan:
    required = (
        input_.track_version_id,
        input_.step_id,
        input_.phase,
        input_.channel,
        input_.next_action_at,
    )
    if any(value is None for value in required):
        return LegacyPausedSearchMigrationPlan(
            outcome=LegacyMigrationOutcome.HOLD_FOR_REVIEW,
            reason=LegacyMigrationReason.INCOMPLETE_CURSOR,
            occurrence=None,
        )

    assert input_.track_version_id is not None
    assert input_.step_id is not None
    assert input_.phase is not None
    assert input_.channel is not None
    assert input_.next_action_at is not None

    occurrence_id = uuid5(input_.workflow_id, "paused-search-migrated-legacy-baseline")
    occurrence = RecurringOccurrence(
        occurrence_id=occurrence_id,
        workspace_id=input_.workspace_id,
        lead_id=input_.lead_id,
        workflow_id=input_.workflow_id,
        track_version_id=input_.track_version_id,
        step_id=input_.step_id,
        phase=input_.phase,
        occurrence_number=0,
        scheduled_for=input_.next_action_at,
        due_at=input_.next_action_at,
        status=RecurringOccurrenceStatus.MIGRATED_LEGACY,
        idempotency_key=(
            f"legacy-migrated:{input_.workflow_id}:{input_.track_version_id}:{input_.step_id}"
        ),
        created_at=now,
        logical_touch_count=0,
        timezone_snapshot=input_.timezone,
    )
    at_touch_limit = input_.logical_touch_count >= input_.max_total_touches
    return LegacyPausedSearchMigrationPlan(
        outcome=LegacyMigrationOutcome.MIGRATED,
        reason=(
            LegacyMigrationReason.TOUCH_LIMIT_AT_MIGRATION
            if at_touch_limit
            else LegacyMigrationReason.MIGRATED_BASELINE
        ),
        occurrence=occurrence,
        terminalize_workflow=at_touch_limit,
    )
