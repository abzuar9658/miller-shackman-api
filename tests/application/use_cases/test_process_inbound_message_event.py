import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.crm import CanonicalLead, CRMActivity
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.services.llm.reply_classification import InboundReplyIntent
from app.application.use_cases.complete_inbound_message_crm_sync import (
    CompleteInboundMessageCRMSyncStatus,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventReasonCode,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import (
    Conversation,
    ConversationSummary,
    Handoff,
    InboundMessage,
)
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.domain.llm import WorkspaceLLMConfig

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
EXTERNAL_EVENT_ID = UUID("00000000-0000-0000-0000-000000000003")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000004")
INBOUND_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000005")
SUMMARY_ID = UUID("00000000-0000-0000-0000-000000000006")
HANDOFF_ID = UUID("00000000-0000-0000-0000-000000000007")


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead

    async def get_by_id(
        self, workspace_id: WorkspaceId, lead_id: LeadId
    ) -> CanonicalLeadRecord | None:
        return self.lead

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return self.lead

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is not None
            and self.lead.workspace_id == workspace_id
            and self.lead.crm_provider == crm_provider
            and self.lead.crm_lead_id == crm_lead_id
        ):
            return self.lead
        return None

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is None
            or self.lead.workspace_id != workspace_id
            or self.lead.primary_phone is None
        ):
            return None
        requested = _normalized_phone(phone_number)
        stored = _normalized_phone(self.lead.primary_phone)
        if requested is None or stored is None:
            return None
        candidates = {requested}
        if len(requested) == 11 and requested.startswith("1"):
            candidates.add(requested[1:])
        elif len(requested) == 10:
            candidates.add(f"1{requested}")
        if stored in candidates:
            return self.lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead is None
            or self.lead.workspace_id != workspace_id
            or self.lead.primary_email is None
        ):
            return None
        requested = email_address.strip().lower()
        stored = self.lead.primary_email.strip().lower()
        if not requested or not stored:
            return None
        if requested == stored:
            return self.lead
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeExternalEventRepository:
    def __init__(self) -> None:
        self.events: dict[tuple[WorkspaceId, str, str], ExternalEvent] = {}

    async def get_by_provider_event_id(
        self,
        workspace_id: WorkspaceId,
        provider: str,
        provider_event_id: str,
    ) -> ExternalEvent | None:
        return self.events.get((workspace_id, provider, provider_event_id))

    async def save(self, event: ExternalEvent) -> ExternalEvent:
        self.events[(event.workspace_id, event.provider, event.provider_event_id)] = event
        return event


class FakeConversationRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, Conversation] = {}

    async def get_latest_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> Conversation | None:
        conversations = [
            conversation
            for conversation in self.by_id.values()
            if conversation.workspace_id == workspace_id and conversation.lead_id == lead_id
        ]
        return (
            max(conversations, key=lambda conversation: conversation.updated_at)
            if conversations
            else None
        )

    async def save(self, conversation: Conversation) -> Conversation:
        self.by_id[conversation.conversation_id] = conversation
        return conversation


class FakeInboundMessageRepository:
    def __init__(self) -> None:
        self.messages: dict[tuple[WorkspaceId, str, str], InboundMessage] = {}

    async def save(self, message: InboundMessage) -> InboundMessage:
        self.messages[(message.workspace_id, message.provider, message.provider_message_id)] = (
            message
        )
        return message


class FakeConversationSummaryRepository:
    def __init__(self) -> None:
        self.saved: list[ConversationSummary] = []

    async def save(self, summary: ConversationSummary) -> ConversationSummary:
        self.saved.append(summary)
        return summary


