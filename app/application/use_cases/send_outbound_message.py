from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from secrets import token_hex
from typing import Protocol
from uuid import UUID

from app.application.ports.crm import CRMActivity
from app.application.ports.crm_sync import CanonicalLeadRefreshSource
from app.application.ports.event_bus import EventBus
from app.application.ports.messaging import EmailMessage, EmailProvider, SMSMessage, SMSProvider
from app.application.ports.repositories import (
    CRMAgentRepository,
    InboundMessageRepository,
    LeadRepository,
    LeadWorkflowRepository,
    OutboundMessageRepository,
    TemporalSignalOutboxRepository,
    UserRepository,
    WorkflowTransitionRepository,
    WorkspaceAgentCRMMappingRepository,
    WorkspaceAgentMappingConfigRepository,
    WorkspaceMembershipRepository,
    WorkspaceOperationalControlRepository,
)
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.application.services.email_threading import (
    EmailThreadingHeaders,
    resolve_lead_email_threading_headers,
)
from app.application.services.lead_assignment_resolution import (
    apply_lead_assignment_resolution,
    load_workspace_lead_assignment_context,
)
from app.application.services.workspace_automation_control import (
    resolve_workspace_operational_control,
    workspace_automation_is_active,
)
from app.application.use_cases.reconcile_lead_assignment import (
    LeadAssignmentMessageRepository,
    reconcile_lead_assignment_change,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    build_outbound_email_message_id,
    build_outbound_reply_to_address,
)
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
from app.domain.leads import CanonicalLeadRecord


class SendOutboundMessageStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


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


class CRMActivitySource(Protocol):
    async def get_recent_activity(
        self,
        workspace_id: WorkspaceId,
        crm_lead_id: str,
        limit: int = 50,
    ) -> list[CRMActivity]:
        raise NotImplementedError


@dataclass(frozen=True)
class PreSendCRMRefreshContext:
    lead_refresh_source: CanonicalLeadRefreshSource
    crm_activity_source: CRMActivitySource
    crm_agent_repository: CRMAgentRepository
    workspace_agent_crm_mapping_repository: WorkspaceAgentCRMMappingRepository
    workspace_agent_mapping_config_repository: WorkspaceAgentMappingConfigRepository
    workspace_membership_repository: WorkspaceMembershipRepository
    user_repository: UserRepository
    lead_workflow_repository: LeadWorkflowRepository | None = None
    workflow_transition_repository: WorkflowTransitionRepository | None = None
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None
    activity_limit: int = 20


@dataclass(frozen=True)
class SendOutboundMessageResult:
    status: SendOutboundMessageStatus
    message: OutboundMessage | None = None
    pre_send_decision: PreSendDecision | None = None
    reasons: tuple[SendOutboundMessageReasonCode, ...] = ()


class _PreSendCRMRefreshStatus(StrEnum):
    REFRESHED = "refreshed"
    FAILED = "failed"
    LEAD_NOT_FOUND = "lead_not_found"


@dataclass(frozen=True)
class _PreSendCRMRefreshResult:
    status: _PreSendCRMRefreshStatus
    lead: CanonicalLeadRecord | None = None
    recent_human_activity: bool = False
    failure_reason: str | None = None


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
    email_thread_anchor_inbound_message_id: UUID | None = None,
) -> SendOutboundMessageResult:
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

    effective_context = context
    if crm_refresh_context is not None:
        refresh_result = await _refresh_lead_for_pre_send(
            lead=lead,
            message=message,
            lead_repository=lead_repository,
            message_repository=message_repository,
            crm_refresh_context=crm_refresh_context,
            event_bus=event_bus,
            now=now,
        )
        if refresh_result.status == _PreSendCRMRefreshStatus.FAILED:
            return SendOutboundMessageResult(
                status=SendOutboundMessageStatus.FAILED,
                message=message,
                reasons=(SendOutboundMessageReasonCode.CRM_REFRESH_FAILED,),
            )
        if refresh_result.status == _PreSendCRMRefreshStatus.LEAD_NOT_FOUND:
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
        effective_context.workspace_contact_policy,
        message.channel,
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
            handoff_active=effective_context.handoff_active,
            human_owned=effective_context.human_owned,
            lead_replied_since_scheduled=effective_context.lead_replied_since_scheduled,
            recent_human_activity=effective_context.recent_human_activity,
            last_global_outreach_at=effective_context.last_global_outreach_at,
            last_campaign_outreach_at=effective_context.last_campaign_outreach_at,
            last_channel_outreach_at=effective_context.last_channel_outreach_at,
            other_channel_sent_at=effective_context.other_channel_sent_at,
        ),
        effective_context.pre_send_policy,
        now,
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
        try:
            provider_message_id = await _send_sms(
                provider=sms_provider,
                message=message,
                to_phone=destination,
            )
        except _ProviderSendFailed as exc:
            return await _failed_send_result(
                message=message,
                message_repository=message_repository,
                pre_send_decision=pre_send_decision,
                failure_reason=str(exc),
                provider_name=provider_name,
                event_bus=event_bus,
                now=now,
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
        try:
            provider_message_id = await _send_email(
                provider=email_provider,
                message=message,
                to_email=destination,
                reply_to_address=build_outbound_reply_to_address(
                    effective_context.workspace_contact_policy.inbound_email_address or "",
                    message.reply_routing_token or "",
                ),
                in_reply_to_message_id=email_threading_headers.in_reply_to_message_id,
                reference_message_ids=email_threading_headers.reference_message_ids,
            )
        except _ProviderSendFailed as exc:
            return await _failed_send_result(
                message=message,
                message_repository=message_repository,
                pre_send_decision=pre_send_decision,
                failure_reason=str(exc),
                provider_name=provider_name,
                event_bus=event_bus,
                now=now,
            )

    if provider_message_id:
        sent_message = replace(
            message,
            status=OutboundMessageStatus.SENT,
            provider_send_status=ProviderSendStatus.ACCEPTED,
            provider_name=provider_name,
            provider_message_id=provider_message_id,
            failure_reason=None,
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

    uncertain_message = replace(
        message,
        status=OutboundMessageStatus.UNCERTAIN,
        provider_send_status=ProviderSendStatus.UNCERTAIN,
        provider_name=provider_name,
        provider_message_id=None,
        failure_reason="provider_message_id_missing",
        updated_at=now,
    )
    saved = await message_repository.save(uncertain_message)
    return SendOutboundMessageResult(
        status=SendOutboundMessageStatus.UNCERTAIN,
        message=saved,
        pre_send_decision=pre_send_decision,
    )


async def _refresh_lead_for_pre_send(
    *,
    lead: CanonicalLeadRecord,
    message: OutboundMessage,
    lead_repository: LeadRepository,
    message_repository: LeadAssignmentMessageRepository,
    crm_refresh_context: PreSendCRMRefreshContext,
    event_bus: EventBus | None,
    now: datetime,
) -> _PreSendCRMRefreshResult:
    try:
        refreshed_lead = await crm_refresh_context.lead_refresh_source.get_lead_snapshot(
            workspace_id=lead.workspace_id,
            crm_lead_id=lead.crm_lead_id,
            mapped_custom_field_keys=tuple(lead.mapped_custom_fields.keys()),
        )
        activities = await crm_refresh_context.crm_activity_source.get_recent_activity(
            lead.workspace_id,
            lead.crm_lead_id,
            limit=crm_refresh_context.activity_limit,
        )
    except Exception as exc:
        return _PreSendCRMRefreshResult(
            status=_PreSendCRMRefreshStatus.FAILED,
            failure_reason=str(exc) or exc.__class__.__name__,
        )

    if refreshed_lead is None:
        return _PreSendCRMRefreshResult(status=_PreSendCRMRefreshStatus.LEAD_NOT_FOUND)

    assignment_context = await load_workspace_lead_assignment_context(
        workspace_id=lead.workspace_id,
        crm_agent_repository=crm_refresh_context.crm_agent_repository,
        workspace_agent_crm_mapping_repository=(
            crm_refresh_context.workspace_agent_crm_mapping_repository
        ),
        workspace_agent_mapping_config_repository=(
            crm_refresh_context.workspace_agent_mapping_config_repository
        ),
        workspace_membership_repository=crm_refresh_context.workspace_membership_repository,
        user_repository=crm_refresh_context.user_repository,
    )
    resolved_lead = apply_lead_assignment_resolution(
        refreshed_lead,
        context=assignment_context,
        now=now,
    )
    saved_lead = await lead_repository.upsert(resolved_lead)
    await reconcile_lead_assignment_change(
        previous_lead=lead,
        current_lead=saved_lead,
        lead_workflow_repository=crm_refresh_context.lead_workflow_repository,
        workflow_transition_repository=crm_refresh_context.workflow_transition_repository,
        temporal_signal_outbox_repository=crm_refresh_context.temporal_signal_outbox_repository,
        outbound_message_repository=message_repository,
        event_bus=event_bus,
        now=now,
    )
    return _PreSendCRMRefreshResult(
        status=_PreSendCRMRefreshStatus.REFRESHED,
        lead=saved_lead,
        recent_human_activity=_recent_human_activity_detected(
            lead=lead,
            refreshed_lead=saved_lead,
            activities=activities,
            message=message,
        ),
    )


def _recent_human_activity_detected(
    *,
    lead: CanonicalLeadRecord,
    refreshed_lead: CanonicalLeadRecord,
    activities: list[CRMActivity],
    message: OutboundMessage,
) -> bool:
    if (
        refreshed_lead.last_agent_activity_at is not None
        and refreshed_lead.last_agent_activity_at > message.created_at
        and refreshed_lead.last_agent_activity_at != lead.last_agent_activity_at
    ):
        return True
    return any(
        activity.agent_id is not None and activity.timestamp > message.created_at
        for activity in activities
    )


async def _send_sms(
    *,
    provider: SMSProvider,
    message: OutboundMessage,
    to_phone: str,
) -> str:
    try:
        return (
            await provider.send(
                SMSMessage(
                    to_phone=to_phone,
                    body=message.body,
                    idempotency_key=message.idempotency_key,
                ),
            )
        ).strip()
    except Exception as exc:
        raise _ProviderSendFailed(str(exc) or exc.__class__.__name__) from exc


async def _send_email(
    *,
    provider: EmailProvider,
    message: OutboundMessage,
    to_email: str,
    reply_to_address: str | None,
    in_reply_to_message_id: str | None,
    reference_message_ids: tuple[str, ...],
) -> str:
    assert message.subject is not None
    try:
        return (
            await provider.send(
                EmailMessage(
                    to_email=to_email,
                    subject=message.subject,
                    body=message.body,
                    html_body=message.html_body,
                    idempotency_key=message.idempotency_key,
                    message_id=build_outbound_email_message_id(message.message_id),
                    reply_to=reply_to_address,
                    in_reply_to_message_id=in_reply_to_message_id,
                    reference_message_ids=reference_message_ids,
                ),
            )
        ).strip()
    except Exception as exc:
        raise _ProviderSendFailed(str(exc) or exc.__class__.__name__) from exc


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
    provider_name: str,
    event_bus: EventBus | None,
    now: datetime,
) -> SendOutboundMessageResult:
    failed_message = replace(
        message,
        status=OutboundMessageStatus.FAILED,
        provider_name=provider_name,
        failure_reason=failure_reason,
        updated_at=now,
    )
    saved = await message_repository.save(failed_message)
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
    )


class _ProviderSendFailed(Exception):
    pass


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
