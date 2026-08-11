from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.ports.temporal import TemporalWorkflowExecutionMode
from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns.enrollment import CampaignEnrollmentSource, CampaignEnrollmentStatus
from app.domain.events import DomainEvent, DomainEventType
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeLeadWorkflowRepository,
    FakeTemporalWorkflowStarter,
    FakeWorkflowTransitionRepository,
)


class _Dependencies:
    def __init__(self) -> None:
        self.campaign_enrollment_repository = FakeCampaignEnrollmentRepository()
        self.lead_workflow_repository = FakeLeadWorkflowRepository()
        self.workflow_transition_repository = FakeWorkflowTransitionRepository()
        self.temporal_workflow_starter = FakeTemporalWorkflowStarter()


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000007")
CAMPAIGN_VERSION_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID_1 = UUID("00000000-0000-0000-0000-000000000004")
LEAD_ID_2 = UUID("00000000-0000-0000-0000-000000000005")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000006")


@pytest.fixture
def base_dependencies() -> _Dependencies:
    return _Dependencies()


async def test_starts_workflow_for_selected_lead(base_dependencies: _Dependencies) -> None:
    event_bus = FakeEventBus()

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=["explicit_enrollment"],
        actor_user_id=ACTOR_ID,
        now=NOW,
        metadata={"manual_reentry_reason": "Lead requested a fresh follow-up."},
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
        event_bus=event_bus,
    )

    assert result.started_count == 1
    assert result.already_enrolled_count == 0
    assert result.failed_count == 0
    lead_result = result.lead_results[0]
    assert lead_result.status == LeadStartStatus.STARTED
    assert lead_result.campaign_enrollment_id is not None
    assert lead_result.workflow_id is not None
    assert lead_result.temporal_workflow_id is not None

    enrollment = await base_dependencies.campaign_enrollment_repository.get_by_lead_and_campaign(
        WORKSPACE_ID, LEAD_ID_1, CAMPAIGN_ID
    )
    assert enrollment is not None
    assert enrollment.status == CampaignEnrollmentStatus.QUEUED
    assert enrollment.source == CampaignEnrollmentSource.MANUAL_ADMIN

    workflow = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    assert workflow.state == WorkflowState.QUEUED
    assert workflow.campaign_enrollment_id == enrollment.campaign_enrollment_id
    assert workflow.temporal_workflow_id == lead_result.temporal_workflow_id

    transitions = await base_dependencies.workflow_transition_repository.list_for_workflow(
        WORKSPACE_ID, workflow.workflow_id
    )
    assert len(transitions) == 1
    assert transitions[0].to_state == WorkflowState.QUEUED
    assert transitions[0].reason_code == WorkflowTransitionReasonCode.CAMPAIGN_ENROLLMENT_STARTED
    assert transitions[0].metadata["manual_reentry_reason"] == "Lead requested a fresh follow-up."

    assert len(base_dependencies.temporal_workflow_starter.calls) == 1
    assert base_dependencies.temporal_workflow_starter.calls[0]["lead_id"] == LEAD_ID_1
    assert (
        base_dependencies.temporal_workflow_starter.calls[0]["campaign_version_id"]
        == CAMPAIGN_VERSION_ID
    )
    assert [event.event_type for event in event_bus.events] == [
        DomainEventType.CAMPAIGN_ENROLLED,
        DomainEventType.WORKFLOW_TRANSITIONED,
    ]
    assert event_bus.events[0].payload["lead_id"] == str(LEAD_ID_1)


