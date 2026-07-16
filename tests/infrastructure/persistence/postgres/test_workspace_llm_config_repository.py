from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.llm import WorkspaceLLMConfig
from app.infrastructure.persistence.postgres.models import WorkspaceLLMConfigModel
from app.infrastructure.persistence.postgres.workspace_llm_config_repository import (
    PostgresWorkspaceLLMConfigRepository,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _FakeResult:
    def __init__(self, *, scalar_value: object | None = None) -> None:
        self._scalar_value = scalar_value

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value


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
        PostgresWorkspaceLLMConfigRepository(cast(AsyncSession, session)).get_by_workspace_id(
            WORKSPACE_ID,
        )
    )

    assert result == _config()
    assert "workspace_llm_configs" in str(session.statements[0])


def test_save_maps_config_to_model() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_config_model())])

    result = _run(
        PostgresWorkspaceLLMConfigRepository(cast(AsyncSession, session)).save(_config())
    )

    assert result == _config()
    assert "workspace_llm_configs" in str(session.statements[0])
    assert "ON CONFLICT (workspace_id) DO UPDATE" in str(session.statements[0])


def _config_model() -> WorkspaceLLMConfigModel:
    return WorkspaceLLMConfigModel(
        workspace_id=WORKSPACE_ID,
        openrouter_model="openai/gpt-4.1-mini",
        created_at=NOW,
        updated_at=NOW,
    )


def _config() -> WorkspaceLLMConfig:
    return WorkspaceLLMConfig(
        workspace_id=WORKSPACE_ID,
        openrouter_model="openai/gpt-4.1-mini",
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)