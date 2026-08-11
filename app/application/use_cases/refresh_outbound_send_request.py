from datetime import datetime

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import LeadRepository, OutboundMessageRepository
from app.application.services.pre_send_crm_refresh import (
    PreSendCRMRefreshContext,
    PreSendCRMRefreshStatus,
    refresh_lead_for_pre_send,
)
from app.application.use_cases.dispatch_outbound_send_requests import (
    OutboundPreDispatchRefreshResult,
)
from app.domain.campaigns.outbound_send_request import OutboundSendRequest


async def refresh_outbound_send_request(
    *,
    request: OutboundSendRequest,
    lead_repository: LeadRepository,
    message_repository: OutboundMessageRepository,
    crm_refresh_context: PreSendCRMRefreshContext,
    event_bus: EventBus | None,
    now: datetime,
) -> OutboundPreDispatchRefreshResult:
    message = await message_repository.get_by_id(
        request.workspace_id,
        request.outbound_message_id,
    )
    if message is None:
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            failure_reason="pre_dispatch_refresh:message_not_found",
        )
    lead = await lead_repository.get_by_id(request.workspace_id, request.lead_id)
    if lead is None:
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=message,
            failure_reason="pre_dispatch_refresh:lead_not_found",
        )

    refresh = await refresh_lead_for_pre_send(
        lead=lead,
        message=message,
        lead_repository=lead_repository,
        message_repository=message_repository,
        crm_refresh_context=crm_refresh_context,
        event_bus=event_bus,
        now=now,
    )
    if refresh.status is PreSendCRMRefreshStatus.FAILED:
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=message,
            failure_reason=(
                "pre_dispatch_refresh:crm_refresh_failed:"
                + (refresh.failure_reason or "unknown")
            ),
            retryable=True,
        )
    if refresh.status is PreSendCRMRefreshStatus.LEAD_NOT_FOUND:
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=message,
            failure_reason="pre_dispatch_refresh:crm_lead_not_found",
        )
    reconciliation = refresh.assignment_reconciliation
    if reconciliation is not None and (
        reconciliation.ownership_changed or reconciliation.pause_requested
    ):
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=message,
            recent_human_activity=refresh.recent_human_activity,
            failure_reason="pre_dispatch_refresh:ownership_changed_or_paused",
        )
    return OutboundPreDispatchRefreshResult(
        allowed=True,
        message=message,
        recent_human_activity=refresh.recent_human_activity,
    )