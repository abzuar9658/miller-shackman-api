from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.crm_sync import WorkspaceCRMSyncConfig, WorkspaceCRMSyncScheduleTarget
from app.domain.identity import WorkspaceStatus
from app.domain.workspace_automation import WorkspaceAutomationStatus
from app.infrastructure.persistence.postgres.models import (
    WorkspaceCRMSyncConfigModel,
    WorkspaceModel,
    WorkspaceOperationalControlModel,
)


class PostgresWorkspaceCRMSyncConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceCRMSyncConfig | None:
        result = await self._session.execute(
            select(WorkspaceCRMSyncConfigModel).where(
                WorkspaceCRMSyncConfigModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _config_from_model(model) if model else None

    async def list_active_workspace_schedule_targets(
        self,
        *,
        limit: int = 100,
        default_interval_seconds: int,
    ) -> tuple[WorkspaceCRMSyncScheduleTarget, ...]:
        result = await self._session.execute(
            select(
                WorkspaceModel.workspace_id,
                WorkspaceCRMSyncConfigModel.crm_sync_enabled,
                WorkspaceCRMSyncConfigModel.crm_sync_interval_seconds,
                WorkspaceCRMSyncConfigModel.max_leads_per_sync_cycle,
                WorkspaceOperationalControlModel.automation_status,
            )
            .select_from(WorkspaceModel)
            .outerjoin(
                WorkspaceCRMSyncConfigModel,
                WorkspaceCRMSyncConfigModel.workspace_id == WorkspaceModel.workspace_id,
            )
            .outerjoin(
                WorkspaceOperationalControlModel,
                WorkspaceOperationalControlModel.workspace_id == WorkspaceModel.workspace_id,
            )
            .where(WorkspaceModel.status == WorkspaceStatus.ACTIVE.value)
            .order_by(WorkspaceModel.created_at.asc())
            .limit(limit),
        )
        rows = result.all()
        return tuple(
            WorkspaceCRMSyncScheduleTarget(
                workspace_id=row[0],
                crm_sync_enabled=(row[1] if row[1] is not None else True),
                crm_sync_interval_seconds=(
                    row[2] if row[2] is not None else default_interval_seconds
                ),
                max_leads_per_sync_cycle=row[3],
                automation_status=(
                    WorkspaceAutomationStatus(row[4])
                    if row[4] is not None
                    else WorkspaceAutomationStatus.ACTIVE
                ),
            )
            for row in rows
        )

    async def save(self, config: WorkspaceCRMSyncConfig) -> WorkspaceCRMSyncConfig:
        now = datetime.now(UTC)
        statement = (
            insert(WorkspaceCRMSyncConfigModel)
            .values(**_config_to_values(config, now))
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_=_config_update_values(config, now),
            )
            .returning(WorkspaceCRMSyncConfigModel)
        )
        result = await self._session.execute(statement)
        return _config_from_model(result.scalar_one())


def _config_from_model(model: WorkspaceCRMSyncConfigModel) -> WorkspaceCRMSyncConfig:
    return WorkspaceCRMSyncConfig(
        workspace_id=model.workspace_id,
        crm_sync_enabled=model.crm_sync_enabled,
        crm_sync_interval_seconds=model.crm_sync_interval_seconds,
        max_leads_per_sync_cycle=model.max_leads_per_sync_cycle,
    )


def _config_to_values(config: WorkspaceCRMSyncConfig, now: datetime) -> dict[str, object]:
    return {
        "workspace_id": config.workspace_id,
        "crm_sync_enabled": config.crm_sync_enabled,
        "crm_sync_interval_seconds": config.crm_sync_interval_seconds,
        "max_leads_per_sync_cycle": config.max_leads_per_sync_cycle,
        "created_at": now,
        "updated_at": now,
    }


def _config_update_values(config: WorkspaceCRMSyncConfig, now: datetime) -> dict[str, object]:
    return {
        "crm_sync_enabled": config.crm_sync_enabled,
        "crm_sync_interval_seconds": config.crm_sync_interval_seconds,
        "max_leads_per_sync_cycle": config.max_leads_per_sync_cycle,
        "updated_at": now,
    }