async def test_skips_already_enrolled_lead(base_dependencies: _Dependencies) -> None:
    args = {
        "workspace_id": WORKSPACE_ID,
        "campaign_id": CAMPAIGN_ID,
        "campaign_version_id": CAMPAIGN_VERSION_ID,
        "lead_ids": [LEAD_ID_1],
        "source": CampaignEnrollmentSource.MANUAL_ADMIN,
        "reason_codes": [],
        "actor_user_id": ACTOR_ID,
        "now": NOW,
        "campaign_enrollment_repository": base_dependencies.campaign_enrollment_repository,
        "lead_workflow_repository": base_dependencies.lead_workflow_repository,
        "workflow_transition_repository": base_dependencies.workflow_transition_repository,
        "temporal_workflow_starter": base_dependencies.temporal_workflow_starter,
    }
    await start_selected_campaign_batch(**args)  # type: ignore[arg-type]

    result = await start_selected_campaign_batch(**args)  # type: ignore[arg-type]

    assert result.started_count == 0
    assert result.already_enrolled_count == 1
    assert result.failed_count == 0
    assert result.lead_results[0].status == LeadStartStatus.ALREADY_ENROLLED


async def test_rejects_enrollment_when_lead_is_active_in_another_campaign(
    base_dependencies: _Dependencies,
) -> None:
    await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=OTHER_CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.DORMANT_SELECTOR,
        reason_codes=[],
        actor_user_id=None,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )

    assert result.started_count == 0
    assert result.already_active_elsewhere_count == 1
    assert result.terminal_requires_manual_enrollment_count == 0
    assert result.lead_results[0].status == LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE
    assert len(base_dependencies.temporal_workflow_starter.calls) == 1


async def test_maps_first_enrollment_race_to_active_elsewhere_and_rolls_back() -> None:
    winner = LeadWorkflow(
        workflow_id=UUID("00000000-0000-0000-0000-000000000008"),
        temporal_workflow_id="lead-nurture:winner",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=UUID("00000000-0000-0000-0000-000000000009"),
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID_1,
        state=WorkflowState.QUEUED,
        last_transition_at=NOW,
        state_version=1,
        created_at=NOW,
        updated_at=NOW,
    )

    class RacingWorkflowRepository(FakeLeadWorkflowRepository):
        def __init__(self) -> None:
            super().__init__()
            self.lookup_count = 0

        async def get_latest_for_lead_for_update(
            self,
            workspace_id: UUID,
            lead_id: UUID,
        ) -> LeadWorkflow | None:
            self.lookup_count += 1
            return None if self.lookup_count == 1 else winner

        async def save(self, workflow: LeadWorkflow) -> LeadWorkflow:
            raise RuntimeError("simulated unique-index conflict")

    enrollment_repository = FakeCampaignEnrollmentRepository()
    workflow_repository = RacingWorkflowRepository()
    temporal_starter = FakeTemporalWorkflowStarter()
    rollback_calls: list[str] = []

    async def rollback() -> None:
        rollback_calls.append("rollback")
        enrollment_repository.enrollments.clear()

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=OTHER_CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.DORMANT_SELECTOR,
        reason_codes=[],
        actor_user_id=None,
        now=NOW,
        campaign_enrollment_repository=enrollment_repository,
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_workflow_starter=temporal_starter,
        rollback=rollback,
    )

    assert result.started_count == 0
    assert result.already_active_elsewhere_count == 1
    assert result.lead_results[0].status == LeadStartStatus.ALREADY_ACTIVE_ELSEWHERE
    assert rollback_calls == ["rollback"]
    assert enrollment_repository.enrollments == {}
    assert temporal_starter.calls == []


async def test_rejects_automatic_re_entry_after_terminal_workflow(
    base_dependencies: _Dependencies,
) -> None:
    await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )
    workflow = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    await base_dependencies.lead_workflow_repository.save(
        replace(workflow, state=WorkflowState.COMPLETED),
    )

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=OTHER_CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.DORMANT_SELECTOR,
        reason_codes=[],
        actor_user_id=None,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )

    assert result.started_count == 0
    assert result.already_active_elsewhere_count == 0
    assert result.terminal_requires_manual_enrollment_count == 1
    assert result.lead_results[0].status == LeadStartStatus.TERMINAL_REQUIRES_MANUAL_ENROLLMENT


