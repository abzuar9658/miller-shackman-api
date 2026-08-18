from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from app.application.ports.repositories import PausedSearchOccurrenceRepository
from app.application.use_cases.schedule_next_paused_search_action import (
    PausedSearchScheduleStatus,
    schedule_next_paused_search_action,
)
from app.domain.campaigns import (
    PausedSearchFallbackTimingPolicy,
    PausedSearchTerminalBehavior,
    PausedSearchTimingBasis,
    PausedSearchTimingReasonCode,
    PausedSearchTrackStep,
    PausedSearchTrackStepPhase,
    PausedSearchTrackVersion,
    RecurringOccurrence,
    RecurringOccurrenceStatus,
)
from app.domain.campaigns.enrollment import (
    CampaignEnrollment,
    CampaignEnrollmentSource,
    CampaignEnrollmentStatus,
)
from app.domain.campaigns.execution import CampaignVersionStatus
from app.domain.common.ids import PausedSearchTrackVersionId
from app.domain.compliance.contactability import (
    ContactChannel as DomainContactChannel,
)
from app.domain.compliance.contactability import (
    WorkspaceContactPolicy,
)
from app.domain.leads import (
    CanonicalLeadRecord,
    CRMProvider,
    LeadType,
    PausedSearchSource,
)
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.domain.workspace_automation import WorkspaceOperationalControl
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceOperationalControlRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
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


class _FakeOccurrenceRepository:
    def __init__(self) -> None:
        self.saved: list[RecurringOccurrence] = []

    async def get_latest_for_step(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
    ) -> RecurringOccurrence | None:
        matches = [
            occurrence
            for occurrence in self.saved
            if occurrence.workspace_id == workspace_id
            and occurrence.workflow_id == workflow_id
            and occurrence.track_version_id == track_version_id
            and occurrence.step_id == step_id
        ]
        return max(
            matches,
            key=lambda occurrence: (occurrence.occurrence_number, occurrence.scheduled_for),
            default=None,
        )

    async def get_by_identity(
        self,
        workspace_id: UUID,
        workflow_id: UUID,
        track_version_id: PausedSearchTrackVersionId,
        step_id: UUID,
        occurrence_number: int,
        scheduled_for: datetime,
    ) -> RecurringOccurrence | None:
        return next(
            (
                occurrence
                for occurrence in self.saved
                if occurrence.workspace_id == workspace_id
                and occurrence.workflow_id == workflow_id
                and occurrence.track_version_id == track_version_id
                and occurrence.step_id == step_id
                and occurrence.occurrence_number == occurrence_number
                and occurrence.scheduled_for == scheduled_for
            ),
            None,
        )

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> RecurringOccurrence | None:
        return next(
            (
                occurrence
                for occurrence in self.saved
                if occurrence.workspace_id == workspace_id
                and occurrence.idempotency_key == idempotency_key
            ),
            None,
        )

    async def create_or_get(self, occurrence: RecurringOccurrence) -> RecurringOccurrence:
        existing_by_key = await self.get_by_idempotency_key(
            occurrence.workspace_id,
            occurrence.idempotency_key,
        )
        if existing_by_key is not None:
            return existing_by_key
        existing = await self.get_by_identity(
            occurrence.workspace_id,
            occurrence.workflow_id,
            occurrence.track_version_id,
            occurrence.step_id,
            occurrence.occurrence_number,
            occurrence.scheduled_for,
        )
        if existing is not None:
            return existing
        self.saved.append(occurrence)
        return occurrence

    async def reopen_failed_for_retry(
        self,
        *,
        workspace_id: UUID,
        occurrence_id: UUID,
        scheduled_for: datetime,
        due_at: datetime,
        now: datetime,
    ) -> RecurringOccurrence | None:
        for index, occurrence in enumerate(self.saved):
            if (
                occurrence.workspace_id == workspace_id
                and occurrence.occurrence_id == occurrence_id
                and occurrence.status is RecurringOccurrenceStatus.FAILED
            ):
                reopened = replace(
                    occurrence,
                    status=RecurringOccurrenceStatus.PLANNED,
                    scheduled_for=scheduled_for,
                    due_at=due_at,
                    closed_at=None,
                    provider_message_id=None,
                    provider_delivery_status=None,
                )
                self.saved[index] = reopened
                return reopened
        return None


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
        paused_search_track_key="rented-year",
        paused_search_track_version_id=TRACK_VERSION_ID,
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
        selection_guidance="Select when a paused lead needs periodic follow-up.",
        enabled=True,
        allowed_channels=(DomainContactChannel.EMAIL,),
        fallback_timing_policy=PausedSearchFallbackTimingPolicy.USE_MAINTENANCE_INTERVAL,
        maintenance_interval_days=60,
        reactivation_window_days=30,
        max_total_touches=5,
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


