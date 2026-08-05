from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.services.paused_search_track_assignment import (
    PausedSearchTrackAssignmentSyncResult,
    PausedSearchTrackAssignmentSyncStatus,
    synchronize_paused_search_track_assignment,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTrack,
    PausedSearchTrackAssignment,
    PausedSearchTrackAssignmentSource,
    PausedSearchTrackStatus,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import FakeLeadWorkflowRepository
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
    FakePausedSearchTrackAssignmentRepository,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_ID = UUID("00000000-0000-0000-0000-000000000003")
TRACK_ID = UUID("00000000-0000-0000-0000-000000000004")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000005")


@pytest.mark.asyncio
async def test_active_profile_creates_assignment_then_pins_workflow() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository()
    workflows = FakeLeadWorkflowRepository()

    first = await _synchronize(assignments=assignments, workflows=workflows)

    assert first.assignment is not None
    assert first.workflow is None
    await workflows.save(_workflow())

    second = await _synchronize(assignments=assignments, workflows=workflows)

    assert second.assignment == first.assignment
    assert second.workflow is not None
    assert second.workflow.paused_search_track_version_id == VERSION_ID
    assert len(assignments.assignments) == 1


@pytest.mark.asyncio
async def test_clear_releases_assignment_and_clears_workflow_pin() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(_workflow(paused_search_track_version_id=VERSION_ID))

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        clear=True,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.CLEARED
    assert result.assignment is None
    assert result.workflow is not None
    assert result.workflow.paused_search_track_version_id is None
    assert assignments.assignments[0].released_at == NOW


@pytest.mark.asyncio
async def test_unmapped_or_retired_track_preserves_assignment_and_pin() -> None:
    assignment = _assignment()
    assignments = FakePausedSearchTrackAssignmentRepository((assignment,))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(_workflow(paused_search_track_version_id=VERSION_ID))
    repository = _track_repository(track=replace(_track(), status=PausedSearchTrackStatus.RETIRED))

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        repository=repository,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.PRESERVED
    assert result.assignment == assignment
    assert result.workflow is not None
    assert result.workflow.paused_search_track_version_id == VERSION_ID
    assert len(assignments.assignments) == 1


async def _synchronize(
    *,
    assignments: FakePausedSearchTrackAssignmentRepository,
    workflows: FakeLeadWorkflowRepository,
    clear: bool = False,
    repository: FakePausedSearchTrackAdminRepository | None = None,
) -> PausedSearchTrackAssignmentSyncResult:
    return await synchronize_paused_search_track_assignment(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        clear=clear,
        actor_user_id=USER_ID,
        source=PausedSearchTrackAssignmentSource.CLASSIFICATION,
        assignment_repository=assignments,
        track_repository=repository or _track_repository(),
        lead_workflow_repository=workflows,
        now=NOW,
        target_track_version_id=None if clear else VERSION_ID,
    )


def _track_repository(
    *,
    track: PausedSearchTrack | None = None,
) -> FakePausedSearchTrackAdminRepository:
    return FakePausedSearchTrackAdminRepository(
        tracks=(track or _track(),),
        versions=(_version(),),
    )


def _track() -> PausedSearchTrack:
    return PausedSearchTrack(
        track_id=TRACK_ID,
        workspace_id=WORKSPACE_ID,
        track_key="waiting-rates",
        display_name="Waiting for rates",
        status=PausedSearchTrackStatus.ACTIVE,
        active_version_id=VERSION_ID,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        selection_guidance="Select when a paused lead needs periodic follow-up.",
        enabled=True,
        allowed_channels=(ContactChannel.EMAIL,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_REENGAGEMENT_NOT_BEFORE,
        maintenance_interval_days=90,
        reactivation_window_days=30,
        max_total_touches=2,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _assignment() -> PausedSearchTrackAssignment:
    return PausedSearchTrackAssignment(
        assignment_id=UUID("00000000-0000-0000-0000-000000000006"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        track_id=TRACK_ID,
        track_version_id=VERSION_ID,
        track_key_snapshot="waiting-rates",
        track_name_snapshot="Waiting for rates",
        track_version_snapshot=1,
        source=PausedSearchTrackAssignmentSource.CLASSIFICATION,
        assigned_by_user_id=USER_ID,
        assigned_at=NOW,
    )


def _workflow(*, paused_search_track_version_id: UUID | None = None) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=UUID("00000000-0000-0000-0000-000000000007"),
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000008"),
        campaign_id=UUID("00000000-0000-0000-0000-000000000010"),
        lead_id=LEAD_ID,
        state=WorkflowState.PAUSED,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )