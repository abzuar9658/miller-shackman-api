from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.auth import AccessTokenService, OpaqueTokenService, PasswordHasher
from app.application.ports.messaging import EmailProvider
from app.application.ports.repositories import (
    AuthAuditLogRepository,
    InvitationRepository,
    PasswordCredentialRepository,
    PasswordResetTokenRepository,
    RefreshSessionRepository,
    UserRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.domain.identity import (
    AuthenticatedActor,
)
from app.infrastructure.persistence.postgres.identity_repository import (
    PostgresAuthAuditLogRepository,
    PostgresInvitationRepository,
    PostgresPasswordCredentialRepository,
    PostgresPasswordResetTokenRepository,
    PostgresRefreshSessionRepository,
    PostgresUserRepository,
    PostgresWorkspaceMembershipRepository,
    PostgresWorkspaceRepository,
)
from app.infrastructure.providers import (
    build_access_token_service,
    build_email_provider,
    build_opaque_token_service,
    build_password_hasher,
)


@dataclass
class AuthServiceBundle:
    user_repository: UserRepository
    workspace_repository: WorkspaceRepository
    membership_repository: WorkspaceMembershipRepository
    credential_repository: PasswordCredentialRepository
    refresh_session_repository: RefreshSessionRepository
    reset_token_repository: PasswordResetTokenRepository
    invitation_repository: InvitationRepository
    audit_log_repository: AuthAuditLogRepository
    password_hasher: PasswordHasher
    access_token_service: AccessTokenService
    opaque_token_service: OpaqueTokenService
    email_provider: EmailProvider
    settings: Settings


def get_email_provider(settings: Annotated[Settings, Depends(get_settings)]) -> EmailProvider:
    return build_email_provider(settings)


async def get_auth_service_bundle(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    email_provider: Annotated[EmailProvider, Depends(get_email_provider)],
) -> AuthServiceBundle:
    return AuthServiceBundle(
        user_repository=PostgresUserRepository(session),
        workspace_repository=PostgresWorkspaceRepository(session),
        membership_repository=PostgresWorkspaceMembershipRepository(session),
        credential_repository=PostgresPasswordCredentialRepository(session),
        refresh_session_repository=PostgresRefreshSessionRepository(session),
        reset_token_repository=PostgresPasswordResetTokenRepository(session),
        invitation_repository=PostgresInvitationRepository(session),
        audit_log_repository=PostgresAuthAuditLogRepository(session),
        password_hasher=build_password_hasher(settings),
        access_token_service=build_access_token_service(settings),
        opaque_token_service=build_opaque_token_service(settings),
        email_provider=email_provider,
        settings=settings,
    )


async def get_current_actor(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedActor:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization[7:]
    access_token_service = build_access_token_service(settings)
    try:
        decoded = access_token_service.decode_token(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_repository = PostgresUserRepository(session)
    workspace_repository = PostgresWorkspaceRepository(session)
    membership_repository = PostgresWorkspaceMembershipRepository(session)

    user = await user_repository.get_by_id(decoded.subject.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    workspace = None
    if decoded.subject.workspace_id is not None:
        workspace = await workspace_repository.get_by_id(decoded.subject.workspace_id)

    membership = None
    if decoded.subject.membership_id is not None:
        membership = await membership_repository.get_by_id(decoded.subject.membership_id)

    if membership is not None and (
        membership.user_id != user.user_id
        or (workspace is not None and membership.workspace_id != workspace.workspace_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid membership context",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthenticatedActor(
        user_id=user.user_id,
        user_status=user.status,
        active_role=decoded.subject.role,
        active_workspace_id=workspace.workspace_id if workspace is not None else None,
        active_workspace_status=workspace.status if workspace is not None else None,
        active_membership_id=membership.membership_id if membership is not None else None,
        active_membership_status=membership.status if membership is not None else None,
    )


def _parse_uuid(value: str | UUID) -> UUID:
    return UUID(str(value))
