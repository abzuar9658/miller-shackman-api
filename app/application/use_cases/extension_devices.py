from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.auth import OpaqueTokenService
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    ExtensionDeviceRepository,
    ExtensionPairingCodeRepository,
    UserRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.domain.identity import (
    AuthAuditEventType,
    AuthAuditLog,
    AuthenticatedActor,
    ExtensionDevice,
    ExtensionPairingCode,
    PermissionCapability,
    User,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
    evaluate_permission,
)

DEFAULT_PAIRING_CODE_TTL = timedelta(minutes=15)
DEFAULT_MAX_ACTIVE_DEVICES = 5


class ExtensionDeviceReasonCode(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    WORKSPACE_MISMATCH = "workspace_mismatch"
    TARGET_NOT_ACTIVE = "target_not_active"
    INVALID_PAIRING_CODE = "invalid_pairing_code"
    DEVICE_LIMIT_REACHED = "device_limit_reached"
    DEVICE_NOT_FOUND = "device_not_found"
    INVALID_DEVICE_CREDENTIAL = "invalid_device_credential"


@dataclass(frozen=True)
class CreatePairingCodeResult:
    pairing_code: ExtensionPairingCode | None = None
    setup_code: str | None = None
    reasons: tuple[ExtensionDeviceReasonCode, ...] = ()


@dataclass(frozen=True)
class ClaimExtensionDeviceResult:
    device: ExtensionDevice | None = None
    credential: str | None = None
    reasons: tuple[ExtensionDeviceReasonCode, ...] = ()


@dataclass(frozen=True)
class ExtensionDeviceActorResult:
    actor: AuthenticatedActor | None = None
    device: ExtensionDevice | None = None
    reasons: tuple[ExtensionDeviceReasonCode, ...] = ()


@dataclass(frozen=True)
class ExtensionDevicesResult:
    devices: tuple[ExtensionDevice, ...] = ()
    reasons: tuple[ExtensionDeviceReasonCode, ...] = ()


@dataclass(frozen=True)
class RevokeExtensionDeviceResult:
    device: ExtensionDevice | None = None
    reasons: tuple[ExtensionDeviceReasonCode, ...] = ()


def parse_extension_setup_code(setup_code: str) -> tuple[UUID, str] | None:
    workspace_text, separator, secret = setup_code.partition(".")
    if not separator or not secret:
        return None
    try:
        workspace_id = UUID(workspace_text)
    except ValueError:
        return None
    return workspace_id, secret


async def create_pairing_code(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    target_user_id: UUID,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    pairing_code_repository: ExtensionPairingCodeRepository,
    audit_log_repository: AuthAuditLogRepository,
    token_service: OpaqueTokenService,
    now: datetime,
    ttl: timedelta = DEFAULT_PAIRING_CODE_TTL,
) -> CreatePairingCodeResult:
    permission = evaluate_permission(actor, PermissionCapability.MANAGE_EXTENSION_DEVICES)
    if not permission.allowed:
        return CreatePairingCodeResult(reasons=(ExtensionDeviceReasonCode.PERMISSION_DENIED,))
    if actor.active_workspace_id != workspace_id:
        return CreatePairingCodeResult(reasons=(ExtensionDeviceReasonCode.WORKSPACE_MISMATCH,))

    user = await user_repository.get_by_id(target_user_id)
    membership = await membership_repository.get_by_user_and_workspace(
        target_user_id, workspace_id
    )
    if (
        user is None
        or user.status != UserStatus.ACTIVE
        or membership is None
        or membership.status != WorkspaceMembershipStatus.ACTIVE
    ):
        return CreatePairingCodeResult(reasons=(ExtensionDeviceReasonCode.TARGET_NOT_ACTIVE,))

    await pairing_code_repository.revoke_pending_for_user(
        workspace_id, target_user_id, revoked_at=now
    )
    token = token_service.generate_token()
    pairing_code = await pairing_code_repository.save(
        ExtensionPairingCode(
            pairing_code_id=uuid4(),
            workspace_id=workspace_id,
            user_id=target_user_id,
            token_hash=token.token_hash,
            expires_at=now + ttl,
            claimed_at=None,
            revoked_at=None,
            created_by_user_id=actor.user_id,
            created_at=now,
        )
    )
    await _append_audit(
        audit_log_repository,
        event_type=AuthAuditEventType.EXTENSION_PAIRING_CODE_CREATED,
        workspace_id=workspace_id,
        actor_user_id=actor.user_id,
        subject_user_id=target_user_id,
        now=now,
        details={"pairing_code_id": str(pairing_code.pairing_code_id)},
    )
    return CreatePairingCodeResult(
        pairing_code=pairing_code,
        setup_code=f"{workspace_id}.{token.plaintext}",
    )


async def claim_extension_device(
    *,
    setup_code: str,
    workspace_id: UUID,
    device_name: str,
    extension_version: str | None,
    pairing_code_repository: ExtensionPairingCodeRepository,
    device_repository: ExtensionDeviceRepository,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    audit_log_repository: AuthAuditLogRepository,
    token_service: OpaqueTokenService,
    now: datetime,
    max_active_devices: int = DEFAULT_MAX_ACTIVE_DEVICES,
) -> ClaimExtensionDeviceResult:
    parsed = parse_extension_setup_code(setup_code)
    if parsed is None or parsed[0] != workspace_id:
        return _invalid_claim()
    pairing_code = await pairing_code_repository.get_by_token_hash_for_update(
        workspace_id, token_service.hash_token(parsed[1])
    )
    if (
        pairing_code is None
        or pairing_code.claimed_at is not None
        or pairing_code.revoked_at is not None
        or pairing_code.expires_at <= now
    ):
        return _invalid_claim()

    workspace = await workspace_repository.get_by_id(workspace_id)
    user = await user_repository.get_by_id(pairing_code.user_id)
    membership = await membership_repository.get_by_user_and_workspace(
        pairing_code.user_id, workspace_id
    )
    if not _active_identity(workspace, user, membership):
        return _invalid_claim()
    if (
        await device_repository.count_active_for_user(workspace_id, pairing_code.user_id)
        >= max_active_devices
    ):
        return ClaimExtensionDeviceResult(
            reasons=(ExtensionDeviceReasonCode.DEVICE_LIMIT_REACHED,)
        )

    credential = token_service.generate_token()
    device = await device_repository.save(
        ExtensionDevice(
            device_id=uuid4(),
            workspace_id=workspace_id,
            user_id=pairing_code.user_id,
            device_name=device_name,
            extension_version=extension_version,
            credential_hash=credential.token_hash,
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
            revoked_by_user_id=None,
            revocation_reason=None,
        )
    )
    await pairing_code_repository.save(replace(pairing_code, claimed_at=now))
    await _append_audit(
        audit_log_repository,
        event_type=AuthAuditEventType.EXTENSION_DEVICE_PAIRED,
        workspace_id=workspace_id,
        actor_user_id=pairing_code.user_id,
        subject_user_id=pairing_code.user_id,
        now=now,
        details={"device_id": str(device.device_id)},
    )
    return ClaimExtensionDeviceResult(device=device, credential=credential.plaintext)


async def authenticate_extension_device(
    *,
    workspace_id: UUID,
    device_id: UUID,
    credential: str,
    device_repository: ExtensionDeviceRepository,
    user_repository: UserRepository,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    token_service: OpaqueTokenService,
    now: datetime,
) -> ExtensionDeviceActorResult:
    device = await device_repository.get_by_id_for_update(workspace_id, device_id)
    if (
        device is None
        or device.revoked_at is not None
        or not token_service.verify_token(credential, device.credential_hash)
    ):
        return ExtensionDeviceActorResult(
            reasons=(ExtensionDeviceReasonCode.INVALID_DEVICE_CREDENTIAL,)
        )
    workspace = await workspace_repository.get_by_id(workspace_id)
    user = await user_repository.get_by_id(device.user_id)
    membership = await membership_repository.get_by_user_and_workspace(
        device.user_id, workspace_id
    )
    if not _active_identity(workspace, user, membership):
        return ExtensionDeviceActorResult(
            reasons=(ExtensionDeviceReasonCode.INVALID_DEVICE_CREDENTIAL,)
        )
    assert workspace is not None and user is not None and membership is not None
    updated_device = await device_repository.save(replace(device, last_seen_at=now))
    return ExtensionDeviceActorResult(
        actor=AuthenticatedActor(
            user_id=user.user_id,
            user_status=user.status,
            active_role=membership.role,
            active_workspace_id=workspace.workspace_id,
            active_workspace_status=workspace.status,
            active_membership_id=membership.membership_id,
            active_membership_status=membership.status,
        ),
        device=updated_device,
    )


async def list_extension_devices(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    target_user_id: UUID,
    device_repository: ExtensionDeviceRepository,
) -> ExtensionDevicesResult:
    if not _can_manage(actor, workspace_id):
        return ExtensionDevicesResult(reasons=(ExtensionDeviceReasonCode.PERMISSION_DENIED,))
    return ExtensionDevicesResult(
        devices=await device_repository.list_by_workspace_and_user(
            workspace_id, target_user_id
        )
    )


async def revoke_extension_device(
    *,
    actor: AuthenticatedActor,
    workspace_id: UUID,
    device_id: UUID,
    reason: str | None,
    device_repository: ExtensionDeviceRepository,
    audit_log_repository: AuthAuditLogRepository,
    now: datetime,
) -> RevokeExtensionDeviceResult:
    if not _can_manage(actor, workspace_id):
        return RevokeExtensionDeviceResult(
            reasons=(ExtensionDeviceReasonCode.PERMISSION_DENIED,)
        )
    device = await device_repository.get_by_id_for_update(workspace_id, device_id)
    if device is None:
        return RevokeExtensionDeviceResult(
            reasons=(ExtensionDeviceReasonCode.DEVICE_NOT_FOUND,)
        )
    if device.revoked_at is None:
        device = await device_repository.save(
            replace(
                device,
                revoked_at=now,
                revoked_by_user_id=actor.user_id,
                revocation_reason=reason,
            )
        )
        await _append_audit(
            audit_log_repository,
            event_type=AuthAuditEventType.EXTENSION_DEVICE_REVOKED,
            workspace_id=workspace_id,
            actor_user_id=actor.user_id,
            subject_user_id=device.user_id,
            now=now,
            details={"device_id": str(device.device_id), "reason": reason or ""},
        )
    return RevokeExtensionDeviceResult(device=device)


def _can_manage(actor: AuthenticatedActor, workspace_id: UUID) -> bool:
    return (
        actor.active_workspace_id == workspace_id
        and evaluate_permission(
            actor, PermissionCapability.MANAGE_EXTENSION_DEVICES
        ).allowed
    )


def _active_identity(
    workspace: Workspace | None,
    user: User | None,
    membership: WorkspaceMembership | None,
) -> bool:
    return (
        workspace is not None
        and workspace.status == WorkspaceStatus.ACTIVE
        and user is not None
        and user.status == UserStatus.ACTIVE
        and membership is not None
        and membership.status == WorkspaceMembershipStatus.ACTIVE
    )


def _invalid_claim() -> ClaimExtensionDeviceResult:
    return ClaimExtensionDeviceResult(
        reasons=(ExtensionDeviceReasonCode.INVALID_PAIRING_CODE,)
    )


async def _append_audit(
    repository: AuthAuditLogRepository,
    *,
    event_type: AuthAuditEventType,
    workspace_id: UUID,
    actor_user_id: UUID,
    subject_user_id: UUID,
    now: datetime,
    details: dict[str, str],
) -> None:
    await repository.append(
        AuthAuditLog(
            audit_log_id=uuid4(),
            event_type=event_type,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            event_details=details,
            created_at=now,
        )
    )