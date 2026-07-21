from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.conversations import WorkspaceHandoffConfig
from app.infrastructure.persistence.postgres.models import WorkspaceHandoffConfigModel


class PostgresWorkspaceHandoffConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceHandoffConfig | None:
        result = await self._session.execute(
            select(WorkspaceHandoffConfigModel).where(
                WorkspaceHandoffConfigModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _config_from_model(model) if model else None

    async def save(self, config: WorkspaceHandoffConfig) -> WorkspaceHandoffConfig:
        now = datetime.now(UTC)
        statement = (
            insert(WorkspaceHandoffConfigModel)
            .values(**_config_to_values(config, now))
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_=_config_update_values(config, now),
            )
            .returning(WorkspaceHandoffConfigModel)
        )
        result = await self._session.execute(statement)
        return _config_from_model(result.scalar_one())


def _config_from_model(model: WorkspaceHandoffConfigModel) -> WorkspaceHandoffConfig:
    return WorkspaceHandoffConfig(
        workspace_id=model.workspace_id,
        fallback_recipient_email=model.fallback_recipient_email,
        crm_handoff_tag=model.crm_handoff_tag,
        crm_review_tag=model.crm_review_tag,
        crm_custom_fields=model.crm_custom_fields,
        crm_snapshot_summary_field=model.crm_snapshot_summary_field,
        crm_snapshot_status_field=model.crm_snapshot_status_field,
        crm_snapshot_latest_inbound_field=model.crm_snapshot_latest_inbound_field,
        crm_snapshot_latest_outbound_field=model.crm_snapshot_latest_outbound_field,
        crm_snapshot_last_activity_at_field=model.crm_snapshot_last_activity_at_field,
    )


def _config_to_values(
    config: WorkspaceHandoffConfig,
    now: datetime,
) -> dict[str, object]:
    return {
        "workspace_id": config.workspace_id,
        "fallback_recipient_email": config.fallback_recipient_email,
        "crm_handoff_tag": config.crm_handoff_tag,
        "crm_review_tag": config.crm_review_tag,
        "crm_custom_fields": dict(config.crm_custom_fields),
        "crm_snapshot_summary_field": config.crm_snapshot_summary_field,
        "crm_snapshot_status_field": config.crm_snapshot_status_field,
        "crm_snapshot_latest_inbound_field": config.crm_snapshot_latest_inbound_field,
        "crm_snapshot_latest_outbound_field": config.crm_snapshot_latest_outbound_field,
        "crm_snapshot_last_activity_at_field": config.crm_snapshot_last_activity_at_field,
        "created_at": now,
        "updated_at": now,
    }


def _config_update_values(
    config: WorkspaceHandoffConfig,
    now: datetime,
) -> dict[str, object]:
    return {
        "fallback_recipient_email": config.fallback_recipient_email,
        "crm_handoff_tag": config.crm_handoff_tag,
        "crm_review_tag": config.crm_review_tag,
        "crm_custom_fields": dict(config.crm_custom_fields),
        "crm_snapshot_summary_field": config.crm_snapshot_summary_field,
        "crm_snapshot_status_field": config.crm_snapshot_status_field,
        "crm_snapshot_latest_inbound_field": config.crm_snapshot_latest_inbound_field,
        "crm_snapshot_latest_outbound_field": config.crm_snapshot_latest_outbound_field,
        "crm_snapshot_last_activity_at_field": config.crm_snapshot_last_activity_at_field,
        "updated_at": now,
    }
