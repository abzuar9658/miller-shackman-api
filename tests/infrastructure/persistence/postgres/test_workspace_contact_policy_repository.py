from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.compliance.contactability import WorkspaceContactPolicy
from app.infrastructure.persistence.postgres.models import WorkspaceContactPolicyModel
from app.infrastructure.persistence.postgres.workspace_contact_policy_repository import (
    PostgresWorkspaceContactPolicyRepository,
)

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


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


def test_get_by_workspace_id_maps_policy() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_policy_model())])

    result = _run(
        PostgresWorkspaceContactPolicyRepository(cast(AsyncSession, session)).get_by_workspace_id(
            WORKSPACE_ID,
        )
    )

    assert result == _policy()
    assert "workspace_contact_policies" in str(session.statements[0])


def test_save_maps_policy_to_model() -> None:
    session = _FakeSession([_FakeResult(scalar_value=_policy_model())])

    result = _run(
        PostgresWorkspaceContactPolicyRepository(cast(AsyncSession, session)).save(_policy())
    )

    assert result == _policy()
    assert "workspace_contact_policies" in str(session.statements[0])


def _policy_model() -> WorkspaceContactPolicyModel:
    return WorkspaceContactPolicyModel(
        workspace_id=WORKSPACE_ID,
        quiet_hours_enabled=True,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        inbound_email_address="inbound@example.com",
        created_at=NOW,
        updated_at=NOW,
    )


def _policy() -> WorkspaceContactPolicy:
    return WorkspaceContactPolicy(
        workspace_id=WORKSPACE_ID,
        quiet_hours_enabled=True,
        quiet_hours_start=time(10, 0),
        quiet_hours_end=time(17, 0),
        inbound_email_address="inbound@example.com",
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
