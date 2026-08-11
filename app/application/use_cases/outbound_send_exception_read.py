import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.application.ports.repositories import (
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
)
from app.domain.campaigns.outbound_provider_failure import OutboundProviderFailure
from app.domain.campaigns.outbound_send_reconciliation import OutboundSendReconciliation
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.common.ids import WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import AuthenticatedActor
from app.domain.identity.permissions import PermissionCapability, evaluate_permission

STALE_DISPATCHING_AFTER = timedelta(minutes=15)
DEFAULT_LIMIT = 100
MAX_LIMIT = 100


class OutboundSendExceptionReadStatus(StrEnum):
    OK = "ok"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class OutboundSendExceptionReadReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    REQUEST_NOT_FOUND = "request_not_found"


@dataclass(frozen=True)
class OutboundSendExceptionView:
    request: OutboundSendRequest
    provider_failure: OutboundProviderFailure | None
    reconciliation: OutboundSendReconciliation | None


@dataclass(frozen=True)
class OutboundSendExceptionListResult:
    status: OutboundSendExceptionReadStatus
    exceptions: tuple[OutboundSendExceptionView, ...] = ()
    reasons: tuple[OutboundSendExceptionReadReasonCode, ...] = ()


@dataclass(frozen=True)
class OutboundSendExceptionDetailResult:
    status: OutboundSendExceptionReadStatus
    exception: OutboundSendExceptionView | None = None
    reasons: tuple[OutboundSendExceptionReadReasonCode, ...] = ()


async def list_outbound_send_exceptions(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    request_repository: OutboundSendRequestRepository,
    provider_failure_repository: OutboundProviderFailureRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    status: OutboundSendRequestStatus | None = None,
    channel: ContactChannel | None = None,
    provider_name: str | None = None,
    older_than_minutes: int | None = None,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> OutboundSendExceptionListResult:
    permission = evaluate_permission(
        actor,
        PermissionCapability.VIEW_OUTBOUND_SEND_EXCEPTIONS,
    )
    if not permission.allowed:
        return OutboundSendExceptionListResult(
            status=OutboundSendExceptionReadStatus.REJECTED,
            reasons=(OutboundSendExceptionReadReasonCode.PERMISSION_DENIED,),
        )

    effective_now = now or datetime.now(UTC)
    allowed_statuses = {
        OutboundSendRequestStatus.FAILED,
        OutboundSendRequestStatus.UNCERTAIN,
        OutboundSendRequestStatus.DISPATCHING,
    }
    if status is not None and status not in allowed_statuses:
        return OutboundSendExceptionListResult(status=OutboundSendExceptionReadStatus.OK)
    statuses = (
        (status,)
        if status is not None
        else (
            OutboundSendRequestStatus.FAILED,
            OutboundSendRequestStatus.UNCERTAIN,
            OutboundSendRequestStatus.DISPATCHING,
        )
    )
    older_than = (
        effective_now - timedelta(minutes=older_than_minutes)
        if older_than_minutes is not None
        else None
    )
    requests = await request_repository.list_exceptions(
        workspace_id=workspace_id,
        statuses=statuses,
        stale_before=effective_now - STALE_DISPATCHING_AFTER,
        older_than=older_than,
        channel=channel,
        provider_name=provider_name,
        limit=min(max(limit, 1), MAX_LIMIT),
    )
    return OutboundSendExceptionListResult(
        status=OutboundSendExceptionReadStatus.OK,
        exceptions=tuple(
            await asyncio.gather(
                *(
                    _build_view(
                        request=request,
                        provider_failure_repository=provider_failure_repository,
                        reconciliation_repository=reconciliation_repository,
                    )
                    for request in requests
                )
            )
        ),
    )


async def get_outbound_send_exception(
    *,
    actor: AuthenticatedActor,
    workspace_id: WorkspaceId,
    request_id: UUID,
    request_repository: OutboundSendRequestRepository,
    provider_failure_repository: OutboundProviderFailureRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
) -> OutboundSendExceptionDetailResult:
    permission = evaluate_permission(
        actor,
        PermissionCapability.VIEW_OUTBOUND_SEND_EXCEPTIONS,
    )
    if not permission.allowed:
        return OutboundSendExceptionDetailResult(
            status=OutboundSendExceptionReadStatus.REJECTED,
            reasons=(OutboundSendExceptionReadReasonCode.PERMISSION_DENIED,),
        )

    request = await request_repository.get_by_id(workspace_id, request_id)
    if request is None or not _is_exception_request(request, datetime.now(UTC)):
        return OutboundSendExceptionDetailResult(
            status=OutboundSendExceptionReadStatus.NOT_FOUND,
            reasons=(OutboundSendExceptionReadReasonCode.REQUEST_NOT_FOUND,),
        )
    return OutboundSendExceptionDetailResult(
        status=OutboundSendExceptionReadStatus.OK,
        exception=await _build_view(
            request=request,
            provider_failure_repository=provider_failure_repository,
            reconciliation_repository=reconciliation_repository,
        ),
    )


async def _build_view(
    *,
    request: OutboundSendRequest,
    provider_failure_repository: OutboundProviderFailureRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
) -> OutboundSendExceptionView:
    provider_failure, reconciliation = await asyncio.gather(
        provider_failure_repository.get_by_outbound_message_id(
            request.workspace_id,
            request.outbound_message_id,
        ),
        reconciliation_repository.get_by_id(
            request.workspace_id,
            request.reconciliation_id,
        ),
    )
    return OutboundSendExceptionView(
        request=request,
        provider_failure=provider_failure,
        reconciliation=reconciliation,
    )


def _is_exception_request(request: OutboundSendRequest, now: datetime) -> bool:
    if request.status in {
        OutboundSendRequestStatus.FAILED,
        OutboundSendRequestStatus.UNCERTAIN,
    }:
        return True
    return (
        request.status is OutboundSendRequestStatus.DISPATCHING
        and request.claimed_at is not None
        and request.claimed_at <= now - STALE_DISPATCHING_AFTER
    )