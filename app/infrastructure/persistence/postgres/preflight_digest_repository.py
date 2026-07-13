from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.domain.common.ids import CampaignId, WorkspaceId
from app.infrastructure.persistence.postgres.models import (
    PreflightDigestModel,
    PreflightVetoModel,
)


class PostgresPreflightDigestRepository(PreflightDigestRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_digests_for_workspace(
        self,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        result = await self._session.execute(
            select(PreflightDigestModel)
            .where(PreflightDigestModel.workspace_id == workspace_id)
            .order_by(PreflightDigestModel.updated_at.desc())
            .limit(limit),
        )
        models = tuple(result.scalars().all())
        records: list[PreflightDigestRecord] = []
        for model in models:
            vetoes = await self._vetoes_for_digest_model(model)
            records.append(_model_to_record(model, vetoes))
        return tuple(records)

    async def get_digest_by_id(
        self,
        workspace_id: WorkspaceId,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        result = await self._session.execute(
            select(PreflightDigestModel).where(
                PreflightDigestModel.workspace_id == workspace_id,
                PreflightDigestModel.digest_id == UUID(digest_id),
            ),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        vetoes = await self._vetoes_for_digest_model(model)
        return _model_to_record(model, vetoes)

    async def get_digest(
        self,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        result = await self._session.execute(
            _digest_statement(workspace_id, campaign_id, batch_id),
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None

        vetoes = await self._vetoes_for_digest_model(model)
        return _model_to_record(model, vetoes)

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        now = datetime.now(UTC)
        values = _record_to_digest_values(record, now=now)
        update_values = {key: value for key, value in values.items() if key != "digest_id"}
        update_values["updated_at"] = now

        await self._session.execute(
            insert(PreflightDigestModel)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_preflight_digests_workspace_campaign_batch",
                set_=update_values,
            )
            .execution_options(synchronize_session="fetch"),
        )

        for veto in record.vetoes:
            await self._insert_veto(record, veto)

    async def _vetoes_for_digest(
        self,
        *,
        workspace_id: WorkspaceId,
        campaign_id: CampaignId,
        batch_id: str,
    ) -> tuple[PreflightVetoRecord, ...]:
        result = await self._session.execute(
            select(PreflightVetoModel).where(
                PreflightVetoModel.workspace_id == workspace_id,
                PreflightVetoModel.campaign_id == campaign_id,
                PreflightVetoModel.batch_id == batch_id,
            ),
        )
        return tuple(_model_to_veto_record(model) for model in result.scalars().all())

    async def _vetoes_for_digest_model(
        self,
        model: PreflightDigestModel,
    ) -> tuple[PreflightVetoRecord, ...]:
        return await self._vetoes_for_digest(
            workspace_id=model.workspace_id,
            campaign_id=model.campaign_id,
            batch_id=model.batch_id,
        )

    async def _insert_veto(
        self,
        record: PreflightDigestRecord,
        veto: PreflightVetoRecord,
    ) -> None:
        await self._session.execute(
            insert(PreflightVetoModel)
            .values(
                workspace_id=record.workspace_id,
                campaign_id=record.campaign_id,
                batch_id=record.batch_id,
                digest_id=UUID(record.digest_id),
                lead_id=veto.lead_id,
                actor_user_id=UUID(veto.actor_id),
                reason=veto.reason or "",
                idempotency_key=veto.idempotency_key,
                created_at=veto.recorded_at,
            )
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "idempotency_key"],
            )
            .execution_options(synchronize_session="fetch"),
        )


def _digest_statement(
    workspace_id: WorkspaceId,
    campaign_id: CampaignId,
    batch_id: str,
) -> Select[tuple[PreflightDigestModel]]:
    return select(PreflightDigestModel).where(
        PreflightDigestModel.workspace_id == workspace_id,
        PreflightDigestModel.campaign_id == campaign_id,
        PreflightDigestModel.batch_id == batch_id,
    )


def _model_to_record(
    model: PreflightDigestModel,
    vetoes: tuple[PreflightVetoRecord, ...],
) -> PreflightDigestRecord:
    return PreflightDigestRecord(
        digest_id=str(model.digest_id),
        workspace_id=model.workspace_id,
        campaign_id=model.campaign_id,
        batch_id=model.batch_id,
        status=PreflightDigestIssueStatus(model.status),
        entries=_jsonb_to_entries(model.entries),
        notification_records=_jsonb_to_notification_records(model.notification_records),
        digest_sent_at=model.sent_at,
        veto_window_expires_at=model.veto_window_expires_at,
        vetoes=vetoes,
    )


def _record_to_digest_values(
    record: PreflightDigestRecord,
    *,
    now: datetime,
) -> dict[str, object]:
    return {
        "digest_id": UUID(record.digest_id),
        "workspace_id": record.workspace_id,
        "campaign_id": record.campaign_id,
        "batch_id": record.batch_id,
        "status": record.status.value,
        "sent_at": record.digest_sent_at,
        "veto_window_expires_at": record.veto_window_expires_at,
        "entries": _entries_to_jsonb(record.entries),
        "notification_records": _notification_records_to_jsonb(record.notification_records),
        "created_at": record.digest_sent_at or now,
        "updated_at": now,
    }


def _entries_to_jsonb(
    entries: tuple[PreflightDigestEntry, ...],
) -> list[dict[str, object]]:
    return [
        {
            "lead_id": str(entry.lead_id),
            "recipient_id": entry.recipient_id,
            "recipient_destination": entry.recipient_destination,
            "display_name": entry.display_name,
        }
        for entry in entries
    ]


def _jsonb_to_entries(data: list[dict[str, object]]) -> tuple[PreflightDigestEntry, ...]:
    return tuple(
        PreflightDigestEntry(
            lead_id=UUID(str(item["lead_id"])),
            recipient_id=str(item["recipient_id"]),
            recipient_destination=str(item["recipient_destination"]),
            display_name=str(item["display_name"]),
        )
        for item in data
    )


def _notification_records_to_jsonb(
    records: tuple[PreflightDigestNotificationRecord, ...],
) -> list[dict[str, object]]:
    return [
        {
            "recipient_id": record.recipient_id,
            "idempotency_key": record.idempotency_key,
            "accepted": record.accepted,
            "provider_reference": record.provider_reference,
            "uncertain": record.uncertain,
        }
        for record in records
    ]


def _jsonb_to_notification_records(
    data: list[dict[str, object]],
) -> tuple[PreflightDigestNotificationRecord, ...]:
    return tuple(
        PreflightDigestNotificationRecord(
            recipient_id=str(item["recipient_id"]),
            idempotency_key=str(item["idempotency_key"]),
            accepted=bool(item["accepted"]),
            provider_reference=_str_or_none(item.get("provider_reference")),
            uncertain=bool(item.get("uncertain", False)),
        )
        for item in data
    )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _model_to_veto_record(model: PreflightVetoModel) -> PreflightVetoRecord:
    return PreflightVetoRecord(
        lead_id=model.lead_id,
        actor_id=str(model.actor_user_id),
        recorded_at=model.created_at,
        idempotency_key=model.idempotency_key,
        reason=model.reason or None,
    )
