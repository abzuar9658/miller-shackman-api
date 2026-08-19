from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.application.ports.crm import CRMActivity
from app.application.ports.messaging import (
    EmailMessage,
    ProviderFailureKind,
    ProviderSendFailure,
    SMSMessage,
)
from app.application.ports.repositories import (
    CRMAgentRepository,
    UserRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
)
from app.application.services.pre_send_crm_refresh import PreSendCRMRefreshContext
from app.application.services.pre_send_policy import build_pre_send_policy
from app.application.use_cases.send_outbound_message import (
    OutboundSendContext,
    SendOutboundMessageReasonCode,
    SendOutboundMessageResult,
    SendOutboundMessageStatus,
    send_outbound_message,
)
from app.application.use_cases.timeout_uncertain_outbound_send import (
    timeout_uncertain_outbound_send,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    build_outbound_email_message_id,
)
from app.domain.campaigns.outbound_provider_failure import (
    OutboundProviderFailure,
    OutboundProviderFailureStatus,
)
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import PreSendReasonCode, ProviderSendStatus, WorkflowState
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    ContactPermissionStatus,
    SuppressionType,
    WorkspaceContactPolicy,
)
from app.domain.events import DomainEvent, DomainEventType
from app.domain.leads import (
    AssignmentResolutionStatus,
    CanonicalLeadRecord,
    CRMProvider,
    EffectiveOwnerSource,
)
from app.infrastructure.messaging.sink import SinkEmailProvider, SinkSMSProvider

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
CAMPAIGN_ID = UUID("22222222-2222-2222-2222-222222222222")
LEAD_ID = UUID("33333333-3333-3333-3333-333333333333")
MESSAGE_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeLeadRepository:
    def __init__(
        self,
        lead: CanonicalLeadRecord | None,
        call_order: list[str] | None = None,
    ) -> None:
        self.lead = lead
        self.locked_ids: list[LeadId] = []
        self.call_order = call_order

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
        if self.call_order is not None:
            self.call_order.append("lead_lock")
        self.locked_ids.append(lead_id)
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self,
        workspace_id: WorkspaceId,
        crm_provider: CRMProvider,
        crm_lead_id: str,
    ) -> CanonicalLeadRecord | None:
        return None

    async def list_by_assigned_agent_crm_id(
        self,
        workspace_id: WorkspaceId,
        assigned_agent_crm_id: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.assigned_agent_crm_id == assigned_agent_crm_id
        ):
            return (self.lead,)
        return ()

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
        matches = await self.list_by_primary_email(workspace_id, email_address)
        if len(matches) != 1:
            return None
        return matches[0]

    async def list_by_primary_email(
        self,
        workspace_id: WorkspaceId,
        email_address: str,
    ) -> tuple[CanonicalLeadRecord, ...]:
        if (
            self.lead
            and self.lead.workspace_id == workspace_id
            and self.lead.primary_email is not None
            and self.lead.primary_email.strip().lower() == email_address.strip().lower()
        ):
            return (self.lead,)
        return ()

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.lead = record
        return record


class FakeOutboundMessageRepository:
    def __init__(
        self,
        message: OutboundMessage | None,
        call_order: list[str] | None = None,
        history: tuple[OutboundMessage, ...] = (),
    ) -> None:
        self.message = message
        self.history = history
        self.saved: list[OutboundMessage] = []
        self.locked_idempotency_keys: list[str] = []
        self.call_order = call_order

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
        if self.call_order is not None:
            self.call_order.append("message_lookup")
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
        if self.call_order is not None:
            self.call_order.append("message_lock")
        self.locked_idempotency_keys.append(idempotency_key)
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.message = message
        self.saved.append(message)
        return message


    async def get_by_provider_message_id_for_workspace(
        self,
        workspace_id: WorkspaceId,
        provider_name: str,
        provider_message_id: str,
    ) -> OutboundMessage | None:
        if (
            self.message
            and self.message.workspace_id == workspace_id
            and self.message.provider_name == provider_name
            and self.message.provider_message_id == provider_message_id
        ):
            return self.message
        return None

    async def get_by_reply_routing_token(
        self,
        workspace_id: WorkspaceId,
        reply_routing_token: str,
    ) -> OutboundMessage | None:
        if (
            self.message
            and self.message.workspace_id == workspace_id
            and self.message.reply_routing_token == reply_routing_token
        ):
            return self.message
        return None

    async def list_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        limit: int = 100,
    ) -> tuple[OutboundMessage, ...]:
        return tuple(
            message
            for message in (*self.history, self.message)
            if message is not None
            and message.workspace_id == workspace_id
            and message.lead_id == lead_id
        )[:limit]

    async def get_latest_sent_at_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        campaign_id: UUID | None = None,
        channel: ContactChannel | None = None,
    ) -> datetime | None:
        messages = await self.list_for_lead(workspace_id, lead_id)
        return max(
            (
                message.sent_at
                for message in messages
                if message.status == OutboundMessageStatus.SENT
                and message.sent_at is not None
                and (campaign_id is None or message.campaign_id == campaign_id)
                and (channel is None or message.channel == channel)
            ),
            default=None,
        )


