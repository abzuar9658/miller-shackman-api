import base64
import hmac
from dataclasses import replace
from datetime import UTC, datetime, time
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import SecretStr
from twilio.request_validator import RequestValidator

from app.application.ports.crm import CRMAgent, CRMClient
from app.application.ports.crm_webhook import FollowUpBossWebhookEventBundle
from app.application.ports.notifications import NotificationProvider
from app.core.config import Settings, get_settings
from app.domain.campaigns import CampaignStatus, CampaignVersionStatus
from app.domain.campaigns.execution import CampaignCadenceStep, CampaignExecutionConfig
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    build_outbound_email_message_id,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance import (
    ContactPermissionStatus,
    ContactSuppressionKind,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    CrmConversationEvent,
    CrmConversationEventDirection,
    WorkspaceHandoffConfig,
)
from app.domain.events import DomainEvent
from app.domain.identity import Workspace, WorkspaceStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.outbound_drafting import default_workspace_outbound_drafting_config
from app.domain.workflows import LeadWorkflow, TemporalSignalName, WorkflowState
from app.infrastructure.crm.follow_up_boss.webhook_event_handler import (
    FollowUpBossWebhookEventHandlerImpl,
)
from app.interfaces.api.dependencies.follow_up_boss_webhook import (
    get_follow_up_boss_webhook_event_handler,
)
from app.interfaces.api.dependencies.inbound import (
    InboundServiceBundle,
    get_inbound_service_bundle,
)
from app.interfaces.api.schemas.inbound import MailgunInboundParsePayload
from app.main import create_app
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeCampaignExecutionRepository,
    FakeClassificationLLMClient,
    FakeCrmConversationEventRepository,
    FakeEmailProvider,
    FakeLeadClassificationArtifactRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeSMSProvider,
    FakeWorkflowTransitionRepository,
    FakeWorkspaceContactPolicyRepository,
    FakeWorkspaceLLMConfigRepository,
    FakeWorkspaceOperationalControlRepository,
    FakeWorkspaceOutboundDraftingConfigRepository,
    FakeWorkspaceRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeCampaignEnrollmentRepository,
    FakeTemporalSignalOutboxRepository,
    FakeTemporalWorkflowStarter,
)
from tests.application.use_cases._paused_search_track_fakes import (
    FakePausedSearchTrackAdminRepository,
)
from tests.application.use_cases.test_complete_handoff import (
    FakeHandoffCompletionRepository,
    FakeNotificationProvider,
    FakeWorkspaceHandoffConfigRepository,
)
from tests.application.use_cases.test_process_inbound_message_event import (
    NOW,
    WORKSPACE_ID,
    FakeConversationRepository,
    FakeConversationSummaryRepository,
    FakeCRMClient,
    FakeExternalEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageCRMCompletionRepository,
    FakeInboundMessageRepository,
    FakeLLMClient,
    FakeOutboundMessageCRMCompletionRepository,
    _acknowledgment_json,
    _classification_json,
    _draft_json,
    _FakeLLMClientForContinuation,
)

LEAD_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("50000000-0000-0000-0000-000000000001")
CAMPAIGN_ID = UUID("50000000-0000-0000-0000-000000000002")
ENROLLMENT_ID = UUID("50000000-0000-0000-0000-000000000003")
DEFAULT_CAMPAIGN_VERSION_ID = UUID("50000000-0000-0000-0000-000000000004")


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
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        lead_classification_artifact_repository=FakeLeadClassificationArtifactRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        outbound_message_crm_completion_repository=FakeOutboundMessageCRMCompletionRepository(),
        paused_search_track_repository=FakePausedSearchTrackAdminRepository(),
        lead_workflow_repository=lead_workflow_repository,
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
                inbound_email_address="nurture@inbound.example.com",
            )
        ),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(workspace_id=WORKSPACE_ID)
        ),
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        crm_client=cast(CRMClient, FakeCRMClient()),
        notification_provider=cast(NotificationProvider, FakeNotificationProvider()),
        llm_client=FakeLLMClient(
            _classification_json(intent="human_requested"),
        ),
        event_bus=FakeEventBus(),
        default_openrouter_model="openai/gpt-4o-mini",
        workspace_repository=FakeWorkspaceRepository(None),
        campaign_execution_repository=FakeCampaignExecutionRepository(None),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        workspace_operational_control_repository=FakeWorkspaceOperationalControlRepository(None),
        workspace_outbound_drafting_config_repository=FakeWorkspaceOutboundDraftingConfigRepository(
            None
        ),
        message_repository=FakeOutboundMessageRepository(),
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
    )


@pytest.fixture
def webhook_client(webhook_bundle: InboundServiceBundle) -> TestClient:
    return _build_webhook_client(webhook_bundle)


def _build_webhook_client(
    webhook_bundle: InboundServiceBundle,
    settings: Settings | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_inbound_service_bundle] = lambda: webhook_bundle
    app.dependency_overrides[get_settings] = lambda: (
        settings
        or Settings(
            twilio_auth_token=None,
            sendgrid_event_webhook_public_key=None,
            mailgun_webhook_signing_key=None,
        )
    )
    return TestClient(app)


class _FakeCRMClientForWebhook(FakeCRMClient):
    def __init__(self, fetch_result: dict[str, Any] | None) -> None:
        super().__init__()
        self._fetch_result = fetch_result
        self.requested_uris: list[str] = []

    async def fetch_resource_by_uri(self, workspace_id: UUID, uri: str) -> dict[str, Any] | None:
        _ = workspace_id
        self.requested_uris.append(uri)
        return self._fetch_result


