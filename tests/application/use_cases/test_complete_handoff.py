from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity, CRMAgent, CRMClient
from app.application.ports.notifications import (
    HandoffNotification,
    NotificationSendResult,
    ReviewNotification,
)
from app.application.use_cases.complete_handoff import HandoffCompletionStatus, complete_handoff
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.conversations import (
    Handoff,
    HandoffCompletionRecord,
    HandoffReasonCode,
    HandoffStatus,
    WorkspaceHandoffConfig,
)
from app.domain.identity import User, UserStatus
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from tests.application.use_cases._lead_read_fakes import FakeUserRepository

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

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if (
            self.lead.workspace_id != workspace_id
            or self.lead.assigned_agent_crm_id != assigned_agent_crm_id
        ):
            return ()
        return (self.lead,)

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        if self.lead.workspace_id != workspace_id or self.lead.primary_phone != phone_number:
            return None
        return self.lead

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        matches = await self.list_by_primary_email(workspace_id, email_address)
        if len(matches) != 1:
            return None
        return matches[0]

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if self.lead.workspace_id != workspace_id or self.lead.primary_email != email_address:
            return ()
        return (self.lead,)

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeHandoffRepository:
    def __init__(self, handoff: Handoff) -> None:
        self.handoff = handoff

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        if self.handoff.workspace_id != workspace_id or self.handoff.lead_id != lead_id:
            return ()
        return (self.handoff,)[:limit]

    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        return ((self.handoff,) if self.handoff.workspace_id == workspace_id else ())[:limit]

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
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    def __init__(self, *, lead_tags: tuple[str, ...] = ()) -> None:
        self.lead_tags = list(lead_tags)
        self.tags: list[str] = []
        self.removed_tags: list[str] = []

    async def validate_connection(self, workspace_id: WorkspaceId) -> bool:
        return True

    async def get_lead(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
    ) -> CanonicalLead | None:
        return CanonicalLead(
            workspace_id=workspace_id,
            crm_lead_id=crm_lead_id,
            first_name="Jamie",
            last_name="Lead",
            tags=list(self.lead_tags),
        )

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

    async def get_lead_url(self, workspace_id: WorkspaceId, crm_lead_id: str) -> str | None:
        return f"https://app.followupboss.com/2/people/{crm_lead_id}"

    async def add_note(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        content: str,
        subject: str | None = None,
    ) -> None:
        self.note = content
        self.note_subject = subject

    async def add_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        self.tag = tag
        self.tags.append(tag)
        if tag not in self.lead_tags:
            self.lead_tags.append(tag)

    async def remove_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        self.removed_tags.append(tag)
        self.lead_tags = [existing_tag for existing_tag in self.lead_tags if existing_tag != tag]

    async def update_custom_fields(
        self, workspace_id: WorkspaceId, crm_lead_id: str, fields: dict[str, str]
    ) -> None:
        self.fields = fields

    async def subscribe_to_events(self, workspace_id: WorkspaceId, webhook_url: str) -> None:
        return None

    async def fetch_resource_by_uri(
        self, workspace_id: WorkspaceId, uri: str
    ) -> dict[str, object] | None:
        return None


class FakeNotificationProvider:
    def __init__(self) -> None:
        self.notifications: list[HandoffNotification] = []
        self.review_notifications: list[ReviewNotification] = []
        self.handoff_send_result: NotificationSendResult = NotificationSendResult(
            accepted=True, provider_reference="notif-123"
        )
        self.handoff_exception: Exception | None = None
        self.review_send_result: NotificationSendResult = NotificationSendResult(
            accepted=True, provider_reference="review-notif-123"
        )

    async def send_handoff_notification(
        self, notification: HandoffNotification
    ) -> NotificationSendResult:
        self.notifications.append(notification)
        if self.handoff_exception is not None:
            raise self.handoff_exception
        return self.handoff_send_result

    async def send_review_notification(
        self, notification: ReviewNotification
    ) -> NotificationSendResult:
        self.review_notifications.append(notification)
        return self.review_send_result

    async def send_preflight_digest(self, notification: object) -> NotificationSendResult:
        raise AssertionError


async def test_complete_handoff_notifies_and_writes_back() -> None:
    crm_client = FakeCRMClient(lead_tags=("needs_agent_review",))
    notification_provider = FakeNotificationProvider()
    completion_repo = FakeHandoffCompletionRepository()
    assigned_user = _assigned_user()
    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=FakeHandoffRepository(_handoff()),
        handoff_completion_repository=completion_repo,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            replace(_config(), crm_review_tag="needs_agent_review")
        ),
        lead_repository=FakeLeadRepository(_lead(assigned_agent_user_id=assigned_user.user_id)),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        user_repository=FakeUserRepository({assigned_user.user_id: assigned_user}),
        now=NOW,
    )
    assert result.status == HandoffCompletionStatus.COMPLETED
    assert len(notification_provider.notifications) == 1
    assert notification_provider.notifications[0].recipient_id == str(assigned_user.user_id)
    assert notification_provider.notifications[0].recipient_destination == "assigned@example.com"
    assert notification_provider.notifications[0].assigned_user_name == "Avery Demo Agent"
    assert (
        notification_provider.notifications[0].crm_lead_url
        == "https://app.followupboss.com/2/people/crm-123"
    )
    assert crm_client.tag == "human_handoff_required"
    assert crm_client.removed_tags == ["needs_agent_review"]
    assert crm_client.fields == {"handoff_status": "required"}
    assert completion_repo.record is not None and completion_repo.record.completed_at == NOW