class FakeOutboundSendReconciliationRepository:
    def __init__(self) -> None:
        self.reconciliations: dict[str, OutboundSendReconciliation] = {}

    async def get_by_id_for_update(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return next(
            (
                item
                for item in self.reconciliations.values()
                if item.workspace_id == workspace_id and item.reconciliation_id == reconciliation_id
            ),
            None,
        )

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return await self.get_by_id_for_update(workspace_id, reconciliation_id)

    async def get_by_outbound_message_id_for_update(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendReconciliation | None:
        return next(
            (
                item
                for item in self.reconciliations.values()
                if (
                    item.workspace_id == workspace_id
                    and item.outbound_message_id == outbound_message_id
                )
            ),
            None,
        )

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        item = self.reconciliations.get(idempotency_key)
        return item if item is not None and item.workspace_id == workspace_id else None

    async def get_by_idempotency_key_for_update(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendReconciliation | None:
        return await self.get_by_idempotency_key(workspace_id, idempotency_key)

    async def create_or_get(
        self,
        reconciliation: OutboundSendReconciliation,
    ) -> OutboundSendReconciliation:
        return self.reconciliations.setdefault(reconciliation.idempotency_key, reconciliation)

    async def resolve(self, **kwargs: object) -> OutboundSendReconciliation | None:
        reconciliation_id = cast(UUID, kwargs["reconciliation_id"])
        workspace_id = cast(WorkspaceId, kwargs["workspace_id"])
        existing = await self.get_by_id_for_update(workspace_id, reconciliation_id)
        if existing is None:
            return None
        if existing.status is not OutboundSendReconciliationStatus.PENDING:
            return existing
        resolved = replace(
            existing,
            status=cast(OutboundSendReconciliationStatus, kwargs["status"]),
            updated_at=cast(datetime, kwargs["now"]),
            resolved_at=cast(datetime, kwargs["now"]),
            failure_reason=cast(str | None, kwargs.get("failure_reason")),
        )
        self.reconciliations[existing.idempotency_key] = resolved
        return resolved

class FakeOutboundProviderFailureRepository:
    def __init__(self) -> None:
        self.failures: dict[UUID, OutboundProviderFailure] = {}

    async def create_or_get(
        self,
        failure: OutboundProviderFailure,
    ) -> OutboundProviderFailure:
        existing = next(
            (
                item
                for item in self.failures.values()
                if item.workspace_id == failure.workspace_id
                and item.outbound_message_id == failure.outbound_message_id
            ),
            None,
        )
        if existing is not None:
            return existing
        self.failures[failure.failure_id] = failure
        return failure

    async def list_open(
        self,
        workspace_id: WorkspaceId,
        limit: int = 100,
    ) -> list[OutboundProviderFailure]:
        return [
            item
            for item in self.failures.values()
            if item.workspace_id == workspace_id
            and item.status is OutboundProviderFailureStatus.OPEN
        ][:limit]

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundProviderFailure | None:
        return next(
            (
                item
                for item in self.failures.values()
                if item.workspace_id == workspace_id
                and item.outbound_message_id == outbound_message_id
            ),
            None,
        )


class FakeOutboundSendRequestRepository:
    def __init__(self) -> None:
        self.requests: dict[str, OutboundSendRequest] = {}

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> OutboundSendRequest | None:
        request = self.requests.get(idempotency_key)
        if request is not None and request.workspace_id == workspace_id:
            return request
        return None

    async def create_or_get(self, request: OutboundSendRequest) -> OutboundSendRequest:
        return self.requests.setdefault(request.idempotency_key, request)

    async def get_by_outbound_message_id(
        self,
        workspace_id: WorkspaceId,
        outbound_message_id: UUID,
    ) -> OutboundSendRequest | None:
        return next(
            (
                request
                for request in self.requests.values()
                if request.workspace_id == workspace_id
                and request.outbound_message_id == outbound_message_id
            ),
            None,
        )

    async def get_by_id(
        self,
        workspace_id: WorkspaceId,
        request_id: UUID,
    ) -> OutboundSendRequest | None:
        return next(
            (
                request
                for request in self.requests.values()
                if request.workspace_id == workspace_id and request.request_id == request_id
            ),
            None,
        )

    async def list_exceptions(self, **_: object) -> tuple[OutboundSendRequest, ...]:
        return tuple(self.requests.values())

    async def save(self, request: OutboundSendRequest) -> OutboundSendRequest:
        self.requests[request.idempotency_key] = request
        return request

    async def claim_due_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        _ = (now, limit)
        return ()

    async def recover_stale_dispatching(
        self,
        *,
        stale_before: datetime,
        now: datetime,
        limit: int,
    ) -> tuple[OutboundSendRequest, ...]:
        _ = (stale_before, now, limit)
        return ()

    async def get_due_pending_summary(
        self,
        *,
        now: datetime,
    ) -> tuple[int, datetime | None]:
        pending = [
            request
            for request in self.requests.values()
            if (
                request.status is OutboundSendRequestStatus.PENDING
                and request.available_at <= now
            )
        ]
        oldest = min((request.available_at for request in pending), default=None)
        return len(pending), oldest


class FakeSMSProvider:
    provider_name = "twilio"

    def __init__(
        self,
        result: str | Exception = "SM123",
        call_order: list[str] | None = None,
    ) -> None:
        self.result = result
        self.call_order = call_order
        self.messages: list[SMSMessage] = []

    async def send(self, message: SMSMessage) -> str:
        if self.call_order is not None:
            self.call_order.append("provider")
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEmailProvider:
    provider_name = "sendgrid"

    def __init__(self, result: str | Exception = "msg-123") -> None:
        self.result = result
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> str:
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class FakeLeadRefreshSource:
    def __init__(self, lead: CanonicalLeadRecord | Exception | None) -> None:
        self.lead = lead

    async def get_lead_snapshot(
        self,
        *,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        mapped_custom_field_keys: tuple[str, ...] = (),
    ) -> CanonicalLeadRecord | None:
        _ = (workspace_id, crm_lead_id, mapped_custom_field_keys)
        if isinstance(self.lead, Exception):
            raise self.lead
        return self.lead


class FakeCRMActivitySource:
    def __init__(self, activities: list[CRMActivity] | None = None) -> None:
        self.activities = activities or []

    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        _ = (workspace_id, crm_lead_id, limit)
        return list(self.activities)


class FakeCRMAgentRepository:
    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[object, ...]:
        _ = workspace_id
        return ()


class FakeWorkspaceAgentCRMMappingRepository:
    async def get_by_id(self, workspace_id: WorkspaceId, mapping_id: UUID) -> None:
        _ = (workspace_id, mapping_id)
        return None

    async def get_by_crm_agent_record_id(
        self, workspace_id: WorkspaceId, crm_agent_record_id: UUID
    ) -> None:
        _ = (workspace_id, crm_agent_record_id)
        return None

    async def get_by_app_user_id(self, workspace_id: WorkspaceId, app_user_id: UUID) -> None:
        _ = (workspace_id, app_user_id)
        return None

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> tuple[object, ...]:
        _ = workspace_id
        return ()

    async def save(self, mapping: object) -> object:
        return mapping


class FakeWorkspaceAgentMappingConfigRepository:
    async def get_by_workspace_id(self, workspace_id: WorkspaceId) -> None:
        _ = workspace_id
        return None


class FakeWorkspaceMembershipRepository:
    async def list_by_workspace_id(self, workspace_id: WorkspaceId) -> tuple[object, ...]:
        _ = workspace_id
        return ()


class FakeUserRepository:
    async def get_by_id(self, user_id: UUID) -> None:
        _ = user_id
        return None


def _lead(
    *,
    primary_email: str | None = "lead@example.com",
    primary_phone: str | None = "+15551234567",
    has_email: bool = True,
    has_sms_capable_phone: bool = True,
    sms_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    email_permission_status: ContactPermissionStatus = ContactPermissionStatus.CONFIRMED,
    suppression_types: frozenset[SuppressionType] = frozenset(),
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
        suppression_types=suppression_types,
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
    inbound_email_address: str | None = None,
) -> OutboundSendContext:
    return OutboundSendContext(
        campaign_status=campaign_status,
        workflow_state=workflow_state,
        enabled_channels=enabled_channels,
        workspace_contact_policy=WorkspaceContactPolicy(
            workspace_id=WORKSPACE_ID,
            inbound_email_address=inbound_email_address,
        ),
        current_message_version=current_message_version,
    )


def _crm_refresh_context(
    *,
    lead: CanonicalLeadRecord | Exception | None,
    activities: list[CRMActivity] | None = None,
) -> PreSendCRMRefreshContext:
    return PreSendCRMRefreshContext(
        lead_refresh_source=FakeLeadRefreshSource(lead),
        crm_activity_source=FakeCRMActivitySource(activities),
        crm_agent_repository=cast(CRMAgentRepository, FakeCRMAgentRepository()),
        workspace_agent_crm_mapping_repository=cast(
            WorkspaceAgentCRMMappingRepository,
            FakeWorkspaceAgentCRMMappingRepository(),
        ),
        workspace_agent_mapping_config_repository=cast(
            WorkspaceAgentMappingConfigRepository,
            FakeWorkspaceAgentMappingConfigRepository(),
        ),
        workspace_membership_repository=cast(
            WorkspaceMembershipRepository,
            FakeWorkspaceMembershipRepository(),
        ),
        user_repository=cast(UserRepository, FakeUserRepository()),
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
    assert result.message.provider_name == "twilio"
    assert result.message.provider_message_id == "SM123"
    assert result.message.sent_at == NOW
    assert sms_provider.messages[0].to_phone == "+15551234567"
    assert lead_repository.locked_ids == [LEAD_ID]
    assert message_repository.locked_idempotency_keys == [result.message.idempotency_key]
    assert len(email_provider.messages) == 0


async def test_enqueues_durable_send_before_commit_without_calling_provider() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    reconciliation_repository = FakeOutboundSendReconciliationRepository()
    request_repository = FakeOutboundSendRequestRepository()
    sms_provider = FakeSMSProvider()
    commit_count = 0

    async def commit() -> None:
        nonlocal commit_count
        assert request_repository.requests
        commit_count += 1

    assert message_repository.message is not None

    async def send() -> SendOutboundMessageResult:
        assert message_repository.message is not None
        return await send_outbound_message(
            workspace_id=WORKSPACE_ID,
            idempotency_key=message_repository.message.idempotency_key,
            context=_send_context(),
            lead_repository=FakeLeadRepository(_lead()),
            message_repository=message_repository,
            sms_provider=sms_provider,
            email_provider=FakeEmailProvider(),
            outbound_send_reconciliation_repository=reconciliation_repository,
            outbound_send_request_repository=request_repository,
            workflow_id=UUID("77777777-7777-7777-7777-777777777777"),
            temporal_workflow_id="lead-nurture-777",
            before_provider_dispatch=commit,
            now=NOW,
        )

    first = await send()
    second = await send()

    assert first.status is SendOutboundMessageStatus.DISPATCH_PENDING
    assert second.status is SendOutboundMessageStatus.DISPATCH_PENDING
    assert first.request_id == second.request_id
    assert first.reconciliation_id == second.reconciliation_id
    assert commit_count == 2
    assert sms_provider.messages == []
    assert len(request_repository.requests) == 1
    request = next(iter(request_repository.requests.values()))
    assert request.provider_payload["to_phone"] == "+15551234567"
    assert request.provider_payload["body"] == message_repository.message.body


async def test_blocks_when_global_frequency_limit_is_found_in_history() -> None:
    pending = _message()
    previous = replace(
        _message(),
        message_id=UUID("55555555-5555-5555-5555-555555555555"),
        idempotency_key="previous-message",
        status=OutboundMessageStatus.SENT,
        sent_at=NOW - timedelta(hours=1),
    )
    message_repository = FakeOutboundMessageRepository(pending, history=(previous,))

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=pending.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.reasons == (PreSendReasonCode.FREQUENCY_LIMIT_REACHED,)


async def test_workspace_policy_allows_sms_after_recent_email() -> None:
    pending = _message()
    previous_email = replace(
        _message(channel=ContactChannel.EMAIL, subject="Checking in"),
        message_id=UUID("55555555-5555-5555-5555-555555555555"),
        idempotency_key="previous-email",
        status=OutboundMessageStatus.SENT,
        sent_at=NOW - timedelta(hours=1),
    )
    message_repository = FakeOutboundMessageRepository(pending, history=(previous_email,))
    context = _send_context()
    context = replace(
        context,
        pre_send_policy=build_pre_send_policy(context.workspace_contact_policy, "UTC"),
    )

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=pending.idempotency_key,
        context=context,
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider("SM123"),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.SENT
    assert result.message is not None
    assert result.message.status == OutboundMessageStatus.SENT


async def test_workspace_policy_blocks_repeat_send_on_same_channel() -> None:
    pending = _message()
    previous_sms = replace(
        _message(),
        message_id=UUID("55555555-5555-5555-5555-555555555555"),
        idempotency_key="previous-sms",
        status=OutboundMessageStatus.SENT,
        sent_at=NOW - timedelta(hours=1),
    )
    message_repository = FakeOutboundMessageRepository(pending, history=(previous_sms,))
    context = _send_context()
    context = replace(
        context,
        pre_send_policy=build_pre_send_policy(context.workspace_contact_policy, "UTC"),
    )

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=pending.idempotency_key,
        context=context,
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.reasons == (PreSendReasonCode.FREQUENCY_LIMIT_REACHED,)


class FailingHistoryRepository(FakeOutboundMessageRepository):
    async def get_latest_sent_at_for_lead(
        self,
        workspace_id: WorkspaceId,
        lead_id: LeadId,
        *,
        campaign_id: UUID | None = None,
        channel: ContactChannel | None = None,
    ) -> datetime | None:
        raise RuntimeError("history lookup failed")


async def test_blocks_when_pre_send_history_lookup_fails() -> None:
    message_repository = FailingHistoryRepository(_message())
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

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.reasons == (PreSendReasonCode.MISSING_REQUIRED_DATA,)


async def test_commits_prepared_message_before_provider_dispatch() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    lead_repository = FakeLeadRepository(_lead())
    commit_markers: list[str] = []
    sms_provider = FakeSMSProvider("SM123", call_order=commit_markers)

    async def commit_prepared_message() -> None:
        commit_markers.append("committed")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        now=NOW,
        before_provider_dispatch=commit_prepared_message,
    )

    assert result.status is SendOutboundMessageStatus.SENT
    assert commit_markers == ["committed", "provider"]
    assert sms_provider.messages


async def test_locks_lead_before_locked_outbound_message_read() -> None:
    call_order: list[str] = []
    message_repository = FakeOutboundMessageRepository(_message(), call_order=call_order)
    lead_repository = FakeLeadRepository(_lead(), call_order=call_order)
    assert message_repository.message is not None

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=FakeSMSProvider("SM123"),
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.SENT
    assert call_order.index("lead_lock") < call_order.index("message_lock")


async def test_sends_message_after_successful_pre_send_crm_refresh() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    lead_repository = FakeLeadRepository(_lead())
    sms_provider = FakeSMSProvider("SM123")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=_lead()),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert sms_provider.messages


async def test_pre_send_crm_refresh_detects_recent_agent_activity_before_provider() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    sms_provider = FakeSMSProvider("must-not-be-used")
    activity = CRMActivity(
        crm_activity_id="activity-after-enqueue",
        activity_type="note",
        timestamp=NOW + timedelta(seconds=1),
        agent_id="agent-1",
    )

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=_lead(), activities=[activity]),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.RECENT_HUMAN_ACTIVITY in result.pre_send_decision.reasons
    assert sms_provider.messages == []


async def test_pre_send_crm_refresh_detects_new_opt_out_before_provider() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    sms_provider = FakeSMSProvider("must-not-be-used")
    refreshed_lead = _lead(suppression_types=frozenset({SuppressionType.SMS_OPT_OUT}))

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=refreshed_lead),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.REJECTED
    assert result.pre_send_decision is not None
    assert PreSendReasonCode.CHANNEL_NOT_CONTACTABLE in result.pre_send_decision.reasons
    assert sms_provider.messages == []


