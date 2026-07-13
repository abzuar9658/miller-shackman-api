import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    ProcessInboundMessageEventReasonCode,
    ProcessInboundMessageEventStatus,
    process_inbound_message_event,
)
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.conversations import Conversation, ConversationSummary, Handoff, InboundMessage
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus
from app.domain.events import DomainEvent, DomainEventType
from app.domain.leads import CanonicalLeadRecord, CRMProvider

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


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.saved: list[Handoff] = []

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