def _build_webhook_client_with_handler(
    webhook_bundle: InboundServiceBundle,
    settings: Settings | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_inbound_service_bundle] = lambda: webhook_bundle
    app.dependency_overrides[get_follow_up_boss_webhook_event_handler] = lambda: (
        FollowUpBossWebhookEventHandlerImpl(
            bundle=FollowUpBossWebhookEventBundle(
                lead_repository=webhook_bundle.lead_repository,
                external_event_repository=webhook_bundle.external_event_repository,
                lead_workflow_repository=webhook_bundle.lead_workflow_repository,
                workflow_transition_repository=webhook_bundle.workflow_transition_repository,
                temporal_signal_outbox_repository=webhook_bundle.temporal_signal_outbox_repository,
                workspace_contact_policy_repository=webhook_bundle.workspace_contact_policy_repository,
                campaign_execution_repository=webhook_bundle.campaign_execution_repository,
                campaign_enrollment_repository=webhook_bundle.campaign_enrollment_repository,
                lead_classification_artifact_repository=webhook_bundle.lead_classification_artifact_repository,
                paused_search_track_repository=webhook_bundle.paused_search_track_repository,
                crm_conversation_event_repository=webhook_bundle.crm_conversation_event_repository,
                workspace_llm_config_repository=webhook_bundle.workspace_llm_config_repository,
                crm_client=webhook_bundle.crm_client,
                temporal_workflow_starter=webhook_bundle.temporal_workflow_starter,
                llm_client=webhook_bundle.llm_client,
                event_bus=webhook_bundle.event_bus,
                workspace_operational_control_repository=webhook_bundle.workspace_operational_control_repository,
                handoff_repository=webhook_bundle.handoff_repository,
                handoff_completion_repository=webhook_bundle.handoff_completion_repository,
                workspace_handoff_config_repository=(
                    webhook_bundle.workspace_handoff_config_repository
                ),
                notification_provider=webhook_bundle.notification_provider,
                user_repository=webhook_bundle.user_repository,
                default_openrouter_model=webhook_bundle.default_openrouter_model,
                commit=webhook_bundle.session.commit,
            ),
        )
    )
    app.dependency_overrides[get_settings] = lambda: (
        settings
        or Settings(
            twilio_auth_token=None,
            sendgrid_event_webhook_public_key=None,
            mailgun_webhook_signing_key=None,
        )
    )
    return TestClient(app)


def _workspace() -> Workspace:
    return Workspace(
        workspace_id=WORKSPACE_ID,
        name="Miller Schackman",
        status=WorkspaceStatus.ACTIVE,
        default_timezone="America/Chicago",
        created_at=NOW,
        updated_at=NOW,
    )


def _campaign_execution_config(
    *,
    channel: ContactChannel,
    campaign_id: UUID = CAMPAIGN_ID,
    version_id: UUID = DEFAULT_CAMPAIGN_VERSION_ID,
    crm_enrollment_tag: str | None = None,
) -> CampaignExecutionConfig:
    step_id = UUID("50000000-0000-0000-0000-000000000005")
    return CampaignExecutionConfig(
        campaign_id=campaign_id,
        campaign_version_id=version_id,
        workspace_id=WORKSPACE_ID,
        campaign_name="Dormant Buyers",
        campaign_status=CampaignStatus.ACTIVE,
        version_status=CampaignVersionStatus.PUBLISHED,
        enabled_channels=(channel,),
        daily_start_cap=50,
        dormant_threshold_days=60,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        timezone="UTC",
        sms_compliance_required=True,
        preflight_digest_enabled=False,
        crm_enrollment_tag=crm_enrollment_tag,
        prompt_version="v1",
        approved_model="openai/gpt-4o-mini",
        cadence_steps=(
            CampaignCadenceStep(
                cadence_step_id=step_id,
                workspace_id=WORKSPACE_ID,
                campaign_version_id=version_id,
                step_order=1,
                channel=channel,
                delay_hours=0,
                message_goal="Follow up on the latest inbound reply.",
                template_key="continuation-step-1",
                max_attempts=1,
                created_at=NOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
        outbound_drafting_config=default_workspace_outbound_drafting_config(WORKSPACE_ID),
    )


def _continue_ai_webhook_bundle(
    webhook_bundle: InboundServiceBundle,
    *,
    channel: ContactChannel,
) -> InboundServiceBundle:
    return replace(
        webhook_bundle,
        llm_client=_FakeLLMClientForContinuation(
            classification_text=_classification_json(
                intent="general_reply",
                summary_text="Lead asked a general follow-up question.",
            ),
            draft_text=_draft_json(body="Absolutely — I can share a few more details."),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
                quiet_hours_enabled=False,
                inbound_email_address="nurture@inbound.example.com",
            )
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_execution_config(channel=channel)
        ),
        message_repository=FakeOutboundMessageRepository(),
        sms_provider=FakeSMSProvider("SM-CONT-123"),
        email_provider=FakeEmailProvider("email-cont-123"),
    )


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


def test_follow_up_boss_inbound_webhook_queues_temporal_signal_after_commit(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
) -> None:
    response = webhook_client.post(
        "/api/v1/webhooks/follow-up-boss/inbound-messages",
        json={
            "workspace_id": str(WORKSPACE_ID),
            "provider_event_id": "evt-signal-1",
            "provider_message_id": "msg-signal-1",
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
    assert body["signal_queued"] is True
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        webhook_bundle.temporal_signal_outbox_repository,
    )
    entries = tuple(outbox_repository.entries.values())
    assert len(entries) == 1
    entry = entries[0]
    assert entry.temporal_workflow_id == "workflow-123"
    assert entry.payload["inbound_action"] == "human_handoff"
    assert entry.payload["reason"] == "human_requested"
    assert entry.payload["lead_id"] == str(LEAD_ID)
    assert entry.payload["conversation_id"] == body["conversation_id"]
    assert entry.payload["inbound_message_id"] == body["inbound_message_id"]
    assert body["handoff_required"] is True
    assert body["intent"] == "human_requested"
    assert body["review_tag_applied"] is False
    assert body["review_notification_sent"] is False
    assert body["continue_ai_status"] is None
    assert body["continue_ai_outbound_message_id"] is None
    assert body["continue_ai_provider_message_id"] is None
    assert body["continue_ai_pause_reason"] is None
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_follow_up_boss_inbound_webhook_returns_duplicate_on_replay(
    webhook_client: TestClient,
    webhook_bundle: InboundServiceBundle,
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
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        webhook_bundle.temporal_signal_outbox_repository,
    )
    assert len(outbox_repository.entries) == 1


def test_twilio_inbound_webhook_processes_sms_reply_with_workspace_scoped_route(
    webhook_bundle: InboundServiceBundle,
) -> None:
    settings = Settings(twilio_auth_token=None, twilio_from_phone="+15551234567")

    with _build_webhook_client(webhook_bundle, settings) as client:
        response = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data={
                "MessageSid": "SM-IN-1",
                "From": "+1 (555) 555-0123",
                "To": "+15551234567",
                "Body": "Can someone call me today?",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is True
    assert body["intent"] == "human_requested"
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_twilio_inbound_webhook_sends_handoff_sms_acknowledgment_with_workspace_policy(
    webhook_bundle: InboundServiceBundle,
) -> None:
    sms_provider = FakeSMSProvider("SM-ACK-1")
    bundle = replace(
        webhook_bundle,
        llm_client=FakeLLMClient(
            _classification_json(intent="human_requested"),
            _acknowledgment_json(body="Thanks — our team will get back to you soon."),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
                quiet_hours_enabled=False,
                inbound_email_address="nurture@inbound.example.com",
            )
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_execution_config(channel=ContactChannel.SMS)
        ),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                lead_acknowledgment_sms_enabled=True,
                lead_acknowledgment_sms_body="Thanks — our team will get back to you soon.",
            )
        ),
        message_repository=FakeOutboundMessageRepository(),
        sms_provider=sms_provider,
    )

    with _build_webhook_client(
        bundle,
        Settings(twilio_auth_token=None, twilio_from_phone="+15551234567"),
    ) as client:
        response = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data={
                "MessageSid": "SM-IN-ACK-1",
                "From": "+1 (555) 555-0123",
                "To": "+15551234567",
                "Body": "Can someone call me today?",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert [message.body for message in sms_provider.messages] == [
        "Thanks — our team will get back to you soon.",
    ]


def test_twilio_inbound_webhook_returns_general_reply_fields_for_sms_route(
    webhook_bundle: InboundServiceBundle,
) -> None:
    bundle = _continue_ai_webhook_bundle(webhook_bundle, channel=ContactChannel.SMS)

    with _build_webhook_client(
        bundle,
        Settings(twilio_auth_token=None, twilio_from_phone="+15551234567"),
    ) as client:
        response = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data={
                "MessageSid": "SM-IN-CONT-1",
                "From": "+15555550123",
                "To": "+15551234567",
                "Body": "Can you tell me a little more?",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is False
    assert body["intent"] == "general_reply"
    assert body["signal_queued"] is True
    assert body["review_tag_applied"] is False
    assert body["review_notification_sent"] is False
    assert body["continue_ai_status"] == "sent"
    assert body["continue_ai_outbound_message_id"] is not None
    assert body["continue_ai_provider_message_id"] == "SM-CONT-123"
    assert body["continue_ai_pause_reason"] is None
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        bundle.temporal_signal_outbox_repository,
    )
    entry = next(iter(outbox_repository.entries.values()))
    assert entry.payload["inbound_action"] == "continue_ai"


def test_twilio_inbound_webhook_returns_duplicate_on_replay(
    webhook_bundle: InboundServiceBundle,
) -> None:
    settings = Settings(twilio_auth_token=None, twilio_from_phone="+15551234567")
    payload = {
        "MessageSid": "SM-IN-DUP",
        "From": "+15555550123",
        "To": "+15551234567",
        "Body": "Can someone call me today?",
    }

    with _build_webhook_client(webhook_bundle, settings) as client:
        first = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )
        second = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


def test_twilio_inbound_webhook_rejects_when_lead_is_not_found(
    webhook_bundle: InboundServiceBundle,
) -> None:
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
    bundle = replace(
        webhook_bundle,
        lead_repository=FakeLeadRepository(None),
        lead_workflow_repository=lead_workflow_repository,
    )

    with _build_webhook_client(
        bundle,
        Settings(twilio_auth_token=None, twilio_from_phone="+15551234567"),
    ) as client:
        response = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data={
                "MessageSid": "SM-IN-MISSING",
                "From": "+15555550999",
                "To": "+15551234567",
                "Body": "Hello?",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reasons"] == ["lead_not_found"]


def test_twilio_inbound_signature_is_required_when_auth_token_is_configured(
    webhook_bundle: InboundServiceBundle,
) -> None:
    settings = Settings(
        twilio_auth_token=SecretStr("secret-token"),
        twilio_from_phone="+15551234567",
    )
    validator = RequestValidator("secret-token")
    form_data = {
        "MessageSid": "SM-IN-SIGNED",
        "From": "+15555550123",
        "To": "+15551234567",
        "Body": "Can someone call me today?",
    }
    signature = validator.compute_signature(
        f"http://testserver/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
        form_data,
    )

    with _build_webhook_client(webhook_bundle, settings) as client:
        good = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data=form_data,
            headers={"X-Twilio-Signature": signature},
        )
        bad = client.post(
            f"/api/v1/webhooks/twilio/inbound-messages/{WORKSPACE_ID}",
            data=form_data,
            headers={"X-Twilio-Signature": "bad-signature"},
        )

    assert good.status_code == 200
    assert bad.status_code == 401


def test_sendgrid_inbound_webhook_processes_email_reply_with_workspace_scoped_route(
    webhook_bundle: InboundServiceBundle,
) -> None:
    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: nurture@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-inbound-1@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Can someone call me today?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is True
    assert body["intent"] == "human_requested"
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_sendgrid_inbound_webhook_sends_handoff_email_acknowledgment_only_on_email_channel(
    webhook_bundle: InboundServiceBundle,
) -> None:
    sms_provider = FakeSMSProvider("SM-ACK-EMAIL-1")
    email_provider = FakeEmailProvider("email-ack-1")
    bundle = replace(
        webhook_bundle,
        llm_client=FakeLLMClient(
            _classification_json(intent="human_requested"),
            _acknowledgment_json(
                body="Thanks for your note. An agent will reply shortly.",
                subject="Ignored in favor of thread subject",
            ),
        ),
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(
            WorkspaceContactPolicy(
                workspace_id=WORKSPACE_ID,
                sms_compliance_state=SmsComplianceState.APPROVED,
                quiet_hours_enabled=False,
                inbound_email_address="nurture@inbound.example.com",
            )
        ),
        workspace_repository=FakeWorkspaceRepository(_workspace()),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_execution_config(channel=ContactChannel.EMAIL)
        ),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                lead_acknowledgment_sms_enabled=True,
                lead_acknowledgment_sms_body="Thanks — our team will get back to you soon.",
                lead_acknowledgment_email_enabled=True,
                lead_acknowledgment_email_subject="We received your request",
                lead_acknowledgment_email_body="Thanks for reaching out. Our team will reply soon.",
            )
        ),
        message_repository=FakeOutboundMessageRepository(),
        sms_provider=sms_provider,
        email_provider=email_provider,
    )

    with _build_webhook_client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: nurture@inbound.example.com\n"
                    "Subject: Re: Need to chat\n"
                    "Message-ID: <sendgrid-inbound-ack@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "nurture@inbound.example.com",
                "subject": "Re: Need to chat",
                "text": "Can someone contact me by email?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert sms_provider.messages == []
    assert len(email_provider.messages) == 1
    assert email_provider.messages[0].subject == "Re: Need to chat"
    assert email_provider.messages[0].body == "Thanks for your note. An agent will reply shortly."