async def test_pre_send_crm_refresh_failure_fails_closed_before_provider() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    sms_provider = FakeSMSProvider("must-not-be-used")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=RuntimeError("crm unavailable")),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.FAILED
    assert result.reasons == (SendOutboundMessageReasonCode.CRM_REFRESH_FAILED,)
    assert sms_provider.messages == []


async def test_sends_message_after_pre_send_crm_refresh_detects_ownership_change() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    original_lead = replace(
        _lead(),
        assigned_agent_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        effective_owner_user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        effective_owner_source=EffectiveOwnerSource.CRM_MAPPING,
        assignment_resolution_status=AssignmentResolutionStatus.RESOLVED,
        assignment_last_resolved_at=NOW - timedelta(hours=1),
        has_accountable_owner=True,
    )
    refreshed_lead = replace(
        _lead(),
        assigned_agent_user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        effective_owner_user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        effective_owner_source=EffectiveOwnerSource.CRM_MAPPING,
        assignment_resolution_status=AssignmentResolutionStatus.RESOLVED,
        assignment_last_resolved_at=NOW,
        has_accountable_owner=True,
    )
    lead_repository = FakeLeadRepository(original_lead)
    sms_provider = FakeSMSProvider("SM123")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=sms_provider,
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=refreshed_lead),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert sms_provider.messages


