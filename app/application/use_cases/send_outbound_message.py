import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from secrets import token_hex
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.messaging import (
    EmailMessage,
    EmailProvider,
    ProviderFailureKind,
    ProviderSendFailure,
    SMSMessage,
    SMSProvider,
)
from app.application.ports.repositories import (
    InboundMessageRepository,
    LeadRepository,
    OutboundMessageRepository,
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.email_threading import (
    EmailThreadingHeaders,
    resolve_lead_email_threading_headers,
)
from app.application.services.pre_send_crm_refresh import (
    PreSendCRMRefreshContext,
    PreSendCRMRefreshStatus,
    refresh_lead_for_pre_send,
)
from app.application.services.pre_send_facts import load_pre_send_history_facts
from app.application.services.workspace_automation_control import (
    resolve_workspace_operational_control,
    workspace_automation_is_active,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
    build_outbound_email_message_id,
    build_outbound_reply_to_address,
)
from app.domain.campaigns.outbound_provider_failure import (
    OutboundProviderFailure,
    OutboundProviderFailureStatus,
)
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import OutboundSendRequest
from app.domain.campaigns.pre_send import (
    PreSendDecision,
    PreSendFacts,
    PreSendPolicy,
    ProviderSendStatus,
    ScheduledMessageStatus,
    WorkflowState,
    evaluate_pre_send_safety,
)
from app.domain.campaigns.start_queue import CampaignStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)
from app.domain.events import AggregateType, DomainEvent, DomainEventType


class SendOutboundMessageStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    DISPATCH_PENDING = "dispatch_pending"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


MAX_PROVIDER_ATTEMPTS = 3
PROVIDER_RETRY_BASE_DELAY = timedelta(milliseconds=100)
PROVIDER_RETRY_MAX_DELAY = timedelta(seconds=1)


class SendOutboundMessageReasonCode(StrEnum):
    MESSAGE_NOT_FOUND = "message_not_found"
    LEAD_NOT_FOUND = "lead_not_found"
    WORKSPACE_AUTOMATION_BLOCKED = "workspace_automation_blocked"
    CRM_REFRESH_UNAVAILABLE = "crm_refresh_unavailable"
    CRM_REFRESH_FAILED = "crm_refresh_failed"
    CRM_LEAD_NOT_FOUND = "crm_lead_not_found"
    PRE_SEND_BLOCKED = "pre_send_blocked"
    CHANNEL_DESTINATION_MISSING = "channel_destination_missing"
    EMAIL_SUBJECT_MISSING = "email_subject_missing"


@dataclass(frozen=True)
class OutboundSendContext:
    campaign_status: CampaignStatus
    workflow_state: WorkflowState
    enabled_channels: tuple[ContactChannel, ...]
    workspace_contact_policy: WorkspaceContactPolicy
    current_message_version: int | None = None
    pre_send_policy: PreSendPolicy = field(default_factory=PreSendPolicy)
    preflight_vetoed: bool = False
    handoff_active: bool = False
    human_owned: bool = False
    lead_replied_since_scheduled: bool = False
    recent_human_activity: bool = False
    last_global_outreach_at: datetime | None = None
    last_campaign_outreach_at: datetime | None = None
    last_channel_outreach_at: datetime | None = None
    other_channel_sent_at: datetime | None = None


@dataclass(frozen=True)
class SendOutboundMessageResult:
    status: SendOutboundMessageStatus
    message: OutboundMessage | None = None
    pre_send_decision: PreSendDecision | None = None
    reasons: tuple[SendOutboundMessageReasonCode, ...] = ()
    failure_kind: ProviderFailureKind | None = None
    reconciliation_id: UUID | None = None
    provider_failure_id: UUID | None = None
    request_id: UUID | None = None


async def send_outbound_message(
    *,
    workspace_id: WorkspaceId,
    idempotency_key: str,
    context: OutboundSendContext,
    lead_repository: LeadRepository,
    message_repository: OutboundMessageRepository,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    now: datetime,
    event_bus: EventBus | None = None,
    workspace_operational_control_repository: WorkspaceOperationalControlRepository | None = None,
    crm_refresh_context: PreSendCRMRefreshContext | None = None,
    email_in_reply_to_message_id: str | None = None,
    email_reference_message_ids: tuple[str, ...] = (),
    inbound_message_repository: InboundMessageRepository | None = None,
    outbound_send_reconciliation_repository: OutboundSendReconciliationRepository | None = None,
    outbound_send_request_repository: OutboundSendRequestRepository | None = None,
    outbound_provider_failure_repository: OutboundProviderFailureRepository | None = None,
    workflow_id: UUID | None = None,
    temporal_workflow_id: str | None = None,
    email_thread_anchor_inbound_message_id: UUID | None = None,
    before_provider_dispatch: Callable[[], Awaitable[None]] | None = None,
    confirmed_frequency_limit_override: bool = False,
) -> SendOutboundMessageResult:
    # confirmed_frequency_limit_override is forwarded to the pre-send domain
    # check and may only be set by an explicit, permission-checked operator
    # action. Every automated caller (cadence, dispatcher, webhooks) must keep
    # the default so the frequency cap always applies to machine-driven sends.
    message = await message_repository.get_by_idempotency_key(
        workspace_id,
        idempotency_key,
    )
    if message is None:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            reasons=(SendOutboundMessageReasonCode.MESSAGE_NOT_FOUND,),
        )

    if message.status == OutboundMessageStatus.SENT:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.ALREADY_SENT,
            message=message,
        )

    if message.status == OutboundMessageStatus.FAILED:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.FAILED,
            message=message,
        )

    if message.status == OutboundMessageStatus.UNCERTAIN:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.UNCERTAIN,
            message=message,
            reconciliation_id=await _existing_reconciliation_id(
                workspace_id=workspace_id,
                message=message,
                reconciliation_repository=outbound_send_reconciliation_repository,
            ),
        )

    operational_control = await resolve_workspace_operational_control(
        workspace_id=workspace_id,
        workspace_operational_control_repository=workspace_operational_control_repository,
    )
    if not workspace_automation_is_active(operational_control):
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            message=message,
            reasons=(SendOutboundMessageReasonCode.WORKSPACE_AUTOMATION_BLOCKED,),
        )

    lead = await lead_repository.get_by_id_for_update(workspace_id, message.lead_id)
    if lead is None:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            message=message,
            reasons=(SendOutboundMessageReasonCode.LEAD_NOT_FOUND,),
        )

    # The lead row is the first mutable business row locked by this send path.
    # This matches cadence execution and CRM/profile mutation paths, preventing
    # a lead/workflow lock inversion during an interruption race.
    message = await message_repository.get_by_idempotency_key_for_update(
        workspace_id,
        idempotency_key,
    )
    if message is None:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            reasons=(SendOutboundMessageReasonCode.MESSAGE_NOT_FOUND,),
        )

    if message.status == OutboundMessageStatus.SENT:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.ALREADY_SENT,
            message=message,
        )

    if message.status == OutboundMessageStatus.FAILED:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.FAILED,
            message=message,
        )

    if message.status == OutboundMessageStatus.UNCERTAIN:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.UNCERTAIN,
            message=message,
            reconciliation_id=await _existing_reconciliation_id(
                workspace_id=workspace_id,
                message=message,
                reconciliation_repository=outbound_send_reconciliation_repository,
            ),
        )

    effective_context = context
    if crm_refresh_context is not None:
        refresh_result = await refresh_lead_for_pre_send(
            lead=lead,
            message=message,
            lead_repository=lead_repository,
            message_repository=message_repository,
            crm_refresh_context=crm_refresh_context,
            event_bus=event_bus,
            now=now,
        )
        if refresh_result.status == PreSendCRMRefreshStatus.FAILED:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.FAILED,
                message=message,
                reasons=(SendOutboundMessageReasonCode.CRM_REFRESH_FAILED,),
            )
        if refresh_result.status == PreSendCRMRefreshStatus.LEAD_NOT_FOUND:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.REJECTED,
                message=message,
                reasons=(SendOutboundMessageReasonCode.CRM_LEAD_NOT_FOUND,),
            )
        lead = refresh_result.lead or lead
        message = await message_repository.get_by_idempotency_key_for_update(
            workspace_id,
            idempotency_key,
        )
        if message is None:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.REJECTED,
                reasons=(SendOutboundMessageReasonCode.MESSAGE_NOT_FOUND,),
            )
        effective_context = replace(
            context,
            recent_human_activity=(
                context.recent_human_activity or refresh_result.recent_human_activity
            ),
        )

    contactability_decision = evaluate_contactability(
        contactability_facts_from_canonical_lead(lead),
        message.channel,
    )
    history_facts = await load_pre_send_history_facts(
        workspace_id=workspace_id,
        lead_id=message.lead_id,
        campaign_id=message.campaign_id,
        message=message,
        message_repository=message_repository,
        inbound_message_repository=inbound_message_repository,
    )
    pre_send_decision = evaluate_pre_send_safety(
        PreSendFacts(
            channel=message.channel,
            campaign_status=effective_context.campaign_status,
            workflow_state=effective_context.workflow_state,
            message_status=_scheduled_message_status(message),
            provider_send_status=message.provider_send_status,
            scheduled_message_version=message.message_version,
            current_message_version=effective_context.current_message_version
            or message.message_version,
            channel_enabled=message.channel in effective_context.enabled_channels,
            contactability_decision=contactability_decision,
            preflight_vetoed=effective_context.preflight_vetoed,
            handoff_active=(
                effective_context.handoff_active
                or (
                    effective_context.workflow_state == WorkflowState.HUMAN_HANDOFF
                    and WorkflowState.HUMAN_HANDOFF
                    not in effective_context.pre_send_policy.sendable_workflow_states
                )
            ),
            human_owned=(
                effective_context.human_owned
                or effective_context.workflow_state == WorkflowState.HUMAN_OWNED
            ),
            lead_replied_since_scheduled=(
                effective_context.lead_replied_since_scheduled
                or (history_facts.lead_replied_since_scheduled if history_facts else False)
            ),
            recent_human_activity=effective_context.recent_human_activity,
            last_global_outreach_at=(
                history_facts.last_global_outreach_at
                if history_facts is not None
                else effective_context.last_global_outreach_at
            ),
            last_campaign_outreach_at=(
                history_facts.last_campaign_outreach_at
                if history_facts is not None
                else effective_context.last_campaign_outreach_at
            ),
            last_channel_outreach_at=(
                history_facts.last_channel_outreach_at
                if history_facts is not None
                else effective_context.last_channel_outreach_at
            ),
            other_channel_sent_at=(
                history_facts.other_channel_sent_at
                if history_facts is not None
                else effective_context.other_channel_sent_at
            ),
            history_facts_available=history_facts is not None,
        ),
        effective_context.pre_send_policy,
        now,
        confirmed_frequency_limit_override=confirmed_frequency_limit_override,
    )
    if not pre_send_decision.allowed:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            message=message,
            pre_send_decision=pre_send_decision,
            reasons=(SendOutboundMessageReasonCode.PRE_SEND_BLOCKED,),
        )

    if message.channel == ContactChannel.SMS:
        provider_name = _provider_name(sms_provider, default="sms")
        destination = lead.primary_phone if lead.has_sms_capable_phone else None
        if destination is None:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.REJECTED,
                message=message,
                pre_send_decision=pre_send_decision,
                reasons=(SendOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING,),
            )
        sms_payload = SMSMessage(
            to_phone=destination,
            body=message.body,
            idempotency_key=message.idempotency_key,
        )
        durable_result = await _enqueue_durable_send_if_configured(
            message=message,
            provider_name=provider_name,
            provider_payload=sms_payload.model_dump(mode="json"),
            pre_send_decision=pre_send_decision,
            outbound_send_reconciliation_repository=outbound_send_reconciliation_repository,
            outbound_send_request_repository=outbound_send_request_repository,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            before_provider_dispatch=before_provider_dispatch,
            now=now,
        )
        if durable_result is not None:
            return durable_result
        if before_provider_dispatch is not None:
            await before_provider_dispatch()
        try:
            dispatch = await _send_sms(
                provider=sms_provider,
                message=message,
                to_phone=destination,
                message_repository=message_repository,
                now=now,
            )
            message = dispatch.message
            provider_message_id = dispatch.provider_message_id
        except _ProviderSendFailed as exc:
            if exc.reconcile_as_uncertain:
                return await _uncertain_send_result(
                    message=exc.message,
                    message_repository=message_repository,
                    pre_send_decision=pre_send_decision,
                    provider_name=provider_name,
                    failure_reason=str(exc),
                    outbound_send_reconciliation_repository=(
                        outbound_send_reconciliation_repository
                    ),
                    workflow_id=workflow_id,
                    temporal_workflow_id=temporal_workflow_id,
                    now=now,
                )
            return await _failed_send_result(
                message=exc.message,
                message_repository=message_repository,
                pre_send_decision=pre_send_decision,
                failure_reason=str(exc),
                failure_kind=exc.kind,
                provider_name=provider_name,
                event_bus=event_bus,
                now=now,
                outbound_provider_failure_repository=outbound_provider_failure_repository,
                workflow_id=workflow_id,
            )
    else:
        provider_name = _provider_name(email_provider, default="email")
        destination = lead.primary_email if lead.has_email else None
        if destination is None:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.REJECTED,
                message=message,
                pre_send_decision=pre_send_decision,
                reasons=(SendOutboundMessageReasonCode.CHANNEL_DESTINATION_MISSING,),
            )
        if message.subject is None:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.REJECTED,
                message=message,
                pre_send_decision=pre_send_decision,
                reasons=(SendOutboundMessageReasonCode.EMAIL_SUBJECT_MISSING,),
            )
        if message.reply_routing_token is None:
            message = await message_repository.save(
                replace(
                    message,
                    reply_routing_token=token_hex(16),
                    updated_at=now,
                )
            )
        email_threading_headers = await _resolve_email_threading_headers(
            workspace_id=workspace_id,
            lead_id=message.lead_id,
            message_repository=message_repository,
            inbound_message_repository=inbound_message_repository,
            current_outbound_message_id=message.message_id,
            anchor_inbound_message_id=email_thread_anchor_inbound_message_id,
            explicit_in_reply_to_message_id=email_in_reply_to_message_id,
            explicit_reference_message_ids=email_reference_message_ids,
        )
        email_payload = EmailMessage(
            to_email=destination,
            subject=message.subject,
            body=message.body,
            html_body=message.html_body,
            idempotency_key=message.idempotency_key,
            message_id=build_outbound_email_message_id(message.message_id),
            reply_to=build_outbound_reply_to_address(
                effective_context.workspace_contact_policy.inbound_email_address or "",
            ),
            in_reply_to_message_id=email_threading_headers.in_reply_to_message_id,
            reference_message_ids=email_threading_headers.reference_message_ids,
        )
        durable_result = await _enqueue_durable_send_if_configured(
            message=message,
            provider_name=provider_name,
            provider_payload=email_payload.model_dump(mode="json"),
            pre_send_decision=pre_send_decision,
            outbound_send_reconciliation_repository=outbound_send_reconciliation_repository,
            outbound_send_request_repository=outbound_send_request_repository,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            before_provider_dispatch=before_provider_dispatch,
            now=now,
        )
        if durable_result is not None:
            return durable_result
        if before_provider_dispatch is not None:
            await before_provider_dispatch()
        try:
            dispatch = await _send_email(
                provider=email_provider,
                message=message,
                to_email=destination,
                reply_to_address=build_outbound_reply_to_address(
                    effective_context.workspace_contact_policy.inbound_email_address or "",
                ),
                in_reply_to_message_id=email_threading_headers.in_reply_to_message_id,
                reference_message_ids=email_threading_headers.reference_message_ids,
                message_repository=message_repository,
                now=now,
            )
            message = dispatch.message
            provider_message_id = dispatch.provider_message_id
        except _ProviderSendFailed as exc:
            if exc.reconcile_as_uncertain:
                return await _uncertain_send_result(
                    message=exc.message,
                    message_repository=message_repository,
                    pre_send_decision=pre_send_decision,
                    provider_name=provider_name,
                    failure_reason=str(exc),
                    outbound_send_reconciliation_repository=(
                        outbound_send_reconciliation_repository
                    ),
                    workflow_id=workflow_id,
                    temporal_workflow_id=temporal_workflow_id,
                    now=now,
                )
            return await _failed_send_result(
                message=exc.message,
                message_repository=message_repository,
                pre_send_decision=pre_send_decision,
                failure_reason=str(exc),
                failure_kind=exc.kind,
                provider_name=provider_name,
                event_bus=event_bus,
                now=now,
                outbound_provider_failure_repository=outbound_provider_failure_repository,
                workflow_id=workflow_id,
            )

    if provider_message_id:
        sent_message = replace(
            message,
            status=OutboundMessageStatus.SENT,
            provider_send_status=ProviderSendStatus.ACCEPTED,
            provider_name=provider_name,
            provider_message_id=provider_message_id,
            provider_delivery_status=ProviderDeliveryStatus.ACCEPTED,
            failure_reason=None,
            status_detail=None,
            provider_next_retry_at=None,
            provider_last_failure_kind=None,
            sent_at=now,
            updated_at=now,
        )
        saved = await message_repository.save(sent_message)
        await _publish_message_event(
            event_bus=event_bus,
            event_type=DomainEventType.MESSAGE_SENT,
            message=saved,
            now=now,
        )
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.SENT,
            message=saved,
            pre_send_decision=pre_send_decision,
        )

    return await _uncertain_send_result(
        message=message,
        message_repository=message_repository,
        pre_send_decision=pre_send_decision,
        provider_name=provider_name,
        failure_reason="provider_message_id_missing",
        outbound_send_reconciliation_repository=outbound_send_reconciliation_repository,
        workflow_id=workflow_id,
        temporal_workflow_id=temporal_workflow_id,
        now=now,
    )


