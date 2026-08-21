from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.services.paused_search_track_assignment import (
    PausedSearchProgressHandling,
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
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import (
    LeadWorkflow,
    WorkflowState,
    WorkflowTransitionReasonCode,
)
from tests.application.use_cases._campaign_cadence_fakes import FakeLeadWorkflowRepository
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)
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
OTHER_VERSION_ID = UUID("00000000-0000-0000-0000-000000000009")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000010")
ENROLLMENT_ID = UUID("00000000-0000-0000-0000-000000000008")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000007")


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
async def test_clear_with_track_pinned_workflow_never_restarts() -> None:
    """Clearing a track is not a lifecycle restart: it releases the assignment
    and leaves the live run pinned (so the caller can terminalize it with the
    track still recorded). Starting the next journey — dormant or another
    track — is a separate explicit admin enrollment decision, never a side
    effect of the clear."""
    assignments = FakePausedSearchTrackAssignmentRepository((_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        clear=True,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.CLEARED
    assert result.error is None
    assert result.assignment is None
    assert assignments.assignments[0].released_at == NOW
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.state is WorkflowState.ACTIVE_NURTURE
    assert result.workflow.paused_search_track_version_id == VERSION_ID
    assert starter.calls == []
    assert transitions.transitions == {}


@pytest.mark.asyncio
async def test_clear_with_dormant_workflow_is_a_noop_repin() -> None:
    """A workflow already on the dormant journey is not restarted by a clear."""
    assignments = FakePausedSearchTrackAssignmentRepository()
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=None,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        clear=True,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.CLEARED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.state is WorkflowState.ACTIVE_NURTURE
    assert starter.calls == []
    assert transitions.transitions == {}


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


@pytest.mark.asyncio
async def test_reassignment_closes_old_workflow_and_starts_fresh_run() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_other_track_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=OTHER_VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.REASSIGNED
    assert result.error is None
    old_workflow = workflows.workflows[WORKFLOW_ID]
    assert old_workflow.state is WorkflowState.CLOSED
    assert any(
        transition.reason_code is WorkflowTransitionReasonCode.TRACK_REASSIGNED
        for transition in transitions.transitions.values()
    )
    new_workflow = result.workflow
    assert new_workflow is not None
    assert new_workflow.workflow_id != WORKFLOW_ID
    assert new_workflow.state is WorkflowState.ACTIVE_NURTURE
    assert new_workflow.paused_search_track_version_id == VERSION_ID
    assert new_workflow.logical_touch_count == 0
    assert new_workflow.campaign_enrollment_id != ENROLLMENT_ID
    start_calls = [call for call in starter.calls if "execution_mode" in call]
    assert len(start_calls) == 1
    assert start_calls[0]["temporal_workflow_id"] == new_workflow.temporal_workflow_id
    assert start_calls[0]["paused_search_track_version_id"] == VERSION_ID


@pytest.mark.asyncio
async def test_dormant_workflow_closes_and_starts_fresh_run_when_track_assigned() -> None:
    """Dormant → track is a lifecycle event: old run ends, a fresh run starts at zero."""
    assignments = FakePausedSearchTrackAssignmentRepository()
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        replace(
            _workflow(
                state=WorkflowState.ACTIVE_NURTURE,
                paused_search_track_version_id=None,
            ),
            logical_touch_count=1,
            ai_interaction_count=2,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.REASSIGNED
    assert result.error is None
    assert workflows.workflows[WORKFLOW_ID].state is WorkflowState.CLOSED
    reassigned = [
        transition
        for transition in transitions.transitions.values()
        if transition.reason_code is WorkflowTransitionReasonCode.TRACK_REASSIGNED
    ]
    assert len(reassigned) == 1
    assert reassigned[0].metadata["previous_track_version_id"] == "dormant"
    new_workflow = result.workflow
    assert new_workflow is not None
    assert new_workflow.workflow_id != WORKFLOW_ID
    assert new_workflow.state is WorkflowState.ACTIVE_NURTURE
    assert new_workflow.paused_search_track_version_id == VERSION_ID
    assert new_workflow.logical_touch_count == 0
    assert new_workflow.ai_interaction_count == 0


@pytest.mark.asyncio
async def test_dormant_workflow_continue_repins_instead_of_restarting() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository()
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=None,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
        progress_handling=PausedSearchProgressHandling.CONTINUE,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.paused_search_track_version_id == VERSION_ID
    assert starter.calls == []
    assert transitions.transitions == {}


@pytest.mark.asyncio
async def test_reassignment_without_lifecycle_deps_falls_back_to_repin() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_other_track_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=OTHER_VERSION_ID,
        )
    )

    result = await _synchronize(assignments=assignments, workflows=workflows)

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.paused_search_track_version_id == VERSION_ID


@pytest.mark.asyncio
async def test_reassignment_skips_human_paused_workflow() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_other_track_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.PAUSED,
            paused_search_track_version_id=OTHER_VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.state is WorkflowState.PAUSED
    assert starter.calls == []


@pytest.mark.asyncio
async def test_reassignment_repins_when_enrollment_row_is_missing() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_other_track_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=OTHER_VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.error == "enrollment_missing_for_reassignment"
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.paused_search_track_version_id == VERSION_ID
    assert starter.calls == []


@pytest.mark.asyncio
async def test_continue_on_different_track_repins_and_clears_step_cursor() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_other_track_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        replace(
            _workflow(
                state=WorkflowState.ACTIVE_NURTURE,
                paused_search_track_version_id=OTHER_VERSION_ID,
            ),
            paused_search_track_step_id=UUID("00000000-0000-0000-0000-000000000020"),
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
        progress_handling=PausedSearchProgressHandling.CONTINUE,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.state is WorkflowState.ACTIVE_NURTURE
    assert result.workflow.paused_search_track_version_id == VERSION_ID
    assert result.workflow.paused_search_track_step_id is None
    assert starter.calls == []
    assert transitions.transitions == {}


@pytest.mark.asyncio
async def test_restart_on_same_track_closes_and_starts_fresh_run() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
        progress_handling=PausedSearchProgressHandling.RESTART,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.REASSIGNED
    assert result.error is None
    assert workflows.workflows[WORKFLOW_ID].state is WorkflowState.CLOSED
    assert any(
        transition.reason_code is WorkflowTransitionReasonCode.TRACK_REASSIGNED
        for transition in transitions.transitions.values()
    )
    new_workflow = result.workflow
    assert new_workflow is not None
    assert new_workflow.workflow_id != WORKFLOW_ID
    assert new_workflow.state is WorkflowState.ACTIVE_NURTURE
    assert new_workflow.paused_search_track_version_id == VERSION_ID
    assert new_workflow.logical_touch_count == 0


@pytest.mark.asyncio
async def test_same_track_without_progress_handling_is_a_noop_repin() -> None:
    assignments = FakePausedSearchTrackAssignmentRepository((_assignment(),))
    workflows = FakeLeadWorkflowRepository()
    await workflows.save(
        _workflow(
            state=WorkflowState.ACTIVE_NURTURE,
            paused_search_track_version_id=VERSION_ID,
        )
    )
    transitions = FakeWorkflowTransitionRepository()
    enrollments = FakeCampaignEnrollmentRepository()
    await enrollments.save(_enrollment())
    starter = FakeTemporalWorkflowStarter()

    result = await _synchronize(
        assignments=assignments,
        workflows=workflows,
        workflow_transitions=transitions,
        enrollments=enrollments,
        starter=starter,
    )

    assert result.status is PausedSearchTrackAssignmentSyncStatus.RESOLVED
    assert result.workflow is not None
    assert result.workflow.workflow_id == WORKFLOW_ID
    assert result.workflow.state is WorkflowState.ACTIVE_NURTURE
    assert starter.calls == []
    assert transitions.transitions == {}


async def _synchronize(
    *,
    assignments: FakePausedSearchTrackAssignmentRepository,
    workflows: FakeLeadWorkflowRepository,
    clear: bool = False,
    repository: FakePausedSearchTrackAdminRepository | None = None,
    workflow_transitions: FakeWorkflowTransitionRepository | None = None,
    enrollments: FakeCampaignEnrollmentRepository | None = None,
    starter: FakeTemporalWorkflowStarter | None = None,
    progress_handling: PausedSearchProgressHandling | None = None,
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
        workflow_transition_repository=workflow_transitions,
        campaign_enrollment_repository=enrollments,
        temporal_workflow_starter=starter,
        progress_handling=progress_handling,
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


def _other_track_assignment() -> PausedSearchTrackAssignment:
    return replace(
        _assignment(),
        assignment_id=UUID("00000000-0000-0000-0000-000000000016"),
        track_version_id=OTHER_VERSION_ID,
        track_version_snapshot=2,
    )


def _enrollment() -> CampaignEnrollment:
    return CampaignEnrollment(
        campaign_enrollment_id=ENROLLMENT_ID,
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=UUID("00000000-0000-0000-0000-000000000011"),
        lead_id=LEAD_ID,
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        status=CampaignEnrollmentStatus.ACTIVE,
        eligible_at=NOW,
        enrolled_at=NOW,
        started_at=NOW,
        ended_at=None,
        created_by_user_id=USER_ID,
        reason_codes=("manual",),
        created_at=NOW,
        updated_at=NOW,
    )


def _workflow(
    *,
    paused_search_track_version_id: UUID | None = None,
    state: WorkflowState = WorkflowState.PAUSED,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture:test",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=state,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )