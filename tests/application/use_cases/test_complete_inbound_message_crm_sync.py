from datetime import UTC, datetime
from uuid import UUID

from app.application.use_cases.complete_inbound_message_crm_sync import (
    CompleteInboundMessageCRMSyncStatus,
    complete_inbound_message_crm_sync,
)
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    InboundMessage,
    InboundMessageCRMCompletionRecord,
    InboundMessageClassificationStatus,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases.test_process_inbound_message_event import FakeCRMClient

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("60000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("60000000-0000-0000-0000-000000000002")
INBOUND_MESSAGE_ID = UUID("60000000-0000-0000-0000-000000000003")
CONVERSATION_ID = UUID("60000000-0000-0000-0000-000000000004")


class FakeInboundMessageCRMCompletionRepository:
    def __init__(self, record: InboundMessageCRMCompletionRecord | None = None) -> None:
        self.record = record

    async def get_by_inbound_message_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> InboundMessageCRMCompletionRecord | None:
        if self.record is None:
            return None
        if self.record.workspace_id == workspace_id and self.record.inbound_message_id == inbound_message_id:
            return self.record
        return None

    async def save(
        self,
        completion: InboundMessageCRMCompletionRecord,
    ) -> InboundMessageCRMCompletionRecord:
        self.record = completion
        return completion


async def test_complete_inbound_message_crm_sync_refreshes_before_writing_note() -> None:
    crm_client = FakeCRMClient(activity_timestamps=(datetime(2026, 7, 16, 12, 5, tzinfo=UTC),))
    repository = FakeInboundMessageCRMCompletionRepository()

    result = await complete_inbound_message_crm_sync(
        lead=_lead(),
        inbound_message=_inbound_message(),
        summary_text="Lead asked for a callback.",
        intent=None,
        handoff_required=True,
        opt_out_detected=False,
        crm_sync_completion_repository=repository,
        crm_client=crm_client,
        now=NOW,
    )

    assert result.status == CompleteInboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["get_lead", "get_recent_activity", "add_note"]
    assert repository.record is not None
    assert repository.record.crm_updates_detected is True
    assert repository.record.completed_at == NOW


async def test_complete_inbound_message_crm_sync_skips_duplicate_note_after_partial_retry() -> None:
    repository = FakeInboundMessageCRMCompletionRepository(
        InboundMessageCRMCompletionRecord(
            inbound_message_id=INBOUND_MESSAGE_ID,
            workspace_id=WORKSPACE_ID,
            crm_note_idempotency_key="inbound-message:test:v1",
            crm_note_written_at=NOW,
            last_attempted_at=NOW,
        )
    )
    crm_client = FakeCRMClient()

    result = await complete_inbound_message_crm_sync(
        lead=_lead(),
        inbound_message=_inbound_message(),
        summary_text="Lead asked for a callback.",
        intent=None,
        handoff_required=False,
        opt_out_detected=False,
        crm_sync_completion_repository=repository,
        crm_client=crm_client,
        now=NOW,
    )

    assert result.status == CompleteInboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["get_lead", "get_recent_activity"]
    assert repository.record is not None
    assert repository.record.completed_at == NOW


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
    )


def _inbound_message() -> InboundMessage:
    return InboundMessage(
        inbound_message_id=INBOUND_MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        lead_id=LEAD_ID,
        channel=ContactChannel.SMS,
        provider="twilio",
        provider_message_id="SM123",
        body="Can an agent call me?",
        received_at=NOW,
        classification_status=InboundMessageClassificationStatus.CLASSIFIED,
        created_at=NOW,
    )