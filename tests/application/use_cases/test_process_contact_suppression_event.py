from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.process_contact_suppression_event import (
    ContactSuppressionEvent,
    ProcessContactSuppressionEventReasonCode,
    ProcessContactSuppressionEventStatus,
    process_contact_suppression_event,
)
from app.domain.compliance import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SmsComplianceState,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeExternalEventRepository,
)

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("70000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("70000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("70000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("70000000-0000-0000-0000-000000000004")
ENROLLMENT_ID = UUID("70000000-0000-0000-0000-000000000005")


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
        primary_email="lead@example.com",
        has_email=True,
        email_count=1,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        primary_phone="+15555550123",
        has_sms_capable_phone=True,
        phone_count=1,
        do_not_contact=False,
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


async def test_processes_sms_opt_out_and_pauses_when_email_remains_usable() -> None:
    lead_repository = FakeLeadRepository(_lead())
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow()
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    outbox = FakeTemporalSignalOutboxRepository()

    result = await process_contact_suppression_event(
        event=ContactSuppressionEvent(
            workspace_id=WORKSPACE_ID,
            source_provider="twilio",
            provider_event_id="evt-1",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="crm-123",
            suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
            occurred_at=NOW,
            provider_message_id="SM123",
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
            )
        ),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
    )

    assert result.status == ProcessContactSuppressionEventStatus.PROCESSED
    assert result.workflow_state == WorkflowState.PAUSED
    assert lead_repository.lead is not None
    assert lead_repository.lead.sms_opted_out is True
    assert SuppressionType.SMS_OPT_OUT in lead_repository.lead.suppression_types
    assert result.signal_queued is True
    assert len(outbox.entries) == 1
    entry = next(iter(outbox.entries.values()))
    assert entry.signal_name == TemporalSignalName.PAUSE_REQUESTED
    assert entry.payload["reason"] == "sms_opt_out"


async def test_processes_email_unsubscribe_and_suppresses_when_no_channel_remains() -> None:
    lead_repository = FakeLeadRepository(
        replace(_lead(), primary_phone=None, has_sms_capable_phone=False, phone_count=0)
    )
    workflow_repository = FakeLeadWorkflowRepository()
    workflow = _workflow()
    workflow_repository.workflows[workflow.workflow_id] = workflow
    workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow

    result = await process_contact_suppression_event(
        event=ContactSuppressionEvent(
            workspace_id=WORKSPACE_ID,
            source_provider="sendgrid",
            provider_event_id="evt-2",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="crm-123",
            suppression_kind=ContactSuppressionKind.EMAIL_UNSUBSCRIBED,
            occurred_at=NOW,
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        lead_workflow_repository=workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(workspace_id=WORKSPACE_ID)
        ),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        now=NOW,
    )

    assert result.status == ProcessContactSuppressionEventStatus.PROCESSED
    assert result.workflow_state == WorkflowState.SUPPRESSED
    assert lead_repository.lead is not None
    assert lead_repository.lead.email_unsubscribed is True
    assert SuppressionType.EMAIL_UNSUBSCRIBED in lead_repository.lead.suppression_types


async def test_returns_duplicate_when_suppression_event_replays() -> None:
    event = ContactSuppressionEvent(
        workspace_id=WORKSPACE_ID,
        source_provider="twilio",
        provider_event_id="evt-dup",
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
        occurred_at=NOW,
    )
    external_events = FakeExternalEventRepository()
    outbox = FakeTemporalSignalOutboxRepository()

    first = await process_contact_suppression_event(
        event=event,
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
    )
    second = await process_contact_suppression_event(
        event=event,
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
    )

    assert first.status == ProcessContactSuppressionEventStatus.PROCESSED
    assert second.status == ProcessContactSuppressionEventStatus.DUPLICATE
    assert second.reasons == (ProcessContactSuppressionEventReasonCode.DUPLICATE_EVENT,)
    assert len(outbox.entries) == 0


async def test_does_not_create_duplicate_outbox_row_for_duplicate_suppression_event() -> None:
    external_events = FakeExternalEventRepository()
    await external_events.save(
        _external_event(
            external_event_id=UUID("70000000-0000-0000-0000-000000000006"),
            provider_event_id="evt-dup",
            lead_id=LEAD_ID,
        )
    )
    outbox = FakeTemporalSignalOutboxRepository()

    result = await process_contact_suppression_event(
        event=ContactSuppressionEvent(
            workspace_id=WORKSPACE_ID,
            source_provider="twilio",
            provider_event_id="evt-dup",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id="crm-123",
            suppression_kind=ContactSuppressionKind.SMS_OPT_OUT,
            occurred_at=NOW,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=external_events,
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
        temporal_signal_outbox_repository=outbox,
        now=NOW,
    )

    assert result.status == ProcessContactSuppressionEventStatus.DUPLICATE
    assert len(outbox.entries) == 0


def _external_event(
    *,
    external_event_id: UUID,
    provider_event_id: str,
    lead_id: UUID,
) -> ExternalEvent:
    return ExternalEvent(
        external_event_id=external_event_id,
        workspace_id=WORKSPACE_ID,
        provider="twilio",
        event_type="sms_opt_out",
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
