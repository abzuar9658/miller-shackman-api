from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.application.use_cases.schedule_next_paused_search_action import (
    PausedSearchScheduleStatus,
    schedule_next_paused_search_action,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTimingReasonCode,
    PausedSearchTrackFamily,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import PausedSearchTrackVersionId
from app.domain.compliance.contactability import ContactChannel as DomainContactChannel
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
    PausedSearchReasonCode,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)

WORKSPACE_ID = uuid4()
LEAD_ID = uuid4()
TRACK_VERSION_ID = uuid4()
TRACK_ID = uuid4()
USER_ID = uuid4()
STEP_ONE_ID = uuid4()
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
TIMEZONE = "America/Chicago"


def _lead(*, paused_search_active: bool = True) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="fub-1",
        facts_derived_at=NOW,
        source_payload_version="1",
        lead_type=LeadType.BUYER,
        paused_search_active=paused_search_active,
        pause_reason_code=PausedSearchReasonCode.RENTED_TEMPORARILY,
        reengagement_not_before=NOW + timedelta(days=120),
        paused_search_source=PausedSearchSource.OPERATOR,
        paused_search_recorded_at=NOW,
    )


def _track_version() -> PausedSearchTrackVersion:
    return PausedSearchTrackVersion(
        track_version_id=TRACK_VERSION_ID,
        workspace_id=WORKSPACE_ID,
        track_id=TRACK_ID,
        version_number=1,
        status=CampaignVersionStatus.PUBLISHED,
        track_family=PausedSearchTrackFamily.MAINTENANCE,
        enabled=True,
        allowed_channels=(DomainContactChannel.EMAIL,),
        default_for_reason_codes=(PausedSearchReasonCode.RENTED_TEMPORARILY,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=5,
        requires_review_before_publish=False,
        created_by_user_id=USER_ID,
        created_at=NOW,
        published_at=NOW,
    )


def _step() -> PausedSearchTrackStep:
    return PausedSearchTrackStep(
        step_id=STEP_ONE_ID,
        workspace_id=WORKSPACE_ID,
        track_version_id=TRACK_VERSION_ID,
        step_order=1,
        phase=PausedSearchTrackStepPhase.MAINTENANCE,
        channel=DomainContactChannel.EMAIL,
        delay_hours=24 * 60,
        message_goal="First maintenance touch",
        template_key="paused-search-maintenance-1",
        max_attempts=1,
        review_required=False,
        created_at=NOW,
    )


def _workflow(
    *,
    paused_search_track_version_id: PausedSearchTrackVersionId | None = TRACK_VERSION_ID,
) -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=uuid4(),
        temporal_workflow_id="wf-1",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=uuid4(),
        campaign_id=uuid4(),
        lead_id=LEAD_ID,
        state=WorkflowState.ACTIVE_NURTURE,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
        paused_search_track_version_id=paused_search_track_version_id,
    )


async def test_no_workflow_returns_no_workflow() -> None:
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.NO_WORKFLOW


async def test_no_pinned_track_returns_no_track() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow(paused_search_track_version_id=None))
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.NO_TRACK
    assert result.reason_code == PausedSearchTimingReasonCode.TRACK_UNAVAILABLE


async def test_lead_not_paused_search_returns_hold() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(_step(),),
    )
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead(paused_search_active=False)),
        paused_search_track_repository=track_repo,
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.HOLD
    assert result.reason_code == PausedSearchTimingReasonCode.PROFILE_NOT_ACTIVE


async def test_missing_track_version_returns_no_track() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.NO_TRACK


async def test_schedules_and_persists_next_action() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(_step(),),
    )
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=track_repo,
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.SCHEDULED
    assert result.step_id == STEP_ONE_ID
    assert result.next_action_at == (NOW + timedelta(hours=24 * 60)).replace(hour=15, minute=0)
    assert result.phase == PausedSearchTrackStepPhase.MAINTENANCE

    saved = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved.paused_search_track_step_id == STEP_ONE_ID
    assert saved.next_action_at == result.next_action_at


async def test_hold_clears_step_and_next_action() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(_step(),),
    )
    lead = _lead()
    lead = replace(lead, paused_search_active=False)
    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(lead),
        paused_search_track_repository=track_repo,
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
    )
    assert result.status == PausedSearchScheduleStatus.HOLD

    saved = workflow_repo.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert saved.paused_search_track_step_id is None
    assert saved.next_action_at is None
