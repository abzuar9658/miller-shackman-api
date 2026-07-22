from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
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
from app.infrastructure.persistence.postgres.models import UserModel, WorkspaceModel

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222201")
USER_ID = UUID("22222222-2222-2222-2222-222222222202")
SECOND_USER_ID = UUID("22222222-2222-2222-2222-222222222203")


@pytest.mark.asyncio
async def test_crm_agent_repository_upserts_by_provider_identity(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    repository = PostgresCRMAgentRepository(postgres_session)
    first = await repository.save(_agent(name="Alex Agent"))

    updated = await repository.save(
        _agent(agent_record_id=uuid4(), name="Alex Updated", is_active=False)
    )
    fetched = await repository.get_by_external_id(
        WORKSPACE_ID,
        CRMProvider.FOLLOW_UP_BOSS,
        "fub-user-123",
    )
    listed = await repository.list_for_workspace(WORKSPACE_ID)

    assert updated.agent_record_id == first.agent_record_id
    assert updated.name == "Alex Updated"
    assert updated.is_active is False
    assert fetched == updated
    assert listed == (updated,)


@pytest.mark.asyncio
async def test_workspace_agent_crm_mapping_repository_allows_multiple_crm_agents_for_same_app_user(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    agent_repository = PostgresCRMAgentRepository(postgres_session)
    mapping_repository = PostgresWorkspaceAgentCRMMappingRepository(postgres_session)
    first_agent = await agent_repository.save(_agent(external_agent_id="fub-user-1"))
    second_agent = await agent_repository.save(_agent(external_agent_id="fub-user-2"))

    verified = await mapping_repository.save(
        _mapping(first_agent.agent_record_id, USER_ID, CRMAgentMappingStatus.VERIFIED)
    )
    suggested_same_user = await mapping_repository.save(
        _mapping(second_agent.agent_record_id, USER_ID, CRMAgentMappingStatus.SUGGESTED)
    )
    fetched = await mapping_repository.get_by_crm_agent_record_id(
        WORKSPACE_ID,
        first_agent.agent_record_id,
    )
    fetched_by_id = await mapping_repository.get_by_id(WORKSPACE_ID, verified.mapping_id)
    overridden = await mapping_repository.save(
        _mapping(second_agent.agent_record_id, USER_ID, CRMAgentMappingStatus.OVERRIDDEN)
    )
    fetched_second = await mapping_repository.get_by_crm_agent_record_id(
        WORKSPACE_ID,
        second_agent.agent_record_id,
    )
    listed = await mapping_repository.list_for_workspace(WORKSPACE_ID)

    assert fetched == verified
    assert fetched_by_id == verified
    assert suggested_same_user.app_user_id == USER_ID
    assert overridden.app_user_id == USER_ID
    assert overridden.mapping_status == CRMAgentMappingStatus.OVERRIDDEN
    assert fetched_second == overridden
    assert set(listed) == {verified, overridden}


@pytest.mark.asyncio
async def test_workspace_agent_mapping_config_repository_saves_fallback_user(
    postgres_session: AsyncSession,
) -> None:
    await _seed_workspace(postgres_session)
    repository = PostgresWorkspaceAgentMappingConfigRepository(postgres_session)

    saved = await repository.save(
        WorkspaceAgentMappingConfig(
            workspace_id=WORKSPACE_ID,
            unmapped_assignment_fallback_user_id=USER_ID,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    fetched = await repository.get_by_workspace_id(WORKSPACE_ID)

    assert saved.unmapped_assignment_fallback_user_id == USER_ID
    assert fetched == saved


async def _seed_workspace(session: AsyncSession) -> None:
    session.add(
        WorkspaceModel(
            workspace_id=WORKSPACE_ID,
            name="Mapping Test Workspace",
            status="active",
            default_timezone="America/Chicago",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    for user_id, email in (
        (USER_ID, "manager@example.com"),
        (SECOND_USER_ID, "agent@example.com"),
    ):
        session.add(
            UserModel(
                user_id=user_id,
                email=email,
                email_normalized=email,
                full_name="Mapping User",
                status="active",
                email_verified_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await session.flush()


def _agent(
    *,
    agent_record_id: UUID | None = None,
    external_agent_id: str = "fub-user-123",
    name: str = "Alex Agent",
    is_active: bool = True,
) -> CRMAgent:
    return CRMAgent(
        agent_record_id=agent_record_id or uuid4(),
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id=external_agent_id,
        name=name,
        email="alex@example.com",
        email_normalized="alex@example.com",
        phone="+15555550123",
        is_active=is_active,
        last_seen_at=NOW,
        raw_payload={"provider": "follow_up_boss"},
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping(
    crm_agent_record_id: UUID,
    app_user_id: UUID,
    status: CRMAgentMappingStatus,
) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=uuid4(),
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=crm_agent_record_id,
        app_user_id=app_user_id,
        mapping_status=status,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        resolved_by_user_id=SECOND_USER_ID,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