async def test_recurring_schedule_is_idempotent_and_stops_at_limit() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(replace(_step(), delay_hours=0, interval_days=30, max_occurrences=2),),
    )
    kwargs: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "lead_id": LEAD_ID,
        "lead_repository": FakeLeadRepository(_lead()),
        "paused_search_track_repository": track_repo,
        "lead_workflow_repository": workflow_repo,
        "timezone": TIMEZONE,
        "now": NOW,
        "occurrence_repository": occurrence_repo,
    }

    first = await schedule_next_paused_search_action(**kwargs)
    duplicate = await schedule_next_paused_search_action(**kwargs)
    assert first.occurrence is not None
    assert duplicate.occurrence == first.occurrence
    assert len(occurrence_repo.saved) == 1

    occurrence_repo.saved[0] = replace(
        occurrence_repo.saved[0], status=RecurringOccurrenceStatus.SENT
    )
    second = await schedule_next_paused_search_action(**kwargs)
    assert second.occurrence is not None
    assert second.occurrence.occurrence_number == 2
    assert len(occurrence_repo.saved) == 2

    occurrence_repo.saved[1] = replace(
        occurrence_repo.saved[1], status=RecurringOccurrenceStatus.SENT
    )
    terminal = await schedule_next_paused_search_action(**kwargs)
    assert terminal.status == PausedSearchScheduleStatus.TERMINAL
    assert terminal.reason_code == PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED


async def test_failed_occurrence_is_retried_without_consuming_cap() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(replace(_step(), delay_hours=0, interval_days=30, max_occurrences=2),),
    )
    kwargs: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "lead_id": LEAD_ID,
        "lead_repository": FakeLeadRepository(_lead()),
        "paused_search_track_repository": track_repo,
        "lead_workflow_repository": workflow_repo,
        "timezone": TIMEZONE,
        "now": NOW,
        "occurrence_repository": occurrence_repo,
    }

    first = await schedule_next_paused_search_action(**kwargs)
    assert first.occurrence is not None
    assert first.occurrence.occurrence_number == 1
    failed = replace(
        occurrence_repo.saved[0],
        status=RecurringOccurrenceStatus.FAILED,
        failure_reason="provider send failed",
    )
    occurrence_repo.saved[0] = failed

    retry = await schedule_next_paused_search_action(
        **{**kwargs, "now": NOW + timedelta(hours=1)}
    )
    assert retry.status == PausedSearchScheduleStatus.SCHEDULED
    assert retry.occurrence is not None
    assert retry.occurrence.occurrence_number == 1
    assert retry.occurrence.occurrence_id == failed.occurrence_id
    assert retry.occurrence.status is RecurringOccurrenceStatus.PLANNED
    assert retry.occurrence.closed_at is None
    assert len(occurrence_repo.saved) == 1

    # The retried slot completes; the second slot is still available because
    # the failed attempt did not consume it.
    occurrence_repo.saved[0] = replace(
        occurrence_repo.saved[0], status=RecurringOccurrenceStatus.SENT
    )
    second = await schedule_next_paused_search_action(
        **{**kwargs, "now": NOW + timedelta(hours=2)}
    )
    assert second.occurrence is not None
    assert second.occurrence.occurrence_number == 2
    assert len(occurrence_repo.saved) == 2

    occurrence_repo.saved[1] = replace(
        occurrence_repo.saved[1], status=RecurringOccurrenceStatus.SENT
    )
    terminal = await schedule_next_paused_search_action(
        **{**kwargs, "now": NOW + timedelta(hours=3)}
    )
    assert terminal.status == PausedSearchScheduleStatus.TERMINAL
    assert terminal.reason_code == PausedSearchTimingReasonCode.OCCURRENCE_LIMIT_REACHED


