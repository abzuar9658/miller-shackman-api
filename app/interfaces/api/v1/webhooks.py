import base64
import hmac
import json
from datetime import UTC, datetime
from email.utils import parseaddr
from hashlib import sha256
from typing import Annotated
from uuid import UUID

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import TypeAdapter, ValidationError
from sendgrid.helpers.eventwebhook import EventWebhook
from starlette.datastructures import FormData, UploadFile
from twilio.request_validator import RequestValidator

from app.application.ports.crm_webhook import FollowUpBossWebhookEventHandler
from app.application.use_cases.process_contact_suppression_event import (
    ContactSuppressionEvent,
    process_contact_suppression_event,
)
from app.application.use_cases.process_crm_human_activity_event import (
    CRMHumanActivityEvent,
    process_crm_human_activity_event,
)
from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    process_inbound_message_event,
)
from app.application.use_cases.process_provider_delivery_callback import (
    ProcessProviderDeliveryCallbackResult,
    ProcessProviderDeliveryCallbackStatus,
    ProviderDeliveryCallback,
    process_provider_delivery_callback,
)
from app.core.config import Settings, get_settings
from app.core.database import enable_postgres_service_access, set_postgres_workspace_context
from app.domain.campaigns.outbound_message import (
    ProviderDeliveryStatus,
    parse_outbound_email_message_id,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.leads import CanonicalLeadRecord, CRMProvider
from app.interfaces.api.dependencies.follow_up_boss_webhook import (
    get_follow_up_boss_webhook_event_handler,
)
from app.interfaces.api.dependencies.inbound import InboundServiceBundle, get_inbound_service_bundle
from app.interfaces.api.dependencies.provider_delivery import (
    ProviderDeliveryServiceBundle,
    get_provider_delivery_service_bundle,
)
from app.interfaces.api.schemas.inbound import (
    ContactSuppressionWebhookResponse,
    CRMHumanActivityWebhookResponse,
    FollowUpBossContactSuppressionRequest,
    FollowUpBossCRMHumanActivityRequest,
    FollowUpBossInboundMessageRequest,
    FollowUpBossWebhookResponse,
    InboundWebhookResponse,
    MailgunInboundParsePayload,
    SendGridInboundParsePayload,
    TwilioInboundMessagePayload,
)
from app.interfaces.api.schemas.provider_delivery import (
    MailgunEventWebhookPayload,
    ProviderDeliveryWebhookResponse,
    ProviderDeliveryWebhookResult,
    SendGridEventWebhookPayload,
    TwilioMessageStatusCallbackPayload,
)

router = APIRouter(tags=["webhooks"])
logger = structlog.get_logger(__name__)


async def _handle_inbound_message_event(
    event: InboundMessageEvent,
    bundle: InboundServiceBundle,
    now: datetime,
) -> InboundWebhookResponse:
    result = await process_inbound_message_event(
        event=event,
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        conversation_repository=bundle.conversation_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        crm_conversation_event_repository=bundle.crm_conversation_event_repository,
        lead_classification_artifact_repository=bundle.lead_classification_artifact_repository,
        routing_review_repository=bundle.routing_review_repository,
        conversation_summary_repository=bundle.conversation_summary_repository,
        handoff_repository=bundle.handoff_repository,
        crm_client=bundle.crm_client,
        inbound_message_crm_completion_repository=bundle.inbound_message_crm_completion_repository,
        outbound_message_crm_completion_repository=bundle.outbound_message_crm_completion_repository,
        notification_provider=bundle.notification_provider,
        workspace_handoff_config_repository=bundle.workspace_handoff_config_repository,
        workspace_llm_config_repository=bundle.workspace_llm_config_repository,
        handoff_completion_repository=bundle.handoff_completion_repository,
        user_repository=bundle.user_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        paused_search_track_repository=bundle.paused_search_track_repository,
        paused_search_track_assignment_repository=(
            bundle.paused_search_track_assignment_repository
        ),
        paused_search_occurrence_repository=bundle.paused_search_occurrence_repository,
        paused_search_reminder_repository=bundle.paused_search_reminder_repository,
        llm_client=bundle.llm_client,
        event_bus=bundle.event_bus,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        default_openrouter_model=bundle.default_openrouter_model,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        workspace_repository=bundle.workspace_repository,
        campaign_execution_repository=bundle.campaign_execution_repository,
        workspace_operational_control_repository=bundle.workspace_operational_control_repository,
        workspace_outbound_drafting_config_repository=bundle.workspace_outbound_drafting_config_repository,
        message_repository=bundle.message_repository,
        sms_provider=bundle.sms_provider,
        email_provider=bundle.email_provider,
        now=now,
    )
    await bundle.session.commit()
    return InboundWebhookResponse(
        status=result.status.value,
        external_event_id=result.external_event_id,
        lead_id=result.lead_id,
        conversation_id=result.conversation_id,
        inbound_message_id=result.inbound_message_id,
        handoff_id=result.handoff_id,
        intent=result.intent.value if result.intent is not None else None,
        handoff_required=result.handoff_required,
        opt_out_detected=result.opt_out_detected,
        signal_queued=result.signal_queued,
        review_tag_applied=result.review_tag_applied,
        review_notification_sent=result.review_notification_sent,
        review_notification_recipient=result.review_notification_recipient,
        review_notification_failure_reason=result.review_notification_failure_reason,
        continue_ai_status=(
            result.continue_ai_status.value if result.continue_ai_status is not None else None
        ),
        continue_ai_outbound_message_id=result.continue_ai_outbound_message_id,
        continue_ai_provider_message_id=result.continue_ai_provider_message_id,
        continue_ai_pause_reason=result.continue_ai_pause_reason,
        reasons=[reason.value for reason in result.reasons],
        classification_reasons=[reason.value for reason in result.classification_reasons],
    )


async def _handle_inbound_email_message(
    workspace_id: UUID,
    provider: str,
    payload: SendGridInboundParsePayload | MailgunInboundParsePayload,
    payload_redacted: dict[str, object],
    bundle: InboundServiceBundle,
) -> InboundWebhookResponse:
    body = payload.body.strip()
    from_email_address = payload.from_email_address
    to_email_address = payload.to_email_address
    thread_message_ids = payload.thread_message_ids
    has_reply_routing_token = False
    if not body:
        _log_email_inbound_rejected(
            workspace_id=workspace_id,
            provider=provider,
            payload=payload,
            reason="empty_body",
            body_length=0,
            from_email_address=from_email_address,
            to_email_address=to_email_address,
            thread_message_ids_count=len(thread_message_ids),
        )
        return InboundWebhookResponse(status="rejected", reasons=["empty_body"])
    if to_email_address is None:
        _log_email_inbound_rejected(
            workspace_id=workspace_id,
            provider=provider,
            payload=payload,
            reason="invalid_to_address",
            body_length=len(body),
            from_email_address=from_email_address,
            to_email_address=to_email_address,
            thread_message_ids_count=len(thread_message_ids),
        )
        return InboundWebhookResponse(status="rejected", reasons=["invalid_to_address"])
    contact_policy = await bundle.workspace_contact_policy_repository.get_by_workspace_id(
        workspace_id,
    )
    configured_inbound_email_address = None
    reply_routing_token = None
    if contact_policy is not None and contact_policy.inbound_email_address is not None:
        configured_inbound_email_address = contact_policy.inbound_email_address.strip().lower()
    if configured_inbound_email_address is not None:
        recipient_matches_inbound_address, reply_routing_token = _match_inbound_email_recipient(
            to_email_address=to_email_address,
            configured_inbound_email_address=configured_inbound_email_address,
        )
        has_reply_routing_token = reply_routing_token is not None
        if not recipient_matches_inbound_address:
            _log_email_inbound_rejected(
                workspace_id=workspace_id,
                provider=provider,
                payload=payload,
                reason="inbound_email_address_mismatch",
                body_length=len(body),
                from_email_address=from_email_address,
                to_email_address=to_email_address,
                configured_inbound_email_address=configured_inbound_email_address,
                thread_message_ids_count=len(thread_message_ids),
                has_reply_routing_token=has_reply_routing_token,
            )
            return InboundWebhookResponse(
                status="rejected",
                reasons=["inbound_email_address_mismatch"],
            )
    if from_email_address is None:
        _log_email_inbound_rejected(
            workspace_id=workspace_id,
            provider=provider,
            payload=payload,
            reason="invalid_from_address",
            body_length=len(body),
            from_email_address=from_email_address,
            to_email_address=to_email_address,
            configured_inbound_email_address=configured_inbound_email_address,
            thread_message_ids_count=len(thread_message_ids),
            has_reply_routing_token=has_reply_routing_token,
        )
        return InboundWebhookResponse(status="rejected", reasons=["invalid_from_address"])
    (
        lead,
        lead_resolution,
        matched_thread_message_id,
        matched_reply_routing_token,
    ) = await _resolve_inbound_email_lead(
        workspace_id=workspace_id,
        provider=provider,
        payload=payload,
        reply_routing_token=reply_routing_token,
        bundle=bundle,
    )
    if lead is None:
        _log_email_inbound_rejected(
            workspace_id=workspace_id,
            provider=provider,
            payload=payload,
            reason=lead_resolution,
            body_length=len(body),
            from_email_address=from_email_address,
            to_email_address=to_email_address,
            configured_inbound_email_address=configured_inbound_email_address,
            thread_message_ids_count=len(thread_message_ids),
            matched_thread_message_id=matched_thread_message_id,
            has_reply_routing_token=has_reply_routing_token,
            matched_reply_routing_token=matched_reply_routing_token,
        )
        return InboundWebhookResponse(status="rejected", reasons=[lead_resolution])
    logger.info(
        "email_inbound_prechecks_passed",
        workspace_id=str(workspace_id),
        provider=provider,
        provider_message_id=payload.provider_message_id,
        body_length=len(body),
        from_address_redacted=_redact_email_address(from_email_address),
        to_address_redacted=_redact_email_address(to_email_address),
        configured_inbound_address_redacted=_redact_email_address(configured_inbound_email_address),
        lead_found=True,
        lead_resolution=lead_resolution,
        thread_message_ids_count=len(thread_message_ids),
        matched_thread_message_id=matched_thread_message_id,
        has_reply_routing_token=has_reply_routing_token,
        matched_reply_routing_token=matched_reply_routing_token,
    )
    return await _handle_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=workspace_id,
            provider=provider,
            provider_event_id=payload.provider_message_id or "",
            provider_message_id=payload.provider_message_id or "",
            crm_lead_id=lead.crm_lead_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.EMAIL,
            body=body,
            received_at=datetime.now(UTC),
            email_subject=payload.subject,
            from_address_redacted=_redact_email_address(from_email_address),
            to_address_redacted=_redact_email_address(to_email_address),
            payload_redacted=payload_redacted,
        ),
        bundle=bundle,
        now=datetime.now(UTC),
    )


