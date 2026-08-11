from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_message import (
    OutboundMessage,
    OutboundMessageStatus,
    ProviderDeliveryStatus,
    ProviderMessageEvent,
)
from app.domain.campaigns.outbound_send_reconciliation import (
    OutboundSendReconciliation,
    OutboundSendReconciliationStatus,
)
from app.domain.campaigns.outbound_send_request import (
    OutboundSendRequest,
    OutboundSendRequestStatus,
)
from app.domain.campaigns.pre_send import ProviderSendStatus
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.compliance.contactability import ContactChannel
from app.infrastructure.persistence.postgres.models import WorkspaceModel
from app.infrastructure.persistence.postgres.outbound_message_repository import (
    PostgresOutboundMessageRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_reconciliation_repository import (
    PostgresOutboundSendReconciliationRepository,
)
from app.infrastructure.persistence.postgres.outbound_send_request_repository import (
    PostgresOutboundSendRequestRepository,
)
from app.infrastructure.persistence.postgres.provider_message_event_repository import (
    PostgresProviderMessageEventRepository,
)

NOW = datetime(2026, 7, 10, 15, 0, tzinfo=UTC)
WORKSPACE_ID = WorkspaceId("11111111-1111-1111-1111-111111111111")
LEAD_ID = LeadId("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("33333333-3333-3333-3333-333333333333")


def _message(
    *,
    provider_delivery_status: ProviderDeliveryStatus | None = None,
    provider_status_updated_at: datetime | None = None,
    delivered_at: datetime | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=MESSAGE_ID,
        workspace_id=WORKSPACE_ID,
        lead_id=LEAD_ID,
        campaign_id=UUID("44444444-4444-4444-4444-444444444444"),
        cadence_step_id="step-1",
        channel=ContactChannel.EMAIL,
        status=OutboundMessageStatus.SENT,
        idempotency_key="outbound:test",
        body="Checking in.",
        created_at=NOW,
        updated_at=NOW,
        sent_at=NOW,
        provider_send_status=ProviderSendStatus.ACCEPTED,
        provider_name="sendgrid",
        provider_message_id="msg-123",
        provider_delivery_status=provider_delivery_status,
        provider_status_updated_at=provider_status_updated_at,
        delivered_at=delivered_at,
    )


@pytest.mark.asyncio
async def test_outbound_message_provider_delivery_fields_round_trip(
    postgres_session: AsyncSession,
) -> None:
    repository = PostgresOutboundMessageRepository(postgres_session)
    saved = await repository.save(
        _message(
            provider_delivery_status=ProviderDeliveryStatus.DELIVERED,
            provider_status_updated_at=NOW,
            delivered_at=NOW,
        )
    )
    await postgres_session.commit()

    loaded = await repository.get_by_provider_message_id_for_update("sendgrid", "msg-123")

    assert loaded is not None
    assert loaded.message_id == saved.message_id
    assert loaded.provider_name == "sendgrid"
    assert loaded.provider_message_id == "msg-123"
    assert loaded.provider_delivery_status == ProviderDeliveryStatus.DELIVERED
    assert loaded.delivered_at == NOW


@pytest.mark.asyncio
async def test_pending_reconciliation_annotation_keeps_resolved_at_unset(
    postgres_session: AsyncSession,
) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()
    message = await PostgresOutboundMessageRepository(postgres_session).save(
        replace(
            _message(),
            status=OutboundMessageStatus.PENDING,
            provider_send_status=ProviderSendStatus.UNCERTAIN,
            provider_message_id=None,
            provider_delivery_status=ProviderDeliveryStatus.UNKNOWN,
            sent_at=None,
        )
    )
    repository = PostgresOutboundSendReconciliationRepository(postgres_session)
    reconciliation_id = uuid4()
    await repository.create_or_get(
        OutboundSendReconciliation(
            reconciliation_id=reconciliation_id,
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            workflow_id=uuid4(),
            temporal_workflow_id="lead-nurture-1",
            outbound_message_id=message.message_id,
            idempotency_key=message.idempotency_key,
            status=OutboundSendReconciliationStatus.PENDING,
            provider_name="sendgrid",
            provider_message_id=None,
            provider_delivery_status=ProviderDeliveryStatus.UNKNOWN,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    annotated = await repository.resolve(
        workspace_id=WORKSPACE_ID,
        reconciliation_id=reconciliation_id,
        status=OutboundSendReconciliationStatus.PENDING,
        failure_reason="provider outcome unknown",
        now=NOW,
    )

    assert annotated is not None
    assert annotated.status is OutboundSendReconciliationStatus.PENDING
    assert annotated.failure_reason == "provider outcome unknown"
    assert annotated.resolved_at is None


@pytest.mark.asyncio
async def test_outbound_send_request_claim_and_stale_recovery_never_requeues(
    postgres_session: AsyncSession,
) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    message = await PostgresOutboundMessageRepository(postgres_session).save(
        replace(
            _message(),
            status=OutboundMessageStatus.PENDING,
            provider_send_status=ProviderSendStatus.NOT_ATTEMPTED,
            provider_message_id=None,
            provider_delivery_status=None,
            sent_at=None,
        )
    )
    reconciliation = await PostgresOutboundSendReconciliationRepository(
        postgres_session
    ).create_or_get(
        OutboundSendReconciliation(
            reconciliation_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            workflow_id=uuid4(),
            temporal_workflow_id="lead-nurture-1",
            outbound_message_id=message.message_id,
            idempotency_key=message.idempotency_key,
            status=OutboundSendReconciliationStatus.PENDING,
            provider_name="sendgrid",
            provider_message_id=None,
            provider_delivery_status=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository = PostgresOutboundSendRequestRepository(postgres_session)
    request = await repository.create_or_get(
        OutboundSendRequest(
            request_id=uuid4(),
            workspace_id=WORKSPACE_ID,
            lead_id=LEAD_ID,
            workflow_id=reconciliation.workflow_id,
            temporal_workflow_id=reconciliation.temporal_workflow_id,
            outbound_message_id=message.message_id,
            reconciliation_id=reconciliation.reconciliation_id,
            idempotency_key=message.idempotency_key,
            channel=ContactChannel.EMAIL,
            provider_name="sendgrid",
            provider_payload={
                "to_email": "lead@example.com",
                "subject": "Checking in",
                "body": message.body,
                "idempotency_key": message.idempotency_key,
            },
            status=OutboundSendRequestStatus.PENDING,
            available_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    pending_count, oldest_pending_at = await repository.get_due_pending_summary(now=NOW)
    assert pending_count == 1
    assert oldest_pending_at == NOW

    claimed = await repository.claim_due_pending(now=NOW, limit=10)
    await postgres_session.commit()
    recovered = await repository.recover_stale_dispatching(
        stale_before=NOW + timedelta(minutes=1),
        now=NOW + timedelta(minutes=2),
        limit=10,
    )
    await postgres_session.commit()
    claimed_again = await repository.claim_due_pending(
        now=NOW + timedelta(minutes=3),
        limit=10,
    )

    assert len(claimed) == 1
    assert claimed[0].request_id == request.request_id
    assert claimed[0].status is OutboundSendRequestStatus.DISPATCHING
    assert len(recovered) == 1
    assert recovered[0].status is OutboundSendRequestStatus.UNCERTAIN
    assert claimed_again == ()
    pending_count, oldest_pending_at = await repository.get_due_pending_summary(
        now=NOW + timedelta(minutes=3)
    )
    assert pending_count == 0
    assert oldest_pending_at is None


@pytest.mark.asyncio
async def test_provider_message_event_repository_round_trips_and_is_idempotent(
    postgres_session: AsyncSession,
) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Test Workspace",
            status="active",
            default_timezone="UTC",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.commit()

    message_repository = PostgresOutboundMessageRepository(postgres_session)
    message = await message_repository.save(_message())
    repository = PostgresProviderMessageEventRepository(postgres_session)
    event_id = uuid4()

    event = ProviderMessageEvent(
        provider_event_id=event_id,
        workspace_id=WORKSPACE_ID,
        provider="sendgrid",
        provider_message_id="msg-123",
        outbound_message_id=message.message_id,
        external_provider_event_id="evt-123",
        event_type="delivered",
        status=ProviderDeliveryStatus.DELIVERED,
        received_at=NOW,
        payload_redacted={"event": "delivered"},
        created_at=NOW,
    )

    saved = await repository.save(event)
    duplicate = await repository.save(event)
    await postgres_session.commit()

    loaded = await repository.get_by_external_provider_event_id("sendgrid", "evt-123")

    assert saved.provider_event_id == event_id
    assert duplicate.provider_event_id == event_id
    assert loaded is not None
    assert loaded.provider_event_id == event_id
    assert loaded.workspace_id == WORKSPACE_ID
    assert loaded.outbound_message_id == message.message_id
    assert loaded.status == ProviderDeliveryStatus.DELIVERED
    assert loaded.payload_redacted == {"event": "delivered"}
