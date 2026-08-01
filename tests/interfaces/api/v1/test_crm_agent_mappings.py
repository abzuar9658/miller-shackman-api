from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.application.ports.crm import CRMAgentDirectoryEntry
from app.domain.crm_agent_mapping import CRMAgentMappingStatus
from app.domain.identity import AuthenticatedActor, WorkspaceMembershipRole
from app.interfaces.api.dependencies.crm_agent_mappings import (
    CRMAgentDirectorySyncBundle,
    CRMAgentMappingBundle,
    get_crm_agent_directory_sync_bundle,
    get_crm_agent_mapping_bundle,
)
from app.interfaces.api.dependencies.membership import get_workspace_actor
from app.main import create_app
from tests.application.use_cases._campaign_cadence_fakes import (
    FakeLeadWorkflowRepository,
    FakeOutboundMessageRepository,
    FakeWorkflowTransitionRepository,
)
from tests.application.use_cases._campaign_enrollment_fakes import (
    FakeTemporalSignalOutboxRepository,
)
from tests.application.use_cases.test_authentication import _actor, _user
from tests.application.use_cases.test_crm_agent_mapping_admin import (
    ADMIN_ID,
    AGENT_ID,
    MAPPING_ID,
    USER_ID,
    WORKSPACE_ID,
    FakeCRMAgentRepository,
    FakeDirectorySource,
    FakeEventBus,
    FakeLeadRepository,
    FakeMappingRepository,
    FakeMembershipRepository,
    FakeUserRepository,
    FakeWorkspaceAgentMappingConfigRepository,
    _agent,
    _lead_record,
    _mapping,
    _membership_for,
)


@dataclass
class CRMAgentMappingApiTestClient:
    client: TestClient
    mapping_repository: FakeMappingRepository
    session: "FakeSession"


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def crm_agent_mapping_client() -> CRMAgentMappingApiTestClient:
    return _client_for_role(WorkspaceMembershipRole.BROKERAGE_ADMIN)


def test_list_crm_agent_mappings_returns_rows(
    crm_agent_mapping_client: CRMAgentMappingApiTestClient,
) -> None:
    response = crm_agent_mapping_client.client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/crm-agent-mappings"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["summary"]["suggested_count"] == 1
    assert body["rows"][0]["agent"]["agent_record_id"] == str(AGENT_ID)
    assert body["rows"][0]["app_user"]["user_id"] == str(USER_ID)


def test_upsert_crm_agent_mapping_confirms_mapping(
    crm_agent_mapping_client: CRMAgentMappingApiTestClient,
) -> None:
    response = crm_agent_mapping_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/crm-agent-mappings",
        json={"crm_agent_record_id": str(AGENT_ID), "app_user_id": str(USER_ID)},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "updated"
    assert body["mapping"]["mapping_status"] == "verified"
    assert crm_agent_mapping_client.session.commits == 1


def test_unlink_crm_agent_mapping_returns_unmapped_mapping(
    crm_agent_mapping_client: CRMAgentMappingApiTestClient,
) -> None:
    response = crm_agent_mapping_client.client.delete(
        f"/api/v1/workspaces/{WORKSPACE_ID}/crm-agent-mappings/{MAPPING_ID}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "deleted"
    assert body["mapping"]["mapping_status"] == "unmapped"
    assert body["mapping"]["app_user_id"] is None


def test_manager_cannot_manage_crm_agent_mappings() -> None:
    client = _client_for_role(WorkspaceMembershipRole.MANAGER)

    response = client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/crm-agent-mappings")

    assert response.status_code == 403
    assert response.json()["detail"] == ["permission_denied"]


def test_sync_crm_agent_directory_route_runs_directory_sync() -> None:
    client = _client_for_role(
        WorkspaceMembershipRole.BROKERAGE_ADMIN,
        directory_agents=(CRMAgentDirectoryEntry(crm_agent_id="fub-2", email="user@example.com"),),
    )

    response = client.client.post(f"/api/v1/workspaces/{WORKSPACE_ID}/crm-agent-directory-sync")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synced"
    assert body["sync_result"]["created_count"] == 1
    assert client.session.commits == 1


def _client_for_role(
    role: WorkspaceMembershipRole,
    *,
    directory_agents: tuple[CRMAgentDirectoryEntry, ...] = (),
) -> CRMAgentMappingApiTestClient:
    app = create_app()
    session = FakeSession()
    agent_repository = FakeCRMAgentRepository((_agent(),))
    mapping_repository = FakeMappingRepository(
        (_mapping(app_user_id=USER_ID, status=CRMAgentMappingStatus.SUGGESTED),)
    )
    user_repository = FakeUserRepository((_user(user_id=USER_ID),))
    membership_repository = FakeMembershipRepository((_membership_for(USER_ID),))
    mapping_bundle = CRMAgentMappingBundle(
        session=session,
        crm_agent_repository=agent_repository,
        mapping_repository=mapping_repository,
        user_repository=user_repository,
        membership_repository=membership_repository,
        lead_repository=FakeLeadRepository((_lead_record(owner_user_id=USER_ID),)),
        workspace_agent_mapping_config_repository=FakeWorkspaceAgentMappingConfigRepository(None),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        outbound_message_repository=FakeOutboundMessageRepository(),
        event_bus=FakeEventBus(),
    )
    sync_bundle = CRMAgentDirectorySyncBundle(
        session=session,
        crm_agent_repository=FakeCRMAgentRepository(()),
        mapping_repository=FakeMappingRepository(()),
        user_repository=user_repository,
        membership_repository=membership_repository,
        lead_repository=FakeLeadRepository(()),
        workspace_agent_mapping_config_repository=FakeWorkspaceAgentMappingConfigRepository(None),
        lead_workflow_repository=FakeLeadWorkflowRepository(),
        workflow_transition_repository=FakeWorkflowTransitionRepository(),
        temporal_signal_outbox_repository=FakeTemporalSignalOutboxRepository(),
        outbound_message_repository=FakeOutboundMessageRepository(),
        event_bus=FakeEventBus(),
        crm_agent_directory_source=FakeDirectorySource(directory_agents),
    )

    def override_get_workspace_actor() -> AuthenticatedActor:
        return _actor(user_id=ADMIN_ID, role=role, active_workspace_id=WORKSPACE_ID)

    def override_get_crm_agent_mapping_bundle() -> CRMAgentMappingBundle:
        return mapping_bundle

    def override_get_crm_agent_directory_sync_bundle() -> CRMAgentDirectorySyncBundle:
        return sync_bundle

    app.dependency_overrides[get_workspace_actor] = override_get_workspace_actor
    app.dependency_overrides[get_crm_agent_mapping_bundle] = override_get_crm_agent_mapping_bundle
    app.dependency_overrides[get_crm_agent_directory_sync_bundle] = (
        override_get_crm_agent_directory_sync_bundle
    )
    return CRMAgentMappingApiTestClient(
        client=TestClient(app),
        mapping_repository=mapping_repository,
        session=session,
    )