async def _resolve_inbound_email_lead(
    *,
    workspace_id: UUID,
    provider: str,
    payload: SendGridInboundParsePayload | MailgunInboundParsePayload,
    reply_routing_token: str | None,
    bundle: InboundServiceBundle,
) -> tuple[CanonicalLeadRecord | None, str, str | None, bool]:
    from_email_address = payload.from_email_address
    if reply_routing_token is not None:
        outbound_message = await bundle.message_repository.get_by_reply_routing_token(
            workspace_id,
            reply_routing_token,
        )
        if outbound_message is None:
            return None, "reply_token_not_found", None, False
        lead = await bundle.lead_repository.get_by_id(workspace_id, outbound_message.lead_id)
        if lead is None:
            return None, "lead_not_found", None, True
        if _normalized_email_value(lead.primary_email) != _normalized_email_value(
            from_email_address
        ):
            return None, "reply_sender_mismatch", None, True
        return lead, "reply_token", None, True

    for thread_message_id in payload.thread_message_ids:
        outbound_message_id = parse_outbound_email_message_id(thread_message_id)
        if outbound_message_id is not None:
            outbound_message = await bundle.message_repository.get_by_id(
                workspace_id,
                outbound_message_id,
            )
            if outbound_message is not None:
                lead = await bundle.lead_repository.get_by_id(
                    workspace_id,
                    outbound_message.lead_id,
                )
                if lead is not None:
                    return lead, "thread_reference", thread_message_id, False
        outbound_message = await bundle.message_repository.get_by_provider_message_id_for_workspace(
            workspace_id,
            provider,
            thread_message_id,
        )
        if outbound_message is None:
            continue
        lead = await bundle.lead_repository.get_by_id(workspace_id, outbound_message.lead_id)
        if lead is not None:
            return lead, "thread_reference", thread_message_id, False

    if from_email_address is None:
        return None, "invalid_from_address", None, False

    candidates = await bundle.lead_repository.list_by_primary_email(
        workspace_id,
        from_email_address,
    )
    if len(candidates) == 1:
        return candidates[0], "sender_email", None, False
    if len(candidates) > 1:
        return None, "ambiguous_lead_match", None, False
    return None, "lead_not_found", None, False


def _match_inbound_email_recipient(
    *,
    to_email_address: str,
    configured_inbound_email_address: str,
) -> tuple[bool, str | None]:
    actual_local_part, actual_separator, actual_domain = to_email_address.partition("@")
    configured_local_part, configured_separator, configured_domain = (
        configured_inbound_email_address.partition("@")
    )
    if not actual_separator or not configured_separator:
        return False, None
    if actual_domain != configured_domain:
        return False, None
    if actual_local_part == configured_local_part:
        return True, None
    token_prefix = f"{configured_local_part}+"
    if not actual_local_part.startswith(token_prefix):
        return False, None
    reply_routing_token = actual_local_part[len(token_prefix) :]
    return (bool(reply_routing_token), reply_routing_token or None)


def _normalized_email_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


@router.post(
    "/follow-up-boss/inbound-messages",
    response_model=InboundWebhookResponse,
)
async def receive_follow_up_boss_inbound_message(
    request: FollowUpBossInboundMessageRequest,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
) -> InboundWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(request.workspace_id))
    return await _handle_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=request.workspace_id,
            provider=CRMProvider.FOLLOW_UP_BOSS.value,
            provider_event_id=request.provider_event_id,
            provider_message_id=request.provider_message_id,
            crm_lead_id=request.crm_lead_id,
            channel=request.channel,
            body=request.body,
            received_at=request.received_at,
            from_address_redacted=request.from_address_redacted,
            to_address_redacted=request.to_address_redacted,
            payload_redacted=request.payload_redacted,
        ),
        bundle=bundle,
        now=datetime.now(UTC),
    )


