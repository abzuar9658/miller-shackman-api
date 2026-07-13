from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.application.ports.crm import CRMClient
from app.application.ports.notifications import NotificationProvider
from app.domain.compliance import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.events import DomainEvent
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.workflows import LeadWorkflow, WorkflowState
from app.interfaces.api.dependencies.inbound import InboundServiceBundle, get_inbound_service_bundle
from app.main import create_app
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeLeadNurtureWorkflowSignaler,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeCRMClient,
    FakeHandoffCompletionRepository,
    FakeNotificationProvider,
    FakeWorkspaceHandoffConfigRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    NOW,
    WORKSPACE_ID,
    FakeConversationRepository,
    FakeConversationSummaryRepository,
    FakeExternalEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeLLMClient,
    _classification_json,
)

LEAD_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("50000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("50000000-0000-0000-0000-000000000002")
ENROLLMENT_ID = UUID("50000000-0000-0000-0000-000000000003")


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


@pytest.fixture
def webhook_bundle() -> InboundServiceBundle:
    workflow = LeadWorkflow(
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
    lead_workflow_repository = FakeLeadWorkflowRepository()
    lead_workflow_repository.workflows[workflow.workflow_id] = workflow
    lead_workflow_repository.latest_by_lead[(workflow.workspace_id, workflow.lead_id)] = workflow
    return InboundServiceBundle(
        session=FakeSession(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
            )
        ),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(workspace_id=WORKSPACE_ID)
        ),
        crm_client=cast(CRMClient, FakeCRMClient()),
        notification_provider=cast(NotificationProvider, FakeNotificationProvider()),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                handoff_required=True,
                handoff_reason="human_requested",
            ),
        ),
        lead_nurture_workflow_signaler=FakeLeadNurtureWorkflowSignaler(),
        event_bus=FakeEventBus(),
    )


@pytest.fixture
def webhook_client(webhook_bundle: InboundServiceBundle) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_inbound_service_bundle] = lambda: webhook_bundle
    return TestClient(app)


def test_follow_up_boss_inbound_webhook_returns_processed_response(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
) -> None:
    response = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/inbound-messages",
        json={
            "workspace_id": str(WORKSPACE_ID),
            "provider_event_id": "evt-1",
            "provider_message_id": "msg-1",
            "crm_lead_id": "crm-123",
            "channel": "sms",
            "body": "Can someone call me today?",
            "received_at": NOW.isoformat(),
            "payload_redacted": {"event": "redacted"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is True
    assert body["intent"] == "human_requested"
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_follow_up_boss_inbound_webhook_returns_duplicate_on_replay(
    webhook_client: TestClient,
) -> None:
    payload = {
        "workspace_id": str(WORKSPACE_ID),
        "provider_event_id": "evt-dup",
        "provider_message_id": "msg-dup",
        "crm_lead_id": "crm-123",
        "channel": "sms",
        "body": "Can someone call me today?",
        "received_at": NOW.isoformat(),
        "payload_redacted": {"event": "redacted"},
    }

    first = webhook_client.post("/api/v1/webhooks/follow-up-boss/inbound-messages", json=payload)
    second = webhook_client.post("/api/v1/webhooks/follow-up-boss/inbound-messages", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


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
        primary_phone="+15555550123",
        has_email=True,
        has_phone=True,
        has_sms_capable_phone=True,
        email_count=1,
        phone_count=1,
        sms_permission_status=ContactPermissionStatus.CONFIRMED,
        email_permission_status=ContactPermissionStatus.CONFIRMED,
        do_not_contact=False,
    )


def test_follow_up_boss_human_activity_webhook_pauses_workflow(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
) -> None:
    response = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/human-activity-events",
        json={
            "workspace_id": str(WORKSPACE_ID),
            "provider_event_id": "evt-human-1",
            "crm_lead_id": "crm-123",
            "occurred_at": datetime(2026, 7, 12, 12, 0, tzinfo=UTC).isoformat(),
            "event_type": "activity_created",
            "activity_type": "note",
            "crm_activity_id": "activity-123",
            "actor_agent_id": "agent-99",
            "payload_redacted": {"event": "redacted"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["activity_kind"] == "crm_note_added"
    assert body["pause_requested"] is True
    assert body["signal_sent"] is True
    workflow_repository = cast(FakeLeadWorkflowRepository, webhook_bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED
    signaler = cast(FakeLeadNurtureWorkflowSignaler, webhook_bundle.lead_nurture_workflow_signaler)
    assert signaler.calls[0]["temporal_workflow_id"] == "workflow-123"


def test_follow_up_boss_human_activity_webhook_returns_duplicate_on_replay(
    webhook_client: TestClient,
) -> None:
    payload = {
        "workspace_id": str(WORKSPACE_ID),
        "provider_event_id": "evt-human-dup",
        "crm_lead_id": "crm-123",
        "occurred_at": NOW.isoformat(),
        "event_type": "lead_reassigned",
        "payload_redacted": {"event": "redacted"},
    }

    first = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/human-activity-events",
        json=payload,
    )
    second = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/human-activity-events",
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


def test_follow_up_boss_suppression_webhook_processes_sms_opt_out(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
) -> None:
    response = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/suppression-events",
        json={
            "workspace_id": str(WORKSPACE_ID),
            "source_provider": "twilio",
            "provider_event_id": "evt-suppression-1",
            "crm_lead_id": "crm-123",
            "suppression_kind": ContactSuppressionKind.SMS_OPT_OUT.value,
            "occurred_at": NOW.isoformat(),
            "provider_message_id": "SM123",
            "payload_redacted": {"event": "redacted"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["suppression_kind"] == "sms_opt_out"
    assert body["workflow_state"] == "paused"
    assert body["suppression_applied"] is True
    assert body["signal_sent"] is True
    saved_lead = cast(FakeLeadRepository, webhook_bundle.lead_repository).lead
    assert saved_lead is not None
    assert saved_lead.sms_opted_out is True
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_follow_up_boss_suppression_webhook_processes_email_unsubscribe(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
) -> None:
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    current_lead = lead_repository.lead
    assert current_lead is not None
    lead_repository._store(
        replace(
            current_lead,
            primary_phone=None,
            has_phone=False,
            has_sms_capable_phone=False,
            phone_count=0,
            sms_permission_status=ContactPermissionStatus.UNKNOWN,
        )
    )

    response = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/suppression-events",
        json={
            "workspace_id": str(WORKSPACE_ID),
            "source_provider": "sendgrid",
            "provider_event_id": "evt-suppression-2",
            "crm_lead_id": "crm-123",
            "suppression_kind": ContactSuppressionKind.EMAIL_UNSUBSCRIBED.value,
            "occurred_at": NOW.isoformat(),
            "payload_redacted": {"event": "redacted"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["suppression_kind"] == "email_unsubscribed"
    assert body["workflow_state"] == "suppressed"
    assert body["suppression_applied"] is True
    saved_lead = lead_repository.lead
    assert saved_lead is not None
    assert saved_lead.email_unsubscribed is True


def test_follow_up_boss_suppression_webhook_returns_duplicate_on_replay(
    webhook_client: TestClient,
) -> None:
    payload = {
        "workspace_id": str(WORKSPACE_ID),
        "source_provider": "twilio",
        "provider_event_id": "evt-suppression-dup",
        "crm_lead_id": "crm-123",
        "suppression_kind": ContactSuppressionKind.SMS_OPT_OUT.value,
        "occurred_at": NOW.isoformat(),
        "payload_redacted": {"event": "redacted"},
    }

    first = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/suppression-events",
        json=payload,
    )
    second = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/suppression-events",
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]
