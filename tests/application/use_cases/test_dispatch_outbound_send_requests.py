from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from app.application.ports.messaging import (
    EmailMessage,
    ProviderFailureKind,
    ProviderSendFailure,
    SMSMessage,
)
from app.application.ports.repositories import (
    OutboundMessageRepository,
    OutboundProviderFailureRepository,
    OutboundSendReconciliationRepository,
    TemporalSignalOutboxRepository,
)
from app.application.use_cases.dispatch_outbound_send_requests import (
    OutboundPreDispatchRefresher,
    OutboundPreDispatchRefreshResult,
    OutboundSendRequestRevalidator,
    dispatch_outbound_send_requests,
)
from app.application.use_cases.revalidate_outbound_send_request import (
    OutboundSendRevalidationReason,
    OutboundSendRevalidationResult,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
)
from app.domain.campaigns.outbound_provider_failure import OutboundProviderFailure
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import (
    PreSendDecision,
    PreSendReasonCode,
    ProviderSendStatus,
)
from app.domain.compliance.contactability import ContactChannel
from app.domain.workflows import TemporalSignalOutboxEntry

NOW = datetime(2026, 8, 9, 15, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("11111111-1111-1111-1111-111111111111")
LEAD_ID = UUID("22222222-2222-2222-2222-222222222222")
WORKFLOW_ID = UUID("33333333-3333-3333-3333-333333333333")
MESSAGE_ID = UUID("44444444-4444-4444-4444-444444444444")
RECONCILIATION_ID = UUID("55555555-5555-5555-5555-555555555555")
REQUEST_ID = UUID("66666666-6666-6666-6666-666666666666")


class FakeRequestRepository:
    def __init__(self, request: OutboundSendRequest) -> None:
        self.request = request

    async def get_by_idempotency_key(
        self, workspace_id: UUID, idempotency_key: str
    ) -> OutboundSendRequest | None:
        if (
            self.request.workspace_id == workspace_id
            and self.request.idempotency_key == idempotency_key
        ):
            return self.request
        return None

    async def get_by_id(
        self, workspace_id: UUID, request_id: UUID
    ) -> OutboundSendRequest | None:
        if self.request.workspace_id == workspace_id and self.request.request_id == request_id:
            return self.request
        return None

    async def list_exceptions(self, **_: object) -> tuple[OutboundSendRequest, ...]:
        return (self.request,)

    async def create_or_get(self, request: OutboundSendRequest) -> OutboundSendRequest:
        return self.request

    async def get_by_outbound_message_id(
        self,
        workspace_id: UUID,
        outbound_message_id: UUID,
    ) -> OutboundSendRequest | None:
        if (
            self.request.workspace_id == workspace_id
            and self.request.outbound_message_id == outbound_message_id
        ):
            return self.request
        return None

    async def save(self, request: OutboundSendRequest) -> OutboundSendRequest:
        self.request = request
        return request

    async def claim_due_pending(
        self, *, now: datetime, limit: int
    ) -> tuple[OutboundSendRequest, ...]:
        _ = limit
        if self.request.status is not OutboundSendRequestStatus.PENDING:
            return ()
        if self.request.available_at > now:
            return ()
        self.request = replace(
            self.request,
            status=OutboundSendRequestStatus.DISPATCHING,
            attempt_count=self.request.attempt_count + 1,
            claimed_at=now,
            updated_at=now,
        )
        return (self.request,)

    async def recover_stale_dispatching(
        self, *, stale_before: datetime, now: datetime, limit: int
    ) -> tuple[OutboundSendRequest, ...]:
        _ = limit
        if (
            self.request.status is not OutboundSendRequestStatus.DISPATCHING
            or self.request.claimed_at is None
            or self.request.claimed_at > stale_before
        ):
            return ()
        self.request = replace(
            self.request,
            status=OutboundSendRequestStatus.UNCERTAIN,
            completed_at=now,
            failure_kind=ProviderFailureKind.UNCERTAIN.value,
            failure_reason="stale_dispatch_recovered_without_redispatch",
            updated_at=now,
        )
        return (self.request,)

    async def get_due_pending_summary(
        self,
        *,
        now: datetime,
    ) -> tuple[int, datetime | None]:
        if (
            self.request.status is OutboundSendRequestStatus.PENDING
            and self.request.available_at <= now
        ):
            return 1, self.request.available_at
        return 0, None


class FakeMessageRepository:
    def __init__(self, message: OutboundMessage) -> None:
        self.message = message

    async def get_by_id(self, workspace_id: UUID, message_id: UUID) -> OutboundMessage | None:
        if self.message.workspace_id == workspace_id and self.message.message_id == message_id:
            return self.message
        return None

    async def save(self, message: OutboundMessage) -> OutboundMessage:
        self.message = message
        return message


class FakeReconciliationRepository:
    def __init__(self, reconciliation: OutboundSendReconciliation) -> None:
        self.reconciliation = reconciliation

    async def get_by_id_for_update(
        self,
        workspace_id: UUID,
        reconciliation_id: UUID,
    ) -> OutboundSendReconciliation | None:
        if (
            self.reconciliation.workspace_id == workspace_id
            and self.reconciliation.reconciliation_id == reconciliation_id
        ):
            return self.reconciliation
        return None

    async def resolve(
        self,
        *,
        workspace_id: UUID,
        reconciliation_id: UUID,
        status: OutboundSendReconciliationStatus,
        provider_message_id: str | None = None,
        provider_delivery_status: ProviderDeliveryStatus | None = None,
        failure_reason: str | None = None,
        now: datetime,
    ) -> OutboundSendReconciliation | None:
        _ = (workspace_id, reconciliation_id)
        self.reconciliation = replace(
            self.reconciliation,
            status=status,
            provider_message_id=provider_message_id,
            provider_delivery_status=provider_delivery_status,
            failure_reason=failure_reason,
            resolved_at=(
                self.reconciliation.resolved_at
                if status is OutboundSendReconciliationStatus.PENDING
                else now
            ),
            updated_at=now,
        )
        return self.reconciliation

class FakeFailureRepository:
    def __init__(self) -> None:
        self.failures: list[OutboundProviderFailure] = []

    async def create_or_get(self, failure: OutboundProviderFailure) -> OutboundProviderFailure:
        self.failures.append(failure)
        return failure


class FakeSignalRepository:
    def __init__(self) -> None:
        self.entries: list[TemporalSignalOutboxEntry] = []

    async def append(self, entry: TemporalSignalOutboxEntry) -> TemporalSignalOutboxEntry:
        self.entries.append(entry)
        return entry


class FakeSMSProvider:
    provider_name = "twilio"

    def __init__(self, outcomes: list[str | Exception], commits: list[int] | None = None) -> None:
        self.outcomes = outcomes
        self.messages: list[SMSMessage] = []
        self.commits = commits

    async def send(self, message: SMSMessage) -> str:
        if self.commits is not None:
            assert self.commits
        self.messages.append(message)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeEmailProvider:
    provider_name = "sendgrid"

    async def send(self, message: EmailMessage) -> str:
        raise AssertionError(f"unexpected email dispatch: {message}")


def _request(
    *,
    status: OutboundSendRequestStatus = OutboundSendRequestStatus.PENDING,
    attempt_count: int = 0,
    claimed_at: datetime | None = None,
) -> OutboundSendRequest:
    return OutboundSendRequest(
        request_id=REQUEST_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        outbound_message_id=MESSAGE_ID,
        reconciliation_id=RECONCILIATION_ID,
        idempotency_key="outbound:test",
        channel=ContactChannel.SMS,
        provider_name="twilio",
        provider_payload=SMSMessage(
            to_phone="+15551234567",
            body="Checking in.",
            idempotency_key="outbound:test",
        ).model_dump(mode="json"),
        status=status,
        attempt_count=attempt_count,
        available_at=NOW - timedelta(minutes=1),
        claimed_at=claimed_at,
        created_at=NOW - timedelta(minutes=2),
        updated_at=NOW - timedelta(minutes=1),
    )


def _message() -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("77777777-7777-7777-7777-777777777777"),
        cadence_step_id="step-1",
        channel=ContactChannel.SMS,
        status=OutboundMessageStatus.PENDING,
        idempotency_key="outbound:test",
        body="Checking in.",
        created_at=NOW,
        updated_at=NOW,
        provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
    )