@router.post(
    "/twilio/inbound-messages/{workspace_id}",
    response_model=InboundWebhookResponse,
)
async def receive_twilio_inbound_message(
    workspace_id: UUID,
    request: Request,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    form = await request.form()
    form_values = {key: str(value) for key, value in form.multi_items()}
    _verify_twilio_signature_if_configured(
        request=request,
        settings=settings,
        form_values=form_values,
    )
    payload = _validate_twilio_inbound_payload(form_values)
    if not payload.body.strip():
        return InboundWebhookResponse(status="rejected", reasons=["empty_body"])
    if not _twilio_inbound_destination_allowed(payload=payload, settings=settings):
        return InboundWebhookResponse(status="rejected", reasons=["destination_phone_mismatch"])
    lead = await bundle.lead_repository.get_by_primary_phone(workspace_id, payload.from_phone)
    if lead is None:
        return InboundWebhookResponse(status="rejected", reasons=["lead_not_found"])
    return await _handle_inbound_message_event(
        event=InboundMessageEvent(
            workspace_id=workspace_id,
            provider="twilio",
            provider_event_id=payload.provider_message_id,
            provider_message_id=payload.provider_message_id,
            crm_lead_id=lead.crm_lead_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            channel=ContactChannel.SMS,
            body=payload.body,
            received_at=datetime.now(UTC),
            from_address_redacted=_redact_phone_number(payload.from_phone),
            to_address_redacted=_redact_phone_number(payload.to_phone),
            payload_redacted=_twilio_inbound_payload_redacted(payload),
        ),
        bundle=bundle,
        now=datetime.now(UTC),
    )


@router.post(
    "/sendgrid/inbound-messages/{workspace_id}",
    response_model=InboundWebhookResponse,
)
async def receive_sendgrid_inbound_message(
    workspace_id: UUID,
    request: Request,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    body = await request.body()
    _verify_sendgrid_signature_if_configured(
        request=request,
        settings=settings,
        body=body,
    )
    form = await request.form()
    payload = _validate_sendgrid_inbound_payload(_string_form_values(form))
    return await _handle_inbound_email_message(
        workspace_id=workspace_id,
        provider="sendgrid",
        payload=payload,
        payload_redacted=_sendgrid_inbound_payload_redacted(payload),
        bundle=bundle,
    )


@router.post(
    "/mailgun/inbound-messages/{workspace_id}",
    response_model=InboundWebhookResponse,
)
async def receive_mailgun_inbound_message(
    workspace_id: UUID,
    request: Request,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InboundWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    form = await request.form()
    form_values = _string_form_values(form)
    logger.info(
        "mailgun_inbound_received",
        workspace_id=str(workspace_id),
        form_field_names=sorted(form_values.keys()),
        has_sender=bool(form_values.get("sender")),
        has_from=bool(form_values.get("from")),
        has_recipient=bool(form_values.get("recipient")),
        has_subject=bool(form_values.get("subject")),
        has_message_id=bool((form_values.get("Message-Id") or "").strip()),
        has_in_reply_to=bool((form_values.get("In-Reply-To") or "").strip()),
        has_references=bool((form_values.get("References") or "").strip()),
        has_stripped_text=bool((form_values.get("stripped-text") or "").strip()),
        has_body_plain=bool((form_values.get("body-plain") or "").strip()),
        has_stripped_html=bool((form_values.get("stripped-html") or "").strip()),
        has_body_html=bool((form_values.get("body-html") or "").strip()),
        has_signature=bool(form_values.get("signature")),
        has_timestamp=bool(form_values.get("timestamp")),
        has_token=bool(form_values.get("token")),
    )
    _verify_mailgun_signature_if_configured(
        settings=settings,
        form_values=form_values,
    )
    payload = _validate_mailgun_inbound_payload(form_values)
    logger.info(
        "mailgun_inbound_payload_parsed",
        workspace_id=str(workspace_id),
        provider_message_id=payload.provider_message_id,
        body_length=len(payload.body.strip()),
        subject_present=payload.subject is not None,
        attachments=payload.attachments,
        thread_message_ids_count=len(payload.thread_message_ids),
        has_stripped_text=bool((payload.stripped_text or "").strip()),
        has_body_plain=bool((payload.body_plain or "").strip()),
        has_stripped_html=bool((payload.stripped_html or "").strip()),
        has_body_html=bool((payload.body_html or "").strip()),
        from_address_redacted=_redact_email_address(payload.from_email_address),
        to_address_redacted=_redact_email_address(payload.to_email_address),
    )
    return await _handle_inbound_email_message(
        workspace_id=workspace_id,
        provider="mailgun",
        payload=payload,
        payload_redacted=_mailgun_inbound_payload_redacted(payload),
        bundle=bundle,
    )


@router.post(
    "/follow-up-boss/human-activity-events",
    response_model=CRMHumanActivityWebhookResponse,
)
async def receive_follow_up_boss_human_activity_event(
    request: FollowUpBossCRMHumanActivityRequest,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
) -> CRMHumanActivityWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(request.workspace_id))
    result = await process_crm_human_activity_event(
        event=CRMHumanActivityEvent(
            workspace_id=request.workspace_id,
            provider=CRMProvider.FOLLOW_UP_BOSS.value,
            provider_event_id=request.provider_event_id,
            crm_lead_id=request.crm_lead_id,
            occurred_at=request.occurred_at,
            event_type=request.event_type,
            activity_type=request.activity_type,
            crm_activity_id=request.crm_activity_id,
            actor_agent_id=request.actor_agent_id,
            changed_field=request.changed_field,
            previous_value_redacted=request.previous_value_redacted,
            new_value_redacted=request.new_value_redacted,
            payload_redacted=request.payload_redacted,
        ),
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    return CRMHumanActivityWebhookResponse(
        status=result.status.value,
        external_event_id=result.external_event_id,
        lead_id=result.lead_id,
        workflow_id=result.workflow_id,
        workflow_transition_id=result.workflow_transition_id,
        activity_kind=result.activity_kind.value if result.activity_kind is not None else None,
        pause_reason=result.pause_reason,
        pause_requested=result.pause_requested,
        signal_queued=result.signal_queued,
        transition_skip_reason=result.transition_skip_reason,
        reasons=[reason.value for reason in result.reasons],
    )


@router.post(
    "/follow-up-boss/suppression-events",
    response_model=ContactSuppressionWebhookResponse,
)
async def receive_follow_up_boss_contact_suppression_event(
    request: FollowUpBossContactSuppressionRequest,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
) -> ContactSuppressionWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(request.workspace_id))
    result = await process_contact_suppression_event(
        event=ContactSuppressionEvent(
            workspace_id=request.workspace_id,
            source_provider=request.source_provider,
            provider_event_id=request.provider_event_id,
            crm_provider=CRMProvider.FOLLOW_UP_BOSS,
            crm_lead_id=request.crm_lead_id,
            suppression_kind=request.suppression_kind,
            occurred_at=request.occurred_at,
            provider_message_id=request.provider_message_id,
            payload_redacted=request.payload_redacted,
        ),
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        workspace_contact_policy_repository=bundle.workspace_contact_policy_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    return ContactSuppressionWebhookResponse(
        status=result.status.value,
        external_event_id=result.external_event_id,
        lead_id=result.lead_id,
        workflow_id=result.workflow_id,
        workflow_transition_id=result.workflow_transition_id,
        suppression_kind=(
            result.suppression_kind.value if result.suppression_kind is not None else None
        ),
        workflow_state=result.workflow_state.value if result.workflow_state is not None else None,
        suppression_applied=result.suppression_applied,
        signal_queued=result.signal_queued,
        transition_skip_reason=result.transition_skip_reason,
        reasons=[reason.value for reason in result.reasons],
    )


@router.post(
    "/crm/follow-up-boss/{workspace_id}",
    response_model=FollowUpBossWebhookResponse,
)
async def receive_follow_up_boss_crm_webhook(
    workspace_id: UUID,
    request: Request,
    handler: Annotated[
        FollowUpBossWebhookEventHandler,
        Depends(get_follow_up_boss_webhook_event_handler),
    ],
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FollowUpBossWebhookResponse:
    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    body = await request.body()
    _verify_follow_up_boss_signature_if_configured(
        request=request,
        settings=settings,
        body=body,
    )
    payload = json.loads(body)
    now = datetime.now(UTC)
    result = await handler.handle(workspace_id, payload, now)
    await bundle.session.commit()
    return FollowUpBossWebhookResponse(
        status=result.status,
        external_event_id=result.external_event_id,
        event_type=result.event_type,
        processed_count=result.processed_count,
        ignored_count=result.ignored_count,
        duplicate_count=result.duplicate_count,
        reasons=result.reasons,
    )


@router.post(
    "/twilio/message-status",
    response_model=ProviderDeliveryWebhookResponse,
)
async def receive_twilio_message_status_callback(
    request: Request,
    bundle: Annotated[
        ProviderDeliveryServiceBundle,
        Depends(get_provider_delivery_service_bundle),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderDeliveryWebhookResponse:
    await enable_postgres_service_access(bundle.session)
    form = await request.form()
    form_values = {key: str(value) for key, value in form.multi_items()}
    _verify_twilio_signature_if_configured(
        request=request,
        settings=settings,
        form_values=form_values,
    )
    payload = _validate_twilio_payload(form_values)
    callback = ProviderDeliveryCallback(
        provider="twilio",
        provider_event_id=_twilio_provider_event_id(payload),
        provider_message_id=payload.provider_message_id,
        event_type=payload.message_status,
        status=_map_twilio_delivery_status(payload.message_status),
        occurred_at=datetime.now(UTC),
        failure_reason=payload.error_message or payload.error_code,
        payload_redacted=_twilio_payload_redacted(payload),
    )
    result = await process_provider_delivery_callback(
        callback=callback,
        message_repository=bundle.message_repository,
        provider_message_event_repository=bundle.provider_message_event_repository,
        reconciliation_repository=bundle.reconciliation_repository,
        occurrence_repository=bundle.occurrence_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
        event_bus=bundle.event_bus,
        now=datetime.now(UTC),
    )
    await bundle.session.commit()
    return _provider_delivery_response((result,))


@router.post(
    "/sendgrid/message-events",
    response_model=ProviderDeliveryWebhookResponse,
)
async def receive_sendgrid_message_events(
    request: Request,
    bundle: Annotated[
        ProviderDeliveryServiceBundle,
        Depends(get_provider_delivery_service_bundle),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderDeliveryWebhookResponse:
    await enable_postgres_service_access(bundle.session)
    body = await request.body()
    _verify_sendgrid_signature_if_configured(
        request=request,
        settings=settings,
        body=body,
    )
    payloads = _validate_sendgrid_payload(body)
    now = datetime.now(UTC)
    results: list[ProviderDeliveryWebhookResult | ProcessProviderDeliveryCallbackResult] = []
    for payload in payloads:
        if payload.event not in {"processed", "deferred", "delivered", "bounce", "dropped"}:
            results.append(
                ProviderDeliveryWebhookResult(
                    status=ProcessProviderDeliveryCallbackStatus.IGNORED.value,
                    reasons=[f"unsupported_event_type:{payload.event}"],
                )
            )
            continue
        provider_message_id = _sendgrid_provider_message_id(payload)
        if provider_message_id is None:
            results.append(
                ProviderDeliveryWebhookResult(
                    status=ProcessProviderDeliveryCallbackStatus.IGNORED.value,
                    reasons=["provider_message_id_missing"],
                )
            )
            continue
        results.append(
            await process_provider_delivery_callback(
                callback=ProviderDeliveryCallback(
                    provider="sendgrid",
                    provider_event_id=_sendgrid_provider_event_id(payload, provider_message_id),
                    provider_message_id=provider_message_id,
                    event_type=payload.event,
                    status=_map_sendgrid_delivery_status(payload.event),
                    occurred_at=datetime.fromtimestamp(payload.timestamp, UTC),
                    failure_reason=payload.reason,
                    payload_redacted=_sendgrid_payload_redacted(payload, provider_message_id),
                ),
                message_repository=bundle.message_repository,
                provider_message_event_repository=bundle.provider_message_event_repository,
                reconciliation_repository=bundle.reconciliation_repository,
                occurrence_repository=bundle.occurrence_repository,
                lead_workflow_repository=bundle.lead_workflow_repository,
                temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
                event_bus=bundle.event_bus,
                now=now,
            )
        )
    await bundle.session.commit()
    return _provider_delivery_response(results)


@router.post(
    "/mailgun/message-events/{workspace_id}",
    response_model=ProviderDeliveryWebhookResponse,
)
async def receive_mailgun_message_events(
    workspace_id: UUID,
    request: Request,
    bundle: Annotated[
        ProviderDeliveryServiceBundle,
        Depends(get_provider_delivery_service_bundle),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProviderDeliveryWebhookResponse:
    await enable_postgres_service_access(bundle.session)
    body = await request.body()
    payload = _validate_mailgun_payload(body)
    _verify_mailgun_delivery_signature_if_configured(
        settings=settings,
        payload=payload,
    )
    results: list[ProviderDeliveryWebhookResult | ProcessProviderDeliveryCallbackResult] = []
    if payload.event not in {"delivered", "failed", "bounced", "rejected", "complained"}:
        results.append(
            ProviderDeliveryWebhookResult(
                status=ProcessProviderDeliveryCallbackStatus.IGNORED.value,
                reasons=[f"unsupported_event_type:{payload.event}"],
            )
        )
    else:
        provider_message_id = payload.provider_message_id
        if provider_message_id is None:
            results.append(
                ProviderDeliveryWebhookResult(
                    status=ProcessProviderDeliveryCallbackStatus.IGNORED.value,
                    reasons=["provider_message_id_missing"],
                )
            )
        else:
            results.append(
                await process_provider_delivery_callback(
                    callback=ProviderDeliveryCallback(
                        provider="mailgun",
                        provider_event_id=_mailgun_provider_event_id(payload, provider_message_id),
                        provider_message_id=provider_message_id,
                        event_type=payload.event,
                        status=_map_mailgun_delivery_status(payload.event, payload.severity),
                        occurred_at=datetime.fromtimestamp(payload.timestamp, UTC),
                        failure_reason=payload.failure_reason,
                        payload_redacted=_mailgun_payload_redacted(payload, provider_message_id),
                    ),
                    message_repository=bundle.message_repository,
                    provider_message_event_repository=bundle.provider_message_event_repository,
                    reconciliation_repository=bundle.reconciliation_repository,
                    occurrence_repository=bundle.occurrence_repository,
                    lead_workflow_repository=bundle.lead_workflow_repository,
                    temporal_signal_outbox_repository=bundle.temporal_signal_outbox_repository,
                    event_bus=bundle.event_bus,
                    now=datetime.now(UTC),
                )
            )
    await bundle.session.commit()
    return _provider_delivery_response(results)


def _validate_twilio_payload(form_values: dict[str, str]) -> TwilioMessageStatusCallbackPayload:
    try:
        return TwilioMessageStatusCallbackPayload.model_validate(form_values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _validate_twilio_inbound_payload(form_values: dict[str, str]) -> TwilioInboundMessagePayload:
    try:
        return TwilioInboundMessagePayload.model_validate(form_values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _validate_sendgrid_inbound_payload(form_values: dict[str, str]) -> SendGridInboundParsePayload:
    try:
        return SendGridInboundParsePayload.model_validate(form_values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _validate_sendgrid_payload(body: bytes) -> tuple[SendGridEventWebhookPayload, ...]:
    try:
        raw_payload = json.loads(body)
        return TypeAdapter(tuple[SendGridEventWebhookPayload, ...]).validate_python(raw_payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_json_payload",
        ) from exc
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _verify_twilio_signature_if_configured(
    *,
    request: Request,
    settings: Settings,
    form_values: dict[str, str],
) -> None:
    auth_token = settings.twilio_auth_token
    if auth_token is None:
        return
    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_twilio_signature"
        )
    validator = RequestValidator(auth_token.get_secret_value())
    if not validator.validate(str(request.url), form_values, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_twilio_signature"
        )


def _verify_follow_up_boss_signature_if_configured(
    *,
    request: Request,
    settings: Settings,
    body: bytes,
) -> None:
    system_key = settings.fub_system_key
    if system_key is None or not system_key.get_secret_value():
        return
    signature = request.headers.get("FUB-Signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_fub_signature"
        )
    # Per FUB webhooks guide: HMAC-SHA256 of the base64-encoded raw JSON body,
    # keyed with the X-System-Key issued at system registration.
    expected = hmac.new(
        system_key.get_secret_value().encode("utf-8"),
        base64.b64encode(body),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_fub_signature"
        )


def _verify_sendgrid_signature_if_configured(
    *,
    request: Request,
    settings: Settings,
    body: bytes,
) -> None:
    public_key = settings.sendgrid_event_webhook_public_key
    if public_key is None:
        return
    signature = request.headers.get("X-Twilio-Email-Event-Webhook-Signature")
    timestamp = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp")
    if not signature or not timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_sendgrid_signature"
        )
    event_webhook = EventWebhook()
    try:
        event_webhook.convert_public_key_to_ecdsa(public_key.get_secret_value()).verify(
            base64.b64decode(signature),
            timestamp.encode("utf-8") + body,
            ec.ECDSA(hashes.SHA256()),
        )
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_sendgrid_signature"
        ) from exc


def _twilio_provider_event_id(payload: TwilioMessageStatusCallbackPayload) -> str:
    error_code = payload.error_code or "none"
    return f"{payload.provider_message_id}:{payload.message_status}:{error_code}"


def _sendgrid_provider_event_id(
    payload: SendGridEventWebhookPayload,
    provider_message_id: str,
) -> str:
    if payload.sg_event_id:
        return payload.sg_event_id
    return f"{provider_message_id}:{payload.event}:{payload.timestamp}"


def _map_twilio_delivery_status(message_status: str) -> ProviderDeliveryStatus:
    normalized = message_status.strip().lower()
    if normalized in {"queued", "accepted", "sending", "sent"}:
        return ProviderDeliveryStatus.ACCEPTED
    if normalized == "delivered":
        return ProviderDeliveryStatus.DELIVERED
    if normalized == "failed":
        return ProviderDeliveryStatus.FAILED
    if normalized == "undelivered":
        return ProviderDeliveryStatus.UNDELIVERED
    return ProviderDeliveryStatus.UNKNOWN


def _map_sendgrid_delivery_status(event: str) -> ProviderDeliveryStatus:
    normalized = event.strip().lower()
    if normalized == "processed":
        return ProviderDeliveryStatus.ACCEPTED
    if normalized == "deferred":
        return ProviderDeliveryStatus.DEFERRED
    if normalized == "delivered":
        return ProviderDeliveryStatus.DELIVERED
    if normalized == "bounce":
        return ProviderDeliveryStatus.BOUNCED
    if normalized == "dropped":
        return ProviderDeliveryStatus.DROPPED
    return ProviderDeliveryStatus.UNKNOWN


def _sendgrid_provider_message_id(payload: SendGridEventWebhookPayload) -> str | None:
    if payload.sg_message_id:
        return payload.sg_message_id.split(".", 1)[0]
    if payload.smtp_id and payload.smtp_id.startswith("<") and "@" in payload.smtp_id:
        return payload.smtp_id[1:].split("@", 1)[0]
    return None


def _twilio_payload_redacted(
    payload: TwilioMessageStatusCallbackPayload,
) -> dict[str, object]:
    return {
        "message_status": payload.message_status,
        "error_code": payload.error_code,
        "error_message": payload.error_message,
    }


def _twilio_inbound_payload_redacted(payload: TwilioInboundMessagePayload) -> dict[str, object]:
    return {
        "provider_message_id": payload.provider_message_id,
        "num_media": payload.num_media,
        "account_sid_present": payload.account_sid is not None,
    }


def _sendgrid_inbound_payload_redacted(payload: SendGridInboundParsePayload) -> dict[str, object]:
    return {
        "provider_message_id": payload.provider_message_id,
        "subject_present": payload.subject is not None,
        "attachments": payload.attachments,
        "attachment_info_present": payload.attachment_info is not None,
        "charsets_present": payload.charsets is not None,
        "sender_ip_present": payload.sender_ip is not None,
        "spam_score": payload.spam_score,
    }


def _twilio_inbound_destination_allowed(
    *,
    payload: TwilioInboundMessagePayload,
    settings: Settings,
) -> bool:
    configured_from_phone = settings.twilio_from_phone.strip()
    if not configured_from_phone:
        return True
    return _normalized_phone_digits(payload.to_phone) == _normalized_phone_digits(
        configured_from_phone
    )


def _redact_phone_number(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    digits_only = _normalized_phone_digits(phone_number)
    if not digits_only:
        return "***"
    return f"***{digits_only[-4:]}" if len(digits_only) >= 4 else "***"


def _normalized_phone_digits(phone_number: str) -> str:
    return "".join(character for character in phone_number if character.isdigit())


def _redact_email_address(email_address: str | None) -> str | None:
    if email_address is None:
        return None
    _, parsed_address = parseaddr(email_address)
    normalized = parsed_address.strip().lower()
    if not normalized or "@" not in normalized:
        return "***"
    _, domain = normalized.split("@", 1)
    return f"***@{domain}"


def _string_form_values(form: FormData) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in form.multi_items():
        if isinstance(value, UploadFile):
            continue
        values[str(key)] = str(value)
    return values


def _sendgrid_payload_redacted(
    payload: SendGridEventWebhookPayload,
    provider_message_id: str,
) -> dict[str, object]:
    return {
        "event": payload.event,
        "provider_message_id": provider_message_id,
        "sg_event_id": payload.sg_event_id,
        "reason": payload.reason,
        "response": payload.response,
        "status": payload.status,
    }


def _provider_delivery_response(
    results: tuple[ProcessProviderDeliveryCallbackResult, ...]
    | list[ProcessProviderDeliveryCallbackResult | ProviderDeliveryWebhookResult],
) -> ProviderDeliveryWebhookResponse:
    serialized: list[ProviderDeliveryWebhookResult] = []
    processed_count = 0
    duplicate_count = 0
    ignored_count = 0
    for result in results:
        if isinstance(result, ProviderDeliveryWebhookResult):
            serialized.append(result)
            if result.status == ProcessProviderDeliveryCallbackStatus.IGNORED.value:
                ignored_count += 1
            continue
        serialized.append(
            ProviderDeliveryWebhookResult(
                status=result.status.value,
                provider_event_id=result.provider_event_id,
                message_id=result.message_id,
                provider_delivery_status=(
                    result.provider_delivery_status.value
                    if result.provider_delivery_status is not None
                    else None
                ),
                reasons=[reason.value for reason in result.reasons],
            )
        )
        if result.status == ProcessProviderDeliveryCallbackStatus.PROCESSED:
            processed_count += 1
        elif result.status == ProcessProviderDeliveryCallbackStatus.DUPLICATE:
            duplicate_count += 1
        else:
            ignored_count += 1
    return ProviderDeliveryWebhookResponse(
        processed_count=processed_count,
        duplicate_count=duplicate_count,
        ignored_count=ignored_count,
        results=serialized,
    )


def _validate_mailgun_inbound_payload(
    form_values: dict[str, str],
) -> MailgunInboundParsePayload:
    try:
        return MailgunInboundParsePayload.model_validate(form_values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _validate_mailgun_payload(body: bytes) -> MailgunEventWebhookPayload:
    try:
        raw_payload = json.loads(body)
        return TypeAdapter(MailgunEventWebhookPayload).validate_python(raw_payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_json_payload",
        ) from exc
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _verify_mailgun_signature_if_configured(
    *,
    settings: Settings,
    form_values: dict[str, str],
) -> None:
    signing_key = settings.mailgun_webhook_signing_key
    if signing_key is None:
        return
    token = form_values.get("token")
    timestamp = form_values.get("timestamp")
    signature = form_values.get("signature")
    if not token or not timestamp or not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_mailgun_signature"
        )
    expected = hmac.new(
        signing_key.get_secret_value().encode(),
        f"{timestamp}{token}".encode(),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_mailgun_signature"
        )


def _verify_mailgun_delivery_signature_if_configured(
    *,
    settings: Settings,
    payload: MailgunEventWebhookPayload,
) -> None:
    signing_key = settings.mailgun_webhook_signing_key
    if signing_key is None:
        return
    signature = payload.signature
    if not isinstance(signature, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_mailgun_signature"
        )
    token = signature.get("token")
    timestamp = signature.get("timestamp")
    signature_value = signature.get("signature")
    if not token or not timestamp or not signature_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_mailgun_signature"
        )
    expected = hmac.new(
        signing_key.get_secret_value().encode(),
        f"{timestamp}{token}".encode(),
        sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(signature_value)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_mailgun_signature"
        )


def _mailgun_provider_event_id(
    payload: MailgunEventWebhookPayload,
    provider_message_id: str,
) -> str:
    if payload.id:
        return payload.id
    return f"{provider_message_id}:{payload.event}:{payload.timestamp}"


def _map_mailgun_delivery_status(event: str, severity: str | None) -> ProviderDeliveryStatus:
    normalized = event.strip().lower()
    if normalized in {"accepted", "stored"}:
        return ProviderDeliveryStatus.ACCEPTED
    if normalized == "delivered":
        return ProviderDeliveryStatus.DELIVERED
    if normalized == "failed":
        if severity and severity.strip().lower() == "temporary":
            return ProviderDeliveryStatus.DEFERRED
        return ProviderDeliveryStatus.FAILED
    if normalized == "bounced":
        return ProviderDeliveryStatus.BOUNCED
    if normalized == "rejected":
        return ProviderDeliveryStatus.DROPPED
    if normalized == "complained":
        return ProviderDeliveryStatus.FAILED
    return ProviderDeliveryStatus.UNKNOWN


def _mailgun_inbound_payload_redacted(
    payload: MailgunInboundParsePayload,
) -> dict[str, object]:
    return {
        "provider_message_id": payload.provider_message_id,
        "subject_present": payload.subject is not None,
        "attachments": payload.attachments,
    }


def _mailgun_payload_redacted(
    payload: MailgunEventWebhookPayload,
    provider_message_id: str,
) -> dict[str, object]:
    return {
        "event": payload.event,
        "provider_message_id": provider_message_id,
        "severity": payload.severity,
        "recipient": payload.recipient,
    }


def _log_email_inbound_rejected(
    *,
    workspace_id: UUID,
    provider: str,
    payload: SendGridInboundParsePayload | MailgunInboundParsePayload,
    reason: str,
    body_length: int,
    from_email_address: str | None,
    to_email_address: str | None,
    configured_inbound_email_address: str | None = None,
    thread_message_ids_count: int = 0,
    matched_thread_message_id: str | None = None,
    has_reply_routing_token: bool = False,
    matched_reply_routing_token: bool = False,
) -> None:
    logger.warning(
        "email_inbound_rejected",
        workspace_id=str(workspace_id),
        provider=provider,
        reason=reason,
        provider_message_id=payload.provider_message_id,
        body_length=body_length,
        subject_present=payload.subject is not None,
        from_address_redacted=_redact_email_address(from_email_address),
        to_address_redacted=_redact_email_address(to_email_address),
        configured_inbound_address_redacted=_redact_email_address(configured_inbound_email_address),
        thread_message_ids_count=thread_message_ids_count,
        matched_thread_message_id=matched_thread_message_id,
        has_reply_routing_token=has_reply_routing_token,
        matched_reply_routing_token=matched_reply_routing_token,
    )