def test_sendgrid_inbound_webhook_returns_general_reply_fields_for_email_route(
    webhook_bundle: InboundServiceBundle,
) -> None:
    bundle = _continue_ai_webhook_bundle(webhook_bundle, channel=ContactChannel.EMAIL)

    with _build_webhook_client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: nurture@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-inbound-cont@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Can you send a little more detail?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is False
    assert body["intent"] == "general_reply"
    assert body["signal_queued"] is True
    assert body["review_tag_applied"] is False
    assert body["review_notification_sent"] is False
    assert body["continue_ai_status"] == "sent"
    assert body["continue_ai_outbound_message_id"] is not None
    assert body["continue_ai_provider_message_id"] == "email-cont-123"
    assert body["continue_ai_pause_reason"] is None
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        bundle.temporal_signal_outbox_repository,
    )
    entry = next(iter(outbox_repository.entries.values()))
    assert entry.payload["inbound_action"] == "continue_ai"


def test_follow_up_boss_inbound_webhook_returns_review_pause_fields(
    webhook_bundle: InboundServiceBundle,
) -> None:
    notification_provider = FakeNotificationProvider()
    crm_client = FakeCRMClient(
        assigned_agent=CRMAgent(
            crm_agent_id="agent-99",
            name="Ada Agent",
            email="agent@example.com",
        )
    )
    bundle = replace(
        webhook_bundle,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="unclear",
                summary_text="Lead reply is ambiguous.",
            )
        ),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                crm_review_tag="needs_agent_review",
            )
        ),
    )

    with _build_webhook_client(bundle) as client:
        response = client.post(
            "/api/v1/webhooks/follow-up-boss/inbound-messages",
            json={
                "workspace_id": str(WORKSPACE_ID),
                "provider_event_id": "evt-review-1",
                "provider_message_id": "msg-review-1",
                "crm_lead_id": "crm-123",
                "channel": "sms",
                "body": "I'm not really sure what I want yet.",
                "received_at": NOW.isoformat(),
                "payload_redacted": {"event": "redacted"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is False
    assert body["intent"] == "unclear"
    assert body["signal_queued"] is True
    assert body["review_tag_applied"] is True
    assert body["review_notification_sent"] is True
    assert body["review_notification_recipient"] == "agent@example.com"
    assert body["review_notification_failure_reason"] is None
    assert body["continue_ai_status"] is None
    assert body["continue_ai_outbound_message_id"] is None
    assert body["continue_ai_provider_message_id"] is None


def test_sendgrid_inbound_webhook_returns_duplicate_on_replay(
    webhook_bundle: InboundServiceBundle,
) -> None:
    payload = {
        "headers": (
            "From: Lead Person <lead@example.com>\n"
            "To: nurture@inbound.example.com\n"
            "Subject: Re: Checking in\n"
            "Message-ID: <sendgrid-inbound-dup@example.com>\n"
        ),
        "from": "Lead Person <lead@example.com>",
        "to": "nurture@inbound.example.com",
        "subject": "Re: Checking in",
        "text": "Can someone call me today?",
        "attachments": "0",
    }

    with _build_webhook_client(webhook_bundle) as client:
        first = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )
        second = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


def test_sendgrid_inbound_webhook_rejects_when_lead_is_not_found(
    webhook_bundle: InboundServiceBundle,
) -> None:
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
    bundle = replace(
        webhook_bundle,
        lead_repository=FakeLeadRepository(None),
        lead_workflow_repository=lead_workflow_repository,
    )

    with _build_webhook_client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Missing Person <missing@example.com>\n"
                    "To: nurture@inbound.example.com\n"
                    "Message-ID: <sendgrid-missing@example.com>\n"
                ),
                "from": "Missing Person <missing@example.com>",
                "to": "nurture@inbound.example.com",
                "text": "Hello?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reasons"] == ["lead_not_found"]


def test_sendgrid_inbound_signature_is_required_when_public_key_is_configured(
    webhook_bundle: InboundServiceBundle,
) -> None:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    public_key = "".join(
        line.strip()
        for line in public_key_pem.splitlines()
        if "BEGIN" not in line and "END" not in line
    )
    settings = Settings(sendgrid_event_webhook_public_key=SecretStr(public_key))
    boundary = "sendgrid-boundary-123"
    multipart_body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="headers"\r\n\r\n'
        "From: Lead Person <lead@example.com>\n"
        "To: nurture@inbound.example.com\n"
        "Message-ID: <sendgrid-signed@example.com>\n\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="from"\r\n\r\n'
        "Lead Person <lead@example.com>\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="to"\r\n\r\n'
        "nurture@inbound.example.com\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="text"\r\n\r\n'
        "Can someone call me today?\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="attachments"\r\n\r\n'
        "1\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="attachment1"; filename="note.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "hello from attachment\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    timestamp = str(int(NOW.timestamp()))
    signature = base64.b64encode(
        private_key.sign(timestamp.encode() + multipart_body, ec.ECDSA(hashes.SHA256()))
    ).decode()

    with _build_webhook_client(webhook_bundle, settings) as client:
        good = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            content=multipart_body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Twilio-Email-Event-Webhook-Signature": signature,
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
            },
        )
        bad = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            content=multipart_body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Twilio-Email-Event-Webhook-Signature": "bad-signature",
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
            },
        )

    assert good.status_code == 200
    assert bad.status_code == 401


