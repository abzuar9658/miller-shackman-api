from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.workspace_automation import (
    WorkspaceAutomationStatus,
    WorkspaceOperationalControl,
)
from app.infrastructure.persistence.postgres.models import (
    WorkspaceModel,
    WorkspaceOperationalControlModel,
)
from app.infrastructure.persistence.postgres.workspace_operational_control_repository import (
    PostgresWorkspaceOperationalControlRepository,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _Result:
    def __init__(self, value: WorkspaceOperationalControlModel) -> None:
        self._value = value

    def scalar_one(self) -> WorkspaceOperationalControlModel:
        return self._value

    def scalar_one_or_none(self) -> WorkspaceOperationalControlModel:
        return self._value


class _Session:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return self.result


def test_get_maps_recurring_flag() -> None:
    model = _model(enabled=True)
    session = _Session(_Result(model))

    result = _run(
        PostgresWorkspaceOperationalControlRepository(cast(AsyncSession, session))
        .get_by_workspace_id(WORKSPACE_ID)
    )

    assert result == _control(enabled=True)
    assert "workspace_operational_controls" in str(session.statements[0])


def test_save_writes_recurring_flag() -> None:
    model = _model(enabled=True)
    session = _Session(_Result(model))

    result = _run(
        PostgresWorkspaceOperationalControlRepository(cast(AsyncSession, session)).save(
            _control(enabled=True)
        )
    )

    assert result == _control(enabled=True)
    assert "recurring_paused_search_enabled" in str(session.statements[0])


async def test_real_postgres_round_trip_persists_recurring_flag(
    postgres_session: AsyncSession,
) -> None:
    postgres_session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Recurring flag test",
            status="active",
            default_timezone="America/Chicago",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await postgres_session.flush()

    repository = PostgresWorkspaceOperationalControlRepository(postgres_session)
    await repository.save(_control(enabled=True))
    await postgres_session.flush()

    result = await repository.get_by_workspace_id(WORKSPACE_ID)

    assert result is not None
    assert result.recurring_paused_search_enabled is True


def _model(*, enabled: bool) -> WorkspaceOperationalControlModel:
    return WorkspaceOperationalControlModel(
        workspace_id=WORKSPACE_ID,
        automation_status=WorkspaceAutomationStatus.ACTIVE.value,
        pause_reason=None,
        recurring_paused_search_enabled=enabled,
        created_at=NOW,
        updated_at=NOW,
    )


def _control(*, enabled: bool) -> WorkspaceOperationalControl:
    return WorkspaceOperationalControl(
        workspace_id=WORKSPACE_ID,
        automation_status=WorkspaceAutomationStatus.ACTIVE,
        recurring_paused_search_enabled=enabled,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)