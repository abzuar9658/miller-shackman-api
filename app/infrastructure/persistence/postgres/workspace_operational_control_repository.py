from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.common.ids import WorkspaceId
from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    WorkspaceOperationalControl,
)
from app.infrastructure.persistence.postgres.models import WorkspaceOperationalControlModel


class PostgresWorkspaceOperationalControlRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_workspace_id(
        self,
        workspace_id: WorkspaceId,
    ) -> WorkspaceOperationalControl | None:
        result = await self._session.execute(
            select(WorkspaceOperationalControlModel).where(
                WorkspaceOperationalControlModel.workspace_id == workspace_id,
            ),
        )
        model = result.scalar_one_or_none()
        return _control_from_model(model) if model else None

    async def save(
        self,
        control: WorkspaceOperationalControl,
    ) -> WorkspaceOperationalControl:
        now = datetime.now(UTC)
        statement = (
            insert(WorkspaceOperationalControlModel)
            .values(
                workspace_id=control.workspace_id,
                automation_status=control.automation_status.value,
                pause_reason=control.pause_reason,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=["workspace_id"],
                set_={
                    "automation_status": control.automation_status.value,
                    "pause_reason": control.pause_reason,
                    "updated_at": now,
                },
            )
            .returning(WorkspaceOperationalControlModel)
        )
        result = await self._session.execute(statement)
        return _control_from_model(result.scalar_one())


def _control_from_model(model: WorkspaceOperationalControlModel) -> WorkspaceOperationalControl:
    return WorkspaceOperationalControl(
        workspace_id=model.workspace_id,
        automation_status=WorkspaceAutomationStatus(model.automation_status),
        pause_reason=model.pause_reason,
    )