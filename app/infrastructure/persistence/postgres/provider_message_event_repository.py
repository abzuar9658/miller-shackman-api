from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.outbound_message import ProviderDeliveryStatus, ProviderMessageEvent
from app.infrastructure.persistence.postgres.models import ProviderMessageEventModel


class PostgresProviderMessageEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_external_provider_event_id(
        self,
        provider: str,
        external_provider_event_id: str,
    ) -> ProviderMessageEvent | None:
        result = await self._session.execute(
            select(ProviderMessageEventModel)
            .where(ProviderMessageEventModel.provider == provider)
            .where(
                ProviderMessageEventModel.external_provider_event_id == external_provider_event_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _model_to_event(model) if model is not None else None

    async def save(self, event: ProviderMessageEvent) -> ProviderMessageEvent:
        values = _event_to_values(event)
        update_values = {
            key: value
            for key, value in values.items()
            if key
            not in {
                "provider_event_id",
                "workspace_id",
                "provider",
                "external_provider_event_id",
                "created_at",
            }
        }
        result = await self._session.execute(
            insert(ProviderMessageEventModel)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_provider_message_events_workspace_provider_event",
                set_=update_values,
            )
            .returning(ProviderMessageEventModel),
        )
        return _model_to_event(result.scalar_one())


def _event_to_values(event: ProviderMessageEvent) -> dict[str, object]:
    return {
        "provider_event_id": event.provider_event_id,
        "workspace_id": event.workspace_id,
        "provider": event.provider,
        "provider_message_id": event.provider_message_id,
        "outbound_message_id": event.outbound_message_id,
        "external_provider_event_id": event.external_provider_event_id,
        "event_type": event.event_type,
        "status": event.status.value,
        "received_at": event.received_at,
        "payload_redacted": event.payload_redacted,
        "created_at": event.created_at,
    }


def _model_to_event(model: ProviderMessageEventModel) -> ProviderMessageEvent:
    return ProviderMessageEvent(
        provider_event_id=model.provider_event_id,
        workspace_id=model.workspace_id,
        provider=model.provider,
        provider_message_id=model.provider_message_id,
        outbound_message_id=model.outbound_message_id,
        external_provider_event_id=model.external_provider_event_id,
        event_type=model.event_type,
        status=ProviderDeliveryStatus(model.status),
        received_at=model.received_at,
        payload_redacted=model.payload_redacted,
        created_at=model.created_at,
    )
