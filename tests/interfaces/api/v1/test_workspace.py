from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.domain.identity import (
    AuthenticatedActor,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)
from app.interfaces.api.dependencies.workspace_settings import (
    WorkspaceSettingsBundle,
    get_workspace_settings_bundle,
)
from app.main import create_app
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    INVITATION_ID,
    MEMBERSHIP_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _Dependencies,
    _invitation,
    _membership,
    _user,
    _workspace,
)


class WorkspaceTestClient:
    def __init__(self, client: TestClient, deps: _Dependencies) -> None:
        self.client = client
        self.deps = deps


class _NoopSession:
    async def commit(self) -> None:
        return None


@pytest.fixture
def workspace_client() -> WorkspaceTestClient:
    app = create_app()
    deps = _Dependencies()
    deps.workspaces[WORKSPACE_ID] = _workspace()
    deps.users[ADMIN_ID] = _user(user_id=ADMIN_ID, status=UserStatus.ACTIVE)
    deps.memberships[MEMBERSHIP_ID] = _membership(
        membership_id=MEMBERSHIP_ID,
        user_id=ADMIN_ID,
        role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
    )
    bundle = AuthServiceBundle(
        user_repository=deps.user_repository,
        workspace_repository=deps.workspace_repository,
        membership_repository=deps.membership_repository,
        credential_repository=deps.credential_repository,
        refresh_session_repository=deps.refresh_session_repository,
        reset_token_repository=deps.reset_token_repository,
        invitation_repository=deps.invitation_repository,
        audit_log_repository=deps.audit_log_repository,
        password_hasher=deps.password_hasher,
        access_token_service=deps.access_token_service,
        opaque_token_service=deps.opaque_token_service,
        email_provider=deps.email_provider,
        settings=get_settings(),
    )

    def override_get_auth_service_bundle() -> AuthServiceBundle:
        return bundle

    def override_get_current_actor() -> AuthenticatedActor:
        return _actor(
            user_id=ADMIN_ID,
            role=WorkspaceMembershipRole.BROKERAGE_ADMIN,
        )

    app.dependency_overrides[get_auth_service_bundle] = override_get_auth_service_bundle
    app.dependency_overrides[get_current_actor] = override_get_current_actor

    def override_get_workspace_settings_bundle() -> WorkspaceSettingsBundle:
        return WorkspaceSettingsBundle(
            session=_NoopSession(),
            workspace_repository=deps.workspace_repository,
            membership_repository=deps.membership_repository,
            audit_log_repository=deps.audit_log_repository,
            workspace_contact_policy_repository=deps.workspace_contact_policy_repository,
            workspace_crm_sync_config_repository=deps.workspace_crm_sync_config_repository,
            workspace_llm_config_repository=deps.workspace_llm_config_repository,
            workspace_handoff_config_repository=deps.workspace_handoff_config_repository,
            workspace_operational_control_repository=deps.workspace_operational_control_repository,
            default_crm_sync_interval_seconds=300,
            default_openrouter_model="openai/gpt-4o-mini",
            allowed_openrouter_models=("openai/gpt-4o-mini", "openai/gpt-4.1-mini"),
        )

    app.dependency_overrides[get_workspace_settings_bundle] = (
        override_get_workspace_settings_bundle
    )

    return WorkspaceTestClient(TestClient(app), deps)


