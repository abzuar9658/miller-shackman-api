from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from app.application.ports.repositories import (
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
)
from app.application.use_cases.outbound_send_exception_read import (
    STALE_DISPATCHING_AFTER,
    OutboundSendExceptionReadStatus,
    get_outbound_send_exception,
    list_outbound_send_exceptions,
)
from app.domain.campaigns.outbound_message import ProviderDeliveryStatus
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
from app.domain.compliance.contactability import ContactChannel
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000002")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000003")
MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000004")
WORKFLOW_ID = UUID("00000000-0000-0000-0000-000000000005")
RECONCILIATION_ID = UUID("00000000-0000-0000-0000-000000000006")
FAILURE_ID = UUID("00000000-0000-0000-0000-000000000007")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000008")
MEMBERSHIP_ID = UUID("00000000-0000-0000-0000-000000000009")


@pytest.mark.asyncio
async def test_exception_list_requires_manager_visibility() -> None:
    result = await list_outbound_send_exceptions(
        actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT),
        workspace_id=WORKSPACE_ID,
        request_repository=cast(OutboundSendRequestRepository, FakeRequestRepository()),
        provider_failure_repository=cast(
            OutboundProviderFailureRepository, FakeFailureRepository()
        ),
        reconciliation_repository=cast(
            OutboundSendReconciliationRepository, FakeReconciliationRepository()
        ),
        now=NOW,
    )

    assert result.status == OutboundSendExceptionReadStatus.REJECTED


@pytest.mark.asyncio
async def test_exception_list_returns_safe_related_operational_data() -> None:
    request = _request(OutboundSendRequestStatus.UNCERTAIN)
    result = await list_outbound_send_exceptions(
        actor=_actor(WorkspaceMembershipRole.MANAGER),
        workspace_id=WORKSPACE_ID,
        request_repository=cast(OutboundSendRequestRepository, FakeRequestRepository(request)),
        provider_failure_repository=cast(
            OutboundProviderFailureRepository, FakeFailureRepository(_failure())
        ),
        reconciliation_repository=cast(
            OutboundSendReconciliationRepository, FakeReconciliationRepository(_reconciliation())
        ),
        channel=ContactChannel.SMS,
        now=NOW,
    )

    assert result.status == OutboundSendExceptionReadStatus.OK
    assert result.exceptions[0].request.request_id == REQUEST_ID
    assert result.exceptions[0].provider_failure is not None
    assert result.exceptions[0].reconciliation is not None


@pytest.mark.asyncio
async def test_detail_is_workspace_scoped_and_missing_requests_are_not_found() -> None:
    result = await get_outbound_send_exception(
        actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
        workspace_id=WORKSPACE_ID,
        request_id=REQUEST_ID,
        request_repository=cast(OutboundSendRequestRepository, FakeRequestRepository()),
        provider_failure_repository=cast(
            OutboundProviderFailureRepository, FakeFailureRepository()
        ),
        reconciliation_repository=cast(
            OutboundSendReconciliationRepository, FakeReconciliationRepository()
        ),
    )

    assert result.status == OutboundSendExceptionReadStatus.NOT_FOUND


class FakeRequestRepository:
    def __init__(self, request: OutboundSendRequest | None = None) -> None:
        self.request = request

    async def list_exceptions(self, **_: object) -> tuple[OutboundSendRequest, ...]:
        return (self.request,) if self.request is not None else ()

    async def get_by_id(self, workspace_id: UUID, request_id: UUID) -> OutboundSendRequest | None:
        if (
            self.request
            and self.request.workspace_id == workspace_id
            and self.request.request_id == request_id
        ):
            return self.request
        return None


class FakeFailureRepository:
    def __init__(self, failure: OutboundProviderFailure | None = None) -> None:
        self.failure = failure

    async def get_by_outbound_message_id(
        self, workspace_id: UUID, outbound_message_id: UUID
    ) -> OutboundProviderFailure | None:
        if (
            self.failure
            and self.failure.workspace_id == workspace_id
            and self.failure.outbound_message_id == outbound_message_id
        ):
            return self.failure
        return None


class FakeReconciliationRepository:
    def __init__(self, reconciliation: OutboundSendReconciliation | None = None) -> None:
        self.reconciliation = reconciliation

    async def get_by_id(
        self, workspace_id: UUID, reconciliation_id: UUID
    ) -> OutboundSendReconciliation | None:
        if (
            self.reconciliation
            and self.reconciliation.workspace_id == workspace_id
            and self.reconciliation.reconciliation_id == reconciliation_id
        ):
            return self.reconciliation
        return None


def _request(request_status: OutboundSendRequestStatus) -> OutboundSendRequest:
    return OutboundSendRequest(
        request_id=REQUEST_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture/1",
        outbound_message_id=MESSAGE_ID,
        reconciliation_id=RECONCILIATION_ID,
        idempotency_key="request-key",
        channel=ContactChannel.SMS,
        provider_name="twilio",
        provider_payload={"body": "redacted"},
        available_at=NOW,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
        status=request_status,
        attempt_count=2,
        claimed_at=NOW - STALE_DISPATCHING_AFTER,
        failure_kind="uncertain",
        failure_reason="provider timeout",
    )


def _failure() -> OutboundProviderFailure:
    return OutboundProviderFailure(
        failure_id=FAILURE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        outbound_message_id=MESSAGE_ID,
        workflow_id=WORKFLOW_ID,
        channel=ContactChannel.SMS,
        provider_name="twilio",
        failure_kind="uncertain",
        failure_reason="provider timeout",
        attempt_count=2,
        status=OutboundProviderFailureStatus.OPEN,
        first_failed_at=NOW - timedelta(hours=1),
        last_failed_at=NOW,
        created_at=NOW - timedelta(hours=1),
    )


def _reconciliation() -> OutboundSendReconciliation:
    return OutboundSendReconciliation(
        reconciliation_id=RECONCILIATION_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture/1",
        outbound_message_id=MESSAGE_ID,
        idempotency_key="reconciliation-key",
        status=OutboundSendReconciliationStatus.PENDING,
        provider_name="twilio",
        provider_message_id=None,
        provider_delivery_status=ProviderDeliveryStatus.UNKNOWN,
        created_at=NOW,
        updated_at=NOW,
    )


def _actor(role: WorkspaceMembershipRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=ACTOR_ID,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=MEMBERSHIP_ID,
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )