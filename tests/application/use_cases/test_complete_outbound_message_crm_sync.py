from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.complete_outbound_message_crm_sync import (
    CompleteOutboundMessageCRMSyncStatus,
    complete_outbound_message_crm_sync,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageCRMCompletionRecord,
    OutboundMessageStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import WorkspaceHandoffConfig
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases.test_process_inbound_message_event import (
    FakeCRMClient,
    FakeOutboundMessageCRMCompletionRepository,
)

NOW = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("70000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("70000000-0000-0000-0000-000000000002")
MESSAGE_ID = UUID("70000000-0000-0000-0000-000000000003")
CAMPAIGN_ID = UUID("70000000-0000-0000-0000-000000000004")


async def test_complete_outbound_message_crm_sync_writes_note_once() -> None:
    crm_client = FakeCRMClient()
    repository = FakeOutboundMessageCRMCompletionRepository()

    result = await complete_outbound_message_crm_sync(
        lead=_lead(),
        outbound_message=_message(),
        crm_sync_completion_repository=repository,
        crm_client=crm_client,
        now=NOW,
        summary_text="Lead is price shopping.",
        latest_inbound_text="How much does it cost?",
    )

    assert result.status == CompleteOutboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["add_note"]
    assert len(crm_client.notes) == 1
    assert crm_client.note_subjects == ["AI OUTBOUND · SMS"]
    assert "AI OUTBOUND · SMS" in crm_client.notes[0]
    assert "Lead: +15555550123" in crm_client.notes[0]
    assert "Provider message id: SM123" in crm_client.notes[0]
    assert "Conversation summary:\nLead is price shopping." in crm_client.notes[0]
    assert repository.record is not None
    assert getattr(repository.record, "completed_at", None) == NOW


async def test_complete_outbound_message_crm_sync_updates_snapshot_fields() -> None:
    crm_client = FakeCRMClient()
    repository = FakeOutboundMessageCRMCompletionRepository()

    result = await complete_outbound_message_crm_sync(
        lead=_lead(),
        outbound_message=_message(),
        crm_sync_completion_repository=repository,
        crm_client=crm_client,
        now=NOW,
        summary_text="Lead is price shopping.",
        latest_inbound_text="How much does it cost?",
        workspace_handoff_config=_snapshot_config(),
        snapshot_status="waiting_for_response",
    )

    assert result.status == CompleteOutboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["add_note", "update_custom_fields"]
    assert crm_client.custom_field_updates == [
        {
            "ai_summary": "Lead is price shopping.",
            "ai_status": "waiting_for_response",
            "ai_latest_inbound": "How much does it cost?",
            "ai_latest_outbound": "Absolutely — I can share a few more details.",
            "ai_last_activity_at": NOW.isoformat(),
        }
    ]
    assert repository.record is not None
    assert getattr(repository.record, "crm_snapshot_updated_at", None) == NOW


async def test_complete_outbound_message_crm_sync_skips_duplicate_note_after_partial_retry(
) -> None:
    repository = FakeOutboundMessageCRMCompletionRepository(
        OutboundMessageCRMCompletionRecord(
            outbound_message_id=MESSAGE_ID,
            workspace_id=WORKSPACE_ID,
            crm_note_idempotency_key="outbound-message:test:v1",
            crm_note_written_at=NOW,
            last_attempted_at=NOW,
        )
    )
    crm_client = FakeCRMClient()

    result = await complete_outbound_message_crm_sync(
        lead=_lead(),
        outbound_message=_message(),
        crm_sync_completion_repository=repository,
        crm_client=crm_client,
        now=NOW,
    )

    assert result.status == CompleteOutboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == []
    assert repository.record is not None
    assert getattr(repository.record, "completed_at", None) == NOW


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        primary_phone="+15555550123",
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="ai-continuation:1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.SENT,
        idempotency_key="message:test:v1",
        body="Absolutely — I can share a few more details.",
        created_at=NOW,
        updated_at=NOW,
        sent_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name="twilio",
        provider_message_id="SM123",
    )


def _snapshot_config() -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=WORKSPACE_ID,
        crm_snapshot_summary_field="ai_summary",
        crm_snapshot_status_field="ai_status",
        crm_snapshot_latest_inbound_field="ai_latest_inbound",
        crm_snapshot_latest_outbound_field="ai_latest_outbound",
        crm_snapshot_last_activity_at_field="ai_last_activity_at",
    )