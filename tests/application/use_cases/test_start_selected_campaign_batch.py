from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.use_cases.campaign_enrollment_types import LeadStartStatus
from app.application.use_cases.start_selected_campaign_batch import start_selected_campaign_batch
from app.domain.campaigns.enrollment import CampaignEnrollmentSource, CampaignEnrollmentStatus
from app.domain.events import DomainEvent, DomainEventType
from app.domain.workflows import WorkflowState, WorkflowTransitionReasonCode
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
        ) -> None:
            call_order.append("start")
            await super().start_lead_nurture_workflow(
                workspace_id=workspace_id,
                lead_id=lead_id,
                campaign_version_id=campaign_version_id,
                temporal_workflow_id=temporal_workflow_id,
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
