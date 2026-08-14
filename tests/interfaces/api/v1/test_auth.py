from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.domain.identity import (
    AuthenticatedActor,
    RefreshSession,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from app.interfaces.api.dependencies.auth import (
    AuthServiceBundle,
    get_auth_service_bundle,
    get_current_actor,
)
from app.main import create_app
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    FAMILY_ID,
    MEMBERSHIP_ID,
    SECOND_MEMBERSHIP_ID,
    SECOND_WORKSPACE_ID,
    SESSION_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _credential,
    _Dependencies,
    _invitation,
    _membership,
    _refresh_session,
    _reset_token,
    _user,
    _workspace,
)


class AuthTestClient:
    def __init__(
        self,
        client: TestClient,
        deps: _Dependencies,
        session: "_FakeCommitSession",
        bundle: AuthServiceBundle,
    ) -> None:
        self.client = client
        self.deps = deps
        self.session = session
        self.bundle = bundle


class _FakeCommitSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


def _admin_refresh_session(
    session_id: UUID = SESSION_ID,
    token_hash: str = "hash::refresh-token",
) -> RefreshSession:
    return RefreshSession(
        session_id=session_id,
        user_id=ADMIN_ID,
        workspace_id=WORKSPACE_ID,
        refresh_token_hash=token_hash,
        family_id=FAMILY_ID,
        rotated_from_session_id=None,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=None,
        revoked_reason=None,
        created_at=datetime.now(UTC) - timedelta(days=1),
        last_used_at=None,
    )


@pytest.fixture
def auth_client() -> AuthTestClient:
    app = create_app()
    deps = _Dependencies()
    session = _FakeCommitSession()
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
        session=session,
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

    return AuthTestClient(TestClient(app), deps, session, bundle)


