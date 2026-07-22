from datetime import UTC, datetime
from uuid import UUID

from app.application.ports.crm import CRMAgentDirectoryEntry
from app.application.use_cases.crm_agent_mapping_admin import (
    CRMAgentMappingAdminReasonCode,
    CRMAgentMappingAdminStatus,
    list_crm_agent_mapping_admin_view,
    sync_crm_agent_directory_by_admin,
    unlink_crm_agent_mapping_by_admin,
    upsert_crm_agent_mapping_by_admin,
)
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import (
    AuthenticatedActor,
    User,
    UserStatus,
    WorkspaceMembership,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.domain.leads import CRMProvider
from tests.application.use_cases.test_authentication import _actor, _membership, _user

NOW = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("55555555-5555-5555-5555-555555555501")
ADMIN_ID = UUID("55555555-5555-5555-5555-555555555502")
USER_ID = UUID("55555555-5555-5555-5555-555555555503")
AGENT_ID = UUID("55555555-5555-5555-5555-555555555505")
SECOND_AGENT_ID = UUID("55555555-5555-5555-5555-555555555506")
MAPPING_ID = UUID("55555555-5555-5555-5555-555555555507")


async def test_list_crm_agent_mapping_admin_view_returns_summary_and_rows() -> None:
    agent = _agent()
    mapping = _mapping(app_user_id=USER_ID, status=CRMAgentMappingStatus.SUGGESTED)
    user = _user(user_id=USER_ID)

    result = await list_crm_agent_mapping_admin_view(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        crm_agent_repository=FakeCRMAgentRepository((agent,)),
        mapping_repository=FakeMappingRepository((mapping,)),
        user_repository=FakeUserRepository((user,)),
    )

    assert result.status == CRMAgentMappingAdminStatus.OK
    assert result.summary is not None
    assert result.summary.suggested_count == 1
    assert result.rows[0].agent == agent
    assert result.rows[0].app_user == user


async def test_upsert_crm_agent_mapping_confirms_suggested_match() -> None:
    mapping_repository = FakeMappingRepository(
        (_mapping(app_user_id=USER_ID, status=CRMAgentMappingStatus.SUGGESTED),)
    )

    result = await upsert_crm_agent_mapping_by_admin(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=AGENT_ID,
        app_user_id=USER_ID,
        crm_agent_repository=FakeCRMAgentRepository((_agent(),)),
        mapping_repository=mapping_repository,
        user_repository=FakeUserRepository((_user(user_id=USER_ID),)),
        membership_repository=FakeMembershipRepository((_membership_for(USER_ID),)),
        now=NOW,
    )

    assert result.status == CRMAgentMappingAdminStatus.UPDATED
    assert result.mapping is not None
    assert result.mapping.mapping_status == CRMAgentMappingStatus.VERIFIED
    assert result.mapping.resolution_source == CRMAgentMappingResolutionSource.ADMIN_MANUAL
    assert result.mapping.resolved_by_user_id == ADMIN_ID


async def test_upsert_crm_agent_mapping_allows_multiple_crm_agents_for_same_app_user() -> None:
    mapping_repository = FakeMappingRepository(
        (_mapping(app_user_id=USER_ID, status=CRMAgentMappingStatus.VERIFIED),)
    )

    result = await upsert_crm_agent_mapping_by_admin(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=SECOND_AGENT_ID,
        app_user_id=USER_ID,
        crm_agent_repository=FakeCRMAgentRepository((_agent(), _agent(agent_id=SECOND_AGENT_ID))),
        mapping_repository=mapping_repository,
        user_repository=FakeUserRepository((_user(user_id=USER_ID),)),
        membership_repository=FakeMembershipRepository((_membership_for(USER_ID),)),
        now=NOW,
    )

    assert result.status == CRMAgentMappingAdminStatus.UPDATED
    assert result.mapping is not None
    assert result.mapping.crm_agent_record_id == SECOND_AGENT_ID
    assert result.mapping.app_user_id == USER_ID
    saved_mappings = await mapping_repository.list_for_workspace(WORKSPACE_ID)
    assert len(saved_mappings) == 2
    assert {mapping.crm_agent_record_id for mapping in saved_mappings} == {
        AGENT_ID,
        SECOND_AGENT_ID,
    }


async def test_unlink_crm_agent_mapping_marks_system_unlinked() -> None:
    mapping_repository = FakeMappingRepository(
        (_mapping(app_user_id=USER_ID, status=CRMAgentMappingStatus.VERIFIED),)
    )

    result = await unlink_crm_agent_mapping_by_admin(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        mapping_id=MAPPING_ID,
        mapping_repository=mapping_repository,
        now=NOW,
    )

    assert result.status == CRMAgentMappingAdminStatus.DELETED
    assert result.mapping is not None
    assert result.mapping.app_user_id is None
    assert result.mapping.mapping_status == CRMAgentMappingStatus.UNMAPPED
    assert result.mapping.resolution_source == CRMAgentMappingResolutionSource.SYSTEM_UNLINKED


async def test_manager_cannot_manage_crm_agent_mappings() -> None:
    result = await list_crm_agent_mapping_admin_view(
        actor=_actor(
            user_id=ADMIN_ID,
            role=WorkspaceMembershipRole.MANAGER,
            active_workspace_id=WORKSPACE_ID,
        ),
        workspace_id=WORKSPACE_ID,
        crm_agent_repository=FakeCRMAgentRepository(()),
        mapping_repository=FakeMappingRepository(()),
        user_repository=FakeUserRepository(()),
    )

    assert result.status == CRMAgentMappingAdminStatus.REJECTED
    assert result.reasons == (CRMAgentMappingAdminReasonCode.PERMISSION_DENIED,)


async def test_sync_crm_agent_directory_by_admin_reuses_directory_sync() -> None:
    agent_repository = FakeCRMAgentRepository(())
    mapping_repository = FakeMappingRepository(())
    user_repository = FakeUserRepository((_user(user_id=USER_ID),))

    result = await sync_crm_agent_directory_by_admin(
        actor=_admin_actor(),
        workspace_id=WORKSPACE_ID,
        crm_agent_directory_source=FakeDirectorySource(
            (CRMAgentDirectoryEntry(crm_agent_id="fub-1", email="user@example.com"),)
        ),
        crm_agent_repository=agent_repository,
        mapping_repository=mapping_repository,
        user_repository=user_repository,
        now=NOW,
    )

    assert result.status == CRMAgentMappingAdminStatus.SYNCED
    assert result.sync_result is not None
    assert result.sync_result.created_count == 1
    assert result.sync_result.suggested_mapping_count == 1
    assert result.summary is not None
    assert result.summary.total_agents == 1


class FakeDirectorySource:
    def __init__(self, agents: tuple[CRMAgentDirectoryEntry, ...]) -> None:
        self.agents = agents

    async def list_agents(self, workspace_id: UUID) -> list[CRMAgentDirectoryEntry]:
        assert workspace_id == WORKSPACE_ID
        return list(self.agents)


class FakeCRMAgentRepository:
    def __init__(self, agents: tuple[CRMAgent, ...]) -> None:
        self.agents = {agent.agent_record_id: agent for agent in agents}

    async def get_by_record_id(self, workspace_id: UUID, agent_record_id: UUID) -> CRMAgent | None:
        agent = self.agents.get(agent_record_id)
        return agent if agent is not None and agent.workspace_id == workspace_id else None

    async def get_by_external_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        return next(
            (
                agent
                for agent in self.agents.values()
                if agent.workspace_id == workspace_id
                and agent.crm_provider == crm_provider
                and agent.external_agent_id == external_agent_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[CRMAgent, ...]:
        return tuple(agent for agent in self.agents.values() if agent.workspace_id == workspace_id)

    async def save(self, agent: CRMAgent) -> CRMAgent:
        self.agents[agent.agent_record_id] = agent
        return agent


class FakeMappingRepository:
    def __init__(self, mappings: tuple[WorkspaceAgentCRMMapping, ...]) -> None:
        self.mappings = {mapping.mapping_id: mapping for mapping in mappings}

    async def get_by_id(
        self,
        workspace_id: UUID,
        mapping_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        mapping = self.mappings.get(mapping_id)
        return mapping if mapping is not None and mapping.workspace_id == workspace_id else None

    async def get_by_crm_agent_record_id(
        self,
        workspace_id: UUID,
        crm_agent_record_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.mappings.values()
                if mapping.workspace_id == workspace_id
                and mapping.crm_agent_record_id == crm_agent_record_id
            ),
            None,
        )

    async def get_by_app_user_id(
        self,
        workspace_id: UUID,
        app_user_id: UUID,
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self.mappings.values()
                if mapping.workspace_id == workspace_id and mapping.app_user_id == app_user_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[WorkspaceAgentCRMMapping, ...]:
        return tuple(
            mapping for mapping in self.mappings.values() if mapping.workspace_id == workspace_id
        )

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        self.mappings[mapping.mapping_id] = mapping
        return mapping


class FakeUserRepository:
    def __init__(self, users: tuple[User, ...]) -> None:
        self.users = {user.user_id: user for user in users}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        return next(
            (user for user in self.users.values() if user.email_normalized == email_normalized),
            None,
        )

    async def get_active_by_workspace_email_normalized(
        self,
        workspace_id: UUID,
        email_normalized: str,
        *,
        allowed_roles: tuple[WorkspaceMembershipRole, ...],
    ) -> User | None:
        _ = (workspace_id, allowed_roles)
        user = await self.get_by_email_normalized(email_normalized)
        return user if user is not None and user.status == UserStatus.ACTIVE else None

    async def save(self, user: User) -> User:
        self.users[user.user_id] = user
        return user


class FakeMembershipRepository:
    def __init__(self, memberships: tuple[WorkspaceMembership, ...]) -> None:
        self.memberships = memberships

    async def get_by_id(self, membership_id: UUID) -> WorkspaceMembership | None:
        return next(
            (
                membership
                for membership in self.memberships
                if membership.membership_id == membership_id
            ),
            None,
        )

    async def get_by_user_and_workspace(
        self,
        user_id: UUID,
        workspace_id: UUID,
    ) -> WorkspaceMembership | None:
        return next(
            (
                membership
                for membership in self.memberships
                if membership.user_id == user_id and membership.workspace_id == workspace_id
            ),
            None,
        )

    async def list_by_user_id(self, user_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(membership for membership in self.memberships if membership.user_id == user_id)

    async def list_by_workspace_id(self, workspace_id: UUID) -> tuple[WorkspaceMembership, ...]:
        return tuple(
            membership for membership in self.memberships if membership.workspace_id == workspace_id
        )

    async def save(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        return membership


def _admin_actor() -> AuthenticatedActor:
    return _actor(
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        active_workspace_id=WORKSPACE_ID,
    )


def _membership_for(user_id: UUID) -> WorkspaceMembership:
    return _membership(
        workspace_id=WORKSPACE_ID,
        user_id=user_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
        status=WorkspaceMembershipStatus.ACTIVE,
    )


def _agent(agent_id: UUID = AGENT_ID) -> CRMAgent:
    return CRMAgent(
        agent_record_id=agent_id,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id=f"fub-{agent_id}",
        name="Alex Agent",
        email="user@example.com",
        email_normalized="user@example.com",
        phone="+15555550123",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={},
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping(
    *,
    app_user_id: UUID | None,
    status: CRMAgentMappingStatus,
) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=MAPPING_ID,
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=AGENT_ID,
        app_user_id=app_user_id,
        mapping_status=status,
        resolution_source=CRMAgentMappingResolutionSource.AUTO_EMAIL_MATCH,
        resolved_by_user_id=None,
        resolved_at=NOW if app_user_id is not None else None,
        created_at=NOW,
        updated_at=NOW,
    )