async def test_complete_handoff_falls_back_to_crm_agent_email_when_assigned_user_missing_email(
) -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    completion_repo = FakeHandoffCompletionRepository()
    assigned_user = _assigned_user(email="")

    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=FakeHandoffRepository(_handoff()),
        handoff_completion_repository=completion_repo,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(_config()),
        lead_repository=FakeLeadRepository(_lead(assigned_agent_user_id=assigned_user.user_id)),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        user_repository=FakeUserRepository({assigned_user.user_id: assigned_user}),
        now=NOW,
    )

    assert result.status == HandoffCompletionStatus.COMPLETED
    assert len(notification_provider.notifications) == 1
    assert notification_provider.notifications[0].recipient_id == "agent-99"
    assert notification_provider.notifications[0].recipient_destination == "agent@example.com"
    assert notification_provider.notifications[0].assigned_user_name == "Agent Smith"


async def test_complete_handoff_writes_crm_when_notification_raises() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    notification_provider.handoff_exception = RuntimeError("mailgun rejected notification")
    completion_repo = FakeHandoffCompletionRepository()
    handoff_repo = FakeHandoffRepository(_handoff())

    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=handoff_repo,
        handoff_completion_repository=completion_repo,
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(_config()),
        lead_repository=FakeLeadRepository(_lead()),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        now=NOW,
    )

    assert result.status == HandoffCompletionStatus.RETRYABLE_FAILURE
    assert result.failure_reason == "notification_exception:RuntimeError"
    assert len(notification_provider.notifications) == 1
    assert handoff_repo.handoff.status == HandoffStatus.CREATED
    assert crm_client.note_subject == "AI HANDOFF"
    assert crm_client.tag == "human_handoff_required"
    assert crm_client.fields == {"handoff_status": "required"}
    assert completion_repo.record is not None
    assert completion_repo.record.notification_sent_at is None
    assert completion_repo.record.crm_note_written_at == NOW
    assert completion_repo.record.crm_tag_applied_at == NOW
    assert completion_repo.record.crm_custom_fields_updated_at == NOW
    assert completion_repo.record.completed_at is None
    assert completion_repo.record.failure_reason == "notification_exception:RuntimeError"


async def test_complete_handoff_writes_crm_when_notification_not_accepted() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()
    notification_provider.handoff_send_result = NotificationSendResult(
        accepted=False, provider_reference="notif-failed"
    )
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

    assert result.status == HandoffCompletionStatus.RETRYABLE_FAILURE
    assert result.failure_reason == "notification_failed"
    assert crm_client.tag == "human_handoff_required"
    assert crm_client.fields == {"handoff_status": "required"}
    assert completion_repo.record is not None
    assert completion_repo.record.notification_provider_reference == "notif-failed"
    assert completion_repo.record.completed_at is None
    assert completion_repo.record.failure_reason == "notification_failed"


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


async def test_complete_handoff_updates_snapshot_fields() -> None:
    crm_client = FakeCRMClient()
    notification_provider = FakeNotificationProvider()

    result = await complete_handoff(
        workspace_id=WORKSPACE_ID,
        handoff_id=HANDOFF_ID,
        handoff_repository=FakeHandoffRepository(_handoff()),
        handoff_completion_repository=FakeHandoffCompletionRepository(),
        workspace_handoff_config_repository=FakeWorkspaceHandoffConfigRepository(
            _config_with_snapshot_fields()
        ),
        lead_repository=FakeLeadRepository(_lead()),
        crm_client=cast(CRMClient, crm_client),
        notification_provider=notification_provider,
        now=NOW,
    )

    assert result.status == HandoffCompletionStatus.COMPLETED
    assert crm_client.fields == {
        "handoff_status": "required",
        "ai_summary": "Lead asked for a callback.",
        "ai_status": "human_handoff_required",
        "ai_latest_inbound": "Can an agent call me?",
        "ai_last_activity_at": NOW.isoformat(),
    }


def _lead(*, assigned_agent_user_id: UUID | None = None) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        assigned_agent_user_id=assigned_agent_user_id,
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="new",
        primary_email="lead@example.com",
        primary_phone="+15555550123",
    )


def _assigned_user(*, email: str = "assigned@example.com") -> User:
    return User(
        user_id=UUID("30000000-0000-0000-0000-000000000004"),
        email=email,
        email_normalized=email.lower(),
        full_name="Avery Demo Agent",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
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


def _config_with_snapshot_fields() -> WorkspaceHandoffConfig:
    return replace(
        _config(),
        crm_snapshot_summary_field="ai_summary",
        crm_snapshot_status_field="ai_status",
        crm_snapshot_latest_inbound_field="ai_latest_inbound",
        crm_snapshot_last_activity_at_field="ai_last_activity_at",
    )
