from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.application.ports.auth import (
    AccessTokenService,
    AccessTokenSubject,
    IssuedAccessToken,
    OpaqueTokenService,
)
from app.application.ports.repositories import (
    RefreshSessionRepository,
    WorkspaceMembershipRepository,
    WorkspaceRepository,
)
from app.domain.common.ids import UserId
from app.domain.identity import (
    AuthenticatedActor,
    RefreshSession,
    RefreshSessionRevocationReason,
    User,
    UserStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipStatus,
    WorkspaceStatus,
)

DEFAULT_ACCESS_TOKEN_TTL = timedelta(minutes=15)
DEFAULT_REFRESH_TOKEN_TTL = timedelta(days=30)
DEFAULT_PASSWORD_RESET_TOKEN_TTL = timedelta(minutes=30)
DEFAULT_INVITATION_TOKEN_TTL = timedelta(days=7)
DEFAULT_SIGNIN_LOCKOUT_WINDOW = timedelta(minutes=15)
DEFAULT_SIGNIN_MAX_FAILED_ATTEMPTS = 5

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


@dataclass(frozen=True)
class AuthIdentityContext:
    user: User
    workspace: Workspace
    membership: WorkspaceMembership


@dataclass(frozen=True)
class IssuedSessionTokens:
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    refresh_session: RefreshSession


def normalize_email_address(email: str) -> str:
    validated = _EMAIL_ADAPTER.validate_python(email.strip())
    return str(validated).lower()


def is_valid_email_address(email: str) -> bool:
    try:
        normalize_email_address(email)
    except ValidationError:
        return False
    return True


def authenticated_actor_from_context(identity: AuthIdentityContext) -> AuthenticatedActor:
    return AuthenticatedActor(
        user_id=identity.user.user_id,
        user_status=identity.user.status,
        active_role=identity.membership.role,
        active_workspace_id=identity.workspace.workspace_id,
        active_workspace_status=identity.workspace.status,
        active_membership_id=identity.membership.membership_id,
        active_membership_status=identity.membership.status,
    )


def allowed_permissions(actor: AuthenticatedActor) -> tuple[str, ...]:
    from app.domain.identity.permissions import PermissionCapability, evaluate_permission

    return tuple(
        capability.value
        for capability in PermissionCapability
        if evaluate_permission(actor, capability).allowed
    )


async def list_identity_contexts_for_user(
    *,
    user: User,
    membership_repository: WorkspaceMembershipRepository,
    workspace_repository: WorkspaceRepository,
) -> tuple[AuthIdentityContext, ...]:
    memberships = await membership_repository.list_by_user_id(user.user_id)
    contexts: list[AuthIdentityContext] = []
    for membership in memberships:
        workspace = await workspace_repository.get_by_id(membership.workspace_id)
        if workspace is None:
            continue
        contexts.append(
            AuthIdentityContext(
                user=user,
                workspace=workspace,
                membership=membership,
            ),
        )
    return tuple(contexts)


async def issue_session_tokens(
    *,
    identity: AuthIdentityContext,
    access_token_service: AccessTokenService,
    opaque_token_service: OpaqueTokenService,
    refresh_session_repository: RefreshSessionRepository,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
    refresh_token_ttl: timedelta = DEFAULT_REFRESH_TOKEN_TTL,
    session_id_factory: Callable[[], UUID] = uuid4,
    family_id_factory: Callable[[], UUID] = uuid4,
    family_id: UUID | None = None,
    rotated_from_session_id: UUID | None = None,
) -> IssuedSessionTokens:
    issued_access_token = issue_access_token(
        identity=identity,
        access_token_service=access_token_service,
        now=now,
        access_token_ttl=access_token_ttl,
    )
    refresh_token = opaque_token_service.generate_token()
    refresh_session = RefreshSession(
        session_id=session_id_factory(),
        user_id=identity.user.user_id,
        workspace_id=identity.workspace.workspace_id,
        refresh_token_hash=refresh_token.token_hash,
        family_id=family_id or family_id_factory(),
        rotated_from_session_id=rotated_from_session_id,
        expires_at=now + refresh_token_ttl,
        revoked_at=None,
        revoked_reason=None,
        created_at=now,
        last_used_at=None,
    )
    saved_session = await refresh_session_repository.save(refresh_session)
    return IssuedSessionTokens(
        access_token=issued_access_token.token,
        access_token_expires_at=issued_access_token.expires_at,
        refresh_token=refresh_token.plaintext,
        refresh_token_expires_at=saved_session.expires_at,
        refresh_session=saved_session,
    )


def issue_access_token(
    *,
    identity: AuthIdentityContext,
    access_token_service: AccessTokenService,
    now: datetime,
    access_token_ttl: timedelta = DEFAULT_ACCESS_TOKEN_TTL,
) -> IssuedAccessToken:
    return access_token_service.issue_token(
        AccessTokenSubject(
            user_id=identity.user.user_id,
            workspace_id=identity.workspace.workspace_id,
            membership_id=identity.membership.membership_id,
            role=identity.membership.role,
        ),
        issued_at=now,
        expires_at=now + access_token_ttl,
    )


async def revoke_user_refresh_sessions(
    *,
    user_id: UserId,
    refresh_session_repository: RefreshSessionRepository,
    reason: RefreshSessionRevocationReason,
    now: datetime,
    family_id: UUID | None = None,
) -> tuple[RefreshSession, ...]:
    sessions = await refresh_session_repository.list_by_user_id(user_id)
    revoked: list[RefreshSession] = []
    for session in sessions:
        if family_id is not None and session.family_id != family_id:
            continue
        if session.revoked_at is not None:
            continue
        updated = replace(
            session,
            revoked_at=now,
            revoked_reason=reason,
        )
        revoked.append(await refresh_session_repository.save(updated))
    return tuple(revoked)


def is_active_workspace_membership_context(identity: AuthIdentityContext) -> bool:
    return (
        identity.user.status == UserStatus.ACTIVE
        and identity.workspace.status == WorkspaceStatus.ACTIVE
        and identity.membership.status == WorkspaceMembershipStatus.ACTIVE
    )
