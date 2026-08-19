from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from app.application.ports.messaging import (
    EmailMessage,
    EmailProvider,
    ProviderFailureKind,
    ProviderSendFailure,
    SMSMessage,
    SMSProvider,
)
from app.application.ports.repositories import (
    OutboundMessageRepository,
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    OutboundSendRequestRepository,
    TemporalSignalOutboxRepository,
)
from app.application.services.retry_backoff import exponential_retry_delay
from app.application.use_cases.revalidate_outbound_send_request import (
    OutboundSendRevalidationResult,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.outbound_provider_failure import (
    OutboundProviderFailure,
    OutboundProviderFailureStatus,
)
from app.domain.campaigns.outbound_send_reconciliation import OutboundSendReconciliationStatus
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import (
    TemporalSignalName,
    TemporalSignalOutboxEntry,
    TemporalSignalOutboxStatus,
)

MAX_OUTBOUND_SEND_ATTEMPTS = 3
OUTBOUND_SEND_RETRY_BASE_DELAY = timedelta(milliseconds=100)
OUTBOUND_SEND_RETRY_MAX_DELAY = timedelta(seconds=1)
OUTBOUND_REFRESH_RETRY_BASE_DELAY = timedelta(seconds=30)
OUTBOUND_REFRESH_RETRY_MAX_DELAY = timedelta(minutes=10)


@dataclass(frozen=True)
class DispatchOutboundSendRequestsResult:
    recovered_uncertain_count: int
    claimed_count: int
    sent_count: int
    retry_scheduled_count: int
    policy_rejected_count: int
    failed_count: int
    uncertain_count: int


@dataclass(frozen=True)
class OutboundPreDispatchRefreshResult:
    allowed: bool
    message: OutboundMessage | None = None
    recent_human_activity: bool = False
    failure_reason: str = "pre_dispatch_refresh_rejected"
    retryable: bool = False


class OutboundPreDispatchRefresher(Protocol):
    async def __call__(
        self,
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        raise NotImplementedError


class OutboundSendRequestRevalidator(Protocol):
    async def __call__(
        self,
        *,
        request: OutboundSendRequest,
        now: datetime,
        recent_human_activity: bool,
    ) -> OutboundSendRevalidationResult:
        raise NotImplementedError


async def dispatch_outbound_send_requests(
    *,
    request_repository: OutboundSendRequestRepository,
    message_repository: OutboundMessageRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    provider_failure_repository: OutboundProviderFailureRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    pre_dispatch_refresh: OutboundPreDispatchRefresher,
    revalidate_request: OutboundSendRequestRevalidator,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
    commit: Callable[[], Awaitable[None]],
    now: datetime,
    batch_size: int = 100,
    stale_after: timedelta = timedelta(minutes=5),
    max_attempts: int = MAX_OUTBOUND_SEND_ATTEMPTS,
    retry_base_delay: timedelta = OUTBOUND_SEND_RETRY_BASE_DELAY,
    retry_max_delay: timedelta = OUTBOUND_SEND_RETRY_MAX_DELAY,
    refresh_retry_base_delay: timedelta = OUTBOUND_REFRESH_RETRY_BASE_DELAY,
    refresh_retry_max_delay: timedelta = OUTBOUND_REFRESH_RETRY_MAX_DELAY,
) -> DispatchOutboundSendRequestsResult:
    recovered = await request_repository.recover_stale_dispatching(
        stale_before=now - stale_after,
        now=now,
        limit=batch_size,
    )
    for request in recovered:
        await _record_uncertain(
            request=request,
            reason=request.failure_reason or "stale_dispatch_recovered_without_redispatch",
            message_repository=message_repository,
            request_repository=request_repository,
            reconciliation_repository=reconciliation_repository,
            temporal_signal_outbox_repository=temporal_signal_outbox_repository,
            now=now,
            request_already_updated=True,
        )
    if recovered:
        await commit()

    claimed = await request_repository.claim_due_pending(now=now, limit=batch_size)
    if claimed:
        # The DISPATCHING claim must be durable before any external provider call.
        await commit()

    sent_count = 0
    retry_scheduled_count = 0
    policy_rejected_count = 0
    failed_count = 0
    uncertain_count = 0
    for request in claimed:
        try:
            refresh = await pre_dispatch_refresh(request=request, now=now)
        except Exception as exc:  # noqa: BLE001
            refresh = OutboundPreDispatchRefreshResult(
                allowed=False,
                failure_reason=(
                    "pre_dispatch_refresh_failed:" + (str(exc) or exc.__class__.__name__)
                ),
                retryable=True,
            )
        if not refresh.allowed:
            if refresh.retryable and request.attempt_count < max_attempts:
                await _schedule_retry(
                    request=request,
                    reason=refresh.failure_reason,
                    message_repository=message_repository,
                    request_repository=request_repository,
                    now=now,
                    retry_base_delay=refresh_retry_base_delay,
                    retry_max_delay=refresh_retry_max_delay,
                )
                retry_scheduled_count += 1
            elif refresh.retryable:
                await _record_failed(
                    request=request,
                    failure_kind=ProviderFailureKind.TEMPORARY,
                    reason=refresh.failure_reason,
                    message_repository=message_repository,
                    request_repository=request_repository,
                    reconciliation_repository=reconciliation_repository,
                    provider_failure_repository=provider_failure_repository,
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                    now=now,
                )
                failed_count += 1
            else:
                await _record_policy_rejected(
                    request=request,
                    message=refresh.message,
                    reason=refresh.failure_reason,
                    message_repository=message_repository,
                    request_repository=request_repository,
                    reconciliation_repository=reconciliation_repository,
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                    now=now,
                )
                policy_rejected_count += 1
            await commit()
            continue
        revalidation = await revalidate_request(
            request=request,
            now=now,
            recent_human_activity=refresh.recent_human_activity,
        )
        request = revalidation.request
        if not revalidation.allowed:
            await _record_policy_rejected(
                request=request,
                message=revalidation.message,
                reason=revalidation.failure_reason,
                message_repository=message_repository,
                request_repository=request_repository,
                reconciliation_repository=reconciliation_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                now=now,
            )
            policy_rejected_count += 1
            await commit()
            continue
        provider_configuration_failure = _provider_configuration_failure(
            request,
            sms_provider=sms_provider,
            email_provider=email_provider,
        )
        if provider_configuration_failure is not None:
            await _record_policy_rejected(
                request=request,
                message=revalidation.message,
                reason=provider_configuration_failure,
                message_repository=message_repository,
                request_repository=request_repository,
                reconciliation_repository=reconciliation_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                now=now,
            )
            policy_rejected_count += 1
            await commit()
            continue
        # The revalidation verdict was reached on a consistent snapshot under
        # row locks. Commit here to release those locks before the external
        # provider call: the durable DISPATCHING claim already prevents
        # double-dispatch, and holding locks through provider I/O would stall
        # webhook processing and concurrent workers for the full call latency.
        await commit()
        try:
            provider_message_id = await _dispatch_provider(
                request=request,
                sms_provider=sms_provider,
                email_provider=email_provider,
            )
            if not provider_message_id.strip():
                raise ProviderSendFailure(
                    ProviderFailureKind.UNCERTAIN,
                    "provider_message_id_missing",
                )
        except ProviderSendFailure as exc:
            if exc.kind is ProviderFailureKind.TEMPORARY and request.attempt_count < max_attempts:
                await _schedule_retry(
                    request=request,
                    reason=str(exc),
                    message_repository=message_repository,
                    request_repository=request_repository,
                    now=now,
                    retry_base_delay=retry_base_delay,
                    retry_max_delay=retry_max_delay,
                )
                retry_scheduled_count += 1
            elif exc.kind is ProviderFailureKind.UNCERTAIN:
                await _record_uncertain(
                    request=request,
                    reason=str(exc),
                    message_repository=message_repository,
                    request_repository=request_repository,
                    reconciliation_repository=reconciliation_repository,
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                    now=now,
                )
                uncertain_count += 1
            else:
                await _record_failed(
                    request=request,
                    failure_kind=exc.kind,
                    reason=str(exc),
                    message_repository=message_repository,
                    request_repository=request_repository,
                    reconciliation_repository=reconciliation_repository,
                    provider_failure_repository=provider_failure_repository,
                    temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                    now=now,
                )
                failed_count += 1
        except Exception as exc:  # noqa: BLE001
            await _record_uncertain(
                request=request,
                reason=str(exc) or exc.__class__.__name__,
                message_repository=message_repository,
                request_repository=request_repository,
                reconciliation_repository=reconciliation_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                now=now,
            )
            uncertain_count += 1
        else:
            await _record_sent(
                request=request,
                provider_message_id=provider_message_id.strip(),
                message_repository=message_repository,
                request_repository=request_repository,
                reconciliation_repository=reconciliation_repository,
                temporal_signal_outbox_repository=temporal_signal_outbox_repository,
                now=now,
            )
            sent_count += 1
        await commit()

    return DispatchOutboundSendRequestsResult(
        recovered_uncertain_count=len(recovered),
        claimed_count=len(claimed),
        sent_count=sent_count,
        retry_scheduled_count=retry_scheduled_count,
        policy_rejected_count=policy_rejected_count,
        failed_count=failed_count,
        uncertain_count=uncertain_count,
    )


async def _dispatch_provider(
    *,
    request: OutboundSendRequest,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
) -> str:
    if request.channel is ContactChannel.SMS:
        return await sms_provider.send(SMSMessage.model_validate(request.provider_payload))
    return await email_provider.send(EmailMessage.model_validate(request.provider_payload))


def _provider_configuration_failure(
    request: OutboundSendRequest,
    *,
    sms_provider: SMSProvider,
    email_provider: EmailProvider,
) -> str | None:
    if request.channel is ContactChannel.SMS:
        if getattr(sms_provider, "provider_name", "sms") == request.provider_name:
            return None
        mismatch = "configured_sms_provider_does_not_match_durable_request"
    elif getattr(email_provider, "provider_name", "email") == request.provider_name:
        return None
    else:
        mismatch = "configured_email_provider_does_not_match_durable_request"
    return f"pre_provider_policy_rejected:{mismatch}"


async def _schedule_retry(
    *,
    request: OutboundSendRequest,
    reason: str,
    message_repository: OutboundMessageRepository,
    request_repository: OutboundSendRequestRepository,
    now: datetime,
    retry_base_delay: timedelta,
    retry_max_delay: timedelta,
) -> None:
    available_at = now + exponential_retry_delay(
        request.attempt_count,
        base_delay=retry_base_delay,
        max_delay=retry_max_delay,
    )
    await request_repository.save(
        replace(
            request,
            status=OutboundSendRequestStatus.PENDING,
            available_at=available_at,
            claimed_at=None,
            failure_kind=ProviderFailureKind.TEMPORARY.value,
            failure_reason=reason,
            updated_at=now,
        )
    )
    message = await message_repository.get_by_id(request.workspace_id, request.outbound_message_id)
    if message is not None:
        await message_repository.save(
            replace(
                message,
                provider_name=request.provider_name,
                provider_attempt_count=request.attempt_count,
                provider_last_attempt_at=now,
                provider_next_retry_at=available_at,
                provider_last_failure_kind=ProviderFailureKind.TEMPORARY.value,
                failure_reason=reason,
                updated_at=now,
            )
        )


async def _record_sent(
    *,
    request: OutboundSendRequest,
    provider_message_id: str,
    message_repository: OutboundMessageRepository,
    request_repository: OutboundSendRequestRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
) -> None:
    await request_repository.save(
        replace(
            request,
            status=OutboundSendRequestStatus.SENT,
            completed_at=now,
            provider_message_id=provider_message_id,
            failure_kind=None,
            failure_reason=None,
            updated_at=now,
        )
    )
    message = await message_repository.get_by_id(request.workspace_id, request.outbound_message_id)
    if message is not None:
        await message_repository.save(
            replace(
                message,
                status=OutboundMessageStatus.SENT,
                provider_send_status=ProviderSendStatus.ACCEPTED,
                provider_name=request.provider_name,
                provider_message_id=provider_message_id,
                provider_delivery_status=ProviderDeliveryStatus.ACCEPTED,
                provider_attempt_count=request.attempt_count,
                provider_last_attempt_at=now,
                provider_next_retry_at=None,
                provider_last_failure_kind=None,
                failure_reason=None,
                status_detail=None,
                sent_at=now,
                updated_at=now,
            )
        )
    await reconciliation_repository.resolve(
        workspace_id=request.workspace_id,
        reconciliation_id=request.reconciliation_id,
        status=OutboundSendReconciliationStatus.CONFIRMED,
        provider_message_id=provider_message_id,
        provider_delivery_status=ProviderDeliveryStatus.ACCEPTED,
        now=now,
    )
    await _append_reschedule_signal(
        request=request,
        outcome=OutboundSendRequestStatus.SENT,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )


async def _record_failed(
    *,
    request: OutboundSendRequest,
    failure_kind: ProviderFailureKind,
    reason: str,
    message_repository: OutboundMessageRepository,
    request_repository: OutboundSendRequestRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    provider_failure_repository: OutboundProviderFailureRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
) -> None:
    await request_repository.save(
        replace(
            request,
            status=OutboundSendRequestStatus.FAILED,
            completed_at=now,
            failure_kind=failure_kind.value,
            failure_reason=reason,
            updated_at=now,
        )
    )
    message = await message_repository.get_by_id(request.workspace_id, request.outbound_message_id)
    if message is not None:
        await message_repository.save(
            replace(
                message,
                status=OutboundMessageStatus.FAILED,
                provider_name=request.provider_name,
                provider_attempt_count=request.attempt_count,
                provider_last_attempt_at=now,
                provider_next_retry_at=None,
                provider_last_failure_kind=failure_kind.value,
                failure_reason=reason,
                status_detail=None,
                updated_at=now,
            )
        )
    await reconciliation_repository.resolve(
        workspace_id=request.workspace_id,
        reconciliation_id=request.reconciliation_id,
        status=OutboundSendReconciliationStatus.FAILED,
        failure_reason=reason,
        now=now,
    )
    await provider_failure_repository.create_or_get(
        OutboundProviderFailure(
            failure_id=uuid4(),
            workspace_id=request.workspace_id,
            lead_id=request.lead_id,
            outbound_message_id=request.outbound_message_id,
            workflow_id=request.workflow_id,
            channel=request.channel,
            provider_name=request.provider_name,
            failure_kind=failure_kind.value,
            failure_reason=reason,
            attempt_count=request.attempt_count,
            status=OutboundProviderFailureStatus.OPEN,
            first_failed_at=request.claimed_at or now,
            last_failed_at=now,
            created_at=now,
        )
    )
    await _append_reschedule_signal(
        request=request,
        outcome=OutboundSendRequestStatus.FAILED,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )


async def _record_policy_rejected(
    *,
    request: OutboundSendRequest,
    message: OutboundMessage | None,
    reason: str,
    message_repository: OutboundMessageRepository,
    request_repository: OutboundSendRequestRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
) -> None:
    failure_kind = "policy_rejected"
    if request.status is OutboundSendRequestStatus.DISPATCHING:
        await request_repository.save(
            replace(
                request,
                status=OutboundSendRequestStatus.FAILED,
                completed_at=now,
                failure_kind=failure_kind,
                failure_reason=reason,
                updated_at=now,
            )
        )
    current_message = message
    if current_message is None:
        current_message = await message_repository.get_by_id(
            request.workspace_id,
            request.outbound_message_id,
        )
    if (
        current_message is not None
        and current_message.status is OutboundMessageStatus.PENDING
    ):
        await message_repository.save(
            replace(
                current_message,
                status=OutboundMessageStatus.FAILED,
                provider_next_retry_at=None,
                provider_last_failure_kind=failure_kind,
                failure_reason=reason,
                status_detail=None,
                updated_at=now,
            )
        )
    reconciliation = await reconciliation_repository.get_by_id_for_update(
        request.workspace_id,
        request.reconciliation_id,
    )
    if (
        reconciliation is not None
        and reconciliation.status is OutboundSendReconciliationStatus.PENDING
    ):
        await reconciliation_repository.resolve(
            workspace_id=request.workspace_id,
            reconciliation_id=request.reconciliation_id,
            status=OutboundSendReconciliationStatus.FAILED,
            failure_reason=reason,
            now=now,
        )
    await _append_reschedule_signal(
        request=request,
        outcome=OutboundSendRequestStatus.FAILED,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )


async def _record_uncertain(
    *,
    request: OutboundSendRequest,
    reason: str,
    message_repository: OutboundMessageRepository,
    request_repository: OutboundSendRequestRepository,
    reconciliation_repository: OutboundSendReconciliationRepository,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
    request_already_updated: bool = False,
) -> None:
    if not request_already_updated:
        await request_repository.save(
            replace(
                request,
                status=OutboundSendRequestStatus.UNCERTAIN,
                completed_at=now,
                failure_kind=ProviderFailureKind.UNCERTAIN.value,
                failure_reason=reason,
                updated_at=now,
            )
        )
    message = await message_repository.get_by_id(request.workspace_id, request.outbound_message_id)
    if message is not None:
        await message_repository.save(
            replace(
                message,
                status=OutboundMessageStatus.UNCERTAIN,
                provider_send_status=ProviderSendStatus.UNCERTAIN,
                provider_name=request.provider_name,
                provider_attempt_count=request.attempt_count,
                provider_last_attempt_at=request.claimed_at or now,
                provider_next_retry_at=None,
                provider_last_failure_kind=ProviderFailureKind.UNCERTAIN.value,
                failure_reason=reason,
                status_detail=None,
                updated_at=now,
            )
        )
    await reconciliation_repository.resolve(
        workspace_id=request.workspace_id,
        reconciliation_id=request.reconciliation_id,
        status=OutboundSendReconciliationStatus.PENDING,
        failure_reason=reason,
        now=now,
    )
    await _append_reschedule_signal(
        request=request,
        outcome=OutboundSendRequestStatus.UNCERTAIN,
        temporal_signal_outbox_repository=temporal_signal_outbox_repository,
        now=now,
    )


async def _append_reschedule_signal(
    *,
    request: OutboundSendRequest,
    outcome: OutboundSendRequestStatus,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository,
    now: datetime,
) -> None:
    await temporal_signal_outbox_repository.append(
        TemporalSignalOutboxEntry(
            temporal_signal_id=uuid4(),
            workspace_id=request.workspace_id,
            workflow_id=request.workflow_id,
            temporal_workflow_id=request.temporal_workflow_id,
            signal_name=TemporalSignalName.RESCHEDULE_REQUESTED,
            payload={
                "lead_id": str(request.lead_id),
                "occurred_at": now.isoformat(),
                "reason": f"outbound_dispatch_{outcome.value}",
            },
            idempotency_key=f"outbound-send-request:{request.request_id}:{outcome.value}",
            status=TemporalSignalOutboxStatus.PENDING,
            attempt_count=0,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
    )