def _reconciliation() -> OutboundSendReconciliation:
    return OutboundSendReconciliation(
        reconciliation_id=RECONCILIATION_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        workflow_id=WORKFLOW_ID,
        temporal_workflow_id="lead-nurture-1",
        outbound_message_id=MESSAGE_ID,
        idempotency_key="outbound:test",
        status=OutboundSendReconciliationStatus.PENDING,
        provider_name="twilio",
        provider_message_id=None,
        provider_delivery_status=None,
        created_at=NOW,
        updated_at=NOW,
    )


async def _run(
    request_repository: FakeRequestRepository,
    provider: FakeSMSProvider,
    *,
    now: datetime = NOW,
    pre_dispatch_refresh: OutboundPreDispatchRefresher | None = None,
    revalidate_request: OutboundSendRequestRevalidator | None = None,
) -> tuple[
    FakeMessageRepository,
    FakeReconciliationRepository,
    FakeFailureRepository,
    FakeSignalRepository,
]:
    message_repository = FakeMessageRepository(_message())
    reconciliation_repository = FakeReconciliationRepository(_reconciliation())
    failure_repository = FakeFailureRepository()
    signal_repository = FakeSignalRepository()
    commits: list[int] = provider.commits if provider.commits is not None else []

    async def commit() -> None:
        commits.append(len(commits) + 1)

    await dispatch_outbound_send_requests(
        request_repository=request_repository,
        message_repository=cast(OutboundMessageRepository, message_repository),
        reconciliation_repository=cast(
            OutboundSendReconciliationRepository,
            reconciliation_repository,
        ),
        provider_failure_repository=cast(
            OutboundProviderFailureRepository,
            failure_repository,
        ),
        temporal_signal_outbox_repository=cast(
            TemporalSignalOutboxRepository,
            signal_repository,
        ),
        pre_dispatch_refresh=pre_dispatch_refresh or _allow_pre_dispatch_refresh,
        revalidate_request=revalidate_request or _allow_revalidation,
        sms_provider=provider,
        email_provider=FakeEmailProvider(),
        commit=commit,
        now=now,
    )
    return message_repository, reconciliation_repository, failure_repository, signal_repository


