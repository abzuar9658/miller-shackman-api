from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.crm import CRMAgentDirectoryEntry
from app.application.use_cases.sync_crm_agents import (
    SyncCRMAgentsStatus,
    sync_crm_agents_for_workspace,
)
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import User, UserStatus, WorkspaceMembershipRole
from app.domain.leads import CRMProvider

NOW = datetime(2026, 7, 21, 13, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("44444444-4444-4444-4444-444444444401")
USER_ID = UUID("44444444-4444-4444-4444-444444444402")
SECOND_USER_ID = UUID("44444444-4444-4444-4444-444444444403")
AGENT_ID = UUID("44444444-4444-4444-4444-444444444404")
MAPPING_ID = UUID("44444444-4444-4444-4444-444444444405")


class FakeCRMAgentDirectorySource:
    def __init__(self, agents: tuple[CRMAgentDirectoryEntry, ...]) -> None:
        self.agents = agents
        self.calls: list[UUID] = []

    async def list_agents(self, workspace_id: UUID) -> list[CRMAgentDirectoryEntry]:
        self.calls.append(workspace_id)
        return list(self.agents)


class FakeCRMAgentRepository:
    def __init__(self, agents: tuple[CRMAgent, ...] = ()) -> None:
        self.by_external_id = {agent.external_agent_id: agent for agent in agents}

    async def get_by_record_id(self, workspace_id: UUID, agent_record_id: UUID) -> CRMAgent | None:
        _ = workspace_id
        return next(
            (
                agent
                for agent in self.by_external_id.values()
                if agent.agent_record_id == agent_record_id
            ),
            None,
        )

    async def get_by_external_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        _ = (workspace_id, crm_provider)
        return self.by_external_id.get(external_agent_id)

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[CRMAgent, ...]:
        return tuple(
            agent for agent in self.by_external_id.values() if agent.workspace_id == workspace_id
        )

    async def save(self, agent: CRMAgent) -> CRMAgent:
        self.by_external_id[agent.external_agent_id] = agent
        return agent


class FakeWorkspaceAgentCRMMappingRepository:
    def __init__(self, mappings: tuple[WorkspaceAgentCRMMapping, ...] = ()) -> None:
        self.by_agent_id = {mapping.crm_agent_record_id: mapping for mapping in mappings}

    async def get_by_id(
        self,
        workspace_id: UUID,
        mapping_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.by_agent_id.values()
                if mapping.workspace_id == workspace_id and mapping.mapping_id == mapping_id
            ),
            None,
        )

    async def get_by_crm_agent_record_id(
        self,
        workspace_id: UUID,
        crm_agent_record_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        mapping = self.by_agent_id.get(crm_agent_record_id)
        if mapping is None or mapping.workspace_id != workspace_id:
            return None
        return mapping

    async def get_by_app_user_id(
        self,
        workspace_id: UUID,
        app_user_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.by_agent_id.values()
                if mapping.workspace_id == workspace_id and mapping.app_user_id == app_user_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[WorkspaceAgentCRMMapping, ...]:
        return tuple(
            mapping for mapping in self.by_agent_id.values() if mapping.workspace_id == workspace_id
        )

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        self.by_agent_id[mapping.crm_agent_record_id] = mapping
        return mapping


class FakeUserRepository:
    def __init__(self, matches: dict[tuple[UUID, str], User] | None = None) -> None:
        self.matches = matches or {}
        self.lookup_calls: list[tuple[UUID, str, tuple[WorkspaceMembershipRole, ...]]] = []

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((user for user in self.matches.values() if user.user_id == user_id), None)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        return next(
            (user for (_, email), user in self.matches.items() if email == email_normalized),
            None,
        )

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
        self.lookup_calls.append((workspace_id, email_normalized, allowed_roles))
        return self.matches.get((workspace_id, email_normalized))

    async def save(self, user: User) -> User:
        self.matches[(WORKSPACE_ID, user.email_normalized)] = user
        return user


async def test_sync_crm_agents_creates_suggested_mapping_for_workspace_email_match() -> None:
    agent_repository = FakeCRMAgentRepository()
    mapping_repository = FakeWorkspaceAgentCRMMappingRepository()
    user_repository = FakeUserRepository({(WORKSPACE_ID, "agent@example.com"): _user()})

    result = await sync_crm_agents_for_workspace(
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeCRMAgentDirectorySource(
            (_source_agent(email="Agent@example.com"),)
        ),
        crm_agent_repository=agent_repository,
        workspace_agent_crm_mapping_repository=mapping_repository,
        user_repository=user_repository,
        now=NOW,
        agent_record_id_factory=lambda: AGENT_ID,
        mapping_id_factory=lambda: MAPPING_ID,
    )

    saved_agent = agent_repository.by_external_id["fub-user-123"]
    saved_mapping = mapping_repository.by_agent_id[saved_agent.agent_record_id]
    assert result.status == SyncCRMAgentsStatus.COMPLETED
    assert result.created_count == 1
    assert result.suggested_mapping_count == 1
    assert saved_agent.email_normalized == "agent@example.com"
    assert saved_mapping.mapping_status == CRMAgentMappingStatus.SUGGESTED
    assert saved_mapping.app_user_id == USER_ID
    assert saved_mapping.resolution_source == CRMAgentMappingResolutionSource.AUTO_EMAIL_MATCH


async def test_sync_crm_agents_creates_unmapped_record_when_no_active_workspace_match_exists() -> (
    None
):
    agent_repository = FakeCRMAgentRepository()
    mapping_repository = FakeWorkspaceAgentCRMMappingRepository()

    result = await sync_crm_agents_for_workspace(
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeCRMAgentDirectorySource(
            (_source_agent(email="nomatch@example.com"),)
        ),
        crm_agent_repository=agent_repository,
        workspace_agent_crm_mapping_repository=mapping_repository,
        user_repository=FakeUserRepository(),
        now=NOW,
        agent_record_id_factory=lambda: AGENT_ID,
        mapping_id_factory=lambda: MAPPING_ID,
    )

    saved_mapping = mapping_repository.by_agent_id[AGENT_ID]
    assert result.unmapped_mapping_count == 1
    assert saved_mapping.mapping_status == CRMAgentMappingStatus.UNMAPPED
    assert saved_mapping.app_user_id is None
    assert saved_mapping.resolved_at is None


async def test_sync_crm_agents_preserves_verified_mapping() -> None:
    existing_agent = _stored_agent(email="old@example.com")
    verified_mapping = _mapping(
        crm_agent_record_id=existing_agent.agent_record_id,
        app_user_id=SECOND_USER_ID,
        status=CRMAgentMappingStatus.VERIFIED,
        source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
    )
    agent_repository = FakeCRMAgentRepository((existing_agent,))
    mapping_repository = FakeWorkspaceAgentCRMMappingRepository((verified_mapping,))

    await sync_crm_agents_for_workspace(
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeCRMAgentDirectorySource(
            (_source_agent(email="agent@example.com"),)
        ),
        crm_agent_repository=agent_repository,
        workspace_agent_crm_mapping_repository=mapping_repository,
        user_repository=FakeUserRepository({(WORKSPACE_ID, "agent@example.com"): _user()}),
        now=NOW,
    )

    saved_mapping = mapping_repository.by_agent_id[existing_agent.agent_record_id]
    assert saved_mapping.mapping_status == CRMAgentMappingStatus.VERIFIED
    assert saved_mapping.app_user_id == SECOND_USER_ID
    assert saved_mapping.resolution_source == CRMAgentMappingResolutionSource.ADMIN_MANUAL


async def test_sync_crm_agents_preserves_system_unlinked_mapping() -> None:
    existing_agent = _stored_agent(email="agent@example.com")
    unlinked_mapping = _mapping(
        crm_agent_record_id=existing_agent.agent_record_id,
        app_user_id=None,
        status=CRMAgentMappingStatus.UNMAPPED,
        source=CRMAgentMappingResolutionSource.SYSTEM_UNLINKED,
    )
    mapping_repository = FakeWorkspaceAgentCRMMappingRepository((unlinked_mapping,))

    await sync_crm_agents_for_workspace(
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeCRMAgentDirectorySource(
            (_source_agent(email="agent@example.com"),)
        ),
        crm_agent_repository=FakeCRMAgentRepository((existing_agent,)),
        workspace_agent_crm_mapping_repository=mapping_repository,
        user_repository=FakeUserRepository({(WORKSPACE_ID, "agent@example.com"): _user()}),
        now=NOW,
    )

    saved_mapping = mapping_repository.by_agent_id[existing_agent.agent_record_id]
    assert saved_mapping.mapping_status == CRMAgentMappingStatus.UNMAPPED
    assert saved_mapping.app_user_id is None
    assert saved_mapping.resolution_source == CRMAgentMappingResolutionSource.SYSTEM_UNLINKED


async def test_sync_crm_agents_deactivates_agents_missing_from_directory() -> None:
    existing_agent = _stored_agent()
    agent_repository = FakeCRMAgentRepository((existing_agent,))

    result = await sync_crm_agents_for_workspace(
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeCRMAgentDirectorySource(()),
        crm_agent_repository=agent_repository,
        workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(),
        user_repository=FakeUserRepository(),
        now=NOW,
    )

    assert result.deactivated_count == 1
    assert agent_repository.by_external_id[existing_agent.external_agent_id].is_active is False


def _source_agent(*, email: str | None = "agent@example.com") -> CRMAgentDirectoryEntry:
    return CRMAgentDirectoryEntry(
        crm_agent_id="fub-user-123",
        name="Alex Agent",
        email=email,
        phone="+15555550123",
        is_active=True,
        raw_payload={"id": "fub-user-123"},
    )


def _stored_agent(*, email: str | None = "agent@example.com") -> CRMAgent:
    return CRMAgent(
        agent_record_id=AGENT_ID,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id="fub-user-123",
        name="Alex Agent",
        email=email,
        email_normalized=email.lower() if email is not None else None,
        phone="+15555550123",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={"id": "fub-user-123"},
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping(
    *,
    crm_agent_record_id: UUID,
    app_user_id: UUID | None,
    status: CRMAgentMappingStatus,
    source: CRMAgentMappingResolutionSource,
) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=MAPPING_ID,
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=crm_agent_record_id,
        app_user_id=app_user_id,
        mapping_status=status,
        resolution_source=source,
        resolved_by_user_id=None,
        resolved_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _user() -> User:
    return User(
        user_id=USER_ID,
        email="agent@example.com",
        email_normalized="agent@example.com",
        full_name="Agent Smith",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
