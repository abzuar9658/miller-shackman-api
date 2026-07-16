from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.temporal import PauseLeadNurtureWorkflowSignal
from app.application.use_cases.process_crm_human_activity_event import (
    CRMHumanActivityEvent,
    CRMHumanActivityKind,
    ProcessCRMHumanActivityEventReasonCode,
    ProcessCRMHumanActivityEventStatus,
    process_crm_human_activity_event,
)
from app.domain.common.ids import LeadId
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowState, WorkflowTransitionReasonCode
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadNurtureWorkflowSignaler,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeExternalEventRepository,
)

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("40000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("40000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("40000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("40000000-0000-0000-0000-000000000005")
EXTERNAL_EVENT_ID = UUID("40000000-0000-0000-0000-000000000006")


async def test_pauses_workflow_and_signals_temporal_for_meaningful_activity() -> None:
    lead_repository = FakeLeadRepository(_lead())
    external_events = FakeExternalEventRepository()
    workflows = FakeLeadWorkflowRepository()
    transitions = FakeWorkflowTransitionRepository()
    signaler = FakeLeadNurtureWorkflowSignaler()
    await workflows.save(_workflow())

    result = await process_crm_human_activity_event(
        event=_event(event_type="activity_created", activity_type="note"),
        lead_repository=lead_repository,
        external_event_repository=external_events,
        lead_workflow_repository=workflows,
        workflow_transition_repository=transitions,
        lead_nurture_workflow_signaler=signaler,
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
    )

    assert result.status == ProcessCRMHumanActivityEventStatus.PROCESSED
    assert result.activity_kind == CRMHumanActivityKind.NOTE_ADDED
    assert result.pause_requested is True
    assert result.signal_sent is True
    assert result.pause_reason == "crm_note_added"
    assert lead_repository.saved[-1].last_agent_activity_at == NOW
    workflow = workflows.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED
    transition = next(iter(transitions.transitions.values()))
    assert transition.reason_code == WorkflowTransitionReasonCode.CRM_HUMAN_ACTIVITY_DETECTED
    assert transition.metadata["human_activity_kind"] == "crm_note_added"
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"
    saved_event = external_events.events[(WORKSPACE_ID, CRMProvider.FOLLOW_UP_BOSS.value, "evt-1")]
    assert saved_event.status.value == "processed"


async def test_returns_duplicate_when_provider_event_was_already_processed() -> None:
    external_events = FakeExternalEventRepository()
    await external_events.save(
        _external_event(
            external_event_id=EXTERNAL_EVENT_ID,
            provider_event_id="evt-dup",
            lead_id=LEAD_ID,
        )
    )

    result = await process_crm_human_activity_event(
        event=_event(provider_event_id="evt-dup", event_type="activity_created"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        lead_nurture_workflow_signaler=FakeLeadNurtureWorkflowSignaler(),
        now=NOW,
    )

    assert result.status == ProcessCRMHumanActivityEventStatus.DUPLICATE
    assert result.reasons == (ProcessCRMHumanActivityEventReasonCode.DUPLICATE_EVENT,)


async def test_ignores_non_meaningful_activity() -> None:
    result = await process_crm_human_activity_event(
        event=_event(event_type="profile_viewed"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        lead_nurture_workflow_signaler=FakeLeadNurtureWorkflowSignaler(),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
    )

    assert result.status == ProcessCRMHumanActivityEventStatus.IGNORED
    assert result.reasons == (ProcessCRMHumanActivityEventReasonCode.NOT_MEANINGFUL_HUMAN_ACTIVITY,)


async def test_records_processed_event_when_no_workflow_exists() -> None:
    result = await process_crm_human_activity_event(
        event=_event(event_type="lead_reassigned"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        lead_nurture_workflow_signaler=FakeLeadNurtureWorkflowSignaler(),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
    )

    assert result.status == ProcessCRMHumanActivityEventStatus.PROCESSED
    assert result.pause_requested is False
    assert result.signal_sent is False
    assert result.reasons == (ProcessCRMHumanActivityEventReasonCode.NO_WORKFLOW,)


async def test_commits_before_signaling_temporal_pause() -> None:
    call_order: list[str] = []

    class RecordingLeadNurtureWorkflowSignaler(FakeLeadNurtureWorkflowSignaler):
        async def signal_pause_lead_nurture_workflow(
            self,
            *,
            temporal_workflow_id: str,
            signal: PauseLeadNurtureWorkflowSignal,
        ) -> None:
            call_order.append("signal")
            await super().signal_pause_lead_nurture_workflow(
                temporal_workflow_id=temporal_workflow_id,
                signal=signal,
            )

    async def commit() -> None:
        call_order.append("commit")

    workflows = FakeLeadWorkflowRepository()
    await workflows.save(_workflow())

    result = await process_crm_human_activity_event(
        event=_event(event_type="activity_created", activity_type="note"),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        lead_workflow_repository=workflows,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        lead_nurture_workflow_signaler=RecordingLeadNurtureWorkflowSignaler(),
        commit=commit,
        now=NOW,
    )

    assert result.signal_sent is True
    assert call_order == ["commit", "signal"]


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="nurture",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
    )


def _workflow() -> LeadWorkflow:
    return LeadWorkflow(
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="workflow-123",
        workspace_id=WORKSPACE_ID,
        campaign_enrollment_id=ENROLLMENT_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        state=WorkflowState.WAITING_FOR_RESPONSE,
        last_transition_at=NOW,
        state_version=3,
        created_at=NOW,
        updated_at=NOW,
    )


def _event(
    *,
    provider_event_id: str = "evt-1",
    event_type: str,
    activity_type: str | None = None,
) -> CRMHumanActivityEvent:
    return CRMHumanActivityEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id=provider_event_id,
        crm_lead_id="crm-123",
        occurred_at=NOW,
        event_type=event_type,
        activity_type=activity_type,
        crm_activity_id="activity-123",
        actor_agent_id="agent-99",
        payload_redacted={"event": "redacted"},
    )


def _external_event(
    *,
    external_event_id: UUID,
    provider_event_id: str,
    lead_id: LeadId,
) -> ExternalEvent:
    return ExternalEvent(
        external_event_id=external_event_id,
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        event_type="activity_created",
        provider_event_id=provider_event_id,
        crm_lead_id="crm-123",
        lead_id=lead_id,
        received_at=NOW,
        processed_at=NOW,
        status=ExternalEventStatus.PROCESSED,
        payload_redacted={"event": "redacted"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )
