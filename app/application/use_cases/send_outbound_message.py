from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from app.application.ports.messaging import EmailMessage, EmailProvider, SMSMessage, SMSProvider
from app.application.ports.repositories import LeadRepository, OutboundMessageRepository
from app.application.services.canonical_lead_inputs import contactability_facts_from_canonical_lead
from app.domain.campaigns.outbound_message import OutboundMessage, OutboundMessageStatus
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
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import (
    ContactChannel,
    WorkspaceContactPolicy,
    evaluate_contactability,
)


class SendOutboundMessageStatus(StrEnum):
    SENT = "sent"
    ALREADY_SENT = "already_sent"
    REJECTED = "rejected"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class SendOutboundMessageReasonCode(StrEnum):
    MESSAGE_NOT_FOUND = "message_not_found"
    LEAD_NOT_FOUND = "lead_not_found"
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
    ownership_changed: bool = False
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

    lead = await lead_repository.get_by_id_for_update(workspace_id, message.lead_id)
    if lead is None:
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.REJECTED,
            message=message,
            reasons=(SendOutboundMessageReasonCode.LEAD_NOT_FOUND,),
        )

    contactability_decision = evaluate_contactability(
        contactability_facts_from_canonical_lead(lead),
        context.workspace_contact_policy,
        message.channel,
    )
    pre_send_decision = evaluate_pre_send_safety(
        PreSendFacts(
            channel=message.channel,
            campaign_status=context.campaign_status,
            workflow_state=context.workflow_state,
            message_status=_scheduled_message_status(message),
            provider_send_status=message.provider_send_status,
            scheduled_message_version=message.message_version,
            current_message_version=context.current_message_version or message.message_version,
            channel_enabled=message.channel in context.enabled_channels,
            contactability_decision=contactability_decision,
            preflight_vetoed=context.preflight_vetoed,
            handoff_active=context.handoff_active,
            human_owned=context.human_owned,
            lead_replied_since_scheduled=context.lead_replied_since_scheduled,
            recent_human_activity=context.recent_human_activity,
            ownership_changed=context.ownership_changed,
            last_global_outreach_at=context.last_global_outreach_at,
            last_campaign_outreach_at=context.last_campaign_outreach_at,
            last_channel_outreach_at=context.last_channel_outreach_at,
            other_channel_sent_at=context.other_channel_sent_at,
        ),
        context.pre_send_policy,
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
                now=now,
            )
    else:
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
        try:
            provider_message_id = await _send_email(
                provider=email_provider,
                message=message,
                to_email=destination,
            )
        except _ProviderSendFailed as exc:
            return await _failed_send_result(
                message=message,
                message_repository=message_repository,
                pre_send_decision=pre_send_decision,
                failure_reason=str(exc),
                now=now,
            )

    if provider_message_id:
        sent_message = replace(
            message,
            status=OutboundMessageStatus.SENT,
            provider_send_status=ProviderSendStatus.ACCEPTED,
            provider_message_id=provider_message_id,
            failure_reason=None,
            sent_at=now,
            updated_at=now,
        )
        saved = await message_repository.save(sent_message)
        return SendOutboundMessageResult(
            status=SendOutboundMessageStatus.SENT,
            message=saved,
            pre_send_decision=pre_send_decision,
        )

    uncertain_message = replace(
        message,
        status=OutboundMessageStatus.UNCERTAIN,
        provider_send_status=ProviderSendStatus.UNCERTAIN,
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
                ),
            )
        ).strip()
    except Exception as exc:
        raise _ProviderSendFailed(str(exc) or exc.__class__.__name__) from exc


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
    now: datetime,
) -> SendOutboundMessageResult:
    failed_message = replace(
        message,
        status=OutboundMessageStatus.FAILED,
        failure_reason=failure_reason,
        updated_at=now,
    )
    saved = await message_repository.save(failed_message)
    return SendOutboundMessageResult(
        status=SendOutboundMessageStatus.FAILED,
        message=saved,
        pre_send_decision=pre_send_decision,
    )


class _ProviderSendFailed(Exception):
    pass