class FakeInboundMessageCRMCompletionRepository:
    def __init__(self, record: object | None = None) -> None:
        self.record = record

    async def get_by_inbound_message_id(
        self,
        workspace_id: WorkspaceId,
        inbound_message_id: UUID,
    ) -> object | None:
        if self.record is None:
            return None
        if (
            getattr(self.record, "workspace_id", None) == workspace_id
            and getattr(self.record, "inbound_message_id", None) == inbound_message_id
        ):
            return self.record
        return None

    async def save(self, record: object) -> object:
        self.record = record
        return record


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.saved: list[Handoff] = []

    async def list_handoffs(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 100,
    ) -> tuple[Handoff, ...]:
        handoffs = tuple(
            handoff for handoff in self.saved if handoff.workspace_id == workspace_id
        )
        return handoffs[:limit]

    async def get_by_id(self, workspace_id: WorkspaceId, handoff_id: UUID) -> Handoff | None:
        for handoff in self.saved:
            if handoff.workspace_id == workspace_id and handoff.handoff_id == handoff_id:
                return handoff
        return None

    async def save(self, handoff: Handoff) -> Handoff:
        self.saved.append(handoff)
        return handoff


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeLLMClient:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> LLMResult:
        self.requests.append(request)
        return LLMResult(
            text=self.text,
            model="openai/gpt-4o-mini",
            prompt_version=request.prompt_version,
            latency_ms=13,
            usage_tokens=37,
        )


class FakeWorkspaceLLMConfigRepository:
    def __init__(self, config: WorkspaceLLMConfig | None) -> None:
        self.config = config

    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> WorkspaceLLMConfig | None:
        if self.config is not None and self.config.workspace_id == workspace_id:
            return self.config
        return None

    async def save(self, config: WorkspaceLLMConfig) -> WorkspaceLLMConfig:
        self.config = config
        return config


class FakeCRMClient:
    supports_custom_fields = True
    supports_tags = True
    supports_notes = True
    supports_webhooks = False

    def __init__(
        self,
        *,
        lead_updated_at: datetime | None = None,
        activity_timestamps: tuple[datetime, ...] = (),
    ) -> None:
        self.calls: list[str] = []
        self.notes: list[str] = []
        self._lead_updated_at = lead_updated_at
        self._activity_timestamps = activity_timestamps

    async def validate_connection(self, workspace_id: WorkspaceId) -> bool:
        return True

    async def get_lead(self, workspace_id: WorkspaceId, crm_lead_id: str) -> CanonicalLead | None:
        self.calls.append("get_lead")
        return CanonicalLead(
            workspace_id=workspace_id,
            crm_lead_id=crm_lead_id,
            first_name="Jamie",
            last_name="Lead",
            email="lead@example.com",
            phone="+15555550123",
            updated_at=self._lead_updated_at,
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
        self.calls.append("get_recent_activity")
        return [
            CRMActivity(
                crm_activity_id=f"activity-{index}",
                activity_type="Note",
                timestamp=timestamp,
                content="recent activity",
            )
            for index, timestamp in enumerate(self._activity_timestamps, start=1)
        ]

    async def get_assigned_agent(self, workspace_id: WorkspaceId, crm_lead_id: str) -> None:
        return None

    async def add_note(self, workspace_id: WorkspaceId, crm_lead_id: str, content: str) -> None:
        self.calls.append("add_note")
        self.notes.append(content)

    async def add_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        return None

    async def remove_tag(self, workspace_id: WorkspaceId, crm_lead_id: str, tag: str) -> None:
        return None

    async def update_custom_fields(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        fields: dict[str, str],
    ) -> None:
        return None

    async def subscribe_to_events(self, workspace_id: WorkspaceId, webhook_url: str) -> None:
        return None


def _normalized_phone(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    digits_only = "".join(character for character in phone_number if character.isdigit())
    return digits_only or None


def _lead() -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="crm-123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        assigned_agent_crm_id="agent-99",
        has_accountable_owner=True,
        primary_phone="+15555550123",
        has_phone=True,
        has_sms_capable_phone=True,
        phone_count=1,
    )


def _event(payload_redacted: Mapping[str, object] | None = None) -> InboundMessageEvent:
    return InboundMessageEvent(
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        provider_event_id="evt-1",
        provider_message_id="msg-1",
        crm_lead_id="crm-123",
        channel=ContactChannel.SMS,
        body="Can an agent call me today?",
        received_at=NOW,
        payload_redacted=payload_redacted or {"event": "redacted"},
    )


def _classification_json(
    *,
    intent: str,
    handoff_required: bool,
    handoff_reason: str | None,
    opt_out_detected: bool = False,
    confidence: float = 0.91,
    summary_text: str = "Lead asked for a human callback.",
) -> str:
    return json.dumps(
        {
            "intent": intent,
            "confidence": confidence,
            "handoff_required": handoff_required,
            "handoff_reason": handoff_reason,
            "opt_out_detected": opt_out_detected,
            "summary_text": summary_text,
            "preferences": {"timeline": "today"},
        },
    )


async def test_returns_duplicate_when_external_event_already_exists() -> None:
    lead_repository = FakeLeadRepository(_lead())
    external_events = FakeExternalEventRepository()
    existing = ExternalEvent(
        external_event_id=EXTERNAL_EVENT_ID,
        workspace_id=WORKSPACE_ID,
        provider=CRMProvider.FOLLOW_UP_BOSS.value,
        event_type="inbound_message.received",
        provider_event_id="evt-1",
        crm_lead_id="crm-123",
        lead_id=LEAD_ID,
        received_at=NOW,
        processed_at=NOW,
        status=ExternalEventStatus.PROCESSED,
        payload_redacted={"event": "redacted"},
        failure_reason=None,
        created_at=NOW,
        updated_at=NOW,
    )
    await external_events.save(existing)
    llm = FakeLLMClient(
        _classification_json(
            intent="human_requested", handoff_required=True, handoff_reason="human_requested"
        )
    )

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=lead_repository,
        external_event_repository=external_events,
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.DUPLICATE
    assert result.reasons == (ProcessInboundMessageEventReasonCode.DUPLICATE_EVENT,)
    assert llm.requests == []


async def test_creates_handoff_for_human_request() -> None:
    conversations = FakeConversationRepository()
    inbound_messages = FakeInboundMessageRepository()
    summaries = FakeConversationSummaryRepository()
    handoffs = FakeHandoffRepository()
    event_bus = FakeEventBus()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=inbound_messages,
        conversation_summary_repository=summaries,
        handoff_repository=handoffs,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                handoff_required=True,
                handoff_reason="human_requested",
            ),
        ),
        now=NOW,
        external_event_id_factory=lambda: EXTERNAL_EVENT_ID,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
        summary_id_factory=lambda: SUMMARY_ID,
        handoff_id_factory=lambda: HANDOFF_ID,
        event_bus=event_bus,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.handoff_required is True
    assert result.handoff_id == HANDOFF_ID
    assert result.conversation_id == CONVERSATION_ID
    assert result.inbound_message_id == INBOUND_MESSAGE_ID
    assert handoffs.saved[0].assigned_agent_crm_id == "agent-99"
    assert handoffs.saved[0].reason_code.value == "human_requested"
    assert summaries.saved[0].summary_id == SUMMARY_ID
    assert conversations.by_id[CONVERSATION_ID].status.value == "human_handoff"
    assert [event.event_type for event in event_bus.events] == [
        DomainEventType.MESSAGE_RECEIVED,
        DomainEventType.HANDOFF_CREATED,
    ]
    assert event_bus.events[1].payload["handoff_id"] == str(HANDOFF_ID)


async def test_uses_workspace_llm_model_for_classification() -> None:
    llm = FakeLLMClient(
        _classification_json(
            intent="human_requested",
            handoff_required=True,
            handoff_reason="human_requested",
        )
    )

    await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=llm,
        workspace_llm_config_repository=FakeWorkspaceLLMConfigRepository(
            WorkspaceLLMConfig(
                workspace_id=WORKSPACE_ID,
                openrouter_model="openai/gpt-4.1-mini",
            )
        ),
        default_openrouter_model="openai/gpt-4o-mini",
        now=NOW,
    )

    assert llm.requests[0].model == "openai/gpt-4.1-mini"


async def test_processes_opt_out_without_handoff() -> None:
    conversations = FakeConversationRepository()
    handoffs = FakeHandoffRepository()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=conversations,
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=handoffs,
        llm_client=FakeLLMClient(
            _classification_json(
                intent="opt_out",
                handoff_required=False,
                handoff_reason=None,
                opt_out_detected=True,
                summary_text="Lead opted out of automated outreach.",
            ),
        ),
        now=NOW,
        conversation_id_factory=lambda: CONVERSATION_ID,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.opt_out_detected is True
    assert result.handoff_id is None
    assert handoffs.saved == []
    assert conversations.by_id[CONVERSATION_ID].status.value == "paused"


