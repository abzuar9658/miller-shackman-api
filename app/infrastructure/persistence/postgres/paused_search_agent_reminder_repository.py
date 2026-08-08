from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.campaigns.paused_search_reminders import (
    PausedSearchAgentReminder,
    PausedSearchReminderStatus,
)
from app.domain.common.ids import WorkspaceId
from app.infrastructure.persistence.postgres.models import PausedSearchAgentReminderModel


class PostgresPausedSearchAgentReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(
        self,
        workspace_id: WorkspaceId,
        idempotency_key: str,
    ) -> PausedSearchAgentReminder | None:
        result = await self._session.execute(
            select(PausedSearchAgentReminderModel).where(
                PausedSearchAgentReminderModel.workspace_id == workspace_id,
                PausedSearchAgentReminderModel.idempotency_key == idempotency_key,
            )
        )
        model = result.scalar_one_or_none()
        return _from_model(model) if model is not None else None

    async def create_or_get(
        self,
        reminder: PausedSearchAgentReminder,
    ) -> PausedSearchAgentReminder:
        await self._session.execute(
            insert(PausedSearchAgentReminderModel)
            .values(**_to_values(reminder))
            .on_conflict_do_nothing(index_elements=["workspace_id", "idempotency_key"])
        )
        saved = await self.get_by_idempotency_key(
            reminder.workspace_id,
            reminder.idempotency_key,
        )
        assert saved is not None
        return saved

    async def cancel_open_for_workflow(
        self,
        *,
        workspace_id: WorkspaceId,
        workflow_id: UUID,
        now: datetime,
    ) -> int:
        result = await self._session.execute(
            update(PausedSearchAgentReminderModel)
            .where(
                PausedSearchAgentReminderModel.workspace_id == workspace_id,
                PausedSearchAgentReminderModel.workflow_id == workflow_id,
                PausedSearchAgentReminderModel.status
                == PausedSearchReminderStatus.PENDING.value,
            )
            .values(
                status=PausedSearchReminderStatus.CANCELLED.value,
                cancelled_at=now,
            )
        )
        return int(cast(CursorResult[Any], result).rowcount)


def _to_values(reminder: PausedSearchAgentReminder) -> dict[str, object]:
    return {
        "reminder_id": reminder.reminder_id,
        "workspace_id": reminder.workspace_id,
        "lead_id": reminder.lead_id,
        "workflow_id": reminder.workflow_id,
        "occurrence_id": reminder.occurrence_id,
        "assigned_user_id": reminder.assigned_user_id,
        "due_at": reminder.due_at,
        "status": reminder.status.value,
        "title": reminder.title,
        "body": reminder.body,
        "idempotency_key": reminder.idempotency_key,
        "created_at": reminder.created_at,
        "completed_at": reminder.completed_at,
        "cancelled_at": reminder.cancelled_at,
    }


def _from_model(model: PausedSearchAgentReminderModel) -> PausedSearchAgentReminder:
    return PausedSearchAgentReminder(
        reminder_id=model.reminder_id,
        workspace_id=model.workspace_id,
        lead_id=model.lead_id,
        workflow_id=model.workflow_id,
        occurrence_id=model.occurrence_id,
        assigned_user_id=model.assigned_user_id,
        due_at=model.due_at,
        status=PausedSearchReminderStatus(model.status),
        title=model.title,
        body=model.body,
        idempotency_key=model.idempotency_key,
        created_at=model.created_at,
        completed_at=model.completed_at,
        cancelled_at=model.cancelled_at,
    )