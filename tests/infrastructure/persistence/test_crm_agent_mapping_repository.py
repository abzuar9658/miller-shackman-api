from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
    WorkspaceAgentMappingConfig,
)
from app.domain.leads import CRMProvider
from app.infrastructure.persistence.postgres.crm_agent_mapping_repository import (
    PostgresCRMAgentRepository,
    PostgresWorkspaceAgentCRMMappingRepository,
    PostgresWorkspaceAgentMappingConfigRepository,
)
from app.infrastructure.persistence.postgres.models import (
    CRMAgentModel,
    WorkspaceAgentCRMMappingModel,
    WorkspaceAgentMappingConfigModel,
)

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("33333333-3333-3333-3333-333333333301")
USER_ID = UUID("33333333-3333-3333-3333-333333333302")
AGENT_ID = UUID("33333333-3333-3333-3333-333333333303")
MAPPING_ID = UUID("33333333-3333-3333-3333-333333333304")


class _FakeScalarSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(
        self,
        *,
        scalar_value: object | None = None,
        scalar_values: list[object] | None = None,
    ) -> None:
        self._scalar_value = scalar_value
        self._scalar_values = scalar_values or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar_value

    def scalar_one(self) -> object:
        assert self._scalar_value is not None
        return self._scalar_value

    def scalars(self) -> _FakeScalarSequence:
        return _FakeScalarSequence(self._scalar_values)


class _FakeSession:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.statements.append(statement)
        return self._result


def test_crm_agent_repository_save_uses_provider_identity_upsert() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_agent_model()))

    saved = _run(PostgresCRMAgentRepository(cast(AsyncSession, session)).save(_agent()))

    assert saved == _agent()
    statement = str(session.statements[0])
    assert "crm_agents" in statement
    assert "ON CONFLICT (workspace_id, crm_provider, crm_agent_id) DO UPDATE" in statement


def test_workspace_agent_crm_mapping_repository_maps_and_upserts_by_crm_agent() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_mapping_model()))

    saved = _run(
        PostgresWorkspaceAgentCRMMappingRepository(cast(AsyncSession, session)).save(_mapping())
    )

    assert saved == _mapping()
    statement = str(session.statements[0])
    assert "workspace_agent_crm_mappings" in statement
    assert "ON CONFLICT (workspace_id, crm_agent_id) DO UPDATE" in statement


def test_workspace_agent_mapping_config_repository_maps_fallback_user() -> None:
    session = _FakeSession(_FakeResult(scalar_value=_config_model()))

    saved = _run(
        PostgresWorkspaceAgentMappingConfigRepository(cast(AsyncSession, session)).save(_config())
    )

    assert saved == _config()
    assert "workspace_agent_mapping_configs" in str(session.statements[0])


def _agent_model() -> CRMAgentModel:
    return CRMAgentModel(
        id=AGENT_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS.value,
        crm_agent_id="fub-user-123",
        name="Alex Agent",
        email="alex@example.com",
        email_normalized="alex@example.com",
        phone="+15555550123",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={"provider": "follow_up_boss"},
        created_at=NOW,
        updated_at=NOW,
    )


def _agent() -> CRMAgent:
    return CRMAgent(
        agent_record_id=AGENT_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id="fub-user-123",
        name="Alex Agent",
        email="alex@example.com",
        email_normalized="alex@example.com",
        phone="+15555550123",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={"provider": "follow_up_boss"},
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping_model() -> WorkspaceAgentCRMMappingModel:
    return WorkspaceAgentCRMMappingModel(
        mapping_id=MAPPING_ID,
        workspace_id=WORKSPACE_ID,
        crm_agent_id=AGENT_ID,
        app_user_id=USER_ID,
        mapping_status=CRMAgentMappingStatus.VERIFIED.value,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL.value,
        resolved_by_user_id=USER_ID,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping() -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=MAPPING_ID,
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=AGENT_ID,
        app_user_id=USER_ID,
        mapping_status=CRMAgentMappingStatus.VERIFIED,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        resolved_by_user_id=USER_ID,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _config_model() -> WorkspaceAgentMappingConfigModel:
    return WorkspaceAgentMappingConfigModel(
        workspace_id=WORKSPACE_ID,
        unmapped_assignment_fallback_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _config() -> WorkspaceAgentMappingConfig:
    return WorkspaceAgentMappingConfig(
        workspace_id=WORKSPACE_ID,
        unmapped_assignment_fallback_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    import asyncio

    return asyncio.run(coroutine)
