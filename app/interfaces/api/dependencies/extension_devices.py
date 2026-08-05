from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID

import structlog
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.auth import OpaqueTokenService
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    ExtensionDeviceRepository,
    ExtensionPairingCodeRepository,
    UserRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.application.use_cases.extension_devices import authenticate_extension_device
from app.core.config import Settings, get_settings
from app.core.database import get_session, set_postgres_workspace_context
from app.domain.identity import AuthenticatedExtensionDevice
from app.infrastructure.persistence.postgres.extension_device_repository import (
    PostgresExtensionDeviceRepository,
    PostgresExtensionPairingCodeRepository,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.providers import build_opaque_token_service

logger = structlog.get_logger(__name__)


class SessionCommitter(Protocol):
    async def commit(self) -> None:
        raise NotImplementedError


@dataclass
class ExtensionDeviceBundle:
    session: SessionCommitter
    user_repository: UserRepository
    workspace_repository: WorkspaceRepository
    membership_repository: WorkspaceMembershipRepository
    pairing_code_repository: ExtensionPairingCodeRepository
    device_repository: ExtensionDeviceRepository
    audit_log_repository: AuthAuditLogRepository
    token_service: OpaqueTokenService


async def get_extension_device_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExtensionDeviceBundle:
    return ExtensionDeviceBundle(
        session=session,
        user_repository=PostgresUserRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        pairing_code_repository=PostgresExtensionPairingCodeRepository(session),
        device_repository=PostgresExtensionDeviceRepository(session),
        audit_log_repository=PostgresAuthAuditLogRepository(session),
        token_service=build_opaque_token_service(settings),
    )


async def get_extension_device_actor(
    workspace_id: UUID,
    bundle: Annotated[ExtensionDeviceBundle, Depends(get_extension_device_bundle)],
    device_id_header: Annotated[
        str | None, Header(alias="X-Extension-Device-Id")
    ] = None,
    device_token: Annotated[
        str | None, Header(alias="X-Extension-Device-Token")
    ] = None,
) -> AuthenticatedExtensionDevice:
    if not device_id_header or not device_token:
        raise _invalid_credential()
    try:
        device_id = UUID(device_id_header)
    except ValueError as exc:
        raise _invalid_credential() from exc

    await set_postgres_workspace_context(bundle.session, str(workspace_id))
    result = await authenticate_extension_device(
        workspace_id=workspace_id,
        device_id=device_id,
        credential=device_token,
        device_repository=bundle.device_repository,
        user_repository=bundle.user_repository,
        workspace_repository=bundle.workspace_repository,
        membership_repository=bundle.membership_repository,
        token_service=bundle.token_service,
        now=datetime.now(UTC),
    )
    if result.actor is None:
        logger.warning(
            "extension_device_authentication_rejected",
            workspace_id=str(workspace_id),
            device_id=str(device_id),
            reasons=[reason.value for reason in result.reasons],
        )
        raise _invalid_credential()
    return AuthenticatedExtensionDevice(actor=result.actor, device_id=device_id)


def _invalid_credential() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid extension device credential",
        headers={"WWW-Authenticate": "ExtensionDevice"},
    )