async def test_rejects_when_pre_send_crm_refresh_cannot_find_lead() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    lead_repository = FakeLeadRepository(_lead())

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=lead_repository,
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=FakeEmailProvider(),
        crm_refresh_context=_crm_refresh_context(lead=None),
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.REJECTED
    assert result.reasons == (SendOutboundMessageReasonCode.CRM_LEAD_NOT_FOUND,)


async def test_sends_message_sent_event_after_successful_send() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    event_bus = FakeEventBus()

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider("SM123"),
        email_provider=FakeEmailProvider(),
        now=NOW,
        event_bus=event_bus,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == DomainEventType.MESSAGE_SENT
    assert event_bus.events[0].payload["provider_message_id"] == "SM123"


async def test_sends_message_failed_event_when_provider_send_fails() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    event_bus = FakeEventBus()

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(RuntimeError("provider down")),
        email_provider=FakeEmailProvider(),
        now=NOW,
        event_bus=event_bus,
    )

    assert result.status == SendOutboundMessageStatus.FAILED
    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == DomainEventType.MESSAGE_FAILED
    assert event_bus.events[0].payload["failure_reason"] == "provider down"


async def test_sends_pending_email_message_with_subject() -> None:
    message_repository = FakeOutboundMessageRepository(
        _message(channel=ContactChannel.EMAIL, subject="Quick check-in"),
    )
    email_provider = FakeEmailProvider("msg-123")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(inbound_email_address="nurture@inbound.example.com"),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert result.message is not None
    assert result.message.channel == ContactChannel.EMAIL
    assert result.message.provider_name == "sendgrid"
    assert result.message.provider_message_id == "msg-123"
    assert result.message.reply_routing_token is not None
    assert len(email_provider.messages) == 1
    assert email_provider.messages[0].reply_to == "nurture@inbound.example.com"


async def test_sends_pending_email_message_with_deterministic_message_id() -> None:
    message_repository = FakeOutboundMessageRepository(
        _message(channel=ContactChannel.EMAIL, subject="Quick check-in"),
    )
    email_provider = FakeEmailProvider("msg-123")

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(inbound_email_address="nurture@inbound.example.com"),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(),
        email_provider=email_provider,
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.SENT
    assert len(email_provider.messages) == 1
    assert email_provider.messages[0].message_id == build_outbound_email_message_id(MESSAGE_ID)


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
    reconciliation_repository = FakeOutboundSendReconciliationRepository()

    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(""),
        email_provider=FakeEmailProvider(),
        outbound_send_reconciliation_repository=reconciliation_repository,
        workflow_id=UUID("55555555-5555-5555-5555-555555555555"),
        temporal_workflow_id="lead-nurture/55555555",
        now=NOW,
    )

    assert result.status == SendOutboundMessageStatus.UNCERTAIN
    assert result.message is not None
    assert result.message.status == OutboundMessageStatus.UNCERTAIN
    assert result.message.provider_send_status == ProviderSendStatus.UNCERTAIN
    assert result.message.provider_name == "twilio"
    assert result.message.failure_reason == "provider_message_id_missing"
    assert result.reconciliation_id is not None
    assert len(reconciliation_repository.reconciliations) == 1
    reconciliation = next(iter(reconciliation_repository.reconciliations.values()))
    assert reconciliation.status is OutboundSendReconciliationStatus.PENDING
    assert reconciliation.outbound_message_id == result.message.message_id

    retry = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=result.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider("unexpected-retry"),
        email_provider=FakeEmailProvider(),
        outbound_send_reconciliation_repository=reconciliation_repository,
        workflow_id=UUID("55555555-5555-5555-5555-555555555555"),
        temporal_workflow_id="lead-nurture/55555555",
        now=NOW,
    )
    assert retry.status is SendOutboundMessageStatus.UNCERTAIN
    assert retry.reconciliation_id == result.reconciliation_id


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
    assert result.message.provider_name == "twilio"
    assert result.message.failure_reason == "twilio unavailable"
    assert result.message.provider_send_status == ProviderSendStatus.NOT_ATTEMPTED


