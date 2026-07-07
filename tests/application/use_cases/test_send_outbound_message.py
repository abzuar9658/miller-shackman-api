from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.messaging import EmailMessage, SMSMessage
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageReasonCode,
    SendOutboundMessageStatus,
    send_outbound_message,
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
        self.locked_ids: list[LeadId] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        if self.lead and self.lead.workspace_id == workspace_id and self.lead.lead_id == lead_id:
            return self.lead
        return None

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
    ) -> CanonicalLeadRecord | None:
        self.locked_ids.append(lead_id)
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeOutboundMessageRepository:
    def __init__(self, message: OutboundMessage | None) -> None:
        self.message = message
        self.saved: list[OutboundMessage] = []
        self.locked_idempotency_keys: list[str] = []

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        message_id: UUID,
    ) -> OutboundMessage | None:
        if (
            self.message
            and self.message.workspace_id == workspace_id
            and self.message.message_id == message_id
        ):
            return self.message
        return None

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        if (
            self.message
            and self.message.workspace_id == workspace_id
            and self.message.idempotency_key == idempotency_key
        ):
            return self.message
        return None

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundMessage | None:
        self.locked_idempotency_keys.append(idempotency_key)
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.message = message
        self.saved.append(message)
        return message


class FakeSMSProvider:
    def __init__(self, result: str | Exception = "SM123") -> None:
        self.result = result
        self.messages: list[SMSMessage] = []

    async def send(self, message: SMSMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEmailProvider:
    def __init__(self, result: str | Exception = "msg-123") -> None:
        self.result = result
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _lead(
    *,
    primary_email: str | None = "lead@example.com",
    primary_phone: str | None = "+15551234567",
    has_email: bool = True,
    has_sms_capable_phone: bool = True,
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
        primary_email=primary_email if has_email else None,
        primary_phone=primary_phone if has_sms_capable_phone else None,
        has_email=has_email,
        has_sms_capable_phone=has_sms_capable_phone,
        sms_permission_status=sms_permission_status,
        email_permission_status=email_permission_status,
        do_not_contact=False,
        last_meaningful_communication_at=NOW - timedelta(days=90),
    )


def _message(
    *,
    channel: ContactChannel = ContactChannel.SMS,
    status: OutboundMessageStatus = OutboundMessageStatus.PENDING,
    provider_send_status: ProviderSendStatus = ProviderSendStatus.NOT_ATTEMPTED,
    subject: str | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=CAMPAIGN_ID,
        cadence_step_id="step-1",
        channel=channel,
        status=status,
        idempotency_key=f"outbound:{WORKSPACE_ID}:{CAMPAIGN_ID}:{LEAD_ID}:step-1:{channel.value}:v1",
        body="Checking in to see whether you'd still like help this season.",
        subject=subject,
        created_at=NOW,
        updated_at=NOW,
        provider_send_status=provider_send_status,
    )


def _send_context(
    *,
    enabled_channels: tuple[ContactChannel, ...] = (ContactChannel.SMS, ContactChannel.EMAIL),
    campaign_status: CampaignStatus = CampaignStatus.ACTIVE,
    workflow_state: WorkflowState = WorkflowState.ACTIVE_NURTURE,
    current_message_version: int | None = None,
) -> OutboundSendContext:
    return OutboundSendContext(
        campaign_status=campaign_status,
        workflow_state=workflow_state,
        enabled_channels=enabled_channels,
        workspace_contact_policy=WorkspaceContactPolicy(
            sms_compliance_state=SmsComplianceState.APPROVED,
        ),
        current_message_version=current_message_version,
    )


async def test_sends_pending_sms_message_and_persists_sent_state() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    lead_repository = FakeLeadRepository(_lead())
    sms_provider = FakeSMSProvider("SM123")
    email_provider = FakeEmailProvider()

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=email_provider,
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert result.message is not None
    assert result.message.status == OutboundMessageStatus.SENT
    assert result.message.provider_send_status == ProviderSendStatus.ACCEPTED
    assert result.message.provider_message_id == "SM123"
    assert result.message.sent_at == NOW
    assert sms_provider.messages[0].to_phone == "+15551234567"
    assert lead_repository.locked_ids == [LEAD_ID]
    assert message_repository.locked_idempotency_keys == [result.message.idempotency_key]
    assert len(email_provider.messages) == 0


async def test_sends_pending_email_message_with_subject() -> None:
    message_repository = FakeOutboundMessageRepository(
        _message(channel=ContactChannel.EMAIL, subject="Quick check-in"),
    )

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider("msg-123"),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert result.message is not None
    assert result.message.channel == ContactChannel.EMAIL
    assert result.message.provider_message_id == "msg-123"


async def test_returns_existing_sent_message_without_resending() -> None:
    sent_message = _message(
        status=OutboundMessageStatus.SENT,
        provider_send_status=ProviderSendStatus.ACCEPTED,
    )
    message_repository = FakeOutboundMessageRepository(sent_message)
    sms_provider = FakeSMSProvider()

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=sent_message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.ALREADY_SENT
    assert result.message == sent_message
    assert sms_provider.messages == []
    assert message_repository.saved == []


async def test_rejects_when_pre_send_blocks_message() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    sms_provider = FakeSMSProvider()

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(workflow_state=WorkflowState.PAUSED),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.REJECTED
    assert result.reasons == (SendOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.allowed is False
    assert sms_provider.messages == []
    assert message_repository.saved == []


async def test_marks_message_uncertain_when_provider_returns_empty_identifier() -> None:
    message_repository = FakeOutboundMessageRepository(_message())

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(""),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.UNCERTAIN
    assert result.message is not None
    assert result.message.status == OutboundMessageStatus.UNCERTAIN
    assert result.message.provider_send_status == ProviderSendStatus.UNCERTAIN
    assert result.message.failure_reason == "provider_message_id_missing"


async def test_marks_message_failed_when_provider_raises() -> None:
    message_repository = FakeOutboundMessageRepository(_message())

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(RuntimeError("twilio unavailable")),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.FAILED
    assert result.message is not None
    assert result.message.status == OutboundMessageStatus.FAILED
    assert result.message.failure_reason == "twilio unavailable"
    assert result.message.provider_send_status == ProviderSendStatus.NOT_ATTEMPTED


async def test_rejects_when_channel_destination_is_missing() -> None:
    message_repository = FakeOutboundMessageRepository(_message())

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(
            _lead(primary_phone=None, has_sms_capable_phone=True),
        ),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.REJECTED
    assert result.reasons == (SendOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING,)


async def test_rejects_email_when_subject_is_missing() -> None:
    message_repository = FakeOutboundMessageRepository(_message(channel=ContactChannel.EMAIL))

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.REJECTED
    assert result.reasons == (SendOutboundMessageReasonCode.EMAIL_SUBJECT_MISSING,)
