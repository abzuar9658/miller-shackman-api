import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.application.ports.lead_activity import LeadActivityItem, LeadActivityKind
from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.use_cases.plan_next_outbound_message import (
    PlanNextOutboundMessageContext,
    plan_next_outbound_message_for_lead,
)
from app.application.use_cases.plan_outbound_message import (
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageStatus,
)
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
from app.domain.campaigns.pre_send import ProviderSendStatus, WorkflowState
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SmsComplianceState,
    WorkspaceContactPolicy,
)
from app.domain.conversations import CrmConversationEvent, CrmConversationEventDirection
from app.domain.leads import CanonicalLeadRecord, CRMProvider, PropertyEventType
from tests.application.use_cases._campaign_cadence_fakes import FakeCrmConversationEventRepository

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
LEAD_ID = UUID("33333333-3333-3333-3333-333333333333")
MESSAGE_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeLeadRepository:
    def __init__(self, lead: CanonicalLeadRecord | None) -> None:
        self.lead = lead

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        if self.lead and self.lead.workspace_id == workspace_id and self.lead.lead_id == lead_id:
            return self.lead
        return None

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeOutboundMessageRepository:
    def __init__(self) -> None:
        self.messages_by_idempotency_key: dict[tuple[WorkspaceId, str], OutboundMessage] = {}
        self.saved: list[OutboundMessage] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> OutboundMessage | None:
        for message in self.messages_by_idempotency_key.values():
            if message.workspace_id == workspace_id and message.message_id == message_id:
                return message
        return None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return self.messages_by_idempotency_key.get((workspace_id, idempotency_key))

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.saved.append(message)
        self.messages_by_idempotency_key[(message.workspace_id, message.idempotency_key)] = message
        return message


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


def _lead(
    *,
    has_sms_capable_phone: bool = True,
    has_email: bool = True,
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
) -> CanonicalLeadRecord:
    return CanonicalLeadRecord(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        crm_lead_id="123",
        facts_derived_at=NOW,
        source_payload_version="test:v1",
        lead_source="website",
        lead_stage="long_term_nurture",
        mapped_custom_fields={"preferred_location": "Austin"},
        primary_email="lead@example.com" if has_email else None,
        primary_phone="+15551234567" if has_sms_capable_phone else None,
        has_sms_capable_phone=has_sms_capable_phone,
        has_email=has_email,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
        has_accountable_owner=True,
        last_meaningful_communication_at=NOW - timedelta(days=90),
        latest_property_event_type=PropertyEventType.PROPERTY_INQUIRY,
        latest_property_price_band="500k-750k",
    )


def _planning_context(
    *,
    enabled_channels: tuple[ContactChannel, ...] = (ContactChannel.SMS,),
    workflow_state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    activity_items: tuple[LeadActivityItem, ...] = (),
) -> PlanNextOutboundMessageContext:
    return PlanNextOutboundMessageContext(
        campaign_status=CampaignStatus.ACTIVE,
        workflow_state=workflow_state,
        enabled_channels=enabled_channels,
        workspace_contact_policy=WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=SmsComplianceState.APPROVED,
        ),
        campaign_goal="Re-engage dormant buyer leads without giving property or finance advice.",
        brokerage_name="Miller Schackman",
        cadence_step_id="step-1",
        assigned_agent_name="Alex Agent",
        allowed_mapped_custom_field_keys=("preferred_location",),
        activity_items=activity_items,
    )


def _crm_event(
    *,
    crm_activity_id: str,
    content: str,
    direction: CrmConversationEventDirection,
) -> CrmConversationEvent:
    return CrmConversationEvent(
        crm_conversation_event_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_activity_id=crm_activity_id,
        activity_type="Note",
        direction=direction,
        occurred_at=NOW,
        content=content,
        created_at=NOW,
        updated_at=NOW,
    )


def _draft_json(
    *,
    body: str = "Hi — are you still thinking about making a move this year?",
    subject: str | None = None,
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": 0.91,
            "personalization_notes": ["Used safe canonical context."],
            "safety_flags": [],
        },
    )


async def test_plans_message_using_safe_context_assembled_from_canonical_lead() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.message is not None
    assert result.message.message_id == MESSAGE_ID
    assert result.message.status == OutboundMessageStatus.PENDING
    assert result.message.provider_send_status == ProviderSendStatus.NOT_ATTEMPTED
    assert len(llm.requests) == 1
    assert "No meaningful communication recorded for 90 days." in llm.requests[0].prompt
    assert "the lead inquired about a property" in llm.requests[0].prompt
    assert "Austin" in llm.requests[0].prompt


async def test_prefers_recent_crm_conversation_history_when_available() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(
            (
                _crm_event(
                    crm_activity_id="1",
                    content="Sent a quick check-in email last week.",
                    direction=CrmConversationEventDirection.OUTBOUND,
                ),
                _crm_event(
                    crm_activity_id="2",
                    content="We are hoping to move before school starts.",
                    direction=CrmConversationEventDirection.INBOUND,
                ),
            )
        ),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert len(llm.requests) == 1
    assert "Recent CRM conversation history:" in llm.requests[0].prompt
    assert "Sent a quick check-in email last week." in llm.requests[0].prompt
    assert "We are hoping to move before school starts." in llm.requests[0].prompt
    assert "No meaningful communication recorded for 90 days." not in llm.requests[0].prompt


async def test_prefers_unified_activity_context_when_available() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(
            activity_items=(
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.OUTBOUND_MESSAGE,
                    occurred_at=NOW - timedelta(days=2),
                    title="Outbound outreach logged",
                    preview="Sent a safe check-in email two days ago.",
                    channel="email",
                    direction="outbound",
                    status="sent",
                ),
                LeadActivityItem(
                    activity_id=uuid4(),
                    lead_id=LEAD_ID,
                    kind=LeadActivityKind.CRM_CONVERSATION_EVENT,
                    occurred_at=NOW,
                    title="CRM reply logged",
                    preview="We are hoping to move before school starts.",
                    direction="inbound",
                    status="Note",
                    actor_name="Avery Agent",
                ),
            )
        ),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert len(llm.requests) == 1
    assert "Recent meaningful activity:" in llm.requests[0].prompt
    assert "Sent a safe check-in email two days ago." in llm.requests[0].prompt
    assert "We are hoping to move before school starts." in llm.requests[0].prompt
    assert "No meaningful communication recorded for 90 days." not in llm.requests[0].prompt


async def test_rejects_without_calling_llm_when_pre_send_blocks_high_level_plan() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_state=WorkflowState.PAUSED),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert llm.requests == []


async def test_falls_back_to_email_when_sms_not_contactable_in_high_level_plan() -> None:
    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(enabled_channels=(ContactChannel.SMS, ContactChannel.EMAIL)),
        lead_repository=FakeLeadRepository(
            _lead(
                has_sms_capable_phone=False,
                sms_permission_status=ContactPermissionStatus.UNKNOWN,
            ),
        ),
        message_repository=FakeOutboundMessageRepository(),
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=FakeLLMClient(_draft_json(subject="Checking in")),
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.selected_channel == ContactChannel.EMAIL
    assert result.message is not None
    assert result.message.subject == "Checking in"


async def test_duplicate_plan_returns_existing_message_without_calling_llm() -> None:
    messages = FakeOutboundMessageRepository()
    existing = OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key=f"outbound:{WORKSPACE_ID}:{CAMPAIGN_ID}:{LEAD_ID}:step-1:sms:v1",
        body="Existing draft",
        created_at=NOW,
        updated_at=NOW,
    )
    await messages.save(existing)
    messages.saved.clear()
    llm = FakeLLMClient(_draft_json())

    result = await plan_next_outbound_message_for_lead(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        crm_conversation_event_repository=FakeCrmConversationEventRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.DUPLICATE
    assert result.message == existing
    assert result.reasons == (PlanOutboundMessageReasonCode.DUPLICATE_PLAN,)
    assert llm.requests == []
