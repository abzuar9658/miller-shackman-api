from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.crm_sync import WorkspaceCRMSyncConfig
from app.infrastructure.persistence.postgres.models import WorkspaceCRMSyncConfigModel
from app.infrastructure.persistence.postgres.workspace_crm_sync_config_repository import (
    PostgresWorkspaceCRMSyncConfigRepository,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def all(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._results.pop(0)


def test_get_by_workspace_id_maps_config() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_config_model())])

    result = _run(
        PostgresWorkspaceCRMSyncConfigRepository(cast(AsyncSession, session)).get_by_workspace_id(
            WORKSPACE_ID,
        )
    )

    assert result == _config()
    assert "workspace_crm_sync_configs" in str(session.statements[0])


def test_list_active_workspace_schedule_targets_applies_defaults() -> None:
    session = _FakeSession(
        [
            _FakeResult(
                rows=[
                    (WORKSPACE_ID, False, 900, 250, "paused"),
                    (UUID("00000000-0000-0000-0000-000000000002"), None, None, None, None),
                ]
            )
        ]
    )

    result = _run(
        PostgresWorkspaceCRMSyncConfigRepository(
            cast(AsyncSession, session)
        ).list_active_workspace_schedule_targets(limit=10, default_interval_seconds=300)
    )

    assert len(result) == 2
    assert result[0].crm_sync_enabled is False
    assert result[0].crm_sync_interval_seconds == 900
    assert result[0].max_leads_per_sync_cycle == 250
    assert result[0].automation_status.value == "paused"
    assert result[1].crm_sync_enabled is True
    assert result[1].crm_sync_interval_seconds == 300
    assert result[1].max_leads_per_sync_cycle is None
    assert result[1].automation_status.value == "active"
    assert "LEFT OUTER JOIN workspace_crm_sync_configs" in str(session.statements[0])


def test_save_maps_config_to_model() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_config_model())])

    result = _run(
        PostgresWorkspaceCRMSyncConfigRepository(cast(AsyncSession, session)).save(_config())
    )

    assert result == _config()
    assert "workspace_crm_sync_configs" in str(session.statements[0])
    assert "ON CONFLICT (workspace_id) DO UPDATE" in str(session.statements[0])


def _config_model() -> WorkspaceCRMSyncConfigModel:
    return WorkspaceCRMSyncConfigModel(
        workspace_id=WORKSPACE_ID,
        crm_sync_enabled=False,
        crm_sync_interval_seconds=900,
        max_leads_per_sync_cycle=250,
        created_at=NOW,
        updated_at=NOW,
    )


def _config() -> WorkspaceCRMSyncConfig:
    return WorkspaceCRMSyncConfig(
        workspace_id=WORKSPACE_ID,
        crm_sync_enabled=False,
        crm_sync_interval_seconds=900,
        max_leads_per_sync_cycle=250,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)