@pytest.mark.parametrize(
    "terminal_state",
    [WorkflowState.COMPLETED, WorkflowState.SUPPRESSED, WorkflowState.CLOSED],
)
async def test_allows_admin_re_entry_with_reason_after_terminal_workflow(
    base_dependencies: _Dependencies,
    terminal_state: WorkflowState,
) -> None:
    await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )
    workflow = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    await base_dependencies.lead_workflow_repository.save(
        replace(workflow, state=terminal_state),
    )

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=OTHER_CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        reentry_reason="Lead requested a new campaign.",
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )

    assert result.started_count == 1
    assert result.already_active_elsewhere_count == 0
    assert result.terminal_requires_manual_enrollment_count == 0
    assert result.lead_results[0].status == LeadStartStatus.STARTED

    latest = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    transitions = await base_dependencies.workflow_transition_repository.list_for_workflow(
        WORKSPACE_ID,
        latest.workflow_id,
    )
    assert transitions[0].metadata["manual_reentry_reason"] == "Lead requested a new campaign."


async def test_rejects_admin_re_entry_without_reason_after_terminal_workflow(
    base_dependencies: _Dependencies,
) -> None:
    await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )
    workflow = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    await base_dependencies.lead_workflow_repository.save(
        replace(workflow, state=WorkflowState.COMPLETED),
    )

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=OTHER_CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=base_dependencies.temporal_workflow_starter,
    )

    assert result.started_count == 0
    assert result.failed_count == 1
    assert result.lead_results[0].status == LeadStartStatus.REENTRY_REASON_REQUIRED


async def test_records_failed_start_when_temporal_raises(
    base_dependencies: _Dependencies,
) -> None:
    starter = FakeTemporalWorkflowStarter(always_fail=True)

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=starter,
    )

    assert result.started_count == 0
    assert result.already_enrolled_count == 0
    assert result.failed_count == 1
    lead_result = result.lead_results[0]
    assert lead_result.status == LeadStartStatus.FAILED
    assert lead_result.error == "Temporal start failed"

    enrollment = await base_dependencies.campaign_enrollment_repository.get_by_lead_and_campaign(
        WORKSPACE_ID, LEAD_ID_1, CAMPAIGN_ID
    )
    assert enrollment is not None
    workflow = base_dependencies.lead_workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID_1)]
    transitions = await base_dependencies.workflow_transition_repository.list_for_workflow(
        WORKSPACE_ID, workflow.workflow_id
    )
    assert len(transitions) == 1


async def test_commits_before_starting_temporal_workflow(
    base_dependencies: _Dependencies,
) -> None:
    call_order: list[str] = []

    class RecordingTemporalWorkflowStarter(FakeTemporalWorkflowStarter):
        async def start_lead_nurture_workflow(
            self,
            *,
            workspace_id: UUID,
            lead_id: UUID,
            campaign_version_id: UUID,
            temporal_workflow_id: str,
            workflow_id: UUID | None = None,
            execution_mode: TemporalWorkflowExecutionMode = (
                TemporalWorkflowExecutionMode.STANDARD_CADENCE
            ),
            paused_search_track_version_id: UUID | None = None,
        ) -> None:
            call_order.append("start")
            await super().start_lead_nurture_workflow(
                workspace_id=workspace_id,
                lead_id=lead_id,
                campaign_version_id=campaign_version_id,
                temporal_workflow_id=temporal_workflow_id,
                    workflow_id=workflow_id,
                    execution_mode=execution_mode,
                    paused_search_track_version_id=paused_search_track_version_id,
            )

    async def commit() -> None:
        call_order.append("commit")

    result = await start_selected_campaign_batch(
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        campaign_version_id=CAMPAIGN_VERSION_ID,
        lead_ids=[LEAD_ID_1],
        source=CampaignEnrollmentSource.MANUAL_ADMIN,
        reason_codes=[],
        actor_user_id=ACTOR_ID,
        now=NOW,
        campaign_enrollment_repository=base_dependencies.campaign_enrollment_repository,
        lead_workflow_repository=base_dependencies.lead_workflow_repository,
        workflow_transition_repository=base_dependencies.workflow_transition_repository,
        temporal_workflow_starter=RecordingTemporalWorkflowStarter(),
        commit=commit,
    )

    assert result.started_count == 1
    assert call_order == ["commit", "start"]
