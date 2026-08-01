import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
)
from app.application.use_cases.preflight_read import (
    PreflightDigestViewStatus,
    PreflightReadStatus,
    get_preflight_digest_view,
    list_preflight_digest_views,
)
from app.domain.crm_agent_mapping import (
    CRMAgent,
    CRMAgentMappingResolutionSource,
    CRMAgentMappingStatus,
    WorkspaceAgentCRMMapping,
)
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)
from app.domain.leads import CRMProvider

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")
DEFAULT_ACTOR_USER_ID = UUID("00000000-0000-0000-0000-000000000005")


class FakePreflightDigestRepository(PreflightDigestRepository):
    def __init__(self, digests: tuple[PreflightDigestRecord, ...]) -> None:
        self._digests = {digest.digest_id: digest for digest in digests}

    async def list_digests_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        return tuple(d for d in self._digests.values() if d.workspace_id == workspace_id)[:limit]

    async def get_digest_by_id(
        self,
        workspace_id: UUID,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        digest = self._digests.get(digest_id)
        if digest is None or digest.workspace_id != workspace_id:
            return None
        return digest

    async def get_digest(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        _ = (campaign_id, batch_id)
        for digest in self._digests.values():
            if digest.workspace_id == workspace_id:
                return digest
        return None

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        self._digests[record.digest_id] = record


class FakeCRMAgentRepository(CRMAgentRepository):
    def __init__(self, agents: tuple[CRMAgent, ...]) -> None:
        self._agents = {agent.agent_record_id: agent for agent in agents}

    async def get_by_record_id(self, workspace_id: UUID, agent_record_id: UUID) -> CRMAgent | None:
        agent = self._agents.get(agent_record_id)
        if agent is None or agent.workspace_id != workspace_id:
            return None
        return agent

    async def get_by_external_id(
        self,
        workspace_id: UUID,
        crm_provider: CRMProvider,
        external_agent_id: str,
    ) -> CRMAgent | None:
        return next(
            (
                agent
                for agent in self._agents.values()
                if agent.workspace_id == workspace_id
                and agent.crm_provider == crm_provider
                and agent.external_agent_id == external_agent_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[CRMAgent, ...]:
        return tuple(agent for agent in self._agents.values() if agent.workspace_id == workspace_id)

    async def save(self, agent: CRMAgent) -> CRMAgent:
        self._agents[agent.agent_record_id] = agent
        return agent


class FakeWorkspaceAgentCRMMappingRepository(WorkspaceAgentCRMMappingRepository):
    def __init__(self, mappings: tuple[WorkspaceAgentCRMMapping, ...]) -> None:
        self._mappings = mappings

    async def get_by_id(
        self, workspace_id: UUID, mapping_id: UUID
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self._mappings
                if mapping.workspace_id == workspace_id and mapping.mapping_id == mapping_id
            ),
            None,
        )

    async def get_by_crm_agent_record_id(
        self, workspace_id: UUID, crm_agent_record_id: UUID
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self._mappings
                if mapping.workspace_id == workspace_id
                and mapping.crm_agent_record_id == crm_agent_record_id
            ),
            None,
        )

    async def get_by_app_user_id(
        self, workspace_id: UUID, app_user_id: UUID
    ) -> WorkspaceAgentCRMMapping | None:
        return next(
            (
                mapping
                for mapping in self._mappings
                if mapping.workspace_id == workspace_id and mapping.app_user_id == app_user_id
            ),
            None,
        )

    async def list_for_workspace(self, workspace_id: UUID) -> tuple[WorkspaceAgentCRMMapping, ...]:
        return tuple(mapping for mapping in self._mappings if mapping.workspace_id == workspace_id)

    async def save(self, mapping: WorkspaceAgentCRMMapping) -> WorkspaceAgentCRMMapping:
        self._mappings = tuple(m for m in self._mappings if m.mapping_id != mapping.mapping_id) + (
            mapping,
        )
        return mapping


def test_list_preflight_digest_views_returns_summary_for_admin() -> None:
    result = asyncio.run(
        list_preflight_digest_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            repository=FakePreflightDigestRepository((_digest(),)),
            crm_agent_repository=FakeCRMAgentRepository(()),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(()),
            now=NOW - timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.views[0].status == PreflightDigestViewStatus.PENDING
    assert result.views[0].lead_count == 1
    assert result.views[0].veto_count == 1


def test_list_preflight_digest_views_marks_issued_digest_ready_after_window_expires() -> None:
    result = asyncio.run(
        list_preflight_digest_views(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            repository=FakePreflightDigestRepository((_digest(),)),
            crm_agent_repository=FakeCRMAgentRepository(()),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(()),
            now=NOW + timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.views[0].status == PreflightDigestViewStatus.READY


def test_get_preflight_digest_view_returns_digest_for_recipient_assigned_agent() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000005")
    crm_agent_id = UUID("00000000-0000-0000-0000-000000000007")
    result = asyncio.run(
        get_preflight_digest_view(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT, user_id=actor_id),
            workspace_id=WORKSPACE_ID,
            digest_id=str(DIGEST_ID),
            repository=FakePreflightDigestRepository((_digest(recipient_id="fub-agent-1"),)),
            crm_agent_repository=FakeCRMAgentRepository(
                (_crm_agent(crm_agent_record_id=crm_agent_id, external_id="fub-agent-1"),)
            ),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(
                (_mapping(app_user_id=actor_id, crm_agent_record_id=crm_agent_id),)
            ),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.view is not None


def test_get_preflight_digest_view_hides_digest_for_unrelated_assigned_agent() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000005")
    result = asyncio.run(
        get_preflight_digest_view(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT, user_id=actor_id),
            workspace_id=WORKSPACE_ID,
            digest_id=str(DIGEST_ID),
            repository=FakePreflightDigestRepository((_digest(recipient_id="fub-agent-1"),)),
            crm_agent_repository=FakeCRMAgentRepository(()),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(()),
        )
    )

    assert result.status == PreflightReadStatus.NOT_FOUND


def test_list_preflight_digest_views_filters_to_recipient_assigned_agent() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000005")
    crm_agent_id = UUID("00000000-0000-0000-0000-000000000007")
    digests = (
        _digest(digest_id=DIGEST_ID, recipient_id="fub-agent-1"),
        _digest(
            digest_id=UUID("00000000-0000-0000-0000-000000000008"),
            recipient_id="fub-agent-2",
        ),
    )
    result = asyncio.run(
        list_preflight_digest_views(
            actor=_actor(WorkspaceMembershipRole.ASSIGNED_AGENT, user_id=actor_id),
            workspace_id=WORKSPACE_ID,
            repository=FakePreflightDigestRepository(digests),
            crm_agent_repository=FakeCRMAgentRepository(
                (_crm_agent(crm_agent_record_id=crm_agent_id, external_id="fub-agent-1"),)
            ),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(
                (_mapping(app_user_id=actor_id, crm_agent_record_id=crm_agent_id),)
            ),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert len(result.views) == 1
    assert result.views[0].digest.digest_id == str(DIGEST_ID)


def test_get_preflight_digest_view_preserves_failed_digest_status() -> None:
    result = asyncio.run(
        get_preflight_digest_view(
            actor=_actor(WorkspaceMembershipRole.BROKERAGE_ADMIN),
            workspace_id=WORKSPACE_ID,
            digest_id=str(DIGEST_ID),
            repository=FakePreflightDigestRepository(
                (_digest(status=PreflightDigestIssueStatus.FAILED),)
            ),
            crm_agent_repository=FakeCRMAgentRepository(()),
            workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(()),
            now=NOW + timedelta(hours=1),
        )
    )

    assert result.status == PreflightReadStatus.OK
    assert result.view is not None
    assert result.view.status == PreflightDigestViewStatus.FAILED


def _digest(
    *,
    status: PreflightDigestIssueStatus = PreflightDigestIssueStatus.ISSUED,
    digest_id: UUID = DIGEST_ID,
    recipient_id: str = "agent-1",
) -> PreflightDigestRecord:
    return PreflightDigestRecord(
        digest_id=str(digest_id),
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id="batch-1",
        status=status,
        entries=(
            PreflightDigestEntry(
                lead_id=LEAD_ID,
                recipient_id=recipient_id,
                recipient_destination="agent@example.com",
                display_name="Jordan Seller",
            ),
        ),
        digest_sent_at=NOW,
        veto_window_expires_at=NOW,
        vetoes=(
            PreflightVetoRecord(
                lead_id=LEAD_ID,
                actor_id=recipient_id,
                recorded_at=NOW,
                idempotency_key="veto-1",
                reason="Already contacted",
            ),
        ),
    )


def _actor(
    role: WorkspaceMembershipRole,
    user_id: UUID = DEFAULT_ACTOR_USER_ID,
) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=user_id,
        user_status=UserStatus.ACTIVE,
        active_role=role,
        active_workspace_id=WORKSPACE_ID,
        active_workspace_status=WorkspaceStatus.ACTIVE,
        active_membership_id=UUID("00000000-0000-0000-0000-000000000006"),
        active_membership_status=WorkspaceMembershipStatus.ACTIVE,
    )


def _crm_agent(
    *,
    crm_agent_record_id: UUID,
    external_id: str = "fub-agent-1",
) -> CRMAgent:
    return CRMAgent(
        agent_record_id=crm_agent_record_id,
        workspace_id=WORKSPACE_ID,
        crm_provider=CRMProvider.FOLLOW_UP_BOSS,
        external_agent_id=external_id,
        name="Alex Agent",
        email="alex@example.com",
        email_normalized="alex@example.com",
        phone="",
        is_active=True,
        last_seen_at=NOW,
        raw_payload={},
        created_at=NOW,
        updated_at=NOW,
    )


def _mapping(
    *,
    app_user_id: UUID,
    crm_agent_record_id: UUID,
) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=UUID("00000000-0000-0000-0000-000000000009"),
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=crm_agent_record_id,
        app_user_id=app_user_id,
        mapping_status=CRMAgentMappingStatus.VERIFIED,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        created_at=NOW,
        updated_at=NOW,
    )