def test_complete_signup_returns_201(auth_client: AuthTestClient) -> None:
    auth_client.bundle.settings = Settings(
        auth_jwt_secret="test-secret",
        auth_access_token_ttl_minutes=6,
        auth_refresh_token_ttl_days=4,
    )
    auth_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    auth_client.deps.memberships[MEMBERSHIP_ID] = _membership(
        status=WorkspaceMembershipStatus.INVITED,
    )
    auth_client.deps.invitations[UUID("00000000-0000-0000-0000-00000000000a")] = _invitation(
        token_hash="hash::invite-token",
    )

    response = auth_client.client.post(
        "/api/v1/auth/signup",
        json={
            "invitation_token": "invite-token",
            "full_name": "Agent Smith",
            "password": "strong-password",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["tokens"]["access_token"] is not None
    issued = auth_client.deps.access_token_service.decode_token(body["tokens"]["access_token"])
    assert issued.expires_at - issued.issued_at == timedelta(minutes=6)
    refresh_session = next(iter(auth_client.deps.refresh_sessions.values()))
    assert refresh_session.expires_at - refresh_session.created_at == timedelta(days=4)
    assert auth_client.session.commit_count == 1


def test_complete_signup_accepts_invitation_alias_route(auth_client: AuthTestClient) -> None:
    auth_client.deps.users[USER_ID] = _user(status=UserStatus.PENDING_VERIFICATION)
    auth_client.deps.memberships[MEMBERSHIP_ID] = _membership(
        status=WorkspaceMembershipStatus.INVITED,
    )
    auth_client.deps.invitations[UUID("00000000-0000-0000-0000-00000000000a")] = _invitation(
        token_hash="hash::invite-token",
    )

    response = auth_client.client.post(
        "/api/v1/auth/invitations/accept",
        json={
            "invitation_token": "invite-token",
            "full_name": "Agent Smith",
            "password": "strong-password",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["tokens"]["access_token"] is not None
    assert auth_client.session.commit_count == 1


def test_preview_invitation_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.deps.invitations[UUID("00000000-0000-0000-0000-00000000000a")] = _invitation(
        token_hash="hash::invite-token",
    )

    response = auth_client.client.post(
        "/api/v1/auth/invitations/preview",
        json={"invitation_token": "invite-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "valid"
    assert body["invitation"]["email"] == "user@example.com"
    assert body["invitation"]["role"] == "assigned_agent"
    assert body["invitation"]["workspace_name"] == f"Workspace {WORKSPACE_ID}"


def test_preview_invitation_unknown_token_returns_400(auth_client: AuthTestClient) -> None:
    response = auth_client.client.post(
        "/api/v1/auth/invitations/preview",
        json={"invitation_token": "unknown-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ["invitation_not_found"]


def test_signin_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.bundle.settings = Settings(
        auth_jwt_secret="test-secret",
        auth_access_token_ttl_minutes=5,
        auth_refresh_token_ttl_days=2,
    )
    auth_client.deps.credentials[ADMIN_ID] = _credential(password_hash="hashed::correct-password")

    response = auth_client.client.post(
        "/api/v1/auth/signin",
        json={
            "email": "user@example.com",
            "password": "correct-password",
            "workspace_id": str(WORKSPACE_ID),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "authenticated"
    assert body["tokens"]["access_token"] is not None
    issued = auth_client.deps.access_token_service.decode_token(body["tokens"]["access_token"])
    assert issued.expires_at - issued.issued_at == timedelta(minutes=5)
    refresh_session = next(iter(auth_client.deps.refresh_sessions.values()))
    assert refresh_session.expires_at - refresh_session.created_at == timedelta(days=2)
    assert auth_client.session.commit_count == 1


def test_signin_wrong_password_returns_401(auth_client: AuthTestClient) -> None:
    auth_client.deps.credentials[ADMIN_ID] = _credential(password_hash="hashed::correct-password")

    response = auth_client.client.post(
        "/api/v1/auth/signin",
        json={
            "email": "user@example.com",
            "password": "wrong-password",
            "workspace_id": str(WORKSPACE_ID),
        },
    )

    assert response.status_code == 401
    assert auth_client.session.commit_count == 1


def test_refresh_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.bundle.settings = Settings(
        auth_jwt_secret="test-secret",
        auth_access_token_ttl_minutes=7,
        auth_refresh_token_ttl_days=3,
    )
    auth_client.deps.refresh_sessions[SESSION_ID] = _admin_refresh_session(
        token_hash="hash::refresh-token",
    )

    response = auth_client.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "refreshed"
    assert body["tokens"]["access_token"] is not None
    issued = auth_client.deps.access_token_service.decode_token(body["tokens"]["access_token"])
    assert issued.expires_at - issued.issued_at == timedelta(minutes=7)
    replacement_session = next(
        session
        for session_id, session in auth_client.deps.refresh_sessions.items()
        if session_id != SESSION_ID
    )
    assert replacement_session.expires_at - replacement_session.created_at == timedelta(days=3)
    assert auth_client.session.commit_count == 1


def test_me_returns_200(auth_client: AuthTestClient) -> None:
    response = auth_client.client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert body["user"]["email"] == "user@example.com"


def test_me_missing_token_returns_401(auth_client: AuthTestClient) -> None:
    app = create_app()
    app.dependency_overrides[get_auth_service_bundle] = lambda: None
    client = TestClient(app)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_switch_workspace_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.bundle.settings = Settings(
        auth_jwt_secret="test-secret",
        auth_access_token_ttl_minutes=9,
    )
    auth_client.deps.workspaces[SECOND_WORKSPACE_ID] = _workspace(workspace_id=SECOND_WORKSPACE_ID)
    auth_client.deps.memberships[SECOND_MEMBERSHIP_ID] = _membership(
        membership_id=SECOND_MEMBERSHIP_ID,
        workspace_id=SECOND_WORKSPACE_ID,
        user_id=ADMIN_ID,
    )

    response = auth_client.client.post(
        "/api/v1/auth/switch-workspace",
        json={"workspace_id": str(SECOND_WORKSPACE_ID)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "switched"
    assert body["workspace"]["workspace_id"] == str(SECOND_WORKSPACE_ID)
    assert body["access_token"] is not None
    issued = auth_client.deps.access_token_service.decode_token(body["access_token"])
    assert issued.expires_at - issued.issued_at == timedelta(minutes=9)


def test_logout_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.deps.refresh_sessions[SESSION_ID] = _admin_refresh_session(
        token_hash="hash::refresh-token",
    )

    response = auth_client.client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "refresh-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "logged_out"
    assert body["revoked"] is True
    assert auth_client.session.commit_count == 1


def test_logout_all_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.deps.refresh_sessions[SESSION_ID] = _admin_refresh_session()

    response = auth_client.client.post("/api/v1/auth/logout-all")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "logged_out"
    assert body["revoked"] is True
    assert auth_client.session.commit_count == 1


def test_forgot_password_returns_202(auth_client: AuthTestClient) -> None:
    response = auth_client.client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "user@example.com"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    assert auth_client.session.commit_count == 1


def test_reset_password_returns_200(auth_client: AuthTestClient) -> None:
    auth_client.deps.users[USER_ID] = _user(status=UserStatus.LOCKED)
    auth_client.deps.credentials[USER_ID] = _credential(password_hash="hashed::old-password")
    auth_client.deps.reset_tokens[UUID("00000000-0000-0000-0000-00000000000b")] = _reset_token(
        token_hash="hash::reset-token",
    )
    auth_client.deps.refresh_sessions[SESSION_ID] = _refresh_session()

    response = auth_client.client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": "reset-token", "new_password": "new-strong-password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reset"
    assert body["user"]["status"] == "active"
    assert auth_client.session.commit_count == 1