async def test_returns_processed_with_classification_rejection_reason() -> None:
    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                handoff_required=False,
                handoff_reason=None,
                confidence=0.2,
                summary_text="Lead replied but confidence is low.",
            ),
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.reasons == (ProcessInboundMessageEventReasonCode.CLASSIFICATION_REJECTED,)


async def test_provider_owned_inbound_reply_syncs_back_to_crm_after_refresh() -> None:
    crm_client = FakeCRMClient(activity_timestamps=(datetime(2026, 7, 8, 12, 5, tzinfo=UTC),))
    crm_sync_repo = FakeInboundMessageCRMCompletionRepository()

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            provider_event_id="evt-twilio-1",
            provider_message_id="SM123",
            crm_lead_id="crm-123",
            channel=ContactChannel.SMS,
            body="Please stop texting me and have an agent call.",
            received_at=NOW,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                handoff_required=True,
                handoff_reason="human_requested",
                summary_text="Lead asked for a human callback.",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=crm_sync_repo,
        now=NOW,
        inbound_message_id_factory=lambda: INBOUND_MESSAGE_ID,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.crm_sync_status == CompleteInboundMessageCRMSyncStatus.COMPLETED
    assert crm_client.calls == ["get_lead", "get_recent_activity", "add_note"]
    assert crm_client.notes
    assert "CRM updates detected before sync: yes" in crm_client.notes[0]
    assert getattr(crm_sync_repo.record, "completed_at", None) == NOW


async def test_follow_up_boss_sourced_inbound_reply_does_not_write_back_to_crm() -> None:
    crm_client = FakeCRMClient()

    result = await process_inbound_message_event(
        event=_event(),
        lead_repository=FakeLeadRepository(_lead()),
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="human_requested",
                handoff_required=True,
                handoff_reason="human_requested",
            ),
        ),
        crm_client=crm_client,
        inbound_message_crm_completion_repository=FakeInboundMessageCRMCompletionRepository(),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.crm_sync_status is None
    assert crm_client.calls == []


async def test_explicit_sms_opt_out_is_applied_even_when_llm_rejects() -> None:
    lead_repository = FakeLeadRepository(_lead())

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="twilio",
            provider_event_id="SMSTOP1",
            provider_message_id="SMSTOP1",
            crm_lead_id="crm-123",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.SMS,
            body="STOP",
            received_at=NOW,
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                handoff_required=False,
                handoff_reason=None,
                confidence=0.10,
                summary_text="Lead replied.",
            )
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.intent == InboundReplyIntent.OPT_OUT
    assert result.opt_out_detected is True
    assert result.reasons == ()
    assert lead_repository.lead is not None
    assert lead_repository.lead.sms_opted_out is True


async def test_explicit_email_unsubscribe_is_applied_even_when_llm_rejects() -> None:
    lead_repository = FakeLeadRepository(_lead())

    result = await process_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=WORKSPACE_ID,
            provider="sendgrid",
            provider_event_id="email-1",
            provider_message_id="email-1",
            crm_lead_id="crm-123",
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.EMAIL,
            body="unsubscribe",
            received_at=NOW,
        ),
        lead_repository=lead_repository,
        external_event_repository=FakeExternalEventRepository(),
        conversation_repository=FakeConversationRepository(),
        inbound_message_repository=FakeInboundMessageRepository(),
        conversation_summary_repository=FakeConversationSummaryRepository(),
        handoff_repository=FakeHandoffRepository(),
        llm_client=FakeLLMClient(
            _classification_json(
                intent="general_reply",
                handoff_required=False,
                handoff_reason=None,
                confidence=0.10,
                summary_text="Lead replied.",
            )
        ),
        now=NOW,
    )

    assert result.status == ProcessInboundMessageEventStatus.PROCESSED
    assert result.intent == InboundReplyIntent.OPT_OUT
    assert result.opt_out_detected is True
    assert result.reasons == ()
    assert lead_repository.lead is not None
    assert lead_repository.lead.email_unsubscribed is True
