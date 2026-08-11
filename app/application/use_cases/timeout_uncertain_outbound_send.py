from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.application.ports.repositories import OutboundSendReconciliationRepository
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.common.ids import WorkspaceId


@dataclass(frozen=True)
class UncertainOutboundSendTimeoutResult:
    reconciliation: OutboundSendReconciliation | None
    timed_out: bool


async def timeout_uncertain_outbound_send(
    *,
    workspace_id: WorkspaceId,
    reconciliation_id: UUID,
    now: datetime,
    reconciliation_repository: OutboundSendReconciliationRepository,
) -> UncertainOutboundSendTimeoutResult:
    reconciliation = await reconciliation_repository.get_by_id_for_update(
        workspace_id,
        reconciliation_id,
    )
    if (
        reconciliation is None
        or reconciliation.status is not OutboundSendReconciliationStatus.PENDING
    ):
        return UncertainOutboundSendTimeoutResult(
            reconciliation=reconciliation,
            timed_out=False,
        )

    resolved = await reconciliation_repository.resolve(
        workspace_id=workspace_id,
        reconciliation_id=reconciliation_id,
        status=OutboundSendReconciliationStatus.TIMED_OUT,
        now=now,
        failure_reason="provider_confirmation_timeout",
    )
    return UncertainOutboundSendTimeoutResult(
        reconciliation=resolved,
        timed_out=resolved is not None,
    )