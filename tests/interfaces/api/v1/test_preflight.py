from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.application.ports.preflight_digest import (
    PreflightDigestEntry,
    PreflightDigestIssueStatus,
    PreflightDigestNotificationRecord,
    PreflightDigestRecord,
    PreflightDigestRepository,
    PreflightVetoRecord,
)
from app.application.ports.repositories import (
    CRMAgentRepository,
    WorkspaceAgentCRMMappingRepository,
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
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.interfaces.api.dependencies.preflight import PreflightReadBundle, get_preflight_read_bundle
from app.main import create_app

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_ID = UUID("00000000-0000-0000-0000-000000000002")
CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000003")
LEAD_ID = UUID("00000000-0000-0000-0000-000000000004")
DEFAULT_ACTOR_USER_ID = UUID("00000000-0000-0000-0000-000000000005")


@dataclass
class PreflightTestClient:
    client: TestClient


class FakePreflightDigestRepository(PreflightDigestRepository):
    def __init__(self) -> None:
        self.digest = _digest()

    async def list_digests_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int = 50,
    ) -> tuple[PreflightDigestRecord, ...]:
        return (self.digest,) if workspace_id == WORKSPACE_ID else ()

    async def get_digest_by_id(
        self,
        workspace_id: UUID,
        digest_id: str,
    ) -> PreflightDigestRecord | None:
        if workspace_id == WORKSPACE_ID and digest_id == self.digest.digest_id:
            return self.digest
        return None

    async def get_digest(
        self,
        workspace_id: UUID,
        campaign_id: UUID,
        batch_id: str,
    ) -> PreflightDigestRecord | None:
        _ = (workspace_id, campaign_id, batch_id)
        return None

    async def save_digest(self, record: PreflightDigestRecord) -> None:
        self.digest = record


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


def test_preflight_routes_return_list_and_detail_for_brokerage_admin() -> None:
    client = _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")
    detail_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests/{DIGEST_ID}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["digests"][0]["status"] == "pending"
    assert list_response.json()["digests"][0]["lead_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["digest"]["status"] == "pending"
    assert detail_response.json()["entries"][0]["vetoed"] is True


def test_preflight_routes_allow_platform_super_admin() -> None:
    client = _client_for_role(WorkspaceMembershipRole.PLATFORM_SUPER_ADMIN)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")
    detail_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests/{DIGEST_ID}"
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200


def test_preflight_routes_allow_assigned_agent_for_own_mapped_lead() -> None:
    actor_id = UUID("00000000-0000-0000-0000-000000000005")
    crm_agent_record_id = UUID("00000000-0000-0000-0000-000000000006")
    client = _client_for_role(
        WorkspaceMembershipRole.ASSIGNED_AGENT,
        actor_id=actor_id,
        crm_agents=(_crm_agent(crm_agent_record_id=crm_agent_record_id, external_id="agent-1"),),
        mappings=(_mapping(actor_id=actor_id, crm_agent_record_id=crm_agent_record_id),),
    )

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")
    detail_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests/{DIGEST_ID}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["digests"][0]["lead_count"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["entries"][0]["vetoed"] is True


def test_preflight_routes_hide_digest_for_unrelated_assigned_agent() -> None:
    client = _client_for_role(WorkspaceMembershipRole.ASSIGNED_AGENT)

    list_response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests")
    detail_response = client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/preflight-digests/{DIGEST_ID}"
    )

    assert list_response.status_code == 200
    assert list_response.json()["digests"] == []
    assert detail_response.status_code == 404


def _client_for_role(
    role: WorkspaceMembershipRole,
    actor_id: UUID = DEFAULT_ACTOR_USER_ID,
    crm_agents: tuple[CRMAgent, ...] = (),
    mappings: tuple[WorkspaceAgentCRMMapping, ...] = (),
) -> PreflightTestClient:
    app = create_app()
    bundle = PreflightReadBundle(
        repository=FakePreflightDigestRepository(),
        crm_agent_repository=FakeCRMAgentRepository(crm_agents),
        workspace_agent_crm_mapping_repository=FakeWorkspaceAgentCRMMappingRepository(mappings),
    )
    app.dependency_overrides[get_workspace_actor] = lambda: _actor(role, user_id=actor_id)
    app.dependency_overrides[get_preflight_read_bundle] = lambda: bundle
    return PreflightTestClient(client=TestClient(app))


def _digest() -> PreflightDigestRecord:
    return PreflightDigestRecord(
        digest_id=str(DIGEST_ID),
        workspace_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        batch_id="batch-1",
        status=PreflightDigestIssueStatus.ISSUED,
        entries=(
            PreflightDigestEntry(
                lead_id=LEAD_ID,
                recipient_id="agent-1",
                recipient_destination="agent@example.com",
                display_name="Jordan Seller",
            ),
        ),
        notification_records=(
            PreflightDigestNotificationRecord(
                recipient_id="agent-1",
                idempotency_key="notif-1",
                accepted=True,
                provider_reference="provider-1",
            ),
        ),
        digest_sent_at=NOW,
        veto_window_expires_at=NOW,
        vetoes=(
            PreflightVetoRecord(
                lead_id=LEAD_ID,
                actor_id="agent-1",
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


def _crm_agent(*, crm_agent_record_id: UUID, external_id: str = "agent-1") -> CRMAgent:
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


def _mapping(*, actor_id: UUID, crm_agent_record_id: UUID) -> WorkspaceAgentCRMMapping:
    return WorkspaceAgentCRMMapping(
        mapping_id=UUID("00000000-0000-0000-0000-000000000007"),
        workspace_id=WORKSPACE_ID,
        crm_agent_record_id=crm_agent_record_id,
        app_user_id=actor_id,
        mapping_status=CRMAgentMappingStatus.VERIFIED,
        resolution_source=CRMAgentMappingResolutionSource.ADMIN_MANUAL,
        created_at=NOW,
        updated_at=NOW,
    )