async def test_uncertain_outbound_send_timeout_is_durable_and_not_repeated() -> None:
    reconciliation_repository = FakeOutboundSendReconciliationRepository()
    reconciliation = OutboundSendReconciliation(
        reconciliation_id=UUID("66666666-6666-6666-6666-666666666666"),
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=UUID("55555555-5555-5555-5555-555555555555"),
        temporal_workflow_id="lead-nurture/55555555",
        outbound_message_id=MESSAGE_ID,
        idempotency_key="uncertain-timeout-key",
        status=OutboundSendReconciliationStatus.PENDING,
        provider_name="twilio",
        provider_message_id=None,
        provider_delivery_status=None,
        created_at=NOW,
        updated_at=NOW,
    )
    await reconciliation_repository.create_or_get(reconciliation)

    first = await timeout_uncertain_outbound_send(
        workspace_id=WORKSPACE_ID,
        reconciliation_id=reconciliation.reconciliation_id,
        now=NOW + timedelta(minutes=30),
        reconciliation_repository=reconciliation_repository,
    )
    second = await timeout_uncertain_outbound_send(
        workspace_id=WORKSPACE_ID,
        reconciliation_id=reconciliation.reconciliation_id,
        now=NOW + timedelta(minutes=60),
        reconciliation_repository=reconciliation_repository,
    )

    assert first.timed_out is True
    assert first.reconciliation is not None
    assert first.reconciliation.status is OutboundSendReconciliationStatus.TIMED_OUT
    assert first.reconciliation.failure_reason == "provider_confirmation_timeout"
    assert second.timed_out is False
    assert second.reconciliation == first.reconciliation


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
    assert result.reasons == (SendOutboundMessageReasonCode.PRE_SEND_BLOCKED,)
    assert result.pre_send_decision is not None
    assert result.pre_send_decision.allowed is False
    assert PreSendReasonCode.CHANNEL_NOT_CONTACTABLE in result.pre_send_decision.reasons


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