async def test_pre_send_blocked_occurrence_is_retried_after_resume() -> None:
    """A pre-send-rejected occurrence never reached the lead, so a manual
    resume must retry the same slot instead of terminalizing the workflow.

    Reproduces the production failure where resume-after-frequency-block went
    straight to COMPLETED with occurrence_limit_reached.
    """
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    transition_repo = FakeWorkflowTransitionRepository()
    track_repo = FakePausedSearchTrackAdminRepository(
        versions=(_track_version(),),
        steps=(replace(_step(), delay_hours=0, max_occurrences=1),),
    )
    kwargs: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "lead_id": LEAD_ID,
        "lead_repository": FakeLeadRepository(_lead()),
        "paused_search_track_repository": track_repo,
        "lead_workflow_repository": workflow_repo,
        "workflow_transition_repository": transition_repo,
        "timezone": TIMEZONE,
        "now": NOW,
        "occurrence_repository": occurrence_repo,
    }

    first = await schedule_next_paused_search_action(**kwargs)
    assert first.occurrence is not None
    assert first.occurrence.occurrence_number == 1

    # Pre-send checks rejected the send (e.g. same-channel frequency limit):
    # the cadence executor pauses the workflow but leaves the occurrence open
    # (PLANNED) — it never reached the lead. The operator then manually resumes.
    blocked = occurrence_repo.saved[0]
    assert blocked.status is RecurringOccurrenceStatus.PLANNED

    retry = await schedule_next_paused_search_action(
        **{**kwargs, "now": NOW + timedelta(hours=1)}
    )

    assert retry.status == PausedSearchScheduleStatus.SCHEDULED
    assert retry.occurrence is not None
    assert retry.occurrence.occurrence_number == 1
    assert retry.occurrence.occurrence_id == blocked.occurrence_id
    assert retry.occurrence.status is RecurringOccurrenceStatus.PLANNED
    assert len(occurrence_repo.saved) == 1
    assert retry.workflow is not None
    assert retry.workflow.state == WorkflowState.ACTIVE_NURTURE
    assert not transition_repo.transitions


async def test_derived_maintenance_recurrence_switches_to_reactivation() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    reactivation_step = replace(
        _step(),
        step_id=uuid4(),
        step_order=2,
        phase=PausedSearchTrackStepPhase.REACTIVATION,
        delay_hours=0,
        timing_basis=PausedSearchTimingBasis.CUSTOMER_REENGAGEMENT_DATE,
        interval_days=None,
        max_occurrences=1,
    )
    kwargs: dict[str, Any] = {
        "workspace_id": WORKSPACE_ID,
        "lead_id": LEAD_ID,
        "lead_repository": FakeLeadRepository(_lead()),
        "paused_search_track_repository": FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(
                replace(_step(), delay_hours=0, interval_days=30, max_occurrences=1),
                reactivation_step,
            ),
        ),
        "lead_workflow_repository": workflow_repo,
        "timezone": TIMEZONE,
        "now": NOW,
        "occurrence_repository": occurrence_repo,
    }

    for _ in range(3):
        result = await schedule_next_paused_search_action(**kwargs)
        assert result.occurrence is not None
        occurrence_repo.saved[-1] = replace(
            occurrence_repo.saved[-1], status=RecurringOccurrenceStatus.SENT
        )

    switched = await schedule_next_paused_search_action(**kwargs)

    assert switched.occurrence is None
    assert switched.status == PausedSearchScheduleStatus.SCHEDULED
    assert switched.phase == PausedSearchTrackStepPhase.REACTIVATION
    assert switched.step_id == reactivation_step.step_id
    assert len(occurrence_repo.saved) == 3


async def test_recurring_schedule_holds_when_flag_is_disabled() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    control_repo = FakeWorkspaceOperationalControlRepository(
        WorkspaceOperationalControl(workspace_id=WORKSPACE_ID)
    )

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(_step(),),
        ),
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repo),
        workspace_operational_control_repository=control_repo,
        recurring_paused_search_pilot_workspace_ids=(WORKSPACE_ID,),
    )

    assert result.status == PausedSearchScheduleStatus.HOLD
    assert result.reason_code == PausedSearchTimingReasonCode.HOLD_FOR_REVIEW
    assert "disabled" in (result.reason_detail or "")
    assert occurrence_repo.saved == []


async def test_recurring_schedule_holds_workspace_outside_pilot_allowlist() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    control_repo = FakeWorkspaceOperationalControlRepository(
        WorkspaceOperationalControl(
            workspace_id=WORKSPACE_ID,
            recurring_paused_search_enabled=True,
        )
    )

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(_step(),),
        ),
        lead_workflow_repository=workflow_repo,
        timezone=TIMEZONE,
        now=NOW,
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repo),
        workspace_operational_control_repository=control_repo,
        recurring_paused_search_pilot_workspace_ids=(uuid4(),),
    )

    assert result.status == PausedSearchScheduleStatus.HOLD
    assert "allowlist" in (result.reason_detail or "")
    assert occurrence_repo.saved == []


