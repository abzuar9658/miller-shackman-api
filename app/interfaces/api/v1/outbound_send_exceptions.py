from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.application.use_cases.outbound_send_exception_read import (
    OutboundSendExceptionReadReasonCode,
    OutboundSendExceptionReadStatus,
    OutboundSendExceptionView,
    get_outbound_send_exception,
    list_outbound_send_exceptions,
)
from app.domain.campaigns.outbound_send_request import OutboundSendRequestStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import AuthenticatedActor
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.outbound_send_exceptions import (
    OutboundSendExceptionReadBundle,
    get_outbound_send_exception_read_bundle,
)
from app.interfaces.api.schemas.attention import (
    OutboundSendExceptionDetailResponse,
    OutboundSendExceptionListResponse,
    OutboundSendExceptionResponse,
)

router = APIRouter(tags=["outbound-send-exceptions"])


@router.get(
    "/{workspace_id}/outbound-send-exceptions",
    response_model=OutboundSendExceptionListResponse,
)
async def list_outbound_send_exceptions_route(
    workspace_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        OutboundSendExceptionReadBundle,
        Depends(get_outbound_send_exception_read_bundle),
    ],
    exception_status: Annotated[OutboundSendRequestStatus | None, Query(alias="status")] = None,
    channel: ContactChannel | None = None,
    provider: str | None = Query(default=None, min_length=1, max_length=50),
    older_than_minutes: Annotated[int | None, Query(ge=1, le=43_200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> OutboundSendExceptionListResponse:
    result = await list_outbound_send_exceptions(
        actor=actor,
        workspace_id=workspace_id,
        request_repository=bundle.request_repository,
        provider_failure_repository=bundle.provider_failure_repository,
        reconciliation_repository=bundle.reconciliation_repository,
        status=exception_status,
        channel=channel,
        provider_name=provider,
        older_than_minutes=older_than_minutes,
        limit=limit,
        now=datetime.now(UTC),
    )
    _raise_for_read_failure(result.status, result.reasons)
    return OutboundSendExceptionListResponse(
        status=result.status.value,
        exceptions=[_response(exception) for exception in result.exceptions],
    )


@router.get(
    "/{workspace_id}/outbound-send-exceptions/{request_id}",
    response_model=OutboundSendExceptionDetailResponse,
)
async def get_outbound_send_exception_route(
    workspace_id: UUID,
    request_id: UUID,
    actor: Annotated[AuthenticatedActor, Depends(get_workspace_actor)],
    bundle: Annotated[
        OutboundSendExceptionReadBundle,
        Depends(get_outbound_send_exception_read_bundle),
    ],
) -> OutboundSendExceptionDetailResponse:
    result = await get_outbound_send_exception(
        actor=actor,
        workspace_id=workspace_id,
        request_id=request_id,
        request_repository=bundle.request_repository,
        provider_failure_repository=bundle.provider_failure_repository,
        reconciliation_repository=bundle.reconciliation_repository,
    )
    _raise_for_read_failure(result.status, result.reasons)
    assert result.exception is not None
    return OutboundSendExceptionDetailResponse(
        status=result.status.value,
        exception=_response(result.exception),
    )


def _raise_for_read_failure(
    read_status: OutboundSendExceptionReadStatus,
    reasons: tuple[OutboundSendExceptionReadReasonCode, ...],
) -> None:
    if read_status == OutboundSendExceptionReadStatus.REJECTED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=[reason.value for reason in reasons],
        )
    if read_status == OutboundSendExceptionReadStatus.NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=[reason.value for reason in reasons],
        )


def _response(view: OutboundSendExceptionView) -> OutboundSendExceptionResponse:
    request = view.request
    provider_failure = view.provider_failure
    reconciliation = view.reconciliation
    return OutboundSendExceptionResponse(
        request_id=request.request_id,
        workspace_id=request.workspace_id,
        lead_id=request.lead_id,
        workflow_id=request.workflow_id,
        outbound_message_id=request.outbound_message_id,
        reconciliation_id=request.reconciliation_id,
        status=request.status.value,
        channel=request.channel.value,
        provider_name=request.provider_name,
        attempt_count=request.attempt_count,
        available_at=request.available_at,
        created_at=request.created_at,
        updated_at=request.updated_at,
        claimed_at=request.claimed_at,
        completed_at=request.completed_at,
        failure_kind=request.failure_kind
        or (provider_failure.failure_kind if provider_failure is not None else None),
        failure_reason=request.failure_reason
        or (provider_failure.failure_reason if provider_failure is not None else None),
        reconciliation_status=reconciliation.status.value if reconciliation is not None else None,
        reconciliation_failure_reason=(
            reconciliation.failure_reason if reconciliation is not None else None
        ),
        provider_failure_status=(
            provider_failure.status.value if provider_failure is not None else None
        ),
        provider_failure_id=provider_failure.failure_id if provider_failure is not None else None,
        first_failed_at=provider_failure.first_failed_at if provider_failure is not None else None,
        last_failed_at=provider_failure.last_failed_at if provider_failure is not None else None,
    )