def test_create_workspace_returns_201(workspace_client: WorkspaceTestClient) -> None:
    response = workspace_client.client.post(
        "/api/v1/workspaces",
        json={"name": "New Brokerage", "default_timezone": "America/Chicago"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "created"
    assert body["workspace"]["name"] == "New Brokerage"
    assert body["membership"]["role"] == "brokerage_admin"


def test_list_workspace_users_returns_200(workspace_client: WorkspaceTestClient) -> None:
    invited_membership_id = UUID("00000000-0000-0000-0000-00000000000f")
    workspace_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    workspace_client.deps.memberships[invited_membership_id] = _membership(
        membership_id=invited_membership_id,
        user_id=USER_ID,
        role=WorkspaceMembershipRole.MANAGER,
        status=WorkspaceMembershipStatus.INVITED,
    )
    workspace_client.deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::invite-token")

    response = workspace_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/users")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert len(body["users"]) == 2
    invited_user = next(
        user
        for user in body["users"]
        if user["membership"]["membership_id"] == str(invited_membership_id)
    )
    assert invited_user["invitation_id"] == str(INVITATION_ID)


def test_invite_user_returns_201(workspace_client: WorkspaceTestClient) -> None:
    response = workspace_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/invitations",
        json={"email": "agent@example.com", "role": "assigned_agent", "full_name": "Agent Smith"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "invited"
    assert body["user"]["email"] == "agent@example.com"
    assert body["membership"]["role"] == "assigned_agent"


def test_resend_invitation_returns_200(workspace_client: WorkspaceTestClient) -> None:
    workspace_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    workspace_client.deps.memberships[UUID("00000000-0000-0000-0000-000000000010")] = _membership(
        user_id=USER_ID,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
        status=WorkspaceMembershipStatus.INVITED,
    )
    workspace_client.deps.invitations[INVITATION_ID] = _invitation(token_hash="hash::old-token")

    response = workspace_client.client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/invitations/{INVITATION_ID}/resend",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resent"
    assert body["invitation_id"] == str(INVITATION_ID)


def test_update_workspace_membership_returns_200(workspace_client: WorkspaceTestClient) -> None:
    user_membership_id = UUID("00000000-0000-0000-0000-000000000010")
    workspace_client.deps.users[USER_ID] = _user()
    workspace_client.deps.memberships[user_membership_id] = _membership(
        membership_id=user_membership_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )

    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/{USER_ID}/membership",
        json={"role": "manager"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["membership"]["role"] == "manager"


def test_update_user_status_returns_200(workspace_client: WorkspaceTestClient) -> None:
    user_membership_id = UUID("00000000-0000-0000-0000-000000000011")
    workspace_client.deps.users[USER_ID] = _user()
    workspace_client.deps.memberships[user_membership_id] = _membership(
        membership_id=user_membership_id,
        role=WorkspaceMembershipRole.ASSIGNED_AGENT,
    )

    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/users/{USER_ID}/status",
        json={"user_status": "disabled"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["user"]["status"] == "disabled"


def test_get_workspace_settings_returns_crm_sync_defaults(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert body["contact_policy"] == {
        "workspace_id": str(WORKSPACE_ID),
        "sms_compliance_state": "not_approved",
        "quiet_hours_enabled": True,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "inbound_email_address": None,
    }
    assert body["crm_sync_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "crm_sync_enabled": True,
        "crm_sync_interval_seconds": 300,
    }
    assert body["llm_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "openrouter_model": "openai/gpt-4o-mini",
        "allowed_openrouter_models": ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"],
    }
    assert body["operational_control"] == {
        "workspace_id": str(WORKSPACE_ID),
        "automation_status": "active",
        "pause_reason": None,
    }


def test_update_workspace_crm_sync_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/crm-sync",
        json={"crm_sync_enabled": False, "crm_sync_interval_seconds": 900},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["crm_sync_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "crm_sync_enabled": False,
        "crm_sync_interval_seconds": 900,
    }


def test_update_workspace_llm_config_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/llm",
        json={"openrouter_model": "openai/gpt-4.1-mini"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["llm_config"] == {
        "workspace_id": str(WORKSPACE_ID),
        "openrouter_model": "openai/gpt-4.1-mini",
        "allowed_openrouter_models": ["openai/gpt-4o-mini", "openai/gpt-4.1-mini"],
    }


def test_update_workspace_operational_control_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/automation",
        json={
            "automation_status": "paused",
            "pause_reason": "Brokerage requested a temporary pause.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["operational_control"] == {
        "workspace_id": str(WORKSPACE_ID),
        "automation_status": "paused",
        "pause_reason": "Brokerage requested a temporary pause.",
    }


def test_update_workspace_contact_policy_returns_200(
    workspace_client: WorkspaceTestClient,
) -> None:
    response = workspace_client.client.patch(
        f"/api/v1/workspaces/{WORKSPACE_ID}/settings/contact-policy",
        json={
            "sms_compliance_state": "approved",
            "quiet_hours_enabled": False,
            "quiet_hours_start": "10:00:00",
            "quiet_hours_end": "17:00:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["contact_policy"] == {
        "workspace_id": str(WORKSPACE_ID),
        "sms_compliance_state": "approved",
        "quiet_hours_enabled": False,
        "quiet_hours_start": "10:00:00",
        "quiet_hours_end": "17:00:00",
        "inbound_email_address": None,
    }
