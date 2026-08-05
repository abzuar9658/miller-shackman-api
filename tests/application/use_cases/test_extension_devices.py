from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.application.use_cases.extension_devices import (
    ClaimExtensionDeviceResult,
    CreatePairingCodeResult,
    ExtensionDeviceReasonCode,
    authenticate_extension_device,
    claim_extension_device,
    create_pairing_code,
)
from app.domain.identity import (
    AuthenticatedActor,
    ExtensionDevice,
    ExtensionPairingCode,
    UserStatus,
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from tests.application.use_cases._extension_device_fakes import (
    FakeExtensionDeviceRepository,
    FakeExtensionPairingCodeRepository,
)
from tests.application.use_cases.test_authentication import (
    ADMIN_ID,
    MEMBERSHIP_ID,
    USER_ID,
    WORKSPACE_ID,
    _actor,
    _FakeAuthAuditLogRepository,
    _FakeOpaqueTokenService,
    _FakeUserRepository,
    _FakeWorkspaceMembershipRepository,
    _FakeWorkspaceRepository,
    _membership,
    _run,
    _user,
    _workspace,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
PAIRING_CODE_ID = UUID("10000000-0000-0000-0000-000000000001")
DEVICE_ID = UUID("10000000-0000-0000-0000-000000000002")
OTHER_WORKSPACE_ID = UUID("10000000-0000-0000-0000-000000000003")


@pytest.mark.parametrize(
    "role",
    [WorkspaceMembershipRole.MANAGER, WorkspaceMembershipRole.ASSIGNED_AGENT],
)
def test_create_pairing_code_requires_brokerage_admin(
    role: WorkspaceMembershipRole,
) -> None:
    context = _context()
    result = _run(
        create_pairing_code(
            actor=_actor(role=role),
            workspace_id=WORKSPACE_ID,
            target_user_id=USER_ID,
            user_repository=context.users,
            membership_repository=context.memberships,
            pairing_code_repository=context.pairing_codes,
            audit_log_repository=context.audits,
            token_service=_FakeOpaqueTokenService(["fake-pair-secret"]),
            now=NOW,
        )
    )
    assert result.reasons == (ExtensionDeviceReasonCode.PERMISSION_DENIED,)


def test_create_pairing_code_rejects_inactive_target_and_workspace_mismatch() -> None:
    inactive = _context(user_status=UserStatus.DISABLED)
    inactive_result = _run(
        _create_pairing_code(inactive, actor=_actor())
    )
    mismatch = _context()
    mismatch_result = _run(
        _create_pairing_code(
            mismatch, actor=_actor(active_workspace_id=OTHER_WORKSPACE_ID)
        )
    )
    assert inactive_result.reasons == (ExtensionDeviceReasonCode.TARGET_NOT_ACTIVE,)
    assert mismatch_result.reasons == (ExtensionDeviceReasonCode.WORKSPACE_MISMATCH,)


def test_create_pairing_code_revokes_prior_pending_code_and_returns_secret_once() -> None:
    prior = _pairing_code(token_hash="hash::prior")
    context = _context(pairing_codes=(prior,))
    result = _run(_create_pairing_code(context, actor=_actor()))

    assert result.pairing_code is not None
    assert result.setup_code == f"{WORKSPACE_ID}.fake-pair-secret"
    assert result.pairing_code.token_hash == "hash::fake-pair-secret"
    assert context.pairing_codes.pairing_codes[PAIRING_CODE_ID].revoked_at == NOW
    assert len(context.audits.logs) == 1


@pytest.mark.parametrize("state", ["expired", "claimed", "revoked"])
def test_claim_rejects_expired_reused_or_revoked_code_generically(state: str) -> None:
    pairing_code = _pairing_code(
        expires_at=NOW - timedelta(seconds=1) if state == "expired" else NOW + timedelta(minutes=1),
        claimed_at=NOW if state == "claimed" else None,
        revoked_at=NOW if state == "revoked" else None,
    )
    context = _context(pairing_codes=(pairing_code,))
    result = _run(_claim(context))
    assert result.reasons == (ExtensionDeviceReasonCode.INVALID_PAIRING_CODE,)
    assert result.device is None


def test_claim_enforces_active_device_limit() -> None:
    devices = tuple(_device(index=index) for index in range(5))
    context = _context(pairing_codes=(_pairing_code(),), devices=devices)
    result = _run(_claim(context))
    assert result.reasons == (ExtensionDeviceReasonCode.DEVICE_LIMIT_REACHED,)


def test_valid_pairing_claim_hashes_credential_and_marks_code_claimed() -> None:
    context = _context(pairing_codes=(_pairing_code(),))
    result = _run(_claim(context))

    assert result.device is not None
    assert result.credential == "fake-device-secret"
    assert result.device.credential_hash == "hash::fake-device-secret"
    assert result.device.device_name == "Chrome on Mac"
    assert context.pairing_codes.pairing_codes[PAIRING_CODE_ID].claimed_at == NOW
    assert len(context.audits.logs) == 1


@pytest.mark.parametrize("failure", ["wrong", "revoked", "inactive_membership"])
def test_device_authentication_rejects_invalid_or_inactive_credentials(failure: str) -> None:
    device = _device(revoked_at=NOW if failure == "revoked" else None)
    membership_status = (
        WorkspaceMembershipStatus.DISABLED
        if failure == "inactive_membership"
        else WorkspaceMembershipStatus.ACTIVE
    )
    context = _context(devices=(device,), membership_status=membership_status)
    result = _run(
        authenticate_extension_device(
            workspace_id=WORKSPACE_ID,
            device_id=DEVICE_ID,
            credential="wrong" if failure == "wrong" else "fake-device-secret",
            device_repository=context.devices,
            user_repository=context.users,
            workspace_repository=context.workspaces,
            membership_repository=context.memberships,
            token_service=_FakeOpaqueTokenService([]),
            now=NOW,
        )
    )
    assert result.reasons == (ExtensionDeviceReasonCode.INVALID_DEVICE_CREDENTIAL,)
    assert result.actor is None


def test_device_authentication_updates_last_seen_and_returns_scoped_actor() -> None:
    context = _context(devices=(_device(last_seen_at=None),))
    result = _run(
        authenticate_extension_device(
            workspace_id=WORKSPACE_ID,
            device_id=DEVICE_ID,
            credential="fake-device-secret",
            device_repository=context.devices,
            user_repository=context.users,
            workspace_repository=context.workspaces,
            membership_repository=context.memberships,
            token_service=_FakeOpaqueTokenService([]),
            now=NOW,
        )
    )
    assert result.actor is not None
    assert result.actor.user_id == USER_ID
    assert result.actor.active_workspace_id == WORKSPACE_ID
    assert context.devices.devices[DEVICE_ID].last_seen_at == NOW


class _Context:
    def __init__(
        self,
        *,
        pairing_codes: tuple[ExtensionPairingCode, ...],
        devices: tuple[ExtensionDevice, ...],
        user_status: UserStatus,
        membership_status: WorkspaceMembershipStatus,
    ) -> None:
        self.users = _FakeUserRepository({USER_ID: _user(status=user_status)})
        self.workspaces = _FakeWorkspaceRepository({WORKSPACE_ID: _workspace()})
        self.memberships = _FakeWorkspaceMembershipRepository(
            {
                MEMBERSHIP_ID: _membership(
                    status=membership_status,
                    role=WorkspaceMembershipRole.ASSIGNED_AGENT,
                )
            }
        )
        self.pairing_codes = FakeExtensionPairingCodeRepository(pairing_codes)
        self.devices = FakeExtensionDeviceRepository(devices)
        self.audits = _FakeAuthAuditLogRepository()


def _context(
    *,
    pairing_codes: tuple[ExtensionPairingCode, ...] = (),
    devices: tuple[ExtensionDevice, ...] = (),
    user_status: UserStatus = UserStatus.ACTIVE,
    membership_status: WorkspaceMembershipStatus = WorkspaceMembershipStatus.ACTIVE,
) -> _Context:
    return _Context(
        pairing_codes=pairing_codes,
        devices=devices,
        user_status=user_status,
        membership_status=membership_status,
    )


def _create_pairing_code(
    context: _Context,
    *,
    actor: AuthenticatedActor,
) -> Coroutine[object, object, CreatePairingCodeResult]:
    return create_pairing_code(
        actor=actor,
        workspace_id=WORKSPACE_ID,
        target_user_id=USER_ID,
        user_repository=context.users,
        membership_repository=context.memberships,
        pairing_code_repository=context.pairing_codes,
        audit_log_repository=context.audits,
        token_service=_FakeOpaqueTokenService(["fake-pair-secret"]),
        now=NOW,
    )


def _claim(context: _Context) -> Coroutine[object, object, ClaimExtensionDeviceResult]:
    return claim_extension_device(
        setup_code=f"{WORKSPACE_ID}.fake-pair-secret",
        workspace_id=WORKSPACE_ID,
        device_name="Chrome on Mac",
        extension_version="1.2.3",
        pairing_code_repository=context.pairing_codes,
        device_repository=context.devices,
        user_repository=context.users,
        workspace_repository=context.workspaces,
        membership_repository=context.memberships,
        audit_log_repository=context.audits,
        token_service=_FakeOpaqueTokenService(["fake-device-secret"]),
        now=NOW,
    )


def _pairing_code(
    *,
    token_hash: str = "hash::fake-pair-secret",
    expires_at: datetime = NOW + timedelta(minutes=15),
    claimed_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ExtensionPairingCode:
    return ExtensionPairingCode(
        pairing_code_id=PAIRING_CODE_ID,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        token_hash=token_hash,
        expires_at=expires_at,
        claimed_at=claimed_at,
        revoked_at=revoked_at,
        created_by_user_id=ADMIN_ID,
        created_at=NOW - timedelta(minutes=1),
    )


def _device(
    *,
    index: int = 0,
    revoked_at: datetime | None = None,
    last_seen_at: datetime | None = NOW - timedelta(minutes=1),
) -> ExtensionDevice:
    device_id = UUID(f"10000000-0000-0000-0000-{index + 2:012d}")
    return ExtensionDevice(
        device_id=device_id,
        workspace_id=WORKSPACE_ID,
        user_id=USER_ID,
        device_name=f"Fake device {index}",
        extension_version="1.2.3",
        credential_hash="hash::fake-device-secret",
        created_at=NOW - timedelta(days=1),
        last_seen_at=last_seen_at,
        revoked_at=revoked_at,
        revoked_by_user_id=ADMIN_ID if revoked_at else None,
        revocation_reason="test" if revoked_at else None,
    )