from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.event_bus import EventBus
from app.application.ports.repositories import (
    LeadWorkflowRepository,
    OutboundSendReconciliationRepository,
    PausedSearchOccurrenceRepository,
    ProviderDeliveryMessageRepository,
    ProviderMessageEventRepository,
    TemporalSignalOutboxRepository,
)
from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
    ProviderMessageEvent,
)
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.paused_search_occurrences import RecurringOccurrenceStatus
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import WorkspaceId
from app.domain.events import AggregateType, DomainEvent, DomainEventType
from app.domain.workflows import TemporalSignalName, TemporalSignalOutboxEntry

_FAILURE_STATUSES = frozenset(
    {
        ProviderDeliveryStatus.FAILED,
        ProviderDeliveryStatus.UNDELIVERED,
        ProviderDeliveryStatus.BOUNCED,
        ProviderDeliveryStatus.DROPPED,
    },
)


class ProcessProviderDeliveryCallbackStatus(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"


class ProcessProviderDeliveryCallbackReasonCode(StrEnum):
    DUPLICATE_EVENT = "duplicate_event"
    OUTBOUND_MESSAGE_NOT_FOUND = "outbound_message_not_found"


def _empty_payload() -> Mapping[str, object]:
    return {}


@dataclass(frozen=True)
class ProviderDeliveryCallback:
    provider: str
    provider_event_id: str
    provider_message_id: str
    event_type: str
    status: ProviderDeliveryStatus
    occurred_at: datetime
    failure_reason: str | None = None
    payload_redacted: Mapping[str, object] = field(default_factory=_empty_payload)
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ProcessProviderDeliveryCallbackResult:
    status: ProcessProviderDeliveryCallbackStatus
    provider_event_id: UUID | None = None
    message_id: UUID | None = None
    provider_delivery_status: ProviderDeliveryStatus | None = None
    reasons: tuple[ProcessProviderDeliveryCallbackReasonCode, ...] = ()


async def process_provider_delivery_callback(
    *,
    callback: ProviderDeliveryCallback,
    message_repository: ProviderDeliveryMessageRepository,
    provider_message_event_repository: ProviderMessageEventRepository,
    occurrence_repository: PausedSearchOccurrenceRepository | None = None,
    reconciliation_repository: OutboundSendReconciliationRepository | None = None,
    lead_workflow_repository: LeadWorkflowRepository | None = None,
    temporal_signal_outbox_repository: TemporalSignalOutboxRepository | None = None,
    now: datetime,
    event_bus: EventBus | None = None,
    provider_message_event_id_factory: Callable[[], UUID] | None = None,
    workspace_id: WorkspaceId | None = None,
) -> ProcessProviderDeliveryCallbackResult:
    existing = await provider_message_event_repository.get_by_external_provider_event_id(
        callback.provider,
        callback.provider_event_id,
    )
    if existing is not None:
        return ProcessProviderDeliveryCallbackResult(
            status=ProcessProviderDeliveryCallbackStatus.DUPLICATE,
            provider_event_id=existing.provider_event_id,
            message_id=existing.outbound_message_id,
            provider_delivery_status=existing.status,
            reasons=(ProcessProviderDeliveryCallbackReasonCode.DUPLICATE_EVENT,),
        )

    # Identify the target lead without taking row locks so the locks below can
    # be acquired in the canonical order shared with the send/dispatch paths:
    # workflow -> outbound message -> reconciliation -> occurrence. Locking the
    # workflow last (as this path previously did) inverted that order and could
    # deadlock against cadence execution and revalidation.
    probe_message = await message_repository.get_by_provider_message_id(
        callback.provider,
        callback.provider_message_id,
    )
    probe_reconciliation = None
    if (
        probe_message is None
        and callback.idempotency_key is not None
        and reconciliation_repository is not None
        and workspace_id is not None
    ):
        probe_reconciliation = await reconciliation_repository.get_by_idempotency_key(
            workspace_id,
            callback.idempotency_key,
        )
    if probe_message is not None:
        lead_workspace_id = probe_message.workspace_id
        lead_id = probe_message.lead_id
    elif probe_reconciliation is not None:
        lead_workspace_id = probe_reconciliation.workspace_id
        lead_id = probe_reconciliation.lead_id
    else:
        return ProcessProviderDeliveryCallbackResult(
            status=ProcessProviderDeliveryCallbackStatus.IGNORED,
            reasons=(ProcessProviderDeliveryCallbackReasonCode.OUTBOUND_MESSAGE_NOT_FOUND,),
        )

    workflow = None
    if lead_workflow_repository is not None:
        workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
            lead_workspace_id,
            lead_id,
        )

    message = await message_repository.get_by_provider_message_id_for_update(
        callback.provider,
        callback.provider_message_id,
    )
    reconciliation = None
    if (
        message is None
        and probe_reconciliation is not None
        and callback.idempotency_key is not None
        and reconciliation_repository is not None
        and workspace_id is not None
    ):
        reconciliation = await reconciliation_repository.get_by_idempotency_key_for_update(
            workspace_id,
            callback.idempotency_key,
        )
        if reconciliation is not None:
            message = await message_repository.get_by_id_for_update(
                reconciliation.workspace_id,
                reconciliation.outbound_message_id,
            )
    if message is None:
        return ProcessProviderDeliveryCallbackResult(
            status=ProcessProviderDeliveryCallbackStatus.IGNORED,
            reasons=(ProcessProviderDeliveryCallbackReasonCode.OUTBOUND_MESSAGE_NOT_FOUND,),
        )

    saved_event = await provider_message_event_repository.save(
        ProviderMessageEvent(
            provider_event_id=(provider_message_event_id_factory or uuid4)(),
            workspace_id=message.workspace_id,
            provider=callback.provider,
            provider_message_id=callback.provider_message_id,
            outbound_message_id=message.message_id,
            external_provider_event_id=callback.provider_event_id,
            event_type=callback.event_type,
            status=callback.status,
            received_at=callback.occurred_at,
            payload_redacted=dict(callback.payload_redacted),
            created_at=now,
        ),
    )
    updated_message = _reconcile_message(message=message, callback=callback, now=now)
    reconciliation_status: OutboundSendReconciliationStatus | None = None
    reconciliation_resolved = None
    if reconciliation_repository is not None:
        if reconciliation is None:
            reconciliation = (
                await reconciliation_repository.get_by_outbound_message_id_for_update(
                    message.workspace_id,
                    message.message_id,
                )
            )
        if (
            reconciliation is not None
            and reconciliation.status is OutboundSendReconciliationStatus.PENDING
        ):
            reconciliation_status = _reconciliation_status_after_delivery(callback.status)
            if reconciliation_status is not None:
                reconciliation_resolved = await reconciliation_repository.resolve(
                    workspace_id=message.workspace_id,
                    reconciliation_id=reconciliation.reconciliation_id,
                    status=reconciliation_status,
                    now=now,
                    provider_message_id=callback.provider_message_id,
                    provider_delivery_status=callback.status,
                    failure_reason=callback.failure_reason,
                )
                if reconciliation_status is OutboundSendReconciliationStatus.CONFIRMED:
                    updated_message = replace(
                        updated_message,
                        status=OutboundMessageStatus.SENT,
                        provider_send_status=ProviderSendStatus.ACCEPTED,
                        provider_name=callback.provider,
                        provider_message_id=callback.provider_message_id,
                        sent_at=updated_message.sent_at or callback.occurred_at,
                        failure_reason=None,
                        updated_at=now,
                    )
                elif reconciliation_status is OutboundSendReconciliationStatus.FAILED:
                    updated_message = replace(
                        updated_message,
                        status=OutboundMessageStatus.FAILED,
                        provider_name=callback.provider,
                        provider_message_id=callback.provider_message_id,
                        failure_reason=callback.failure_reason,
                        updated_at=now,
                    )
    if (
        reconciliation_resolved is not None
        and reconciliation_status is OutboundSendReconciliationStatus.CONFIRMED
        and temporal_signal_outbox_repository is not None
    ):
        await temporal_signal_outbox_repository.append(
            TemporalSignalOutboxEntry(
                temporal_signal_id=uuid4(),
                workspace_id=message.workspace_id,
                workflow_id=reconciliation_resolved.workflow_id,
                temporal_workflow_id=reconciliation_resolved.temporal_workflow_id,
                signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
                payload={
                    "lead_id": str(message.lead_id),
                    "outbound_message_id": str(message.message_id),
                    "reconciliation_id": str(reconciliation_resolved.reconciliation_id),
                    "provider_message_id": callback.provider_message_id,
                    "status": reconciliation_status.value,
                    "occurred_at": callback.occurred_at.isoformat(),
                    "reason": "provider_delivery_reconciled",
                },
                idempotency_key=(
                    "provider-delivery-reconciled:"
                    f"{message.workspace_id}:{reconciliation_resolved.reconciliation_id}:"
                    f"{callback.provider_event_id}"
                ),
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )
    if updated_message != message:
        updated_message = await message_repository.save(updated_message)
        await _publish_delivery_event(
            event_bus=event_bus,
            callback=callback,
            message=updated_message,
            now=now,
        )

    if occurrence_repository is not None:
        occurrence = await occurrence_repository.get_by_provider_message_id_for_update(
            message.workspace_id,
            callback.provider_message_id,
        )
        if occurrence is not None:
            was_uncertain = occurrence.status == RecurringOccurrenceStatus.UNCERTAIN
            occurrence_status = _occurrence_status_after_delivery(
                occurrence.status,
                callback.status,
            )
            updated_occurrence = await occurrence_repository.update_status(
                workspace_id=message.workspace_id,
                occurrence_id=occurrence.occurrence_id,
                status=occurrence_status.value,
                now=now,
                provider_message_id=callback.provider_message_id,
                provider_delivery_status=updated_message.provider_delivery_status,
                failure_reason=updated_message.failure_reason,
            )
            # The lead's workflow row was already locked (canonical order)
            # before the message/occurrence locks; only re-lock if the
            # occurrence unexpectedly belongs to a different lead.
            if lead_workflow_repository is not None and (
                workflow is None or occurrence.lead_id != lead_id
            ):
                workflow = await lead_workflow_repository.get_latest_for_lead_for_update(
                    message.workspace_id,
                    occurrence.lead_id,
                )
            if (
                was_uncertain
                and occurrence_status == RecurringOccurrenceStatus.SENT
                and updated_occurrence is not None
                and updated_occurrence.logical_touch_count == 1
                and workflow is not None
                and workflow.workflow_id == occurrence.workflow_id
            ):
                assert lead_workflow_repository is not None
                await lead_workflow_repository.save(
                    replace(
                        workflow,
                        logical_touch_count=workflow.logical_touch_count + 1,
                        updated_at=now,
                    )
                )
            if (
                was_uncertain
                and temporal_signal_outbox_repository is not None
                and workflow is not None
                and workflow.workflow_id == occurrence.workflow_id
            ):
                await temporal_signal_outbox_repository.append(
                    TemporalSignalOutboxEntry(
                        temporal_signal_id=uuid4(),
                        workspace_id=message.workspace_id,
                        workflow_id=workflow.workflow_id,
                        temporal_workflow_id=workflow.temporal_workflow_id,
                        signal_name=TemporalSignalName.BLOCKED_REVIEW_COMPLETED,
                        payload={
                            "lead_id": str(occurrence.lead_id),
                            "occurrence_id": str(occurrence.occurrence_id),
                            "provider_message_id": callback.provider_message_id,
                            "status": occurrence_status.value,
                            "occurred_at": callback.occurred_at.isoformat(),
                            "reason": "provider_delivery_reconciled",
                        },
                        idempotency_key=(
                            "provider-delivery-reconciled:"
                            f"{message.workspace_id}:{occurrence.occurrence_id}:"
                            f"{callback.provider_event_id}"
                        ),
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )

    return ProcessProviderDeliveryCallbackResult(
        status=ProcessProviderDeliveryCallbackStatus.PROCESSED,
        provider_event_id=saved_event.provider_event_id,
        message_id=updated_message.message_id,
        provider_delivery_status=updated_message.provider_delivery_status,
    )


def _reconciliation_status_after_delivery(
    delivery_status: ProviderDeliveryStatus,
) -> OutboundSendReconciliationStatus | None:
    if delivery_status in {
        ProviderDeliveryStatus.ACCEPTED,
        ProviderDeliveryStatus.DELIVERED,
    }:
        return OutboundSendReconciliationStatus.CONFIRMED
    if delivery_status in _FAILURE_STATUSES:
        return OutboundSendReconciliationStatus.FAILED
    return None


def _occurrence_status_after_delivery(
    current: RecurringOccurrenceStatus,
    delivery_status: ProviderDeliveryStatus,
) -> RecurringOccurrenceStatus:
    if current != RecurringOccurrenceStatus.UNCERTAIN:
        return current
    if delivery_status in {
        ProviderDeliveryStatus.ACCEPTED,
        ProviderDeliveryStatus.DELIVERED,
    }:
        return RecurringOccurrenceStatus.SENT
    if delivery_status in _FAILURE_STATUSES:
        return RecurringOccurrenceStatus.FAILED
    return RecurringOccurrenceStatus.UNCERTAIN


def _reconcile_message(
    *,
    message: OutboundMessage,
    callback: ProviderDeliveryCallback,
    now: datetime,
) -> OutboundMessage:
    current_status = message.provider_delivery_status
    current_status_updated_at = message.provider_status_updated_at

    if current_status == ProviderDeliveryStatus.DELIVERED:
        return message

    if callback.status == ProviderDeliveryStatus.DELIVERED:
        delivered_at = (
            min(message.delivered_at, callback.occurred_at)
            if message.delivered_at is not None
            else callback.occurred_at
        )
        return replace(
            message,
            provider_delivery_status=ProviderDeliveryStatus.DELIVERED,
            provider_status_updated_at=callback.occurred_at,
            delivered_at=delivered_at,
            failure_reason=None,
            updated_at=now,
        )

    if current_status in _FAILURE_STATUSES and callback.status not in _FAILURE_STATUSES:
        return message

    if callback.status in _FAILURE_STATUSES:
        if current_status in _FAILURE_STATUSES and _is_older(
            callback.occurred_at, current_status_updated_at
        ):
            return message
        return replace(
            message,
            provider_delivery_status=callback.status,
            provider_status_updated_at=callback.occurred_at,
            failure_reason=callback.failure_reason,
            updated_at=now,
        )

    if _is_older(callback.occurred_at, current_status_updated_at):
        return message

    return replace(
        message,
        provider_delivery_status=callback.status,
        provider_status_updated_at=callback.occurred_at,
        failure_reason=None,
        updated_at=now,
    )


def _is_older(incoming_at: datetime, current_at: datetime | None) -> bool:
    return current_at is not None and incoming_at < current_at


async def _publish_delivery_event(
    *,
    event_bus: EventBus | None,
    callback: ProviderDeliveryCallback,
    message: OutboundMessage,
    now: datetime,
) -> None:
    if event_bus is None:
        return
    event_type = DomainEventType.MESSAGE_DELIVERED
    if callback.status in _FAILURE_STATUSES:
        event_type = DomainEventType.MESSAGE_DELIVERY_FAILED
    await event_bus.publish(
        DomainEvent(
            workspace_id=message.workspace_id,
            aggregate_type=AggregateType.MESSAGE,
            aggregate_id=message.message_id,
            event_type=event_type,
            payload={
                "message_id": str(message.message_id),
                "lead_id": str(message.lead_id),
                "campaign_id": str(message.campaign_id),
                "provider": callback.provider,
                "provider_event_id": callback.provider_event_id,
                "provider_message_id": callback.provider_message_id,
                "provider_delivery_status": callback.status.value,
                "provider_event_type": callback.event_type,
                "failure_reason": callback.failure_reason,
                "occurred_at": callback.occurred_at.isoformat(),
                "processed_at": now.isoformat(),
            },
        ),
    )