async def _enqueue_durable_send_if_configured(
    *,
    message: OutboundMessage,
    provider_name: str,
    provider_payload: dict[str, object],
    pre_send_decision: PreSendDecision,
    outbound_send_reconciliation_repository: OutboundSendReconciliationRepository | None,
    outbound_send_request_repository: OutboundSendRequestRepository | None,
    workflow_id: UUID | None,
    temporal_workflow_id: str | None,
    before_provider_dispatch: Callable[[], Awaitable[None]] | None,
    now: datetime,
) -> SendOutboundMessageResult | None:
    if (
        outbound_send_reconciliation_repository is None
        or outbound_send_request_repository is None
        or workflow_id is None
        or temporal_workflow_id is None
    ):
        return None
    reconciliation = await outbound_send_reconciliation_repository.create_or_get(
        OutboundSendReconciliation(
            reconciliation_id=uuid4(),
            workspace_id=message.workspace_id,
            lead_id=message.lead_id,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            outbound_message_id=message.message_id,
            idempotency_key=message.idempotency_key,
            status=OutboundSendReconciliationStatus.PENDING,
            provider_name=provider_name,
            provider_message_id=None,
            provider_delivery_status=None,
            created_at=now,
            updated_at=now,
        )
    )
    request = await outbound_send_request_repository.create_or_get(
        OutboundSendRequest(
            request_id=uuid4(),
            workspace_id=message.workspace_id,
            lead_id=message.lead_id,
            workflow_id=workflow_id,
            temporal_workflow_id=temporal_workflow_id,
            outbound_message_id=message.message_id,
            reconciliation_id=reconciliation.reconciliation_id,
            idempotency_key=message.idempotency_key,
            channel=message.channel,
            provider_name=provider_name,
            provider_payload=provider_payload,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    if before_provider_dispatch is not None:
        await before_provider_dispatch()
    return SendOutboundMessageResult(
        status=SendOutboundMessageStatus.DISPATCH_PENDING,
        message=message,
        pre_send_decision=pre_send_decision,
        reconciliation_id=reconciliation.reconciliation_id,
        request_id=request.request_id,
    )


async def _existing_reconciliation_id(
    *,
    workspace_id: WorkspaceId,
    message: OutboundMessage,
    reconciliation_repository: OutboundSendReconciliationRepository | None,
) -> UUID | None:
    if reconciliation_repository is None:
        return None
    reconciliation = await reconciliation_repository.get_by_outbound_message_id_for_update(
        workspace_id,
        message.message_id,
    )
    return reconciliation.reconciliation_id if reconciliation is not None else None


async def _uncertain_send_result(
    *,
    message: OutboundMessage,
    message_repository: OutboundMessageRepository,
    pre_send_decision: PreSendDecision,
    provider_name: str,
    failure_reason: str,
    outbound_send_reconciliation_repository: OutboundSendReconciliationRepository | None,
    workflow_id: UUID | None,
    temporal_workflow_id: str | None,
    now: datetime,
) -> SendOutboundMessageResult:
    uncertain_message = replace(
        message,
        status=OutboundMessageStatus.UNCERTAIN,
        provider_send_status=ProviderSendStatus.UNCERTAIN,
        provider_delivery_status=ProviderDeliveryStatus.UNKNOWN,
        provider_name=provider_name,
        provider_message_id=None,
        failure_reason=failure_reason,
        status_detail=None,
        updated_at=now,
    )
    saved = await message_repository.save(uncertain_message)
    reconciliation_id: UUID | None = None
    if (
        outbound_send_reconciliation_repository is not None
        and workflow_id is not None
        and temporal_workflow_id is not None
    ):
        reconciliation = await outbound_send_reconciliation_repository.create_or_get(
            OutboundSendReconciliation(
                reconciliation_id=uuid4(),
                workspace_id=saved.workspace_id,
                lead_id=saved.lead_id,
                workflow_id=workflow_id,
                temporal_workflow_id=temporal_workflow_id,
                outbound_message_id=saved.message_id,
                idempotency_key=saved.idempotency_key,
                status=OutboundSendReconciliationStatus.PENDING,
                provider_name=provider_name,
                provider_message_id=saved.provider_message_id,
                provider_delivery_status=saved.provider_delivery_status,
                created_at=now,
                updated_at=now,
            )
        )
        reconciliation_id = reconciliation.reconciliation_id
    return SendOutboundMessageResult(
        status=SendOutboundMessageStatus.UNCERTAIN,
        message=saved,
        failure_kind=ProviderFailureKind.UNCERTAIN,
        pre_send_decision=pre_send_decision,
        reconciliation_id=reconciliation_id,
    )


@dataclass(frozen=True)
class _ProviderDispatchResult:
    provider_message_id: str
    message: OutboundMessage


async def _send_sms(
    *,
    provider: SMSProvider,
    message: OutboundMessage,
    to_phone: str,
    message_repository: OutboundMessageRepository,
    now: datetime,
) -> _ProviderDispatchResult:
    return await _dispatch_with_retry(
        message=message,
        message_repository=message_repository,
        now=now,
        send=lambda current: provider.send(
            SMSMessage(
                to_phone=to_phone,
                body=current.body,
                idempotency_key=current.idempotency_key,
            )
        ),
    )


async def _send_email(
    *,
    provider: EmailProvider,
    message: OutboundMessage,
    to_email: str,
    reply_to_address: str | None,
    in_reply_to_message_id: str | None,
    reference_message_ids: tuple[str, ...],
    message_repository: OutboundMessageRepository,
    now: datetime,
) -> _ProviderDispatchResult:
    return await _dispatch_with_retry(
        message=message,
        message_repository=message_repository,
        now=now,
        send=lambda current: provider.send(
            EmailMessage(
                to_email=to_email,
                subject=current.subject or "",
                body=current.body,
                html_body=current.html_body,
                idempotency_key=current.idempotency_key,
                message_id=build_outbound_email_message_id(current.message_id),
                reply_to=reply_to_address,
                in_reply_to_message_id=in_reply_to_message_id,
                reference_message_ids=reference_message_ids,
            )
        ),
    )


async def _dispatch_with_retry(
    *,
    message: OutboundMessage,
    message_repository: OutboundMessageRepository,
    now: datetime,
    send: Callable[[OutboundMessage], Awaitable[str]],
) -> _ProviderDispatchResult:
    current = message
    while current.provider_attempt_count < MAX_PROVIDER_ATTEMPTS:
        if current.provider_next_retry_at is not None:
            remaining = (current.provider_next_retry_at - now).total_seconds()
            if remaining > 0:
                await asyncio.sleep(remaining)
        attempt = current.provider_attempt_count + 1
        current = await message_repository.save(
            replace(
                current,
                provider_attempt_count=attempt,
                provider_last_attempt_at=now,
                provider_next_retry_at=None,
                updated_at=now,
            )
        )
        try:
            provider_message_id = (await send(current)).strip()
            return _ProviderDispatchResult(
                provider_message_id=provider_message_id,
                message=current,
            )
        except ProviderSendFailure as exc:
            retryable = exc.kind is ProviderFailureKind.TEMPORARY
            has_attempts_left = attempt < MAX_PROVIDER_ATTEMPTS
            next_retry_at = (
                now + _provider_retry_delay(attempt) if retryable and has_attempts_left else None
            )
            current = await message_repository.save(
                replace(
                    current,
                    provider_next_retry_at=next_retry_at,
                    provider_last_failure_kind=exc.kind.value,
                    failure_reason=str(exc),
                    updated_at=now,
                )
            )
            if retryable and has_attempts_left:
                await asyncio.sleep(_provider_retry_delay(attempt).total_seconds())
                continue
            raise _ProviderSendFailed(
                exc.kind,
                str(exc),
                current,
                reconcile_as_uncertain=exc.kind is ProviderFailureKind.UNCERTAIN,
            ) from exc
        except Exception as exc:
            current = await message_repository.save(
                replace(
                    current,
                    provider_last_failure_kind=ProviderFailureKind.UNCERTAIN.value,
                    failure_reason=str(exc),
                    updated_at=now,
                )
            )
            raise _ProviderSendFailed(
                ProviderFailureKind.UNCERTAIN,
                str(exc),
                current,
                reconcile_as_uncertain=False,
            ) from exc
    raise _ProviderSendFailed(
        ProviderFailureKind.TEMPORARY,
        "provider retry attempt limit exhausted",
        current,
    )


def _provider_retry_delay(attempt: int) -> timedelta:
    delay = PROVIDER_RETRY_BASE_DELAY * (2 ** (attempt - 1))
    return PROVIDER_RETRY_MAX_DELAY if delay > PROVIDER_RETRY_MAX_DELAY else delay


async def _resolve_email_threading_headers(
    *,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    message_repository: OutboundMessageRepository,
    inbound_message_repository: InboundMessageRepository | None,
    current_outbound_message_id: UUID,
    anchor_inbound_message_id: UUID | None,
    explicit_in_reply_to_message_id: str | None,
    explicit_reference_message_ids: tuple[str, ...],
) -> EmailThreadingHeaders:
    if explicit_in_reply_to_message_id is not None or explicit_reference_message_ids:
        return EmailThreadingHeaders(
            in_reply_to_message_id=explicit_in_reply_to_message_id,
            reference_message_ids=explicit_reference_message_ids,
        )
    return await resolve_lead_email_threading_headers(
        workspace_id=workspace_id,
        lead_id=lead_id,
        inbound_message_repository=inbound_message_repository,
        message_repository=message_repository,
        anchor_inbound_message_id=anchor_inbound_message_id,
        current_outbound_message_id=current_outbound_message_id,
    )


def _scheduled_message_status(message: OutboundMessage) -> ScheduledMessageStatus:
    if message.status == OutboundMessageStatus.CANCELLED:
        return ScheduledMessageStatus.CANCELLED
    if message.status == OutboundMessageStatus.SENT:
        return ScheduledMessageStatus.SENT
    return ScheduledMessageStatus.PENDING


async def _failed_send_result(
    *,
    message: OutboundMessage,
    message_repository: OutboundMessageRepository,
    pre_send_decision: PreSendDecision,
    failure_reason: str,
    failure_kind: ProviderFailureKind,
    provider_name: str,
    event_bus: EventBus | None,
    now: datetime,
    outbound_provider_failure_repository: OutboundProviderFailureRepository | None,
    workflow_id: UUID | None,
) -> SendOutboundMessageResult:
    failed_message = replace(
        message,
        status=OutboundMessageStatus.FAILED,
        provider_name=provider_name,
        failure_reason=failure_reason,
        status_detail=None,
        updated_at=now,
    )
    saved = await message_repository.save(failed_message)
    provider_failure_id: UUID | None = None
    if outbound_provider_failure_repository is not None:
        failure = await outbound_provider_failure_repository.create_or_get(
            OutboundProviderFailure(
                failure_id=uuid4(),
                workspace_id=saved.workspace_id,
                lead_id=saved.lead_id,
                outbound_message_id=saved.message_id,
                workflow_id=workflow_id,
                channel=saved.channel,
                provider_name=provider_name,
                failure_kind=failure_kind.value,
                failure_reason=failure_reason,
                attempt_count=saved.provider_attempt_count,
                status=OutboundProviderFailureStatus.OPEN,
                first_failed_at=saved.provider_last_attempt_at or now,
                last_failed_at=now,
                created_at=now,
            )
        )
        provider_failure_id = failure.failure_id
    await _publish_message_event(
        event_bus=event_bus,
        event_type=DomainEventType.MESSAGE_FAILED,
        message=saved,
        now=now,
    )
    return SendOutboundMessageResult(
        status=SendOutboundMessageStatus.FAILED,
        message=saved,
        pre_send_decision=pre_send_decision,
        failure_kind=failure_kind,
        provider_failure_id=provider_failure_id,
    )


class _ProviderSendFailed(Exception):
    def __init__(
        self,
        kind: ProviderFailureKind,
        message: str,
        outbound_message: OutboundMessage,
        reconcile_as_uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = outbound_message
        self.reconcile_as_uncertain = reconcile_as_uncertain


def _provider_name(provider: object, *, default: str) -> str:
    provider_name = getattr(provider, "provider_name", default)
    return provider_name if isinstance(provider_name, str) and provider_name else default


async def _publish_message_event(
    *,
    event_bus: EventBus | None,
    event_type: DomainEventType,
    message: OutboundMessage,
    now: datetime,
) -> None:
    if event_bus is None:
        return
    await event_bus.publish(
        DomainEvent(
            workspace_id=message.workspace_id,
            aggregate_type=AggregateType.MESSAGE,
            aggregate_id=message.message_id,
            event_type=event_type,
            payload={
                "message_id": str(message.message_id),
                "lead_id": str(message.lead_id),
                "campaign_id": str(message.campaign_id),
                "cadence_step_id": message.cadence_step_id,
                "channel": message.channel.value,
                "status": message.status.value,
                "provider_name": message.provider_name,
                "provider_message_id": message.provider_message_id,
                "failure_reason": message.failure_reason,
                "occurred_at": now.isoformat(),
            },
        ),
    )
