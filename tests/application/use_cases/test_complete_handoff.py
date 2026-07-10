from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent, CRMClient
from app.application.ports.notifications import HandoffNotification, NotificationSendResult
from app.application.use_cases.complete_handoff import HandoffCompletionStatus, complete_handoff
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import (
    Handoff,
    HandoffCompletionRecord,
    HandoffReasonCode,
    HandoffStatus,
    WorkspaceHandoffConfig,
)
from app.domain.leads import CanonicalLeadRecord, CRMProvider

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("30000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("30000000-0000-0000-0000-000000000002")
HANDOFF_ID = UUID("30000000-0000-0000-0000-000000000003")


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord) -> None:
        self.lead = lead

    async def get_by_id(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> CanonicalLeadRecord | None:
        return (
            self.lead
            if self.lead.workspace_id == workspace_id and self.lead.lead_id == lead_id
            else None
        )

    async def get_by_id_for_update(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self, workspace_id: WorkspaceId, crm_provider: CRMProvider, crm_lead_id: str
    ) -> CanonicalLeadRecord | None:
        return (
            self.lead
            if self.lead.workspace_id == workspace_id
            and self.lead.crm_provider == crm_provider
            and self.lead.crm_lead_id == crm_lead_id
            else None
        )

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeHandoffRepository:
    def __init__(self, handoff: Handoff) -> None:
        self.handoff = handoff

    async def get_by_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Handoff | None:
        return (
            self.handoff
            if self.handoff.workspace_id == workspace_id and self.handoff.handoff_id == handoff_id
            else None
        )

    async def save(self, handoff: Handoff) -> Handoff:
        self.handoff = handoff
        return handoff


class FakeHandoffCompletionRepository:
    def __init__(self, record: HandoffCompletionRecord | None = None) -> None:
        self.record = record

    async def get_by_handoff_id(
        self, workspace_id: WorkspaceId, handoff_id: UUID
    ) -> HandoffCompletionRecord | None:
        return (
            self.record
            if self.record
            and self.record.workspace_id == workspace_id
            and self.record.handoff_id == handoff_id
            else None
        )

    async def save(self, record: HandoffCompletionRecord) -> HandoffCompletionRecord:
        self.record = record
        return record


class FakeWorkspaceHandoffConfigRepository:
    def __init__(self, config: WorkspaceHandoffConfig | None = None) -> None:
        self.config = config

    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> WorkspaceHandoffConfig | None:
        return self.config if self.config and self.config.workspace_id == workspace_id else None

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        self.config = config
        return config


class FakeCRMClient:
    async def validate_connection(self, workspace_id: WorkspaceId) -> bool:
        return True

    async def get_lead(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CanonicalLead | None:
        return None

    async def search_leads(
        self,
        workspace_id: WorkspaceId,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[CanonicalLead]:
        return []

    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        return []

    async def get_assigned_agent(
        self, workspace_id: WorkspaceId, crm_lead_id: str
    ) -> CRMAgent | None:
        return CRMAgent(crm_agent_id="agent-99", name="Agent Smith", email="agent@example.com")

    async def add_note(self, workspace_id: WorkspaceId, crm_lead_id: str, content: str) -> None:
        self.note = content

    async def add_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        self.tag = tag

    async def remove_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self, workspace_id: WorkspaceId, crm_lead_id: str, fields: dict[str, str]
    ) -> None:
        self.fields = fields

    async def subscribe_to_events(self, workspace_id: WorkspaceId, webhook_url: str) -> None:
        return None


class FakeNotificationProvider:
    def __init__(self) -> None:
        self.notifications: list[HandoffNotification] = []

    async def send_handoff_notification(
        self, notification: HandoffNotification
    ) -> NotificationSendResult:
        self.notifications.append(notification)
        return NotificationSendResult(accepted=True, provider_reference="notif-123")

    async def send_preflight_digest(self, notification: object) -> NotificationSendResult:
        raise AssertionError


async def test_complete_handoff_notifies_and_writes_back() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    completion_repo = FakeHandoffCompletionRepository()
    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=FakeHandoffRepository(_handoff()),
        handoff_completion_repository=completion_repo,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(_config()),
        lead_repository=FakeLeadRepository(_lead()),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        now=NOW,
    )
    assert result.status == HandoffCompletionStatus.COMPLETED
    assert len(notification_provider.notifications) == 1
    assert crm_client.tag == "human_handoff_required"
    assert crm_client.fields == {"handoff_status": "required"}
    assert completion_repo.record is not None and completion_repo.record.completed_at == NOW


async def test_complete_handoff_retries_partial_record_without_resending_notification() -> None:
    initial = HandoffCompletionRecord(
        handoff_id=HANDOFF_ID,
        workspace_id=WORKSPACE_ID,
        notification_idempotency_key="handoff:test:v1",
        notification_recipient_id="agent-99",
        notification_recipient_destination="agent@example.com",
        notification_provider_reference="notif-123",
        notification_sent_at=NOW,
        crm_note_written_at=NOW,
        last_attempted_at=NOW,
    )
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=FakeHandoffRepository(
            replace(_handoff(), status=HandoffStatus.NOTIFIED, notified_at=NOW)
        ),
        handoff_completion_repository=FakeHandoffCompletionRepository(initial),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(_config()),
        lead_repository=FakeLeadRepository(_lead()),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        now=NOW,
    )
    assert result.status == HandoffCompletionStatus.COMPLETED
    assert notification_provider.notifications == []
    assert crm_client.tag == "human_handoff_required"


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="new",
        primary_email="lead@example.com",
        primary_phone="+15555550123",
    )


def _handoff() -> Handoff:
    return Handoff(
        handoff_id=HANDOFF_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        assigned_agent_crm_id="agent-99",
        reason_code=HandoffReasonCode.HUMAN_REQUESTED,
        summary="Lead asked for a callback.",
        latest_inbound_text="Can an agent call me?",
        preferences={"timeline": "today"},
        created_at=NOW,
    )


def _config() -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=WORKSPACE_ID,
        fallback_recipient_email="fallback@example.com",
        crm_handoff_tag="human_handoff_required",
        crm_custom_fields={"handoff_status": "required"},
    )
