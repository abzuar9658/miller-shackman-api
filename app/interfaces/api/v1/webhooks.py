from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.use_cases.process_inbound_message_event import (
    InboundMessageEvent,
    process_inbound_message_event,
)
from app.domain.leads import CRMProvider
from app.interfaces.api.dependencies.inbound import InboundServiceBundle, get_inbound_service_bundle
from app.interfaces.api.schemas.inbound import (
    FollowUpBossInboundMessageRequest,
    InboundWebhookResponse,
)

router = APIRouter(tags=["webhooks"])


@router.post(
    "/follow-up-boss/inbound-messages",
    response_model=InboundWebhookResponse,
)
async def receive_follow_up_boss_inbound_message(
    request: FollowUpBossInboundMessageRequest,
    bundle: Annotated[InboundServiceBundle, Depends(get_inbound_service_bundle)],
) -> InboundWebhookResponse:
    result = await process_inbound_message_event(
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
        lead_repository=bundle.lead_repository,
        external_event_repository=bundle.external_event_repository,
        conversation_repository=bundle.conversation_repository,
        inbound_message_repository=bundle.inbound_message_repository,
        conversation_summary_repository=bundle.conversation_summary_repository,
        handoff_repository=bundle.handoff_repository,
        lead_workflow_repository=bundle.lead_workflow_repository,
        workflow_transition_repository=bundle.workflow_transition_repository,
        llm_client=bundle.llm_client,
        now=datetime.now(UTC),
    )
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
        reasons=[reason.value for reason in result.reasons],
        classification_reasons=[reason.value for reason in result.classification_reasons],
    )
