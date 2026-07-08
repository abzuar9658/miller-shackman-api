import pytest
from fastapi.testclient import TestClient

from app.interfaces.api.dependencies.inbound import InboundServiceBundle, get_inbound_service_bundle
from app.main import create_app
from tests.application.use_cases.test_process_inbound_message_event import (
    NOW,
    WORKSPACE_ID,
    FakeConversationRepository,
    FakeConversationSummaryRepository,
    FakeExternalEventRepository,
    FakeHandoffRepository,
    FakeInboundMessageRepository,
    FakeLeadRepository,
    FakeLeadWorkflowRepository,
    FakeLLMClient,
    FakeWorkflowTransitionRepository,
    _classification_json,
    _lead,
)


@pytest.fixture
def webhook_client() -> TestClient:
    app = create_app()
    bundle = InboundServiceBundle(
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        lead_workflow_repository=FakeLeadWorkflowRepository(None),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                handoff_required=True,
                handoff_reason="human_requested",
            ),
        ),
    )
    app.dependency_overrides[get_inbound_service_bundle] = lambda: bundle
    return TestClient(app)


def test_follow_up_boss_inbound_webhook_returns_processed_response(
    webhook_client: TestClient,
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