async def test_recurring_schedule_uses_workspace_quiet_hours() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(_workflow())
    occurrence_repo = _FakeOccurrenceRepository()
    control_repo = FakeWorkspaceOperationalControlRepository(
        WorkspaceOperationalControl(
            workspace_id=WORKSPACE_ID,
            recurring_paused_search_enabled=True,
        )
    )
    policy_repo = FakeWorkspaceContactPolicyRepository(
        WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            quiet_hours_start=time(11, 30),
            quiet_hours_end=time(16, 0),
        )
    )

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(replace(_step(), delay_hours=0, interval_days=30, max_occurrences=1),),
        ),
        lead_workflow_repository=workflow_repo,
        occurrence_repository=cast(PausedSearchOccurrenceRepository, occurrence_repo),
        workspace_operational_control_repository=control_repo,
        workspace_contact_policy_repository=policy_repo,
        recurring_paused_search_pilot_workspace_ids=(WORKSPACE_ID,),
        timezone=TIMEZONE,
        now=NOW,
    )

    assert result.occurrence is not None
    assert result.occurrence.scheduled_for == datetime(2026, 7, 1, 16, 30, tzinfo=UTC)
    assert result.occurrence.timezone_snapshot == TIMEZONE


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


async def test_touch_limit_terminalizes_workflow_with_published_behavior() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow = replace(_workflow(), logical_touch_count=5)
    await workflow_repo.save(workflow)
    transition_repo = FakeWorkflowTransitionRepository()

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(_step(),),
        ),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transition_repo,
        timezone=TIMEZONE,
        now=NOW,
    )

    assert result.status == PausedSearchScheduleStatus.TERMINAL
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.COMPLETED
    assert len(transition_repo.transitions) == 1


async def test_touch_limit_terminalization_closes_campaign_enrollment() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    workflow = replace(_workflow(), logical_touch_count=5)
    await workflow_repo.save(workflow)
    transition_repo = FakeWorkflowTransitionRepository()
    enrollment_repo = FakeCampaignEnrollmentRepository()
    await enrollment_repo.save(
        CampaignEnrollment(
            campaign_enrollment_id=workflow.campaign_enrollment_id,
            workspace_id=WORKSPACE_ID,
            campaign_id=workflow.campaign_id,
            campaign_version_id=uuid4(),
            lead_id=LEAD_ID,
            source=CampaignEnrollmentSource.MANUAL_ADMIN,
            status=CampaignEnrollmentStatus.QUEUED,
            eligible_at=NOW,
            enrolled_at=NOW,
            started_at=None,
            ended_at=None,
            created_by_user_id=None,
            reason_codes=(),
            created_at=NOW,
            updated_at=NOW,
        )
    )

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(_track_version(),),
            steps=(_step(),),
        ),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transition_repo,
        campaign_enrollment_repository=enrollment_repo,
        timezone=TIMEZONE,
        now=NOW,
    )

    assert result.status == PausedSearchScheduleStatus.TERMINAL
    stored = await enrollment_repo.get_latest_by_lead_and_campaign(
        WORKSPACE_ID,
        LEAD_ID,
        workflow.campaign_id,
    )
    assert stored is not None
    assert stored.status == CampaignEnrollmentStatus.COMPLETED
    assert stored.ended_at == NOW


async def test_terminal_pause_for_review_keeps_workflow_open_for_resolution() -> None:
    workflow_repo = FakeLeadWorkflowRepository()
    await workflow_repo.save(replace(_workflow(), logical_touch_count=5))
    transition_repo = FakeWorkflowTransitionRepository()
    track = replace(
        _track_version(),
        terminal_behavior=PausedSearchTerminalBehavior.PAUSE_FOR_REVIEW,
    )

    result = await schedule_next_paused_search_action(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        lead_repository=FakeLeadRepository(_lead()),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(
            versions=(track,),
            steps=(_step(),),
        ),
        lead_workflow_repository=workflow_repo,
        workflow_transition_repository=transition_repo,
        timezone=TIMEZONE,
        now=NOW,
    )

    assert result.status == PausedSearchScheduleStatus.REVIEW
    assert result.workflow is not None
    assert result.workflow.state == WorkflowState.PAUSED


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