async def test_sends_pending_sms_message_via_sink_provider() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    lead_repository = FakeLeadRepository(_lead())
    sms_provider = SinkSMSProvider()
    email_provider = SinkEmailProvider()

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
    assert result.message.provider_message_id is not None
    assert result.message.provider_message_id.startswith("sink-sms-")
    assert result.message.sent_at == NOW
    assert len(sms_provider.messages) == 1
    assert sms_provider.messages[0].to_phone == "+15551234567"
    assert sms_provider.messages[0].body == message_repository.message.body
    assert len(email_provider.messages) == 0


async def test_sends_pending_email_message_via_sink_provider() -> None:
    message_repository = FakeOutboundMessageRepository(
        _message(channel=ContactChannel.EMAIL, subject="Quick check-in"),
    )
    lead_repository = FakeLeadRepository(_lead())
    sms_provider = SinkSMSProvider()
    email_provider = SinkEmailProvider()

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
    assert result.message.channel == ContactChannel.EMAIL
    assert result.message.provider_message_id is not None
    assert result.message.provider_message_id.startswith("sink-email-")
    assert len(email_provider.messages) == 1
    assert email_provider.messages[0].to_email == "lead@example.com"
    assert email_provider.messages[0].subject == "Quick check-in"
    assert len(sms_provider.messages) == 0


