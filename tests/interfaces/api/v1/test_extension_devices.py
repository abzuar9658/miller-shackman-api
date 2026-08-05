from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.interfaces.api.dependencies.extension_devices import (
    ExtensionDeviceBundle,
    get_extension_device_bundle,
)
from app.main import app
from tests.application.use_cases._extension_device_fakes import (
    FakeExtensionDeviceRepository,
    FakeExtensionPairingCodeRepository,
)
from tests.application.use_cases.test_authentication import (
    MEMBERSHIP_ID,
    USER_ID,
    WORKSPACE_ID,
    _FakeAuthAuditLogRepository,
    _FakeOpaqueTokenService,
    _FakeUserRepository,
    _FakeWorkspaceMembershipRepository,
    _FakeWorkspaceRepository,
    _membership,
    _user,
    _workspace,
)
from tests.application.use_cases.test_extension_devices import _device, _pairing_code


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


def test_public_pair_returns_credential_once_and_commits_once() -> None:
    bundle = _bundle()
    app.dependency_overrides[get_extension_device_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/extension-auth/pair",
                json={
                    "setup_code": f"{WORKSPACE_ID}.fake-pair-secret",
                    "device_name": "Chrome on Mac",
                    "extension_version": "1.2.3",
                },
            )
        assert response.status_code == 201
        assert response.json()["credential"] == "fake-device-secret"
        assert response.json()["device"]["workspace_id"] == str(WORKSPACE_ID)
        assert response.headers["cache-control"] == "no-store"
        assert bundle.session.commit_count == 1  # type: ignore[attr-defined]
    finally:
        app.dependency_overrides.clear()


def test_public_pair_uses_same_generic_failure_for_malformed_and_expired_codes() -> None:
    bundle = _bundle(expired=True)
    app.dependency_overrides[get_extension_device_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            malformed = client.post(
                "/api/v1/extension-auth/pair",
                json={"setup_code": "bad", "device_name": "Chrome"},
            )
            expired = client.post(
                "/api/v1/extension-auth/pair",
                json={
                    "setup_code": f"{WORKSPACE_ID}.fake-pair-secret",
                    "device_name": "Chrome",
                },
            )
        assert malformed.status_code == expired.status_code == 401
        assert malformed.json() == expired.json() == {
            "detail": "Invalid extension pairing code"
        }
        assert malformed.headers["www-authenticate"] == "PairingCode"
    finally:
        app.dependency_overrides.clear()


def test_public_pair_explains_active_device_limit() -> None:
    bundle = _bundle(at_device_limit=True)
    app.dependency_overrides[get_extension_device_bundle] = lambda: bundle
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/extension-auth/pair",
                json={
                    "setup_code": f"{WORKSPACE_ID}.fake-pair-secret",
                    "device_name": "Chrome",
                },
            )
        assert response.status_code == 409
        assert "revoke a device" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def _bundle(*, expired: bool = False, at_device_limit: bool = False) -> ExtensionDeviceBundle:
    pairing_code = _pairing_code(
        expires_at=(
            datetime.now(UTC) - timedelta(seconds=1)
            if expired
            else datetime.now(UTC) + timedelta(minutes=15)
        )
    )
    return ExtensionDeviceBundle(
        session=_FakeSession(),
        user_repository=_FakeUserRepository({USER_ID: _user()}),
        workspace_repository=_FakeWorkspaceRepository({WORKSPACE_ID: _workspace()}),
        membership_repository=_FakeWorkspaceMembershipRepository(
            {MEMBERSHIP_ID: _membership()}
        ),
        pairing_code_repository=FakeExtensionPairingCodeRepository((pairing_code,)),
        device_repository=FakeExtensionDeviceRepository(
            tuple(_device(index=index) for index in range(5)) if at_device_limit else ()
        ),
        audit_log_repository=_FakeAuthAuditLogRepository(),
        token_service=_FakeOpaqueTokenService(["fake-device-secret"]),
    )