def test_sendgrid_inbound_webhook_rejects_when_to_address_does_not_match_configured_inbound_email(
    webhook_bundle: InboundServiceBundle,
) -> None:
    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: wrong@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-mismatch@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "wrong@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Can someone call me today?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reasons"] == ["inbound_email_address_mismatch"]


def test_sendgrid_inbound_webhook_rejects_when_to_address_is_unparseable(
    webhook_bundle: InboundServiceBundle,
) -> None:
    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: \n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-unparseable@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "",
                "subject": "Re: Checking in",
                "text": "Can someone call me today?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reasons"] == ["invalid_to_address"]


def test_sendgrid_inbound_webhook_allows_when_no_contact_policy_is_configured(
    webhook_bundle: InboundServiceBundle,
) -> None:
    bundle = replace(
        webhook_bundle,
        workspace_contact_policy_repository=FakeWorkspaceContactPolicyRepository(None),
    )

    with _build_webhook_client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: any@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-no-policy@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "any@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Can someone call me today?",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"


def _lead(
    *,
    lead_id: UUID = LEAD_ID,
    crm_lead_id: str = "crm-123",
    primary_email: str = "lead@example.com",
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id=crm_lead_id,
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="nurture",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        primary_email=primary_email,
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


def _outbound_email_message(
    *,
    message_id: UUID,
    lead_id: UUID,
    provider_name: str,
    provider_message_id: str,
    idempotency_key: str,
    subject: str = "Checking in",
    reply_routing_token: str | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=message_id,
        workspace_id=WORKSPACE_ID,
        lead_id=lead_id,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="email-step-1",
        channel=ContactChannel.EMAIL,
        status=OutboundMessageStatus.SENT,
        idempotency_key=idempotency_key,
        body="Checking in",
        created_at=NOW,
        updated_at=NOW,
        subject=subject,
        sent_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name=provider_name,
        provider_message_id=provider_message_id,
        reply_routing_token=reply_routing_token,
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
    assert body["signal_queued"] is True
    workflow_repository = cast(FakeLeadWorkflowRepository, webhook_bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        webhook_bundle.temporal_signal_outbox_repository,
    )
    entries = tuple(outbox_repository.entries.values())
    assert len(entries) == 1
    assert entries[0].temporal_workflow_id == "workflow-123"


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
    assert first.json()["status"] == "ignored"
    assert first.json()["reasons"] == ["not_meaningful_human_activity"]
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
    assert body["signal_queued"] is True
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


def test_follow_up_boss_crm_webhook_processes_people_updated_without_pausing_workflow(
    webhook_bundle: InboundServiceBundle,
) -> None:
    crm_client = _FakeCRMClientForWebhook(
        fetch_result={
            "people": [
                {
                    "id": "crm-123",
                    "firstName": "Jamie",
                    "lastName": "Lead",
                    "stage": "nurture",
                    "assignedTo": "agent-100",
                }
            ]
        }
    )
    bundle = replace(
        webhook_bundle,
        crm_client=cast(CRMClient, crm_client),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": "evt-people-1",
                "eventCreated": NOW.isoformat(),
                "event": "peopleUpdated",
                "resourceIds": [123],
                "uri": "https://api.followupboss.com/v1/people?id=crm-123",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["event_type"] == "peopleUpdated"
    assert body["processed_count"] == 1
    workflow_repository = cast(FakeLeadWorkflowRepository, bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.WAITING_FOR_RESPONSE


def test_follow_up_boss_crm_webhook_pauses_for_people_updated_contacted_change(
    webhook_bundle: InboundServiceBundle,
) -> None:
    crm_client = _FakeCRMClientForWebhook(
        fetch_result={
            "people": [
                {
                    "id": "crm-123",
                    "firstName": "Jamie",
                    "lastName": "Lead",
                    "stage": "nurture",
                    "assignedTo": "agent-100",
                    "contacted": 1,
                    "customFields": {"email_permission_status": "confirmed"},
                }
            ]
        }
    )
    bundle = replace(
        webhook_bundle,
        crm_client=cast(CRMClient, crm_client),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": "evt-people-contacted-1",
                "eventCreated": NOW.isoformat(),
                "event": "peopleUpdated",
                "resourceIds": [123],
                "uri": "https://api.followupboss.com/v1/people?id=crm-123",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["event_type"] == "peopleUpdated"
    assert body["processed_count"] == 1
    workflow_repository = cast(FakeLeadWorkflowRepository, bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED
    outbox_repository = cast(
        FakeTemporalSignalOutboxRepository,
        bundle.temporal_signal_outbox_repository,
    )
    entries = tuple(outbox_repository.entries.values())
    assert len(entries) == 1
    assert entries[0].signal_name == TemporalSignalName.PAUSE_REQUESTED
    assert entries[0].payload["reason"] == "crm_status_changed"


@pytest.mark.parametrize(
    ("event_type", "collection_key", "resource"),
    [
        (
            "textMessagesCreated",
            "textMessages",
            {
                "id": 88,
                "personId": "crm-123",
                "created": NOW.isoformat(),
                "isIncoming": False,
                "userId": 42,
                "message": "Checking whether you are still looking.",
            },
        ),
        (
            "callsCreated",
            "calls",
            {
                "id": 55,
                "personId": "crm-123",
                "created": NOW.isoformat(),
                "isIncoming": False,
                "userId": 42,
                "description": "Left voicemail",
            },
        ),
    ],
)
def test_follow_up_boss_crm_webhook_pauses_for_outbound_communication_activity(
    webhook_bundle: InboundServiceBundle,
    event_type: str,
    collection_key: str,
    resource: dict[str, object],
) -> None:
    bundle = replace(
        webhook_bundle,
        crm_client=cast(
            CRMClient,
            _FakeCRMClientForWebhook(fetch_result={collection_key: [resource]}),
        ),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": f"evt-{event_type}",
                "eventCreated": NOW.isoformat(),
                "event": event_type,
                "resourceIds": [123],
                "uri": f"https://api.followupboss.com/v1/{collection_key}?id=1",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["processed_count"] == 1
    workflow_repository = cast(FakeLeadWorkflowRepository, bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED


@pytest.mark.parametrize(
    ("event_type", "collection_key", "resource"),
    [
        (
            "textMessagesCreated",
            "textMessages",
            {
                "id": 89,
                "personId": "crm-123",
                "created": NOW.isoformat(),
                "isIncoming": True,
                "userId": 42,
                "message": "Yes, I am still looking.",
            },
        ),
        (
            "callsCreated",
            "calls",
            {
                "id": 56,
                "personId": "crm-123",
                "created": NOW.isoformat(),
                "isIncoming": True,
                "userId": 42,
                "description": "Lead returned the call",
            },
        ),
    ],
)
def test_follow_up_boss_crm_webhook_processes_inbound_communication_activity(
    webhook_bundle: InboundServiceBundle,
    event_type: str,
    collection_key: str,
    resource: dict[str, object],
) -> None:
    bundle = replace(
        webhook_bundle,
        crm_client=cast(
            CRMClient,
            _FakeCRMClientForWebhook(fetch_result={collection_key: [resource]}),
        ),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": f"evt-{event_type}-incoming",
                "eventCreated": NOW.isoformat(),
                "event": event_type,
                "resourceIds": [123],
                "uri": f"https://api.followupboss.com/v1/{collection_key}?id=1",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["processed_count"] == 1
    assert body["reasons"] == []
    workflow_repository = cast(FakeLeadWorkflowRepository, bundle.lead_workflow_repository)
    workflow = workflow_repository.latest_by_lead[(WORKSPACE_ID, LEAD_ID)]
    assert workflow.state == WorkflowState.PAUSED


def test_follow_up_boss_crm_webhook_returns_duplicate_on_replay(
    webhook_bundle: InboundServiceBundle,
) -> None:
    fetch_result = {
        "people": [
            {
                "id": "crm-123",
                "firstName": "Jamie",
                "lastName": "Lead",
                "stage": "nurture",
                "assignedTo": "agent-100",
            }
        ]
    }
    bundle = replace(
        webhook_bundle,
        crm_client=cast(CRMClient, _FakeCRMClientForWebhook(fetch_result=fetch_result)),
    )
    payload = {
        "eventId": "evt-people-dup",
        "eventCreated": NOW.isoformat(),
        "event": "peopleUpdated",
        "resourceIds": [123],
        "uri": "https://api.followupboss.com/v1/people?id=crm-123",
    }

    with _build_webhook_client_with_handler(bundle) as client:
        first = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json=payload,
        )
        second = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json=payload,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


def test_follow_up_boss_crm_webhook_ignores_unknown_event(
    webhook_bundle: InboundServiceBundle,
) -> None:
    bundle = replace(
        webhook_bundle,
        crm_client=cast(CRMClient, _FakeCRMClientForWebhook(fetch_result=None)),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": "evt-unknown-1",
                "eventCreated": NOW.isoformat(),
                "event": "customEvent",
                "resourceIds": [1],
                "uri": "https://api.followupboss.com/v1/custom?id=1",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ignored"
    assert body["reasons"] == ["unsupported_event_type"]


def test_follow_up_boss_crm_webhook_auto_enrolls_matching_configured_tag(
    webhook_bundle: InboundServiceBundle,
) -> None:
    fetch_result = {
        "people": [
            {
                "id": "crm-tag-1",
                "firstName": "Taylor",
                "lastName": "Tagged",
                "stage": "Lead",
                "assignedTo": "agent-99",
                "email": "tagged@example.com",
                "phone": "+15555550124",
                "tags": ["configured_fub_tag"],
                "customFields": {"email_permission_status": "confirmed"},
            }
        ]
    }
    bundle = replace(
        webhook_bundle,
        lead_repository=FakeLeadRepository(None),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        crm_client=cast(CRMClient, _FakeCRMClientForWebhook(fetch_result=fetch_result)),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_execution_config(
                channel=ContactChannel.EMAIL,
                crm_enrollment_tag="configured_fub_tag",
            )
        ),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        llm_client=FakeClassificationLLMClient(outcome="dormant"),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": "evt-people-tag-enroll-1",
                "eventCreated": NOW.isoformat(),
                "event": "peopleCreated",
                "resourceIds": [456],
                "uri": "https://api.followupboss.com/v1/people?id=crm-tag-1",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["processed_count"] == 1
    enrollments = cast(FakeCampaignEnrollmentRepository, bundle.campaign_enrollment_repository)
    assert len(enrollments.enrollments) == 1
    temporal = cast(FakeTemporalWorkflowStarter, bundle.temporal_workflow_starter)
    assert len(temporal.calls) == 1
    assert cast(FakeSession, bundle.session).commit_count == 2


def test_follow_up_boss_crm_webhook_completes_tag_time_human_handoff(
    webhook_bundle: InboundServiceBundle,
) -> None:
    fetch_result = {
        "people": [
            {
                "id": "crm-tag-2",
                "firstName": "Taylor",
                "lastName": "Tagged",
                "stage": "Lead",
                "assignedTo": "agent-99",
                "email": "tagged@example.com",
                "phone": "+15555550124",
                "tags": ["configured_fub_tag", "needs_agent_review"],
                "customFields": {"email_permission_status": "confirmed"},
            }
        ]
    }
    notification_provider = FakeNotificationProvider()
    crm_client = _FakeCRMClientForWebhook(fetch_result=fetch_result)
    bundle = replace(
        webhook_bundle,
        lead_repository=FakeLeadRepository(replace(_lead(), crm_lead_id="crm-tag-2")),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        handoff_repository=FakeHandoffRepository(),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=cast(NotificationProvider, notification_provider),
        campaign_execution_repository=FakeCampaignExecutionRepository(
            _campaign_execution_config(
                channel=ContactChannel.EMAIL,
                crm_enrollment_tag="configured_fub_tag",
            )
        ),
        campaign_enrollment_repository=FakeCampaignEnrollmentRepository(),
        temporal_workflow_starter=FakeTemporalWorkflowStarter(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            (
                CrmConversationEvent(
                    crm_conversation_event_id=UUID(
                        "50000000-0000-0000-0000-000000000006"
                    ),
                    workspace_id=WORKSPACE_ID,
                    lead_id=LEAD_ID,
                    crm_provider="follow_up_boss",
                    crm_activity_id="crm-tag-inbound-1",
                    activity_type="TextMessage",
                    occurred_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                    direction=CrmConversationEventDirection.INBOUND,
                    content="I want to speak with an agent about buying.",
                ),
            )
        ),
        llm_client=FakeClassificationLLMClient(
            outcome="human_handoff",
            handoff_reason_code="human_requested",
        ),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            WorkspaceHandoffConfig(
                workspace_id=WORKSPACE_ID,
                fallback_recipient_email="fallback@example.com",
                crm_handoff_tag="human_handoff_required",
                crm_review_tag="needs_agent_review",
                crm_custom_fields={"handoff_status": "required"},
            )
        ),
    )

    with _build_webhook_client_with_handler(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/crm/follow-up-boss/{WORKSPACE_ID}",
            json={
                "eventId": "evt-people-tag-handoff-1",
                "eventCreated": NOW.isoformat(),
                "event": "peopleCreated",
                "resourceIds": [789],
                "uri": "https://api.followupboss.com/v1/people?id=crm-tag-2",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["processed_count"] == 1
    handoffs = cast(FakeHandoffRepository, bundle.handoff_repository)
    enrollments = cast(FakeCampaignEnrollmentRepository, bundle.campaign_enrollment_repository)
    completion_repository = cast(
        FakeHandoffCompletionRepository,
        bundle.handoff_completion_repository,
    )
    handoff_record = completion_repository.record
    assert {handoff.handoff_id for handoff in handoffs.saved} == {
        handoff_record.handoff_id if handoff_record is not None else None
    }
    assert len(notification_provider.notifications) == 1
    assert crm_client.tags == ["human_handoff_required"]
    assert crm_client.custom_field_updates[-1]["handoff_status"] == "required"
    assert len(crm_client.notes) == 1
    assert len(enrollments.enrollments) == 0
    assert cast(FakeSession, bundle.session).commit_count == 1


def _mailgun_signature(signing_key: str, token: str, timestamp: str) -> str:
    return hmac.new(
        signing_key.encode(),
        f"{timestamp}{token}".encode(),
        sha256,
    ).hexdigest()


def test_mailgun_inbound_webhook_processes_email_reply(
    webhook_bundle: InboundServiceBundle,
) -> None:
    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "Can someone call me today?",
                "body-plain": "Can someone call me today?",
                "Message-Id": "<mailgun-inbound-1@example.com>",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["handoff_required"] is True
    assert body["intent"] == "human_requested"
    assert cast(FakeSession, webhook_bundle.session).commit_count == 1


def test_mailgun_inbound_payload_uses_subject_from_message_headers_when_field_missing() -> None:
    payload = MailgunInboundParsePayload.model_validate(
        {
            "sender": "lead@example.com",
            "from": "Lead Person <lead@example.com>",
            "recipient": "nurture@inbound.example.com",
            "stripped-text": "Can someone call me today?",
            "Message-Id": "<mailgun-inbound-headers-only@example.com>",
            "message-headers": (
                '[["Subject", "Re: Checking in"], '
                '["In-Reply-To", "<thread-root@example.com>"], '
                '["References", "<thread-root@example.com>"]]'
            ),
        }
    )

    assert payload.subject == "Re: Checking in"
    assert payload.in_reply_to_message_ids == ("thread-root@example.com",)
    assert payload.reference_message_ids == ("thread-root@example.com",)


def test_mailgun_inbound_webhook_matches_duplicate_email_lead_from_thread_reference(
    webhook_bundle: InboundServiceBundle,
) -> None:
    older_lead_id = UUID("40000000-0000-0000-0000-000000000099")
    older_lead = _lead(
        lead_id=older_lead_id,
        crm_lead_id="crm-older",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(older_lead)

    message_repository = cast(FakeOutboundMessageRepository, webhook_bundle.message_repository)
    message_repository._store(
        _outbound_email_message(
            message_id=UUID("60000000-0000-0000-0000-000000000001"),
            lead_id=older_lead_id,
            provider_name="mailgun",
            provider_message_id="thread-older@example.com",
            idempotency_key="email:older-thread",
        )
    )

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "Following up on the older thread.",
                "body-plain": "Following up on the older thread.",
                "Message-Id": "<mailgun-inbound-threaded@example.com>",
                "message-headers": (
                    '[["In-Reply-To", "<'
                    + build_outbound_email_message_id(UUID("60000000-0000-0000-0000-000000000001"))
                    + '>"], ["References", "<'
                    + build_outbound_email_message_id(UUID("60000000-0000-0000-0000-000000000001"))
                    + '>"]]'
                ),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["lead_id"] == str(older_lead_id)


def test_mailgun_inbound_webhook_matches_duplicate_email_lead_from_reply_token(
    webhook_bundle: InboundServiceBundle,
) -> None:
    older_lead_id = UUID("40000000-0000-0000-0000-000000000102")
    older_lead = _lead(
        lead_id=older_lead_id,
        crm_lead_id="crm-older-token",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(older_lead)

    message_repository = cast(FakeOutboundMessageRepository, webhook_bundle.message_repository)
    message_repository._store(
        _outbound_email_message(
            message_id=UUID("60000000-0000-0000-0000-000000000003"),
            lead_id=older_lead_id,
            provider_name="mailgun",
            provider_message_id="thread-token-older@example.com",
            idempotency_key="email:older-token",
            reply_routing_token="replytoken123",
        )
    )

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "nurture+replytoken123@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "Following up using reply routing.",
                "body-plain": "Following up using reply routing.",
                "Message-Id": "<mailgun-inbound-reply-token@example.com>",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["lead_id"] == str(older_lead_id)


def test_mailgun_inbound_webhook_rejects_unknown_reply_token_before_sender_fallback(
    webhook_bundle: InboundServiceBundle,
) -> None:
    duplicate_lead = _lead(
        lead_id=UUID("40000000-0000-0000-0000-000000000103"),
        crm_lead_id="crm-duplicate-token",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(duplicate_lead)

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "nurture+missingtoken@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "This token should not resolve.",
                "body-plain": "This token should not resolve.",
                "Message-Id": "<mailgun-missing-token@example.com>",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reasons"] == ["reply_token_not_found"]


def test_mailgun_inbound_webhook_rejects_when_to_address_does_not_match_configured_inbound_email(
    webhook_bundle: InboundServiceBundle,
) -> None:
    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "wrong@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "Can someone call me today?",
                "Message-Id": "<mailgun-mismatch@example.com>",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reasons"] == ["inbound_email_address_mismatch"]


def test_mailgun_inbound_webhook_rejects_when_lead_is_not_found(
    webhook_bundle: InboundServiceBundle,
) -> None:
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
    bundle = replace(
        webhook_bundle,
        lead_repository=FakeLeadRepository(None),
        lead_workflow_repository=lead_workflow_repository,
    )

    with _build_webhook_client(bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "missing@example.com",
                "from": "Missing Person <missing@example.com>",
                "recipient": "nurture@inbound.example.com",
                "stripped-text": "Hello?",
                "Message-Id": "<mailgun-missing@example.com>",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reasons"] == ["lead_not_found"]


def test_mailgun_inbound_webhook_rejects_ambiguous_duplicate_sender(
    webhook_bundle: InboundServiceBundle,
) -> None:
    duplicate_lead = _lead(
        lead_id=UUID("40000000-0000-0000-0000-000000000100"),
        crm_lead_id="crm-duplicate",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(duplicate_lead)

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={
                "sender": "lead@example.com",
                "from": "Lead Person <lead@example.com>",
                "recipient": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "stripped-text": "No thread metadata here.",
                "body-plain": "No thread metadata here.",
                "Message-Id": "<mailgun-ambiguous@example.com>",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["reasons"] == ["ambiguous_lead_match"]


def test_mailgun_inbound_signature_is_required_when_signing_key_is_configured(
    webhook_bundle: InboundServiceBundle,
) -> None:
    signing_key = "mailgun-signing-key"
    settings = Settings(mailgun_webhook_signing_key=SecretStr(signing_key))
    token = "token-123"
    timestamp = "1234567890"
    signature = _mailgun_signature(signing_key, token, timestamp)
    form_data = {
        "sender": "lead@example.com",
        "from": "Lead Person <lead@example.com>",
        "recipient": "nurture@inbound.example.com",
        "subject": "Re: Checking in",
        "stripped-text": "Can someone call me today?",
        "Message-Id": "<mailgun-signed@example.com>",
        "token": token,
        "timestamp": timestamp,
        "signature": signature,
    }

    with _build_webhook_client(webhook_bundle, settings) as client:
        good = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data=form_data,
        )
        bad = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data={**form_data, "signature": "bad-signature"},
        )

    assert good.status_code == 200
    assert bad.status_code == 401


def test_mailgun_inbound_webhook_returns_duplicate_on_replay(
    webhook_bundle: InboundServiceBundle,
) -> None:
    payload = {
        "sender": "lead@example.com",
        "from": "Lead Person <lead@example.com>",
        "recipient": "nurture@inbound.example.com",
        "subject": "Re: Checking in",
        "stripped-text": "Can someone call me today?",
        "Message-Id": "<mailgun-inbound-dup@example.com>",
    }

    with _build_webhook_client(webhook_bundle) as client:
        first = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )
        second = client.post(
            f"/api/v1/webhooks/mailgun/inbound-messages/{WORKSPACE_ID}",
            data=payload,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["reasons"] == ["duplicate_event"]


def test_sendgrid_inbound_webhook_matches_duplicate_email_lead_from_thread_reference(
    webhook_bundle: InboundServiceBundle,
) -> None:
    older_lead_id = UUID("40000000-0000-0000-0000-000000000101")
    older_lead = _lead(
        lead_id=older_lead_id,
        crm_lead_id="crm-sendgrid-older",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(older_lead)

    message_repository = cast(FakeOutboundMessageRepository, webhook_bundle.message_repository)
    message_repository._store(
        _outbound_email_message(
            message_id=UUID("60000000-0000-0000-0000-000000000002"),
            lead_id=older_lead_id,
            provider_name="sendgrid",
            provider_message_id="sendgrid-thread-older@example.com",
            idempotency_key="email:sendgrid-older-thread",
        )
    )
    thread_message_id = build_outbound_email_message_id(
        UUID("60000000-0000-0000-0000-000000000002")
    )

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: nurture@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-threaded-inbound@example.com>\n"
                    f"In-Reply-To: <{thread_message_id}>\n"
                    f"References: <{thread_message_id}>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "nurture@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Following up on the older SendGrid thread.",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["lead_id"] == str(older_lead_id)


def test_sendgrid_inbound_webhook_matches_duplicate_email_lead_from_reply_token(
    webhook_bundle: InboundServiceBundle,
) -> None:
    older_lead_id = UUID("40000000-0000-0000-0000-000000000104")
    older_lead = _lead(
        lead_id=older_lead_id,
        crm_lead_id="crm-sendgrid-token",
        primary_email="lead@example.com",
    )
    lead_repository = cast(FakeLeadRepository, webhook_bundle.lead_repository)
    lead_repository._store(older_lead)

    message_repository = cast(FakeOutboundMessageRepository, webhook_bundle.message_repository)
    message_repository._store(
        _outbound_email_message(
            message_id=UUID("60000000-0000-0000-0000-000000000004"),
            lead_id=older_lead_id,
            provider_name="sendgrid",
            provider_message_id="sendgrid-token-older@example.com",
            idempotency_key="email:sendgrid-token",
            reply_routing_token="sendgridtoken123",
        )
    )

    with _build_webhook_client(webhook_bundle) as client:
        response = client.post(
            f"/api/v1/webhooks/sendgrid/inbound-messages/{WORKSPACE_ID}",
            data={
                "headers": (
                    "From: Lead Person <lead@example.com>\n"
                    "To: nurture+sendgridtoken123@inbound.example.com\n"
                    "Subject: Re: Checking in\n"
                    "Message-ID: <sendgrid-reply-token@example.com>\n"
                ),
                "from": "Lead Person <lead@example.com>",
                "to": "nurture+sendgridtoken123@inbound.example.com",
                "subject": "Re: Checking in",
                "text": "Following up using SendGrid reply routing.",
                "attachments": "0",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["lead_id"] == str(older_lead_id)
