from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.application.ports.repositories import ExternalEventRepository
from app.domain.common.ids import LeadId, WorkspaceId
from app.domain.crm_sync import ExternalEvent, ExternalEventStatus

_INTERNAL_PROVIDER = "internal"


async def create_internal_external_event(
    *,
    external_event_repository: ExternalEventRepository,
    workspace_id: WorkspaceId,
    lead_id: LeadId,
    event_type: str,
    now: datetime,
    payload_redacted: Mapping[str, object] | None = None,
    provider_event_id: str | None = None,
    id_generator: Callable[[], UUID] = uuid4,
) -> ExternalEvent:
    if provider_event_id is not None:
        existing = await external_event_repository.get_by_provider_event_id(
            workspace_id,
            _INTERNAL_PROVIDER,
            provider_event_id,
        )
        if existing is not None:
            return existing
    external_event_id = id_generator()
    event = ExternalEvent(
        external_event_id=external_event_id,
        workspace_id=workspace_id,
        provider=_INTERNAL_PROVIDER,
        event_type=event_type,
        provider_event_id=(provider_event_id or f"{event_type}:{lead_id}:{external_event_id}"),
        crm_lead_id=None,
        lead_id=lead_id,
        received_at=now,
        processed_at=None,
        status=ExternalEventStatus.PENDING,
        payload_redacted=dict(payload_redacted or {}),
        failure_reason=None,
        created_at=now,
        updated_at=now,
    )
    return await external_event_repository.save(event)


async def update_internal_external_event_status(
    *,
    external_event_repository: ExternalEventRepository,
    event: ExternalEvent,
    status: ExternalEventStatus,
    now: datetime,
    failure_reason: str | None = None,
) -> ExternalEvent:
    processed_at = now if status == ExternalEventStatus.PROCESSED else event.processed_at
    return await external_event_repository.save(
        replace(
            event,
            status=status,
            processed_at=processed_at,
            failure_reason=failure_reason,
            updated_at=now,
        )
    )