async def test_typed_permanent_provider_failure_is_returned_for_fallback_decision() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    failure_repository = FakeOutboundProviderFailureRepository()
    assert message_repository.message is not None
    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=FakeSMSProvider(
            ProviderSendFailure(ProviderFailureKind.PERMANENT, "invalid destination")
        ),
        email_provider=FakeEmailProvider(),
        outbound_provider_failure_repository=failure_repository,
        workflow_id=UUID("77777777-7777-7777-7777-777777777777"),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.PERMANENT
    assert result.provider_failure_id is not None
    assert len(await failure_repository.list_open(WORKSPACE_ID)) == 1


async def test_temporary_provider_failure_retries_once_with_same_idempotency_key() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    provider = _TemporaryThenSuccessSMSProvider()
    assert message_repository.message is not None

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=provider,
        email_provider=FakeEmailProvider(),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.SENT
    assert provider.calls == 2
    assert provider.idempotency_keys == [message_repository.message.idempotency_key] * 2
    assert message_repository.message.provider_attempt_count == 2


class _TemporaryThenSuccessSMSProvider:
    provider_name = "test"

    def __init__(self) -> None:
        self.calls = 0
        self.idempotency_keys: list[str] = []

    async def send(self, message: SMSMessage) -> str:
        self.calls += 1
        self.idempotency_keys.append(message.idempotency_key)
        if self.calls == 1:
            raise ProviderSendFailure(ProviderFailureKind.TEMPORARY, "provider busy")
        return "provider-message-2"


class _AlwaysTemporaryFailureSMSProvider:
    provider_name = "test"

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, message: SMSMessage) -> str:
        self.calls += 1
        raise ProviderSendFailure(ProviderFailureKind.TEMPORARY, "provider busy")


async def test_exhausted_temporary_provider_failure_is_distinct_and_restart_safe() -> None:
    message_repository = FakeOutboundMessageRepository(_message())
    failure_repository = FakeOutboundProviderFailureRepository()
    provider = _AlwaysTemporaryFailureSMSProvider()
    assert message_repository.message is not None

    result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=provider,
        email_provider=FakeEmailProvider(),
        outbound_provider_failure_repository=failure_repository,
        workflow_id=UUID("77777777-7777-7777-7777-777777777777"),
        now=NOW,
    )

    assert result.status is SendOutboundMessageStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.TEMPORARY
    assert provider.calls == 3
    assert message_repository.message.status is OutboundMessageStatus.FAILED
    assert message_repository.message.provider_attempt_count == 3
    assert result.provider_failure_id is not None

    restart_result = await send_outbound_message(
        workspace_id=WORKSPACE_ID,
        idempotency_key=message_repository.message.idempotency_key,
        context=_send_context(),
        lead_repository=FakeLeadRepository(_lead()),
        message_repository=message_repository,
        sms_provider=provider,
        email_provider=FakeEmailProvider(),
        outbound_provider_failure_repository=failure_repository,
        now=NOW,
    )

    assert restart_result.status is SendOutboundMessageStatus.FAILED
    assert provider.calls == 3