async def _allow_revalidation(
    *,
    request: OutboundSendRequest,
    now: datetime,
    recent_human_activity: bool,
) -> OutboundSendRevalidationResult:
    _ = (now, recent_human_activity)
    return OutboundSendRevalidationResult(allowed=True, request=request, message=_message())


async def _allow_pre_dispatch_refresh(
    *,
    request: OutboundSendRequest,
    now: datetime,
) -> OutboundPreDispatchRefreshResult:
    _ = (request, now)
    return OutboundPreDispatchRefreshResult(allowed=True, message=_message())


async def test_dispatch_success_commits_claim_before_provider_and_signals() -> None:
    commits: list[int] = []
    request_repository = FakeRequestRepository(_request())
    provider = FakeSMSProvider(["SM123"], commits)

    messages, reconciliations, failures, signals = await _run(request_repository, provider)

    assert request_repository.request.status is OutboundSendRequestStatus.SENT
    assert messages.message.status is OutboundMessageStatus.SENT
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.CONFIRMED
    assert not failures.failures
    assert len(signals.entries) == 1
    assert len(provider.messages) == 1
    assert len(commits) == 2


async def test_temporary_failure_retries_then_exhausts_without_early_signal() -> None:
    request_repository = FakeRequestRepository(_request())
    temporary = ProviderSendFailure(ProviderFailureKind.TEMPORARY, "provider busy")
    refresh_attempts: list[int] = []
    revalidated_attempts: list[int] = []

    async def track_refresh(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        _ = now
        refresh_attempts.append(request.attempt_count)
        return OutboundPreDispatchRefreshResult(allowed=True, message=_message())

    async def track_revalidation(
        *,
        request: OutboundSendRequest,
        now: datetime,
        recent_human_activity: bool,
    ) -> OutboundSendRevalidationResult:
        _ = (now, recent_human_activity)
        revalidated_attempts.append(request.attempt_count)
        return OutboundSendRevalidationResult(
            allowed=True,
            request=request,
            message=_message(),
        )

    first = await _run(
        request_repository,
        FakeSMSProvider([temporary]),
        pre_dispatch_refresh=track_refresh,
        revalidate_request=track_revalidation,
    )
    assert request_repository.request.status is OutboundSendRequestStatus.PENDING
    assert request_repository.request.attempt_count == 1
    assert not first[3].entries

    request_repository.request = replace(request_repository.request, available_at=NOW)
    await _run(
        request_repository,
        FakeSMSProvider([temporary]),
        now=NOW + timedelta(seconds=1),
        pre_dispatch_refresh=track_refresh,
        revalidate_request=track_revalidation,
    )
    request_repository.request = replace(request_repository.request, available_at=NOW)
    messages, reconciliations, failures, signals = await _run(
        request_repository,
        FakeSMSProvider([temporary]),
        now=NOW + timedelta(seconds=2),
        pre_dispatch_refresh=track_refresh,
        revalidate_request=track_revalidation,
    )

    assert request_repository.request.status is OutboundSendRequestStatus.FAILED
    assert request_repository.request.attempt_count == 3
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert len(failures.failures) == 1
    assert len(signals.entries) == 1
    assert refresh_attempts == [1, 2, 3]
    assert revalidated_attempts == [1, 2, 3]


async def test_permanent_failure_marks_all_records_failed() -> None:
    request_repository = FakeRequestRepository(_request())
    messages, reconciliations, failures, signals = await _run(
        request_repository,
        FakeSMSProvider(
            [ProviderSendFailure(ProviderFailureKind.PERMANENT, "invalid destination")]
        ),
    )

    assert request_repository.request.status is OutboundSendRequestStatus.FAILED
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert failures.failures[0].failure_kind == ProviderFailureKind.PERMANENT.value
    assert len(signals.entries) == 1


async def test_workflow_pause_after_enqueue_rejects_without_calling_provider() -> None:
    request_repository = FakeRequestRepository(_request())
    provider = FakeSMSProvider(["must-not-be-used"])

    async def reject_paused_workflow(
        *,
        request: OutboundSendRequest,
        now: datetime,
        recent_human_activity: bool,
    ) -> OutboundSendRevalidationResult:
        _ = recent_human_activity
        return OutboundSendRevalidationResult(
            allowed=False,
            request=request,
            message=_message(),
            reasons=(OutboundSendRevalidationReason.PRE_SEND_BLOCKED,),
            pre_send_decision=PreSendDecision(
                allowed=False,
                channel=ContactChannel.SMS,
                evaluated_at=now,
                reasons=(PreSendReasonCode.WORKFLOW_NOT_SENDABLE,),
            ),
        )

    messages, reconciliations, failures, signals = await _run(
        request_repository,
        provider,
        revalidate_request=reject_paused_workflow,
    )

    assert provider.messages == []
    assert request_repository.request.status is OutboundSendRequestStatus.FAILED
    assert request_repository.request.failure_kind == "policy_rejected"
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert not failures.failures
    assert len(signals.entries) == 1


async def test_live_crm_activity_after_enqueue_rejects_without_calling_provider() -> None:
    request_repository = FakeRequestRepository(_request())
    provider = FakeSMSProvider(["must-not-be-used"])
    refresh_calls: list[int] = []

    async def refresh_with_recent_activity(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        _ = now
        refresh_calls.append(request.attempt_count)
        return OutboundPreDispatchRefreshResult(
            allowed=True,
            message=_message(),
            recent_human_activity=True,
        )

    async def reject_recent_activity(
        *,
        request: OutboundSendRequest,
        now: datetime,
        recent_human_activity: bool,
    ) -> OutboundSendRevalidationResult:
        assert recent_human_activity is True
        return OutboundSendRevalidationResult(
            allowed=False,
            request=request,
            message=_message(),
            reasons=(OutboundSendRevalidationReason.PRE_SEND_BLOCKED,),
            pre_send_decision=PreSendDecision(
                allowed=False,
                channel=ContactChannel.SMS,
                evaluated_at=now,
                reasons=(PreSendReasonCode.RECENT_HUMAN_ACTIVITY,),
            ),
        )

    messages, reconciliations, failures, signals = await _run(
        request_repository,
        provider,
        pre_dispatch_refresh=refresh_with_recent_activity,
        revalidate_request=reject_recent_activity,
    )

    assert refresh_calls == [1]
    assert provider.messages == []
    assert request_repository.request.failure_kind == "policy_rejected"
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert not failures.failures
    assert len(signals.entries) == 1


async def test_live_crm_opt_out_after_enqueue_rejects_without_calling_provider() -> None:
    request_repository = FakeRequestRepository(_request())
    provider = FakeSMSProvider(["must-not-be-used"])
    refresh_completed = False

    async def refresh_new_opt_out(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        nonlocal refresh_completed
        _ = (request, now)
        refresh_completed = True
        return OutboundPreDispatchRefreshResult(allowed=True, message=_message())

    async def reject_changed_contactability(
        *,
        request: OutboundSendRequest,
        now: datetime,
        recent_human_activity: bool,
    ) -> OutboundSendRevalidationResult:
        assert refresh_completed is True
        assert recent_human_activity is False
        return OutboundSendRevalidationResult(
            allowed=False,
            request=request,
            message=_message(),
            reasons=(OutboundSendRevalidationReason.PRE_SEND_BLOCKED,),
            pre_send_decision=PreSendDecision(
                allowed=False,
                channel=ContactChannel.SMS,
                evaluated_at=now,
                reasons=(PreSendReasonCode.CHANNEL_NOT_CONTACTABLE,),
            ),
        )

    messages, reconciliations, failures, signals = await _run(
        request_repository,
        provider,
        pre_dispatch_refresh=refresh_new_opt_out,
        revalidate_request=reject_changed_contactability,
    )

    assert refresh_completed is True
    assert provider.messages == []
    assert request_repository.request.failure_kind == "policy_rejected"
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert not failures.failures
    assert len(signals.entries) == 1


async def test_live_crm_lead_not_found_fails_closed_without_provider() -> None:
    reason = "pre_dispatch_refresh:crm_lead_not_found"
    request_repository = FakeRequestRepository(_request())
    provider = FakeSMSProvider(["must-not-be-used"])

    async def reject_refresh(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        _ = (request, now)
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=_message(),
            failure_reason=reason,
        )

    messages, reconciliations, failures, signals = await _run(
        request_repository,
        provider,
        pre_dispatch_refresh=reject_refresh,
    )

    assert provider.messages == []
    assert request_repository.request.failure_kind == "policy_rejected"
    assert request_repository.request.failure_reason == reason
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert not failures.failures
    assert len(signals.entries) == 1


async def test_transient_crm_refresh_failure_schedules_retry_then_exhausts() -> None:
    reason = "pre_dispatch_refresh:crm_refresh_failed:crm unavailable"
    request_repository = FakeRequestRepository(_request())

    async def transient_refresh(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        _ = (request, now)
        return OutboundPreDispatchRefreshResult(
            allowed=False,
            message=_message(),
            failure_reason=reason,
            retryable=True,
        )

    first = await _run(
        request_repository,
        FakeSMSProvider(["must-not-be-used"]),
        pre_dispatch_refresh=transient_refresh,
    )

    assert request_repository.request.status is OutboundSendRequestStatus.PENDING
    assert request_repository.request.attempt_count == 1
    assert request_repository.request.available_at > NOW
    assert request_repository.request.failure_reason == reason
    assert first[0].message.status is OutboundMessageStatus.PENDING
    assert first[1].reconciliation.status is OutboundSendReconciliationStatus.PENDING
    assert not first[3].entries

    request_repository.request = replace(request_repository.request, available_at=NOW)
    await _run(
        request_repository,
        FakeSMSProvider(["must-not-be-used"]),
        now=NOW + timedelta(seconds=1),
        pre_dispatch_refresh=transient_refresh,
    )
    request_repository.request = replace(request_repository.request, available_at=NOW)
    messages, reconciliations, failures, signals = await _run(
        request_repository,
        FakeSMSProvider(["must-not-be-used"]),
        now=NOW + timedelta(seconds=2),
        pre_dispatch_refresh=transient_refresh,
    )

    assert request_repository.request.status is OutboundSendRequestStatus.FAILED
    assert request_repository.request.attempt_count == 3
    assert request_repository.request.failure_kind == ProviderFailureKind.TEMPORARY.value
    assert messages.message.status is OutboundMessageStatus.FAILED
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.FAILED
    assert len(failures.failures) == 1
    assert len(signals.entries) == 1


async def test_refresh_exception_is_treated_as_retryable() -> None:
    request_repository = FakeRequestRepository(_request())

    async def raising_refresh(
        *,
        request: OutboundSendRequest,
        now: datetime,
    ) -> OutboundPreDispatchRefreshResult:
        _ = (request, now)
        raise ConnectionError("name resolution failed")

    first = await _run(
        request_repository,
        FakeSMSProvider(["must-not-be-used"]),
        pre_dispatch_refresh=raising_refresh,
    )

    assert request_repository.request.status is OutboundSendRequestStatus.PENDING
    assert request_repository.request.attempt_count == 1
    assert (
        request_repository.request.failure_reason
        == "pre_dispatch_refresh_failed:name resolution failed"
    )
    assert first[0].message.status is OutboundMessageStatus.PENDING
    assert not first[3].entries


@pytest.mark.parametrize(
    "failure",
    [
        ProviderSendFailure(ProviderFailureKind.UNCERTAIN, "timeout after submit"),
        RuntimeError("unknown provider error"),
    ],
)
async def test_uncertain_or_unknown_failure_never_retries(failure: Exception) -> None:
    request_repository = FakeRequestRepository(_request())
    messages, reconciliations, failures, signals = await _run(
        request_repository,
        FakeSMSProvider([failure]),
    )

    assert request_repository.request.status is OutboundSendRequestStatus.UNCERTAIN
    assert messages.message.status is OutboundMessageStatus.UNCERTAIN
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.PENDING
    assert reconciliations.reconciliation.failure_reason == str(failure)
    assert reconciliations.reconciliation.resolved_at is None
    assert not failures.failures
    assert len(signals.entries) == 1


async def test_stale_dispatch_recovery_does_not_call_provider_twice() -> None:
    request_repository = FakeRequestRepository(
        _request(
            status=OutboundSendRequestStatus.DISPATCHING,
            attempt_count=1,
            claimed_at=NOW - timedelta(minutes=10),
        )
    )
    provider = FakeSMSProvider(["must-not-be-used"])

    messages, reconciliations, failures, signals = await _run(request_repository, provider)

    assert provider.messages == []
    assert request_repository.request.status is OutboundSendRequestStatus.UNCERTAIN
    assert messages.message.status is OutboundMessageStatus.UNCERTAIN
    assert reconciliations.reconciliation.status is OutboundSendReconciliationStatus.PENDING
    assert reconciliations.reconciliation.failure_reason == (
        "stale_dispatch_recovered_without_redispatch"
    )
    assert reconciliations.reconciliation.resolved_at is None
    assert not failures.failures
    assert len(signals.entries) == 1