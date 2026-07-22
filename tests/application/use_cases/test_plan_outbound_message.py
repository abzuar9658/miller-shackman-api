import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.llm import LLMCompletionRequest, LLMResult
from app.application.use_cases.plan_outbound_message import (
    OutboundPlanningContext,
    PlanOutboundMessageReasonCode,
    PlanOutboundMessageStatus,
    plan_outbound_message,
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
from app.domain.leads import CanonicalLeadRecord, CRMProvider

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

    async def get_by_primary_phone(
        self,
        workspace_id: WorkspaceId,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.primary_phone == phone_number
        ):
            return self.lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.primary_email == email_address
        ):
            return self.lead
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

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        return tuple(
            message
            for message in self.messages_by_idempotency_key.values()
            if message.workspace_id == workspace_id and message.lead_id == lead_id
        )[:limit]


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
            latency_ms=11,
            usage_tokens=31,
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
        primary_email="lead@example.com" if has_email else None,
        primary_phone="+15551234567" if has_sms_capable_phone else None,
        has_sms_capable_phone=has_sms_capable_phone,
        has_email=has_email,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
        last_meaningful_communication_at=NOW - timedelta(days=90),
    )


def _planning_context(
    *,
    enabled_channels: tuple[ContactChannel, ...] = (ContactChannel.SMS,),
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    workflow_state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    sms_compliance_state: SmsComplianceState = SmsComplianceState.APPROVED,
) -> OutboundPlanningContext:
    return OutboundPlanningContext(
        campaign_status=campaign_status,
        workflow_state=workflow_state,
        enabled_channels=enabled_channels,
        workspace_contact_policy=WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            sms_compliance_state=sms_compliance_state,
        ),
        campaign_goal="Re-engage dormant buyer leads without giving property or finance advice.",
        brokerage_name="Miller Schackman",
        cadence_step_id="step-1",
        assigned_agent_name="Alex Agent",
    )


def _draft_json(
    *,
    body: str = "Hi — are you still thinking about making a move this year?",
    subject: str | None = None,
    safety_flags: tuple[str, ...] = (),
) -> str:
    return json.dumps(
        {
            "body": body,
            "subject": subject,
            "confidence": 0.92,
            "personalization_notes": ["Used safe dormant lead context."],
            "safety_flags": list(safety_flags),
        },
    )


async def test_plans_pending_sms_message_after_rules_and_llm_draft_pass() -> None:
    messages = FakeOutboundMessageRepository()
    llm = FakeLLMClient(_draft_json())

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.selected_channel == ContactChannel.SMS
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.allowed is True
    assert result.message is not None
    assert result.message.message_id == MESSAGE_ID
    assert result.message.status == OutboundMessageStatus.PENDING
    assert result.message.channel == ContactChannel.SMS
    assert result.message.provider_send_status == ProviderSendStatus.NOT_ATTEMPTED
    assert result.message.idempotency_key.endswith(f":{ContactChannel.SMS.value}:v1")
    assert result.message.draft_model == "openai/gpt-4o-mini"
    assert messages.saved == [result.message]
    assert len(llm.requests) == 1


async def test_falls_back_to_email_when_sms_is_not_contactable() -> None:
    result = await plan_outbound_message(
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
        llm_client=FakeLLMClient(_draft_json(subject="Checking in")),
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.selected_channel == ContactChannel.EMAIL
    assert result.message is not None
    assert result.message.subject == "Checking in | Miller Schackman"


async def test_falls_back_to_email_when_workspace_sms_compliance_is_not_approved() -> None:
    llm = FakeLLMClient(_draft_json(subject="Checking in"))

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(
            enabled_channels=(ContactChannel.SMS, ContactChannel.EMAIL),
            sms_compliance_state=SmsComplianceState.NOT_APPROVED,
        ),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=llm,
        now=NOW,
        message_id_factory=lambda: MESSAGE_ID,
    )

    assert result.status == PlanOutboundMessageStatus.PLANNED
    assert result.selected_channel == ContactChannel.EMAIL
    assert result.message is not None
    assert len(llm.requests) == 1


async def test_rejects_without_calling_llm_when_sms_only_workspace_is_not_approved() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(sms_compliance_state=SmsComplianceState.NOT_APPROVED),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.CHANNEL_NOT_CONTACTABLE,)
    assert llm.requests == []


async def test_rejects_without_calling_llm_when_no_enabled_channel_has_destination() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(enabled_channels=(ContactChannel.SMS, ContactChannel.EMAIL)),
        lead_repository=FakeLeadRepository(_lead(has_sms_capable_phone=False, has_email=False)),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING,)
    assert llm.requests == []


async def test_rejects_without_calling_llm_when_pre_send_blocks_message() -> None:
    llm = FakeLLMClient(_draft_json())

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(workflow_state=WorkflowState.PAUSED),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=FakeOutboundMessageRepository(),
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert llm.requests == []


async def test_rejects_when_llm_draft_has_safety_flags() -> None:
    messages = FakeOutboundMessageRepository()

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=FakeLLMClient(_draft_json(safety_flags=("human_agent_required",))),
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.REJECTED
    assert result.reasons == (PlanOutboundMessageReasonCode.DRAFT_REJECTED,)
    assert messages.saved == []


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

    result = await plan_outbound_message(
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        context=_planning_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=messages,
        llm_client=llm,
        now=NOW,
    )

    assert result.status == PlanOutboundMessageStatus.DUPLICATE
    assert result.message == existing
    assert result.reasons == (PlanOutboundMessageReasonCode.DUPLICATE_PLAN,)
    assert messages.saved == []
    assert llm.requests == []
